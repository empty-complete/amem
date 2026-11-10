"""Память агентов: hook — хук Claude Code (amemo/agents/hooks.py); install и uninstall — установщик
(amemo/agents/install.py).

`amemo hook СОБЫТИЕ` читает JSON события со stdin и пишет ответ протокола хуков в stdout; код выхода всегда 0, даже
при неверном вызове: код 2 у Claude Code блокирует событие. Поэтому main CLI отдаёт `amemo hook …` сюда до разбора
опций и проверки агента (AMEMO_AS_MODEL с ошибкой не должен ронять сессию); разборщик ниже нужен для справки.

`amemo install AGENT [--project DIR] [--dry-run]` ставит в Claude Code или Codex сервер MCP, хуки и навыки;
`amemo uninstall AGENT [--project DIR] [--dry-run]` убирает ровно поставленное. Базы установщик не касается.
"""
from __future__ import annotations

from pathlib import Path

from ..errors import ENV, USAGE, CliError
from . import add


def register(sub, shared) -> None:
    p = add(sub, shared, "hook", "хук Claude Code: JSON события на stdin, ответ протокола хуков в stdout (код 0)",
            run_hook)
    p.add_argument("event", metavar="СОБЫТИЕ", help="SessionStart, UserPromptSubmit или PreCompact")

    for name, help_, run in (("install", "поставить amemo в агента: сервер MCP, хуки, навыки", run_install),
                             ("uninstall", "убрать amemo из агента (только поставленное установщиком)",
                              run_uninstall)):
        p = add(sub, shared, name, help_, run)
        p.add_argument("target", metavar="АГЕНТ", choices=("claude-code", "codex"), help="claude-code или codex")
        p.add_argument("--project", metavar="DIR", type=Path, help="в проект DIR, а не глобально")
        p.add_argument("--dry-run", action="store_true", help="показать изменения, ничего не записывая")


def run_hook(ctx, args) -> int:
    from ...agents import hooks

    return hooks.main(args.event, ctx.env)


def run_install(ctx, args) -> int:
    return _run(ctx, args, remove=False)


def run_uninstall(ctx, args) -> int:
    return _run(ctx, args, remove=True)


def _run(ctx, args, *, remove: bool) -> int:
    from ...agents import install

    try:
        do = install.uninstall if remove else install.install
        report = do(args.target, ctx.env, args.project, dry_run=args.dry_run)
    except install.InstallError as e:
        raise CliError(str(e), exit=USAGE, code="install") from None
    except install.AgentCommandError as e:
        raise CliError(str(e), exit=ENV, code="install_command",
                       hint="проверьте `claude mcp list`; без команды claude в PATH установщик правит файл сам")
    if not ctx.json:
        for line in report.notes:
            ctx.note(f"amemo: {line}")
        for line in report.warnings:
            ctx.note(f"amemo: предупреждение: {line}")
    ctx.emit(report.to_json(), lambda data: "\n".join(report.lines()))
    return 0
