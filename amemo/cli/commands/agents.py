"""Память агентов: hook — хук Claude Code (amemo/agents/hooks.py); install и uninstall — установщик
(amemo/agents/install.py).

`amemo hook СОБЫТИЕ` читает JSON события со stdin и пишет ответ протокола хуков в stdout; код выхода всегда 0, даже
при неверном вызове: код 2 у Claude Code блокирует событие. Поэтому main CLI отдаёт `amemo hook …` сюда до разбора
опций и проверки агента (AMEMO_AS_MODEL с ошибкой не должен ронять сессию); разборщик ниже нужен для справки.

`amemo install AGENT [--project DIR] [--dry-run]` ставит в Claude Code или Codex сервер MCP, хуки и навыки;
`amemo uninstall AGENT [--project DIR] [--dry-run]` убирает ровно поставленное. Базы установщик не касается.
`amemo install cowork [--out FILE]` собирает zip-плагин для Claude Cowork (amemo/agents/cowork.py): в аккаунт его
загружает человек. `amemo install claude-code --unless-synced` — прямая установка, пока в Claude Code нет плагина
amemo из аккаунта, и её снятие, когда он появился (install.prefer_plugin; так делает приложение для Windows).
"""
from __future__ import annotations

from pathlib import Path

from ..errors import ENV, USAGE, CliError
from . import add


def register(sub, shared) -> None:
    p = add(sub, shared, "hook", "хук Claude Code: JSON события на stdin, ответ протокола хуков в stdout (код 0)",
            run_hook)
    p.add_argument("event", metavar="СОБЫТИЕ", help="SessionStart, UserPromptSubmit или PreCompact")

    for name, help_, run in (("install", "поставить amemo в агента: сервер MCP, хуки, навыки (cowork — zip-плагин)",
                              run_install),
                             ("uninstall", "убрать amemo из агента (только поставленное установщиком)",
                              run_uninstall)):
        p = add(sub, shared, name, help_, run)
        p.add_argument("target", metavar="АГЕНТ", choices=("claude-code", "codex", "cowork"),
                       help="claude-code, codex или cowork (zip-плагин для Claude Cowork)")
        p.add_argument("--project", metavar="DIR", type=Path, help="в проект DIR, а не глобально")
        p.add_argument("--out", metavar="FILE", type=Path,
                       help="cowork: путь к zip плагина (по умолчанию ~/amemo-plugin.zip)")
        p.add_argument("--dry-run", action="store_true", help="показать изменения, ничего не записывая")
        if name == "install":
            p.add_argument("--unless-synced", action="store_true",
                           help="claude-code: если плагин amemo из аккаунта claude.ai уже в Claude Code — снять "
                                "прямую установку, иначе поставить")


def run_hook(ctx, args) -> int:
    from ...agents import hooks

    return hooks.main(args.event, ctx.env)


def run_install(ctx, args) -> int:
    return _run(ctx, args, remove=False)


def run_uninstall(ctx, args) -> int:
    return _run(ctx, args, remove=True)


def _run(ctx, args, *, remove: bool) -> int:
    from ...agents import cowork, install

    if args.target != "cowork" and args.out is not None:
        raise CliError("--out — только для cowork", exit=USAGE, code="install")
    unless_synced = getattr(args, "unless_synced", False)
    if unless_synced and (args.target != "claude-code" or args.project is not None):
        raise CliError("--unless-synced — только для claude-code и без --project: плагин из аккаунта — глобальный",
                       exit=USAGE, code="install")
    if args.target == "cowork" and args.project is not None:
        raise CliError("--project — не для cowork: плагин ставится в аккаунт, а не в проект", exit=USAGE,
                       code="install")
    try:
        if args.target == "cowork":
            do_plugin = cowork.remove if remove else cowork.build
            report = do_plugin(ctx.env, args.out, dry_run=args.dry_run)
        elif unless_synced:
            report, synced = install.prefer_plugin(ctx.env, dry_run=args.dry_run)
        else:
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
    data = report.to_json()
    if unless_synced:
        data["synced"] = synced
    ctx.emit(data, lambda _: "\n".join(report.lines()))
    return 0
