"""Задачи агентам (спецификация подпроекта 4, разд. 6a.5): поставить, перечислить, взять с арендой, вернуть,
закрыть с итогом, отменить. Таблица task — миграция 0012.

Задача — о версии объекта: kind parse — «разобрать файл в атомы». Незакрытая (open или claimed) задача на
(вид, объект, версия) одна (индекс task_open): повтор постановки возвращает её же. Права (разд. 6a.6): ставить —
человек и модель; брать, возвращать и закрывать — только модель (через MCP), и только ту, что взяла сама; отменить —
тот, кто поставил, или человек.

Аренда — LEASE от взятия. Истёкшая аренда в базе остаётся claimed, пока задачу не возьмут снова: список показывает
такую задачу открытой (state open, без claimed_by и claimed_until), и её берёт любой агент — так задача, брошенная
упавшим агентом, не висит. Закрыть её тот, кто брал, ещё может, пока её не взял другой.

Строки блокируются FOR UPDATE; выбор «самой старой свободной» — FOR UPDATE SKIP LOCKED: два агента не берут одну
задачу и не ждут друг друга.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.types.json import Jsonb

from . import records
from .ids import uuid7

KINDS = ("parse",)
STATES = ("open", "claimed", "done", "cancelled")
CLOSED = ("done", "cancelled")
LEASE = timedelta(minutes=30)
LIST_MAX = 500
FIELDS = ("id", "kind", "object_id", "version", "note", "state", "created_by", "created_at", "claimed_by",
          "claimed_until", "done_at", "result")
_SELECT = ("SELECT id, kind, object_id, version, note, state, created_by, created_at, claimed_by, claimed_until, "
           "done_at, result FROM task")


class TaskError(ValueError):
    """Неверное действие с задачей. code — для служб (HTTP, MCP, CLI):
    - not_found — нет задачи, объекта или его версии;
    - closed — задача уже закрыта (done или cancelled);
    - claimed — задачу держит другой агент, аренда не истекла;
    - forbidden — действие не по праву агента;
    - invalid — неверный аргумент или действие не к месту (закрыть не взятую)."""

    CODES = ("not_found", "closed", "claimed", "forbidden", "invalid")

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def _now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise TaskError(f"now {now!r}: нужно время с часовым поясом", code="invalid")
    return now


def _who(agent: str) -> str:
    if isinstance(agent, str) and agent.startswith("person:"):
        return "person"
    if isinstance(agent, str) and agent.startswith("model:"):
        return "model"
    raise TaskError(f"агент {agent!r}: нужен person:<имя> или model:<имя>", code="invalid")


def _model_only(agent: str, what: str) -> None:
    if _who(agent) != "model":
        raise TaskError(f"{what} только модель (model:, через MCP), а не {agent}: человек ставит и отменяет задачи",
                        code="forbidden")


def _id(value) -> uuid.UUID:
    try:
        return records.as_uuid(value, "task_id")
    except records.RecordError as e:
        raise TaskError(str(e), code="invalid") from e


def _require_autocommit(conn: psycopg.Connection) -> None:
    if not conn.autocommit:
        raise TaskError("задачи: нужно соединение с autocommit=True (db.connect)", code="invalid")


def _row(row, now: datetime) -> dict:
    """Задача словарём; истёкшая аренда — открытая задача без держателя (см. докстринг модуля)."""
    task = dict(zip(FIELDS, row))
    if task["state"] == "claimed" and task["claimed_until"] < now:
        task.update(state="open", claimed_by=None, claimed_until=None)
    return task


def _lock(conn, task_id: uuid.UUID, now: datetime) -> tuple[dict, tuple]:
    """Задача под блокировкой: (как её видит список, сырые state и claimed_by из базы)."""
    row = conn.execute(f"{_SELECT} WHERE id = %s FOR UPDATE", (task_id,)).fetchone()
    if row is None:
        raise TaskError(f"задачи {task_id} нет", code="not_found")
    return _row(row, now), (row[5], row[8])


def _closed(task: dict) -> TaskError:
    return TaskError(f"задача {task['id']} уже закрыта ({task['state']}, {task['done_at'].isoformat()})",
                     code="closed")


def _held(task: dict) -> TaskError:
    return TaskError(f"задачу {task['id']} держит {task['claimed_by']} до {task['claimed_until'].isoformat()}",
                     code="claimed")


def get(conn: psycopg.Connection, task_id, *, now: datetime | None = None) -> dict:
    row = conn.execute(f"{_SELECT} WHERE id = %s", (_id(task_id),)).fetchone()
    if row is None:
        raise TaskError(f"задачи {task_id} нет", code="not_found")
    return _row(row, _now(now))


# --- постановка ---

def create(conn: psycopg.Connection, kind: str, object_id: uuid.UUID, version: int, *, agent: str,
           note: str | None = None, now: datetime | None = None) -> tuple[dict, bool]:
    """Поставить задачу; (задача, создана ли). Незакрытая задача на (kind, объект, версия) уже есть — она же
    и False. Объекта или версии нет — not_found; parse — только о файле."""
    _require_autocommit(conn)
    _who(agent)
    if kind not in KINDS:
        raise TaskError(f"вид задачи {kind!r}: допустимы {', '.join(KINDS)}", code="invalid")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise TaskError(f"version {version!r}: нужен номер версии от 1", code="invalid")
    now = _now(now)
    found = conn.execute("SELECT kind FROM object_version WHERE object_id = %s AND n = %s",
                         (object_id, version)).fetchone()
    if found is None:
        raise TaskError(f"у объекта {object_id} нет версии {version}", code="not_found")
    if kind == "parse" and found[0] != "file":
        raise TaskError(f"объект {object_id} — не файл ({found[0]}): разбирать нечего", code="invalid")
    while True:
        with conn.transaction():
            records._ensure_agent(conn, agent)
            row = conn.execute(
                "INSERT INTO task (id, kind, object_id, version, note, state, created_by, created_at) "
                "VALUES (%s, %s, %s, %s, %s, 'open', %s, %s) ON CONFLICT DO NOTHING RETURNING id",
                (uuid7(), kind, object_id, version, note, agent, now)).fetchone()
            if row is not None:
                return get(conn, row[0], now=now), True
            row = conn.execute(f"{_SELECT} WHERE kind = %s AND object_id = %s AND version = %s "
                               "AND state IN ('open', 'claimed')", (kind, object_id, version)).fetchone()
            if row is not None:
                return _row(row, now), False
        # незакрытую закрыли между вставкой и чтением — ставим снова


def list_(conn: psycopg.Connection, *, state: str | None = None, object_id: uuid.UUID | None = None,
          agent: str | None = None, limit: int = 100, now: datetime | None = None) -> list[dict]:
    """Задачи от новых к старым. state — как его видит список (истёкшая аренда — open); без state — только
    незакрытые (open и claimed): закрытые просят явно (state done или cancelled). agent — то, что нужно агенту:
    свободные задачи и взятые им самим (state тогда не задают)."""
    if state is not None and state not in STATES:
        raise TaskError(f"state {state!r}: допустимы {', '.join(STATES)}", code="invalid")
    if not 1 <= limit <= LIST_MAX:
        raise TaskError(f"limit {limit}: нужно от 1 до {LIST_MAX}", code="invalid")
    now = _now(now)
    effective = "(CASE WHEN state = 'claimed' AND claimed_until < %(now)s THEN 'open' ELSE state END)"
    where, params = [], {"now": now, "limit": limit}
    if state is not None:
        where.append(f"{effective} = %(state)s")
        params["state"] = state
    else:
        where.append("state IN ('open', 'claimed')")
    if object_id is not None:
        where.append("object_id = %(object)s")
        params["object"] = object_id
    if agent is not None:
        where.append(f"({effective} = 'open' OR (state = 'claimed' AND claimed_by = %(agent)s))")
        params["agent"] = agent
    sql = f"{_SELECT}{' WHERE ' + ' AND '.join(where) if where else ''} ORDER BY created_at DESC, id DESC LIMIT %(limit)s"
    return [_row(row, now) for row in conn.execute(sql, params)]


# --- работа агента ---

def claim(conn: psycopg.Connection, task_id=None, *, agent: str, kind: str | None = None,
          lease: timedelta = LEASE, now: datetime | None = None) -> dict | None:
    """Взять задачу (только модель): названную или, без task_id, самую старую свободную (kind — только такого
    вида); None — свободных нет. Своя — аренда продлевается. Чужая с живой арендой — claimed, закрытая — closed."""
    _require_autocommit(conn)
    _model_only(agent, "берёт задачи")
    if kind is not None and kind not in KINDS:
        raise TaskError(f"вид задачи {kind!r}: допустимы {', '.join(KINDS)}", code="invalid")
    now = _now(now)
    until = now + lease
    with conn.transaction():
        records._ensure_agent(conn, agent)
        if task_id is None:
            row = conn.execute(
                f"{_SELECT} WHERE (state = 'open' OR (state = 'claimed' AND claimed_until < %(now)s)) "
                "AND (%(kind)s::text IS NULL OR kind = %(kind)s) "
                "ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED", {"now": now, "kind": kind}).fetchone()
            if row is None:
                return None
            task = _row(row, now)
        else:
            task, _ = _lock(conn, _id(task_id), now)
            if task["state"] in CLOSED:
                raise _closed(task)
            if task["state"] == "claimed" and task["claimed_by"] != agent:
                raise _held(task)
        conn.execute("UPDATE task SET state = 'claimed', claimed_by = %s, claimed_until = %s WHERE id = %s",
                     (agent, until, task["id"]))
    return {**task, "state": "claimed", "claimed_by": agent, "claimed_until": until}


def release(conn: psycopg.Connection, task_id, *, agent: str, now: datetime | None = None) -> dict:
    """Вернуть взятую задачу в open; вернуть может только тот, кто её держит, и после истечения аренды: чужую с
    живой арендой — claimed, чужую с истёкшей — forbidden (она и так свободна, а держатель ещё может её закрыть).
    Свободная, которую никто не держит, — без изменений."""
    _require_autocommit(conn)
    _model_only(agent, "возвращает задачи")
    now = _now(now)
    with conn.transaction():
        task, (state, holder) = _lock(conn, _id(task_id), now)
        if task["state"] in CLOSED:
            raise _closed(task)
        if task["state"] == "claimed" and task["claimed_by"] != agent:
            raise _held(task)
        if state == "claimed" and holder != agent:
            raise TaskError(f"задачу {task['id']} брал {holder}, а не {agent}: вернуть её может только он "
                            f"(аренда истекла — задача и так свободна)", code="forbidden")
        if state == "claimed":
            conn.execute("UPDATE task SET state = 'open', claimed_by = NULL, claimed_until = NULL WHERE id = %s",
                         (task["id"],))
    return {**task, "state": "open", "claimed_by": None, "claimed_until": None}


def done(conn: psycopg.Connection, task_id, *, agent: str, result: dict | None = None,
         now: datetime | None = None) -> dict:
    """Закрыть взятую задачу с итогом result (объект JSON: что сделано — ссылки записей). Закрывает тот, кто
    взял (и после истечения аренды, пока задачу не взял другой); повторно — closed."""
    _require_autocommit(conn)
    _model_only(agent, "закрывает задачи")
    if result is not None and not isinstance(result, dict):
        raise TaskError("result: нужен объект JSON", code="invalid")
    now = _now(now)
    with conn.transaction():
        task, (state, holder) = _lock(conn, _id(task_id), now)
        if task["state"] in CLOSED:
            raise _closed(task)
        if state != "claimed" or holder != agent:
            if task["state"] == "claimed":
                raise _held(task)
            raise TaskError(f"задача {task['id']} не взята {agent}: сначала возьмите её (amem_task_claim)",
                            code="invalid")
        conn.execute("UPDATE task SET state = 'done', claimed_until = NULL, done_at = %s, result = %s WHERE id = %s",
                     (now, Jsonb(result) if result is not None else None, task["id"]))
    return {**task, "state": "done", "claimed_by": agent, "claimed_until": None, "done_at": now, "result": result}


def cancel(conn: psycopg.Connection, task_id, *, agent: str, now: datetime | None = None) -> dict:
    """Отменить незакрытую задачу: тот, кто поставил, или человек. Закрытая — closed."""
    _require_autocommit(conn)
    who = _who(agent)
    now = _now(now)
    with conn.transaction():
        task, _ = _lock(conn, _id(task_id), now)
        if who != "person" and task["created_by"] != agent:
            raise TaskError(f"задачу {task['id']} поставил {task['created_by']}: отменить её может он или человек, "
                            f"а не {agent}", code="forbidden")
        if task["state"] in CLOSED:
            raise _closed(task)
        conn.execute("UPDATE task SET state = 'cancelled', claimed_until = NULL, done_at = %s WHERE id = %s",
                     (now, task["id"]))
    return {**task, "state": "cancelled", "claimed_until": None, "done_at": now}
