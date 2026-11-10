"""Бэкап подпроекта 2 (amemo/backup.py) из CLI: create, list, restore, verify.

Копии — в AMEMO_BACKUPS (по умолчанию AMEMO_STATE/backups); база — AMEMO_DSN; нужен клиент PostgreSQL 18 (AMEMO_PG_BIN
или PATH). create — дамп с манифестом и ротацией (--snapshot — полный снимок с копией хранилища AMEMO_DATA); у модели
create — без ротации: --keep и удаление старых копий — только человек. restore — только человек и только в пустую
базу (и пустую папку объектов у снимка). verify — пробное восстановление во временную базу того же сервера, рабочая
база не меняется. list — то же, что GET /backups.
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
    p = add(inner, shared, "restore", "восстановить в пустую базу AMEMO_DSN", run_restore)
    p.add_argument("source", metavar="ИСТОЧНИК", help="манифест дампа (.json) или каталог снимка")
    p.add_argument("--objects", metavar="DIR", help="куда восстановить хранилище снимка (по умолчанию AMEMO_DATA)")
    p = add(inner, shared, "verify", "пробное восстановление во временную базу и поиск", run_verify)
    p.add_argument("source", metavar="ИСТОЧНИК", help="манифест дампа (.json) или каталог снимка")


def _person_only(ctx, what: str) -> None:
    """Удалять копии (ротация) и восстанавливать базу вправе только человек: модель, стёршая прежние дампы, оставила
    бы базу без отката. Отказ — api.Forbidden (код 2, как у прочих действий только для человека)."""
    if not ctx.is_person:
        from ... import api

        raise api.Forbidden(f"{what} только человек (person:), а не {ctx.agent}: модели доступен amemo backup create "
                            f"без ротации")


def run_create(ctx, args) -> int:
    from ... import backup

    target = Path(ctx.settings.backups)
    if args.keep is not None:
        _person_only(ctx, "ротацию копий (--keep) задаёт")
    if args.snapshot:
        made = backup.snapshot(ctx.dsn(), ctx.settings.data, target)
    elif ctx.is_person:
        made = backup.create(ctx.dsn(), target, **({"keep": args.keep} if args.keep is not None else {}))
    else:
        made = backup.create(ctx.dsn(), target, keep=None)     # модель копию добавляет, но старые не удаляет
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

    _person_only(ctx, "базу из копии восстанавливает")
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
