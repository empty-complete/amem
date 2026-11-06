"""Очередь проверки (спецификация подпроекта 3, разд. 7.2–7.5 и 8): постановка пунктов, устаревание, выборка аудита,
захват с арендой, решение с вердиктом и последствиями, ручная постановка, список.

Пункт ставится в транзакции записи, когда запись уже заблокирована; открытый пункт на (ревизия, причина) один —
повтор не плодит дубликатов (индекс review_item_open).

Порядок блокировок — общий с записью (разд. 7.5): агент → запись (FOR NO KEY UPDATE) → пункты очереди.
claim записи не блокирует: берёт пункты FOR UPDATE SKIP LOCKED и меняет только их. resolve узнаёт запись
по пункту без блокировки, блокирует запись и только затем пункт — поэтому с submit по той же записи не встаёт
в тупик. Метрики и пересмотр при новой версии объекта — следующие задачи части 3b.
"""
from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.types.json import Jsonb

from . import records
from .ids import uuid7
from .records import PREFIX, check_target

AUDIT_RATE = 0.02                      # постоянная доля аудита записей, перешедших в auto_verified (разд. 7.4)
OPEN = ("queued", "claimed")
CLOSING_STATUSES = ("rejected", "deprecated", "superseded")    # у такой записи открытых пунктов не остаётся
RETIRED = ("deprecated", "superseded")                          # выведенные из оборота: решение статус не меняет

REASONS = ("semantic", "warning", "high_risk", "semantic_doubt", "edit", "source_changed", "audit", "calibration")
MODEL_REASONS = frozenset({"semantic"})                         # модели решают только смысл (уровень 5)
HUMAN_REASONS = frozenset(REASONS)                              # человек — всё, semantic тоже
MANUAL_REASONS = ("calibration", "audit")                       # что человек ставит вручную (разд. 8.6)
MODEL_OUTCOMES = frozenset({"confirmed", "partial", "refuted", "uncertain"})
HUMAN_OUTCOMES = frozenset({"confirmed", "refuted"})            # решение человека — итоговое: да или нет
SEMANTIC_MIN_CONFIDENCE = 0.8                                   # ниже — сомнение, пункт semantic_doubt человеку
LEASE = timedelta(minutes=15)


class ReviewError(ValueError):
    """Неверное действие с очередью: нет прав, недопустимый исход, пункт закрыт, захвачен другим или устарел."""


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


# --- общее ---

_ITEM = ("SELECT ri.id, ri.target, ri.record_id, coalesce(ri.atom_revision_id, ri.entity_revision_id), ri.reason, "
         "ri.state, ri.changeset_id, ri.details, ri.created_at, ri.created_by, ri.claimed_by, ri.claimed_until, "
         "ri.closed_at, cs.agent FROM review_item ri LEFT JOIN changeset cs ON cs.id = ri.changeset_id")
_FIELDS = ("id", "target", "record_id", "revision_id", "reason", "state", "changeset_id", "details", "created_at",
           "created_by", "claimed_by", "claimed_until", "closed_at", "author")


def _row(row) -> dict:
    item = dict(zip(_FIELDS, row))
    item["ref"] = f"{PREFIX[item['target']]}:{item['record_id']}"
    return item


def _now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ReviewError(f"now {now!r}: нужно время с часовым поясом (datetime с tzinfo)")
    return now


def _kind(agent: str) -> str:
    """person: — человек, model: — модель; метод вердикта выводится отсюда, а не передаётся."""
    if agent.startswith("person:"):
        return "human"
    if agent.startswith("model:"):
        return "llm_judge"
    raise ReviewError(f"агент {agent!r}: нужен person:<имя> или model:<имя>")


def _require_autocommit(conn: psycopg.Connection) -> None:
    if not conn.autocommit:
        raise ReviewError("очередь: нужно соединение с autocommit=True (db.connect): иначе решение не фиксируется")


def _allowed(agent: str) -> frozenset[str]:
    return HUMAN_REASONS if _kind(agent) == "human" else MODEL_REASONS


def _stale(conn, item: dict) -> bool:
    """Ревизия пункта больше не та, о которой спрашивают (разд. 7.3) — правило close_stale для одного пункта."""
    t = item["target"]
    status, current_id, current_n, n, review_state = conn.execute(
        f"SELECT r.status, c.id, c.n, v.n, v.review_state FROM {t} r JOIN {t}_revision v ON v.id = %(rev)s "
        f"LEFT JOIN {t}_current c ON c.{t}_id = r.id WHERE r.id = %(rec)s",
        {"rev": item["revision_id"], "rec": item["record_id"]}).fetchone()
    if status in CLOSING_STATUSES:
        return True
    return item["revision_id"] != current_id and (review_state != "pending" or n < (current_n or 0))


def _close(conn, item_id: uuid.UUID, state: str, at: datetime) -> None:
    conn.execute("UPDATE review_item SET state = %s, closed_at = %s WHERE id = %s", (state, at, item_id))


def _body(conn, item: dict) -> dict:
    """Тело ревизии и источники с итогами сверки — то, что проверяющему нужно для решения."""
    t = item["target"]
    n, payload, review_state = conn.execute(f"SELECT n, payload, review_state FROM {t}_revision WHERE id = %s",
                                            (item["revision_id"],)).fetchone()
    sources = conn.execute(
        "SELECT position, object_id, object_version, selectors, quote, role, verdict, page, anchor, checked_at "
        f"FROM source WHERE {t}_revision_id = %s ORDER BY position", (item["revision_id"],)).fetchall()
    keys = ("position", "object", "object_version", "selectors", "quote", "role", "verdict", "page", "anchor",
            "checked_at")
    return {"n": n, "payload": payload, "review_state": review_state,
            "sources": [{**dict(zip(keys, s)), "object": f"obj:{s[1]}"} for s in sources]}


# --- захват ---

def claim(conn: psycopg.Connection, *, agent: str, reasons: Sequence[str] | None = None, limit: int = 1,
          lease: timedelta = LEASE, now: datetime | None = None) -> list[dict]:
    """Захватить самые старые пункты, которые агент вправе решать (разд. 8.4): queued или с истёкшей арендой.

    Модель получает только semantic и не свой: модель не подтверждает свой же текст; человек свои пункты получает
    (разд. 8.2). reasons — список причин из ReviewReason; недоступные агенту просто не выдаются. FOR UPDATE SKIP
    LOCKED: параллельные проверяющие не берут один пункт и не ждут друг друга. Записи не блокируются. Устаревший
    пункт закрывается obsolete и не выдаётся — вместо него берётся следующий."""
    _require_autocommit(conn)
    allowed = _allowed(agent)
    if reasons is not None:
        if not isinstance(reasons, (list, tuple, set, frozenset)):
            raise ReviewError(f"claim: reasons {reasons!r} — нужен список причин, а не строка")
        unknown = sorted(set(reasons) - set(REASONS))
        if unknown:
            raise ReviewError(f"claim: неизвестные причины {', '.join(map(str, unknown))}; "
                              f"допустимы {', '.join(REASONS)}")
    wanted = sorted(allowed if reasons is None else allowed & set(reasons))
    if limit < 1:
        raise ReviewError(f"claim: limit {limit} — нужно хотя бы 1")
    now = _now(now)
    if not wanted:
        return []
    out: list[dict] = []
    with conn.transaction():
        records._ensure_agent(conn, agent)
        while len(out) < limit:
            rows = conn.execute(
                f"{_ITEM} WHERE (ri.state = 'queued' OR (ri.state = 'claimed' AND ri.claimed_until < %(now)s)) "
                "AND ri.reason = ANY(%(reasons)s) "
                "AND NOT (ri.reason = 'semantic' AND %(model)s AND cs.agent IS NOT DISTINCT FROM %(agent)s) "
                "AND NOT ri.id = ANY(%(taken)s) "
                "ORDER BY ri.created_at, ri.id LIMIT %(limit)s FOR UPDATE OF ri SKIP LOCKED",
                {"now": now, "reasons": wanted, "agent": agent, "model": _kind(agent) == "llm_judge",
                 "taken": [o["id"] for o in out], "limit": limit - len(out)}).fetchall()
            if not rows:
                break
            for row in rows:
                item = _row(row)
                if _stale(conn, item):
                    _close(conn, item["id"], "obsolete", now)
                    continue
                until = now + lease
                conn.execute("UPDATE review_item SET state = 'claimed', claimed_by = %s, claimed_until = %s "
                             "WHERE id = %s", (agent, until, item["id"]))
                out.append({**item, "state": "claimed", "claimed_by": agent, "claimed_until": until,
                            **_body(conn, item)})
    return out


def release(conn: psycopg.Connection, item_id: uuid.UUID | str, *, agent: str) -> None:
    """Вернуть захваченный пункт в queued; вернуть может только тот, кто его держит."""
    _require_autocommit(conn)
    item_id = _id(item_id)
    with conn.transaction():
        row = conn.execute("SELECT state, claimed_by FROM review_item WHERE id = %s FOR UPDATE",
                           (item_id,)).fetchone()
        if row is None:
            raise ReviewError(f"пункта очереди {item_id} нет")
        if row[0] != "claimed" or row[1] != agent:
            raise ReviewError(f"пункт {item_id}: его держит не {agent} (состояние {row[0]}, захвачен {row[1]})")
        conn.execute("UPDATE review_item SET state = 'queued', claimed_by = NULL, claimed_until = NULL WHERE id = %s",
                     (item_id,))


def _id(value) -> uuid.UUID:
    try:
        return records.as_uuid(value, "item_id")
    except records.RecordError as e:
        raise ReviewError(str(e)) from e


# --- решение ---

def resolve(conn: psycopg.Connection, item_id: uuid.UUID | str, outcome: str, *, agent: str,
            confidence: float | None = None, note: str | None = None, now: datetime | None = None) -> dict:
    """Решить пункт (разд. 8.5): вердикт, закрытие done, последствия по причине и исходу.

    Порядок: пункт без блокировки (узнать запись) → агент → запись FOR NO KEY UPDATE → пункт FOR UPDATE
    и перепроверка. Последствие срабатывает только при ожидаемом статусе записи, иначе вердикт пишется без смены
    статуса. Ответ: verification_id, status (статус записи после решения), queued (новые пункты)."""
    _require_autocommit(conn)
    item_id = _id(item_id)
    method = _kind(agent)
    outcomes = HUMAN_OUTCOMES if method == "human" else MODEL_OUTCOMES
    if outcome not in outcomes:
        raise ReviewError(f"исход {outcome!r} {'человеку' if method == 'human' else 'модели'} недоступен: "
                          f"допустимы {', '.join(sorted(outcomes))}")
    if method == "llm_judge" and confidence is None:
        raise ReviewError("решение модели — с уверенностью: нужен confidence от 0 до 1")
    if confidence is not None and not 0 <= confidence <= 1:
        raise ReviewError(f"confidence {confidence}: нужна доля от 0 до 1")
    now = _now(now)
    head = conn.execute("SELECT target, record_id FROM review_item WHERE id = %s", (item_id,)).fetchone()
    if head is None:
        raise ReviewError(f"пункта очереди {item_id} нет")
    target, record_id = head
    try:
        with conn.transaction():
            records._ensure_agent(conn, agent)
            last = records._lock(conn, target, record_id)
            at = max(now, last)
            item = _row(conn.execute(f"{_ITEM} WHERE ri.id = %s FOR UPDATE OF ri", (item_id,)).fetchone())
            # порядок: закрыт ли → устарел ли (закрыть, даже если решающий не вправе) → аренда и права
            if item["state"] in ("done", "obsolete"):
                raise ReviewError(f"пункт {item_id} уже закрыт ({item['state']})")
            stale = _stale(conn, item)
            if stale:
                _close(conn, item_id, "obsolete", at)     # закрытие фиксируется: ошибка — уже после транзакции
            else:
                _check(item, agent, method, now)
                result = _apply(conn, item, outcome, method, agent=agent, confidence=confidence, note=note, at=at)
    except records.RecordError as e:
        raise ReviewError(f"пункт {item_id}: {e}") from e
    if stale:
        raise ReviewError(f"пункт {item_id} устарел: его ревизия больше не та, о которой спрашивали, — "
                          "пункт закрыт obsolete")
    return result


def _check(item: dict, agent: str, method: str, now: datetime) -> None:
    """Перепроверка под блокировкой: аренда и права на причину (закрытый и устаревший отсеяны раньше)."""
    if item["state"] == "claimed" and item["claimed_by"] != agent and item["claimed_until"] >= now:
        raise ReviewError(f"пункт {item['id']} захвачен {item['claimed_by']} до {item['claimed_until']}")
    if item["reason"] not in _allowed(agent):
        raise ReviewError(f"пункт {item['id']} ({item['reason']}) решает только человек (person:)")
    if method == "llm_judge" and item["author"] == agent:
        raise ReviewError(f"пункт {item['id']}: модель — автор пакета и не подтверждает свой же текст")


def _apply(conn, item: dict, outcome: str, method: str, *, agent: str, confidence, note, at: datetime) -> dict:
    t, record_id, revision_id, reason = item["target"], item["record_id"], item["revision_id"], item["reason"]
    verification_id = uuid7()
    conn.execute("INSERT INTO verification (id, review_item_id, method, outcome, confidence, agent, note, created_at) "
                 "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                 (verification_id, item["id"], method, outcome, confidence, agent, note, at))
    _close(conn, item["id"], "done", at)
    status = conn.execute(f"SELECT status FROM {t} WHERE id = %s", (record_id,)).fetchone()[0]
    new: list[dict] = []

    def put(why: str, details: dict) -> None:
        added = insert_item(conn, t, record_id, revision_id, why, changeset_id=item["changeset_id"],
                            details=details, agent=agent, at=at)
        if added is not None:
            new.append(added)

    def set_status(value: str) -> None:
        records.set_status_locked(conn, t, record_id, value, agent=agent, reason=f"review:{reason}", at=at)

    final = False
    if reason == "semantic" and method == "llm_judge":
        if status == "draft":
            if outcome == "confirmed" and confidence >= SEMANTIC_MIN_CONFIDENCE:
                set_status("auto_verified")
                if in_audit(revision_id, AUDIT_RATE):
                    put("audit", {"verification": str(verification_id)})
            else:
                set_status("needs_review")
                put("semantic_doubt", {**item["details"], "verification": str(verification_id),
                                       "outcome": outcome, "confidence": confidence, "note": note})
    elif reason == "edit":
        pending = conn.execute(f"SELECT review_state FROM {t}_revision WHERE id = %s", (revision_id,)).fetchone()[0]
        if status == "verified" and pending == "pending":
            # records.decide — в нашей транзакции: его transaction() становится точкой сохранения
            records.decide(conn, t, revision_id, outcome == "confirmed", agent=agent)
            final = True
    elif status not in RETIRED:
        set_status("verified" if outcome == "confirmed" else "rejected")
        final = True
    if final:
        # итоговое решение человека: остальные вопросы об этой ревизии сняты, кроме source_changed — новую версию
        # файла решавший не видел, это отдельный вопрос (разд. 7.3); затем — устаревшее по записи
        conn.execute("UPDATE review_item SET state = 'obsolete', closed_at = %s WHERE state = ANY(%s) "
                     f"AND {t}_revision_id = %s AND id <> %s AND reason <> 'source_changed'",
                     (at, list(OPEN), revision_id, item["id"]))
        close_stale(conn, t, record_id, at=at)
    status = conn.execute(f"SELECT status FROM {t} WHERE id = %s", (record_id,)).fetchone()[0]
    return {"verification_id": verification_id, "status": status, "queued": new}


# --- ручная постановка и список ---

def _record(conn, ref: str) -> tuple[str, uuid.UUID]:
    """ref (atm:/ent:<UUID> или ключ) → (вид, id); ошибки ссылки — ReviewError."""
    try:
        prefix = ref.split(":", 1)[0]
        if prefix not in records.TARGET:
            raise ReviewError(f"ref {ref!r}: нужна ссылка atm:… или ent:…")
        canonical = records.resolve_ref(conn, ref, {})
    except records.RecordError as e:
        raise ReviewError(str(e)) from e
    except AttributeError as e:
        raise ReviewError(f"ref {ref!r}: нужна строка atm:… или ent:…") from e
    prefix, rest = canonical.split(":", 1)
    return records.TARGET[prefix], uuid.UUID(rest)


def enqueue(conn: psycopg.Connection, ref: str, reason: str, *, agent: str, note: str | None = None) -> uuid.UUID:
    """Поставить пункт на текущую ревизию записи вручную (разд. 8.6): calibration или audit, только person:.
    Открытый пункт той же причины не дублируется — возвращается его id."""
    _require_autocommit(conn)
    if reason not in MANUAL_REASONS:
        raise ReviewError(f"вручную ставятся только {', '.join(MANUAL_REASONS)}, а не {reason!r}")
    if _kind(agent) != "human":
        raise ReviewError(f"вручную пункт ставит только человек (person:), а не {agent}")
    target, record_id = _record(conn, ref)
    with conn.transaction():
        records._ensure_agent(conn, agent)
        last = records._lock(conn, target, record_id)
        at = max(datetime.now(timezone.utc), last)
        status = conn.execute(f"SELECT status FROM {target} WHERE id = %s", (record_id,)).fetchone()[0]
        if status in CLOSING_STATUSES:
            raise ReviewError(f"{ref}: запись со статусом {status} в очередь не ставится")
        current = conn.execute(f"SELECT id FROM {target}_current WHERE {target}_id = %s", (record_id,)).fetchone()
        if current is None:
            raise ReviewError(f"{ref}: у записи нет текущей ревизии")
        item = insert_item(conn, target, record_id, current[0], reason, changeset_id=None,
                           details={"note": note} if note else {}, agent=agent, at=at)
        if item is not None:
            return item["id"]
        return conn.execute(f"SELECT id FROM review_item WHERE {target}_revision_id = %s AND reason = %s "
                            "AND state = ANY(%s)", (current[0], reason, list(OPEN))).fetchone()[0]


def items(conn: psycopg.Connection, *, state: str | None = None, reason: str | None = None,
          record: str | uuid.UUID | None = None, limit: int = 100) -> list[dict]:
    """Пункты очереди для интерфейсов — по времени постановки; record — ref (atm:/ent:…) или id записи."""
    where, params = [], {"limit": limit}
    if state is not None:
        where.append("ri.state = %(state)s")
        params["state"] = state
    if reason is not None:
        where.append("ri.reason = %(reason)s")
        params["reason"] = reason
    if record is not None:
        where.append("ri.record_id = %(record)s")
        params["record"] = _record(conn, record)[1] if isinstance(record, str) and ":" in record else _id(record)
    sql = f"{_ITEM}{' WHERE ' + ' AND '.join(where) if where else ''} ORDER BY ri.created_at, ri.id LIMIT %(limit)s"
    return [_row(r) for r in conn.execute(sql, params).fetchall()]
