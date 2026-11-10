"""Обновления amemo из CLI (amemo/updates.py): `amemo update [check]`, `amemo update install`, `amemo update auto on|off`.

check (по умолчанию) — проверить релизы GitHub сейчас и показать статус; --json — UpdateStatus, тот же, что
GET /api/v1/updates. install — поставить доступную версию здесь же, по шагам службы (временный venv и --check,
бэкап перед новыми миграциями, установка на место, сверка версий), под тем же замком: служба и CLI не ставят
одновременно; запущенная служба заметит новую версию на диске и перезапустится в простое. auto — переключатель
автообновления службы в AMEMO_STATE/updates.json (amemo.toml не правится). install и auto — только человек.

Коды выхода (разд. 5.1): 0 — готово (и «обновлений нет»); 1 — окружение: проверка не удалась (сеть, API), этот вид
установки не обновляется сам (docker, исходники), нужен бэкап, а его не сделать, установка не встала; 2 — модель
вместо человека; 6 — конфликт: обновление уже ставится, автообновление выключено настройкой.
"""
from __future__ import annotations

from ..errors import CONFLICT, ENV, OK, CliError
from . import add


def register(sub, shared) -> None:
    parser = add(sub, shared, "update", "обновления amemo: check (по умолчанию), install, auto on|off", run_check)
    inner = parser.add_subparsers(dest="update_command", metavar="ДЕЙСТВИЕ", parser_class=type(parser))
    add(inner, shared, "check", "проверить релизы сейчас и показать статус", run_check)
    add(inner, shared, "install", "поставить доступную версию сейчас (только человек)", run_install)
    p = add(inner, shared, "auto", "автообновление службы: on или off (только человек)", run_auto)
    p.add_argument("mode", choices=("on", "off"), metavar="on|off")


def _updater(ctx):
    from ... import updates

    return updates.Updater(ctx.settings)


def _person_only(ctx, what: str) -> None:
    if not ctx.is_person:
        from ... import api

        raise api.Forbidden(f"{what} только человек (person:), а не {ctx.agent}: обновление — из своего терминала")


def text(status: dict) -> str:
    latest = status["latest"]
    lines = [f"amemo {status['current']} — установка {status['install']}, канал {status['channel']}"]
    if latest:
        lines.append(f"доступна {latest['version']}: {latest['url']}")
    lines.append(status["message"])
    lines.append(f"автообновление службы: {'включено' if status['auto'] else 'выключено'}"
                 + (f"; последняя проверка — {status['checked_at']}" if status["checked_at"] else ""))
    return "\n".join(lines)


def _code(updater, status: dict) -> int:
    if status["state"] == "failed":
        return ENV
    data = updater.read()
    if data.get("check_error") and status["latest"] is None:
        return ENV
    need = data.get("backup_needed") or {}
    if status["state"] == "available" and status["latest"] and need.get("version") == status["latest"]["version"]:
        return ENV
    return OK


def run_check(ctx, args) -> int:
    updater = _updater(ctx)
    status = updater.check(manual=True)
    ctx.emit(status, text)
    return _code(updater, status)


def run_install(ctx, args) -> int:
    from ... import updates

    _person_only(ctx, "обновление ставит")
    updater = _updater(ctx)
    status = updater.check(manual=True)
    try:
        version = updater.ready_to_install()
    except updates.UpdateError as e:
        if e.code == "no_update":
            if updater.read().get("check_error"):
                raise CliError(str(status["message"]), exit=ENV, code="update_check_failed") from None
            ctx.emit(status, text)
            return OK
        raise CliError(str(e), exit=CONFLICT if e.code == "update_busy" else ENV, code=e.code, status=409) from None
    ctx.note(f"ставится {version}: временное окружение, проверка на рабочей базе, установка — это займёт "
             f"несколько минут")
    status = updater.install(version)
    ctx.emit(status, lambda s: text(s) + ("\nзапущенная служба перезапустится сама в простое; агентам с amemo mcp "
                                          "нужен перезапуск" if s["state"] == "ready" else ""))
    return OK if status["state"] == "ready" else ENV


def run_auto(ctx, args) -> int:
    from ... import updates

    _person_only(ctx, "автообновление включает и выключает")
    try:
        status = _updater(ctx).set_auto(args.mode == "on")
    except updates.UpdateError as e:
        raise CliError(str(e), exit=CONFLICT, code=e.code, status=409) from None
    ctx.emit(status, text)
    return OK
