"""Журнал выдачи и полезность атомов с экспоненциальным затуханием.

Отметка принадлежит атому, а не ревизии, поэтому правки не обнуляют её вклад. В публичные
карточки очки не попадают: рецепт получает только множитель для окончательного RRF-ранжирования.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Sequence

import psycopg

from . import ids, records

_HALF_LIFE_SECONDS = 180 * 24 * 60 * 60
# блокировка задачи сессии — pg_advisory_xact_lock(int, int): первый ключ «amemo», второй — hashtext метки;
# двухключевые блокировки не пересекаются с одноключевыми (миграции, объекты, папки)
SESSION_LOCK = 0x616D656D


def _at(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now должен быть datetime с часовым поясом")
    return value


def multiplier(score: float) -> float:
    """Ограниченный логарифмический вклад полезности; новый атом имеет множитель 1."""
    return min(1.25, 1 + 0.05 * math.log1p(score))


def _decayed_score(used_marks, now: datetime) -> float:
    total = 0.0
    for used_at in used_marks:
        age = (now - used_at).total_seconds()
        if age < 0:
            raise ValueError("отметка полезности из будущего")
        total += 2 ** (-age / _HALF_LIFE_SECONDS)
    return total


def score(conn: psycopg.Connection, atom_id: uuid.UUID | str, *, now: datetime | None = None) -> float:
    """Сумма отметок атома на момент now; now задаётся явно в воспроизводимых тестах."""
    at = _at(now)
    selected = records.as_uuid(atom_id, "atom_id")
    rows = conn.execute("SELECT used_at FROM atom_use WHERE atom_id = %s", (selected,)).fetchall()
    return _decayed_score((row[0] for row in rows), at)


def multipliers(conn: psycopg.Connection, hits: list[dict], *, now: datetime | None = None) -> dict[str, float]:
    """Множители только для атомов выдачи; сущности и атомы без отметок не читаются лишний раз."""
    at = _at(now)
    atom_ids = list(dict.fromkeys(hit["record_id"] for hit in hits if hit["target"] == "atom"))
    if not atom_ids:
        return {}
    rows = conn.execute(
        "SELECT atom_id, used_at FROM atom_use WHERE atom_id = ANY(%s::uuid[]) ORDER BY atom_id, used_at",
        (atom_ids,)).fetchall()
    grouped: dict[uuid.UUID, list[datetime]] = {}
    for atom_id, used_at in rows:
        grouped.setdefault(atom_id, []).append(used_at)
    return {f"atm:{atom_id}": multiplier(_decayed_score(marks, at))
            for atom_id, marks in grouped.items()}


def record_retrieval(conn: psycopg.Connection, *, agent: str, activity: uuid.UUID | None,
                     recipe: str, query: str, ranking_version: str, hits: list[dict],
                     now: datetime | None = None) -> str:
    """Записать происхождение одной выдачи и окончательные места только её атомов."""
    records._require_autocommit(conn)
    at = _at(now)
    retrieval_id = ids.uuid7()
    atom_items = [(retrieval_id, hit["record_id"], rank)
                  for rank, hit in enumerate(hits, 1) if hit["target"] == "atom"]
    with conn.transaction():
        records._ensure_agent(conn, agent)
        conn.execute(
            "INSERT INTO retrieval (id, activity, recipe, query, agent, created_at, ranking_version) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (retrieval_id, activity, recipe, query, agent, at, ranking_version))
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO retrieval_item (retrieval_id, atom_id, rank) VALUES (%s, %s, %s)",
                            atom_items)
    return str(retrieval_id)


def session_activity(conn: psycopg.Connection, label: str, *, now: datetime | None = None) -> uuid.UUID:
    """Задача вида session с меткой label (например mcp:<id процесса и время>): та же метка — та же задача.

    Польза отмечается только в задаче выдачи, поэтому сервер MCP берёт задачу на сессию и передаёт её во все поиски
    и отметки этой сессии. Задачи других видов с той же меткой не в счёт. Поиск и создание — под рекомендательной
    блокировкой метки: параллельные вызовы с одной меткой не создают двух задач."""
    records._require_autocommit(conn)
    if not isinstance(label, str) or not label.strip():
        raise ValueError(f"метка задачи сессии {label!r}: нужна непустая строка")
    at = _at(now)
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s::int, hashtext(%s))", (SESSION_LOCK, label))
        row = conn.execute("SELECT id FROM activity WHERE kind = 'session' AND label = %s ORDER BY id LIMIT 1",
                           (label,)).fetchone()
        if row is not None:
            return row[0]
        activity = ids.uuid7()
        conn.execute("INSERT INTO activity (id, kind, label, started_at) VALUES (%s, 'session', %s, %s)",
                     (activity, label, at))
    return activity


def mark_helpful(conn: psycopg.Connection, retrieval_id: uuid.UUID | str, refs: Sequence[str], *,
                 agent: str, activity: uuid.UUID | str | None, now: datetime | None = None) -> None:
    """Отметить атомы одной выдачи для той же непустой задачи; всю пачку проверить до записи."""
    records._require_autocommit(conn)
    selected_retrieval = records.as_uuid(retrieval_id, "retrieval_id")
    if activity is None:
        raise ValueError("для отметки полезности нужна непустая activity")
    selected_activity = records.as_uuid(activity, "activity")
    at = _at(now)
    if isinstance(refs, str):
        raise ValueError("refs должен быть последовательностью ссылок, не строкой")

    atom_ids = []
    for ref in refs:
        if not isinstance(ref, str) or not ref.startswith("atm:") or ref.count(":") != 1:
            raise ValueError(f"{ref!r}: полезность отмечается только для атомов выдачи")
        atom_ids.append(records.as_uuid(ref.split(":", 1)[1], "atom ref"))
    unique_atom_ids = list(dict.fromkeys(atom_ids))

    with conn.transaction():
        row = conn.execute("SELECT activity FROM retrieval WHERE id = %s", (selected_retrieval,)).fetchone()
        if row is None:
            raise ValueError(f"retrieval {selected_retrieval}: такой выдачи нет")
        if row[0] is None or row[0] != selected_activity:
            raise ValueError("activity отметки должна совпадать с непустой activity выдачи")
        if unique_atom_ids:
            rows = conn.execute(
                "SELECT atom_id FROM retrieval_item WHERE retrieval_id = %s AND atom_id = ANY(%s::uuid[])",
                (selected_retrieval, unique_atom_ids)).fetchall()
            allowed = {item[0] for item in rows}
            foreign = [atom_id for atom_id in unique_atom_ids if atom_id not in allowed]
            if foreign:
                raise ValueError(f"atm:{foreign[0]}: атом не входит в эту выдачу")
            records._ensure_agent(conn, agent)
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO atom_use (id, atom_id, retrieval_id, activity, agent, used_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (activity, atom_id) DO NOTHING",
                    [(ids.uuid7(), atom_id, selected_retrieval, selected_activity, agent, at)
                     for atom_id in unique_atom_ids])


# Будущий kb_merge должен перенести atom_use на сохраняемый атом с учётом UNIQUE (activity, atom_id).
