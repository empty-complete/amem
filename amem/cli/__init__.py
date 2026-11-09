"""CLI amem (спецификация подпроекта 4, разд. 5): `amem КОМАНДА …`, тонкий слой над операциями amem/api.py.

Команды зовут те же операции, что служба HTTP, поэтому `--json` печатает тот же объект, что HTTP отдаёт для этой
операции, а права агента проверяет та же библиотека. Без --json — короткий текст для человека с подписями записей.
Ошибка — строка «amem: …» и подсказка, что сделать, в stderr (с --json — тело problem+json, как у службы, в stdout)
и код выхода по разд. 5.1 (amem/cli/errors.py). Агент — по окружению (amem/cli/context.py).

main(argv) возвращает код выхода и не вызывает sys.exit: так его зовут тесты и скрипт `amem` (pyproject).
Команды частей 4c и задачи MCP (mcp, install, uninstall, hook) появятся вместе со своими частями.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence

from .context import Context, dumps, environ
from .errors import ENV, OK, USAGE, CliError, exit_code

PROG = "amem"


class _Parser(argparse.ArgumentParser):
    """argparse без sys.exit: ошибка разбора — CliError (код 2), справка — _Done (код 0)."""

    def error(self, message: str):
        raise CliError(message, exit=USAGE, code="usage", hint=f"справка: {self.prog} --help")

    def exit(self, status: int = 0, message: str | None = None):
        if message:
            print(message, file=sys.stderr, end="")
        raise _Done(status)


class _Done(Exception):
    def __init__(self, status: int):
        super().__init__(status)
        self.status = status


def common() -> argparse.ArgumentParser:
    """Общие опции: и до команды, и после неё (amem --json search … и amem search … --json)."""
    parent = _Parser(add_help=False)
    parent.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="вывод JSON — тот же объект, что отдаёт HTTP")
    parent.add_argument("--agent", default=argparse.SUPPRESS, metavar="AGENT",
                        help="агент записи явно: person:<имя> или model:<имя> (person: — не из окружения агента)")
    return parent


def parser() -> argparse.ArgumentParser:
    from .commands import COMMANDS

    shared = common()
    ap = _Parser(prog=PROG, parents=[shared], description="amem — база знаний из атомов: поиск, запись, очередь "
                 "проверки, подборки, бэкап, служба HTTP.",
                 epilog="Коды выхода: 0 — успех, 1 — окружение, 2 — неверный вызов, 3 — неоднозначность, "
                        "4 — не найдено, 5 — отказ проверки, 6 — конфликт.")
    sub = ap.add_subparsers(dest="command", metavar="КОМАНДА", parser_class=_Parser)
    for module in COMMANDS:
        module.register(sub, shared)
    return ap


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None, runner=None) -> int:
    """Вход `amem`: код выхода по разд. 5.1. env — окружение (по умолчанию os.environ); runner — замена uvicorn.run
    у `amem serve` (тесты)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    ctx = None
    as_json = "--json" in argv
    try:
        try:
            args = parser().parse_args(argv)
        except _Done as done:
            return done.status
        if getattr(args, "run", None) is None:
            parser().print_help(sys.stderr)
            return USAGE
        ctx = Context(args, environ(env), runner=runner)
        as_json = ctx.json
        if getattr(args, "agent", None) is not None or ctx.env.get("AMEM_AS_MODEL", "").strip():
            ctx.agent                     # явный агент проверяется сразу, у любой команды, а не при первой записи
        return args.run(ctx, args) or OK
    except KeyboardInterrupt:
        print("amem: прервано", file=sys.stderr)
        return 130
    except BaseException as exc:          # noqa: BLE001 — перевод любой ошибки в код выхода и сообщение
        if isinstance(exc, SystemExit):
            raise
        return report(exc, as_json=as_json, out=ctx.out if ctx else sys.stdout, err=ctx.err if ctx else sys.stderr)
    finally:
        if ctx is not None:
            ctx.close()


def report(exc: BaseException, *, as_json: bool, out, err) -> int:
    """Сообщение об ошибке и код выхода: CliError — как есть, прочее — через таблицу службы (problems.to_problem)."""
    from .. import backup, db, settings
    from ..service import problems

    if isinstance(exc, settings.SettingsError):
        exc = CliError(str(exc), exit=USAGE, code="settings")
    elif isinstance(exc, backup.BackupError):
        exc = CliError(str(exc), exit=ENV, code="backup")
    elif isinstance(exc, db.MigrationError):
        exc = CliError(str(exc), exit=ENV, code="not_ready")
    elif isinstance(exc, (FileNotFoundError, IsADirectoryError, NotADirectoryError, PermissionError)):
        exc = CliError(f"{getattr(exc, 'filename', None) or ''}: {exc.strerror or exc}".lstrip(": "), exit=USAGE,
                       code="file")
    if isinstance(exc, CliError):
        status, code, detail, extra, code_out, hint = exc.status, exc.code, str(exc), exc.extra, exc.exit, exc.hint
    else:
        problem = problems.to_problem(exc)
        status, code, detail, extra = problem.status, problem.code, problem.detail, problem.extra
        code_out, hint = exit_code(status, code), problems_hint(code)
        if code == "internal":
            detail = f"внутренняя ошибка: {type(exc).__name__}: {exc}"
    if as_json:
        print(dumps(problems.body(status or 0, code, detail, extra=extra)), file=out)
    else:
        print(f"amem: {detail or code}", file=err)
        _details(code, extra, out)
        if hint:
            print(f"подсказка: {hint}", file=err)
    return code_out


def problems_hint(code: str) -> str | None:
    from .errors import HINTS

    return HINTS.get(code)


def _details(code: str, extra: dict, out) -> None:
    """Что ещё показать человеку при ошибке: кандидатов, отчёт проверки, коллизии подборки."""
    if code == "ambiguous":
        for item in extra.get("candidates", []):
            kind = item.get("kind") or item.get("entity_class") or ""
            print(f"  {item['ref']}  {item['label']}" + (f"  [{kind}]" if kind else "")
                  + (f"  {item['status']}" if item.get("status") else ""), file=out)
    elif code == "check_rejected":
        for issue in extra.get("issues", []):
            where = issue["ref"] + (f": {issue['path']}" if issue.get("path") else "")
            print(f"  {issue['severity']}  {issue['code']}  {where}: {issue['message']}", file=out)
        for warning in extra.get("warnings", []):
            print(f"  предупреждение  {warning['code']}  {warning['ref']}: {warning['path']}", file=out)
    elif code == "bundle_key_collision":
        for item in extra.get("collisions", []) or []:
            print(f"  {item}", file=out)
