"""Память агентов: hook — хук Claude Code (amem/agents/hooks.py).

`amem hook СОБЫТИЕ` читает JSON события со stdin и пишет ответ протокола хуков в stdout; код выхода всегда 0, даже
при неверном вызове: код 2 у Claude Code блокирует событие. Поэтому main CLI отдаёт `amem hook …` сюда до разбора
опций и проверки агента (AMEM_AS_MODEL с ошибкой не должен ронять сессию); разборщик ниже нужен для справки.
"""
from __future__ import annotations

from . import add


def register(sub, shared) -> None:
    p = add(sub, shared, "hook", "хук Claude Code: JSON события на stdin, ответ протокола хуков в stdout (код 0)",
            run_hook)
    p.add_argument("event", metavar="СОБЫТИЕ", help="SessionStart, UserPromptSubmit или PreCompact")


def run_hook(ctx, args) -> int:
    from ...agents import hooks

    return hooks.main(args.event, ctx.env)
