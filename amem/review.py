"""Очередь проверки (спецификация подпроекта 3, разд. 7.2–7.4 и 8): постановка пунктов, устаревание, выборка аудита.

Часть 3a — то, что нужно записи пакета (check.submit): пункт ставится в транзакции записи, когда запись уже
заблокирована; открытый пункт на (ревизия, причина) один — повтор не плодит дубликатов (индекс review_item_open).
Захват, решение, метрики и пересмотр при новой версии объекта — часть 3b.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from psycopg.types.json import Jsonb

from .ids import uuid7
from .records import check_target

AUDIT_RATE = 0.02                      # постоянная доля аудита записей, перешедших в auto_verified (разд. 7.4)
OPEN = ("queued", "claimed")
CLOSING_STATUSES = ("rejected", "deprecated", "superseded")    # у такой записи открытых пунктов не остаётся


def in_audit(revision_id: uuid.UUID, rate: float) -> bool:
    """Детерминированная выборка: первые 8 байт sha256("amem-audit" ‖ revision_id) как доля от 2⁶⁴ меньше rate.
    Одна и та же ревизия всегда попадает или не попадает в выборку — повтор пакета её не меняет."""
    digest = hashlib.sha256(b"amem-audit" + revision_id.bytes).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < rate


def insert_item(conn, target: str, record_id: uuid.UUID, revision_id: uuid.UUID, reason: str, *,
                changeset_id: uuid.UUID | None, details: dict, agent: str, at: datetime) -> dict | None:
    """Поставить пункт в очередь; словарь пункта (id, reason, record_id) или None, если такой открытый пункт
    у ревизии уже есть. Вызывается в транзакции, где запись уже заблокирована, а агент уже записан."""
    check_target(target)
    row = conn.execute(
        f"INSERT INTO review_item (id, target, record_id, {target}_revision_id, reason, state, changeset_id, details, "
        "created_at, created_by) VALUES (%s, %s, %s, %s, %s, 'queued', %s, %s, %s, %s) "
        "ON CONFLICT DO NOTHING RETURNING id",
        (uuid7(), target, record_id, revision_id, reason, changeset_id, Jsonb(details), at, agent)).fetchone()
    if row is None:
        return None
    return {"id": row[0], "reason": reason, "record_id": record_id}


def close_stale(conn, target: str, record_id: uuid.UUID, *, at: datetime) -> int:
    """Закрыть (obsolete) открытые пункты записи, чья ревизия больше не та, о которой спрашивают (разд. 7.3):
    ревизия не текущая и не ждёт решения; ждёт решения, но старше текущей; запись выведена из работы
    (rejected, deprecated, superseded). Число закрытых пунктов. Запись должна быть заблокирована."""
    check_target(target)
    cur = conn.execute(f"SELECT c.id, c.n, r.status FROM {target} r LEFT JOIN {target}_current c "
                       f"ON c.{target}_id = r.id WHERE r.id = %s", (record_id,)).fetchone()
    if cur is None:
        return 0
    current_id, current_n, status = cur
    retired = status in CLOSING_STATUSES
    return conn.execute(
        f"UPDATE review_item i SET state = 'obsolete', closed_at = %(at)s FROM {target}_revision v "
        f"WHERE v.id = i.{target}_revision_id AND i.record_id = %(id)s AND i.state = ANY(%(open)s) "
        "AND (%(retired)s OR (v.id IS DISTINCT FROM %(cur)s "
        "     AND (v.review_state <> 'pending' OR v.n < coalesce(%(n)s, 0))))",
        {"at": at, "id": record_id, "open": list(OPEN), "retired": retired, "cur": current_id,
         "n": current_n}).rowcount
