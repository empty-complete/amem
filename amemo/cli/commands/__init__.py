"""Команды CLI: модуль на группу; register(sub, shared) добавляет разборщики и set_defaults(run=…)."""
from __future__ import annotations


def add(sub, shared, name: str, help: str, run=None, **kw):
    """Подкоманда с общими опциями (--json, --agent) и функцией run(ctx, args) -> код выхода."""
    parser = sub.add_parser(name, help=help, description=help, parents=[shared], **kw)
    if run is not None:
        parser.set_defaults(run=run)
    return parser


def group(sub, shared, name: str, help: str):
    """Группа подкоманд (amemo review list|claim|…): без подкоманды — справка группы."""
    parser = add(sub, shared, name, help)
    parser.set_defaults(run=lambda ctx, args: _help(ctx, parser))
    inner = parser.add_subparsers(dest=f"{name}_command", metavar="ДЕЙСТВИЕ", parser_class=type(parser))
    return parser, inner


def _help(ctx, parser) -> int:
    parser.print_help(ctx.err)
    return 2


# модули команд берут add и group отсюда — импорт после них
from . import agents, backup, bundles, ocr, read, setup, tasks, tokens, write  # noqa: E402

COMMANDS = (setup, read, write, tasks, bundles, backup, tokens, ocr, agents)
