"""CLI amem (спецификация подпроекта 4, разд. 5): `amem КОМАНДА …`, тонкий слой над операциями amem/api.py.

Команды зовут те же операции, что служба HTTP, поэтому `--json` печатает тот же объект, что HTTP отдаёт для этой
операции, а права агента проверяет та же библиотека. Без --json — короткий текст для человека с подписями записей.
Ошибка — строка «amem: …» и подсказка, что сделать, в stderr (с --json — тело problem+json, как у службы, в stdout)
и код выхода по разд. 5.1 (amem/cli/errors.py). Агент — по окружению (amem/cli/context.py).

main(argv) возвращает код выхода и не вызывает sys.exit: так его зовут тесты и скрипт `amem` (pyproject).
`amem mcp` — сервер MCP на stdio (amem/service/mcp.py). `amem hook СОБЫТИЕ` — хук Claude Code (amem/agents/hooks.py):
он идёт мимо разбора опций и всегда выходит с кодом 0. Команды install и uninstall части 4c появятся вместе с ней.
"""
from __future__ import annotations

import argparse
import io
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
    environment = environ(env)
    if len(argv) == 2 and argv[0] == "hook" and not argv[1].startswith("-"):
        from ..agents import hooks

        return hooks.main(argv[1], environment)       # хук не роняет сессию агента: код 0 при любом сбое
    made: list[Context] = []              # Context вызова: report берёт из него вывод и --json; close — в конце
    try:
        try:
            code = _run(argv, environment, runner, made)
        except KeyboardInterrupt:
            print("amem: прервано", file=sys.stderr)
            code = 130
        except BrokenPipeError:
            raise
        except BaseException as exc:      # noqa: BLE001 — перевод любой ошибки в код выхода и сообщение
            if isinstance(exc, SystemExit):
                raise
            ctx = made[0] if made else None
            code = report(exc, as_json=ctx.json if ctx is not None else "--json" in argv,
                          out=ctx.out if ctx else sys.stdout, err=ctx.err if ctx else sys.stderr, env=environment)
        sys.stdout.flush()                # здесь, а не при выходе: закрытый конвейер (| head) ловится ниже
        return code
    except BrokenPipeError:
        # читатель конвейера закрылся (amem … | head): вывод больше не нужен — это не ошибка; дальнейшие записи
        # и сброс буфера при выходе интерпретатора уходят в /dev/null, а не в «Exception ignored … BrokenPipe»
        _silence_stdout()
        return OK
    finally:
        for ctx in made:
            ctx.close()


def _run(argv, environment, runner, made: list) -> int:
    try:
        args = parser().parse_args(argv)
    except _Done as done:
        return done.status
    if getattr(args, "run", None) is None:
        parser().print_help(sys.stderr)
        return USAGE
    ctx = Context(args, environment, runner=runner)
    made.append(ctx)
    if getattr(args, "agent", None) is not None or ctx.env.get("AMEM_AS_MODEL", "").strip():
        ctx.agent                         # явный агент проверяется сразу, у любой команды, а не при первой записи
    return args.run(ctx, args) or OK


def _silence_stdout() -> None:
    import os

    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
    except (OSError, ValueError, AttributeError, io.UnsupportedOperation):
        pass                              # stdout без дескриптора (перехват в тестах) — подменяется ниже
    sys.stdout = open(os.devnull, "w", encoding="utf-8")


def _auth_failed(exc: BaseException) -> bool:
    """Отказ входа (пользователь, пароль) — не «база не запущена»: подсказка другая. Текст libpq — по-английски
    при любой локали клиента; сам текст наружу не идёт (в нём адрес сервера)."""
    import psycopg

    text = str(exc).lower()
    return isinstance(exc, psycopg.OperationalError) and not isinstance(exc, psycopg.errors.QueryCanceled) and (
        "authentication failed" in text or "password authentication" in text or "no password supplied" in text
        or ("role" in text and "does not exist" in text))


def report(exc: BaseException, *, as_json: bool, out, err, env: Mapping[str, str] | None = None) -> int:
    """Сообщение об ошибке и код выхода: CliError — как есть, прочее — через таблицу службы (problems.to_problem).
    AMEM_DEBUG=1 — ещё и traceback внутренней ошибки в stderr."""
    from .. import backup, db, settings
    from ..service import problems

    if _auth_failed(exc):
        exc = CliError("вход в базу не удался: сервер отверг пользователя или пароль", exit=ENV, code="db_auth")
    elif isinstance(exc, settings.SettingsError):
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
            if (env or {}).get("AMEM_DEBUG", "").strip() not in ("", "0"):
                import traceback

                traceback.print_exception(exc, file=err)
    if as_json:
        body = problems.body(status or 0, code, detail, extra=extra)
        if status is None:                # у ошибки CLI нет HTTP-аналога: статуса нет, а не «0»
            del body["status"]
            body["title"] = "Ошибка"
        print(dumps(body), file=out)
    else:
        print(f"amem: {detail or code}", file=err)
        _details(code, extra, err)
        if hint:
            print(f"подсказка: {hint}", file=err)
    return code_out


def problems_hint(code: str) -> str | None:
    from .errors import HINTS

    return HINTS.get(code)


def _details(code: str, extra: dict, err) -> None:
    """Что ещё показать человеку при ошибке: кандидатов, отчёт проверки, коллизии подборки."""
    if code == "ambiguous":
        for item in extra.get("candidates", []):
            kind = item.get("kind") or item.get("entity_class") or ""
            print(f"  {item['ref']}  {item['label']}" + (f"  [{kind}]" if kind else "")
                  + (f"  {item['status']}" if item.get("status") else ""), file=err)
    elif code == "check_rejected":
        for issue in extra.get("issues", []):
            where = issue["ref"] + (f": {issue['path']}" if issue.get("path") else "")
            print(f"  {issue['severity']}  {issue['code']}  {where}: {issue['message']}", file=err)
        for warning in extra.get("warnings", []):
            print(f"  предупреждение  {warning['code']}  {warning['ref']}: {warning['path']}", file=err)
    elif code == "bundle_key_collision":
        for item in extra.get("collisions", []) or []:
            print(f"  {item}", file=err)
