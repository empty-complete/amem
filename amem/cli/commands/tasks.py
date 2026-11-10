"""Задачи агентам (разд. 6a.5): amem tasks list — что поставлено и в каком состоянии, amem tasks cancel — отменить.

Брать и закрывать задачи — дело модели через MCP (amem_task_claim, amem_task_done), у CLI этих команд нет. Отменить
может тот, кто поставил, или человек — это проверяет библиотека (amem/tasks.py).
"""
from __future__ import annotations

from . import add, group


def register(sub, shared) -> None:
    tasks, inner = group(sub, shared, "tasks", "задачи агентам: список, отмена")
    tasks.set_defaults(run=run_tasks_list)             # amem tasks — список
    p = add(inner, shared, "list", "задачи по времени постановки", run_tasks_list)
    p.add_argument("--state", help="open, claimed, done, cancelled")
    p.add_argument("--object", help="только об этом объекте: UUID")
    p = add(inner, shared, "cancel", "отменить незакрытую задачу (поставивший или человек)", run_tasks_cancel)
    p.add_argument("task", metavar="ID", help="id задачи")


def task_line(task: dict) -> str:
    line = f"{task['id']}  {task['kind']}  {task['state']}  obj:{task['object']} v{task['version']}"
    if task["claimed_by"]:
        line += f"  взял {task['claimed_by']} до {task['claimed_until']}"
    line += f"  (поставил {task['created_by']})"
    if task["note"]:
        line += f" — {task['note']}"
    return line


def run_tasks_list(ctx, args) -> int:
    from ... import api

    found = api.task_list(ctx.connect(), state=getattr(args, "state", None), object=getattr(args, "object", None))
    ctx.emit(found, lambda rows: "\n".join(task_line(t) for t in rows) or "Задач нет.")
    return 0


def run_tasks_cancel(ctx, args) -> int:
    from ... import api

    done = api.task_cancel(ctx.connect(), args.task, agent=ctx.agent)
    ctx.emit(done, f"Задача {done['id']} отменена.")
    return 0
