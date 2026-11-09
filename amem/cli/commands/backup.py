"""Бэкап подпроекта 2 (amem/backup.py) из CLI: create, list, restore, verify.

Копии — в AMEM_BACKUPS (по умолчанию AMEM_STATE/backups); база — AMEM_DSN; нужен клиент PostgreSQL 18 (AMEM_PG_BIN
или PATH). create — дамп с манифестом и ротацией (--snapshot — полный снимок с копией хранилища AMEM_DATA);
restore — только в пустую базу (и пустую папку объектов у снимка); verify — пробное восстановление во временную
базу того же сервера, рабочая база не меняется. list — то же, что GET /backups.
"""
from __future__ import annotations

from pathlib import Path

from . import add, group


def register(sub, shared) -> None:
    _, inner = group(sub, shared, "backup", "бэкап базы: create, list, restore, verify")
    p = add(inner, shared, "create", "дамп базы с манифестом (или полный снимок)", run_create)
    p.add_argument("--snapshot", action="store_true", help="полный снимок: дамп и копия хранилища объектов")
    p.add_argument("--keep", type=int, help="сколько последних дампов оставить (по умолчанию 14)")
    add(inner, shared, "list", "готовые копии", run_list)
    p = add(inner, shared, "restore", "восстановить в пустую базу AMEM_DSN", run_restore)
    p.add_argument("source", metavar="ИСТОЧНИК", help="манифест дампа (.json) или каталог снимка")
    p.add_argument("--objects", metavar="DIR", help="куда восстановить хранилище снимка (по умолчанию AMEM_DATA)")
    p = add(inner, shared, "verify", "пробное восстановление во временную базу и поиск", run_verify)
    p.add_argument("source", metavar="ИСТОЧНИК", help="манифест дампа (.json) или каталог снимка")


def run_create(ctx, args) -> int:
    from ... import backup

    target = Path(ctx.settings.backups)
    if args.snapshot:
        made = backup.snapshot(ctx.dsn(), ctx.settings.data, target)
    else:
        made = backup.create(ctx.dsn(), target, **({"keep": args.keep} if args.keep is not None else {}))
    ctx.emit(made, lambda m: f"Копия готова: {m.get('name') or m.get('dump') or target}")
    return 0


def run_list(ctx, args) -> int:
    from ... import api

    items = api.backup_list(ctx.settings.backups)
    ctx.emit(items, lambda found: "\n".join(f"{b['name']}  {b['created_at']}  {b['size']} байт" for b in found)
             or f"Копий нет в {ctx.settings.backups}.")
    return 0


def run_restore(ctx, args) -> int:
    from ... import backup

    source = Path(args.source)
    objects = Path(args.objects) if args.objects else (ctx.settings.data if source.is_dir() else None)
    done = backup.restore(source, ctx.dsn(), objects_root=objects)
    ctx.emit(done, lambda d: f"Восстановлено: база {d['base_id']}, миграций {len(d['migrations'])}")
    return 0


def run_verify(ctx, args) -> int:
    from ... import backup

    done = backup.verify(Path(args.source), ctx.dsn(), provider=None)
    ctx.emit(done, lambda d: f"Копия проверена: база {d['base_id']} восстанавливается, поиск находит "
                             f"{'пробный атом' if (d.get('search') or {}).get('found') else 'то, что есть'}")
    return 0
