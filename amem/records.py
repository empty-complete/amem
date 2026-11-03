"""Запись схемы v1: пакеты изменений, ревизии атомов и сущностей, связи, статусы, решения проверки.

Сюда приходят данные, уже проверенные моделями model_v1 (строгий JSON) и с источниками, разрешёнными
в объекты (amem/objects.resolve_sources). Здесь:
- @имена и ключи (ent:sp20_13330) заменяются на UUID, проверяются вид ссылки и существование цели;
- у источника проверяется версия объекта и её digest; источники ревизии раскладываются в таблицу source;
- тело приводится к канонической форме и хэшируется (amem/canon.py);
- тело, совпадающее с текущей ревизией, новой ревизии не даёт; совпадающее с последней ждущей проверки (новее
  текущей) — тоже, если и новое ждёт проверки: принятое без проверки должно стать текущим;
- всё в одной транзакции: ошибка — и в базе ничего не появилось.

Порядок внутри commit:
1. id новым записям — заранее, чтобы @имена работали в любом порядке;
2. автор — до блокировок, как во всех функциях записи: иначе первый пакет нового автора мог бы встать в тупик
   с его же решением проверки по той же записи;
3. существующие записи блокируются (FOR NO KEY UPDATE) по возрастанию id: два писателя одной записи идут по очереди,
   а два пакета с общими записями не встают в тупик; ссылки других пакетов на заблокированную запись не ждут —
   кроме случая, когда пакет меняет её key: такое обновление блокирует запись так же, как FOR UPDATE;
4. одно время на весь пакет — после блокировок и не раньше последнего изменения этих записей: «на момент» не увидит
   половину пакета, даже если часы ушли назад;
5. строки новых записей — до ревизий: ссылка @имя на запись дальше в пачке проходит внешние ключи;
6. все ссылки пачки — в ревизиях и связях — разрешаются до записи ревизий: ключи (ent:sp20_13330) ищутся по состоянию
   базы до пачки, на записи этой же пачки ссылаются @имена;
7. ревизии, затем связи — в одном порядке для всех пакетов (вид связи, концы), а не в порядке пачки: два пакета
   с общими связями в разном порядке не встают в тупик на уникальном индексе.
Пакет без новых ревизий и связей тоже записывается — это след попытки.
Ошибка называет место: @имя записи, её id или items[i]; у связи — links[i]; дальше — путь поля.

Решения проверки (статус, review_state) принимает вызывающий код — автопроверка этапа 3.
Соединение — только в режиме autocommit (db.connect): без него транзакции становятся точками сохранения и запись
не фиксируется.
"""
from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Literal

import psycopg
from psycopg.types.json import Jsonb
from psycopg.types.range import Range

from . import canon, search
from .ids import uuid7

Target = Literal["atom", "entity"]
PREFIX = {"atom": "atm", "entity": "ent"}
TARGET = {"atm": "atom", "ent": "entity"}
SCHEMA_VERSION = {"atom": "amem.atom/1", "entity": "amem.entity/1"}
UUID7 = re.compile(canon.UUID7)


class RecordError(ValueError):
    pass


@dataclass
class Item:
    """Предложенная ревизия: новая запись (record_id нет) или новая ревизия существующей.

    status: у новой записи — её статус (по умолчанию draft); у существующей — новый статус, если задан,
    ставится в той же транзакции, что и ревизия."""
    target: Target
    payload: dict
    record_id: uuid.UUID | None = None
    status: str | None = None
    review_state: Literal["none", "pending"] = "none"


@dataclass
class Revision:
    target: Target
    record_id: uuid.UUID
    revision_id: uuid.UUID
    n: int
    content_hash: str
    created: bool          # False — тело совпало с текущей или ждущей проверки ревизией, новой не появилось


@dataclass
class Committed:
    changeset_id: uuid.UUID
    revisions: list[Revision] = field(default_factory=list)
    links: list[uuid.UUID] = field(default_factory=list)
    refs: dict[str, str] = field(default_factory=dict)        # @имя → atm:/ent: UUID


@dataclass
class _Planned:
    item: Item
    record_id: uuid.UUID
    label: str                         # как назвать запись в ошибке
    body: dict | None = None
    content_hash: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def check_target(target: str) -> None:
    """Вид записи — из закрытого набора: он подставляется в имена таблиц SQL."""
    if target not in PREFIX:
        raise RecordError(f"неизвестный вид записи {target!r}: нужен atom или entity")


def as_uuid(value: uuid.UUID | str, what: str = "id") -> uuid.UUID:
    """id из вызова → UUID; не UUID — RecordError, а не ошибка базы."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError as e:
        raise RecordError(f"{what} {value!r}: это не UUID") from e


def _require_autocommit(conn: psycopg.Connection) -> None:
    if not conn.autocommit:
        raise RecordError("нужно соединение с autocommit=True (db.connect): иначе запись не фиксируется")


def _ensure_agent(conn: psycopg.Connection, agent: str) -> None:
    conn.execute("INSERT INTO agent (id) VALUES (%s) ON CONFLICT (id) DO NOTHING", (agent,))


def _new_changeset(conn, *, agent, activity, reason, state, check_report, at) -> uuid.UUID:
    if activity is not None and conn.execute("SELECT 1 FROM activity WHERE id = %s", (activity,)).fetchone() is None:
        raise RecordError(f"задачи (activity) {activity} нет")
    cs = uuid7()
    conn.execute("INSERT INTO changeset (id, agent, activity, reason, state, check_report, created_at) "
                 "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                 (cs, agent, activity, reason, state, Jsonb(check_report) if check_report is not None else None, at))
    return cs


def _lock(conn, target: Target, record_id: uuid.UUID) -> datetime:
    """Заблокировать запись до конца транзакции; вернуть время её последнего изменения — новое не раньше его."""
    if conn.execute(f"SELECT 1 FROM {target} WHERE id = %s FOR NO KEY UPDATE", (record_id,)).fetchone() is None:
        raise RecordError(f"{PREFIX[target]}:{record_id}: такой записи нет")
    # отдельным запросом, после блокировки: он видит и то, что записал писатель, которого ждали
    return conn.execute(
        f"SELECT greatest(status_changed_at, (SELECT max(greatest(recorded_at, reviewed_at)) FROM {target}_revision "
        f"WHERE {target}_id = %(id)s)) FROM {target} WHERE id = %(id)s", {"id": record_id}).fetchone()[0]


def resolve_ref(conn: psycopg.Connection, ref: str, refs: dict[str, str]) -> str:
    """@имя, ключ или UUID → каноническая ссылка atm:/ent:<UUID>; цель должна существовать.

    obj: — объект должен быть в базе (amem/objects.py); версию и digest проверяет запись ревизии."""
    if ref.startswith("@"):
        if ref not in refs:
            raise RecordError(f"{ref}: в пачке нет записи с таким ref")
        return refs[ref]
    prefix, rest = ref.split(":", 1)
    if prefix == "obj":
        if not UUID7.fullmatch(rest) or conn.execute("SELECT 1 FROM object WHERE id = %s", (rest,)).fetchone() is None:
            raise RecordError(f"{ref}: такого объекта нет")
        return ref
    table = TARGET[prefix]
    if UUID7.fullmatch(rest):
        if conn.execute(f"SELECT 1 FROM {table} WHERE id = %s", (rest,)).fetchone() is None:
            raise RecordError(f"{ref}: такой записи нет")
        return ref
    row = conn.execute(f"SELECT id FROM {table} WHERE key = %s", (rest,)).fetchone()
    if row is None:
        raise RecordError(f"{ref}: нет записи с ключом {rest}")
    return f"{prefix}:{row[0]}"


def _resolve_payload(conn, target: Target, payload: dict, refs: dict[str, str]) -> dict:
    body = {**payload}
    for path in canon.REF_FIELDS[target]:
        _replace(conn, body, path.split("."), refs, "")
    return body


def _replace(conn, node, parts, refs, where):
    name, each = parts[0].removesuffix("[]"), parts[0].endswith("[]")
    if not isinstance(node, dict) or node.get(name) is None:
        return
    here = f"{where}.{name}" if where else name
    if len(parts) == 1:
        values = node[name] if each and isinstance(node[name], list) else None
        try:
            if values is not None:
                resolved = []
                for i, ref in enumerate(values):
                    here = f"{where}.{name}[{i}]" if where else f"{name}[{i}]"
                    resolved.append(resolve_ref(conn, ref, refs))
                node[name] = resolved
            else:
                node[name] = resolve_ref(conn, node[name], refs)
        except RecordError as e:
            raise RecordError(f"{here}: {e}") from e
        return
    if each:
        node[name] = [{**element} for element in node[name]]
        for i, element in enumerate(node[name]):
            _replace(conn, element, parts[1:], refs, f"{here}[{i}]")
    else:
        node[name] = {**node[name]}
        _replace(conn, node[name], parts[1:], refs, here)


def _ids(body: dict, path: str) -> list[str]:
    """UUID из поля-ссылки, без повторов и в исходном порядке."""
    return list(dict.fromkeys(ref.split(":", 1)[1] for _, ref in canon.values_at(body, path)))


def _insert_record(conn, item: Item, record_id: uuid.UUID, agent: str, at: datetime) -> None:
    target = item.target
    kind_column = "kind" if target == "atom" else "entity_class"
    status = item.status or "draft"
    conn.execute(f"INSERT INTO {target} (id, {kind_column}, status, created_at, status_changed_at) "
                 "VALUES (%s, %s, %s, %s, %s)", (record_id, item.payload[kind_column], status, at, at))
    _log_status(conn, target, record_id, status, agent, None, at)


def _prepare_body(conn, plan: _Planned, refs: dict) -> None:
    """Ссылки тела → UUID, каноническая форма, хэш; ошибка — с меткой записи."""
    target = plan.item.target
    try:
        body = canon.canonical(_resolve_payload(conn, target, plan.item.payload, refs), target)
        plan.content_hash = canon.content_hash(body)
    except (canon.CanonError, RecordError) as e:
        raise RecordError(f"{plan.label}: {e}") from e
    if body.get("valid_from") and body.get("valid_to") and body["valid_from"] > body["valid_to"]:
        raise RecordError(f"{plan.label}: valid_from {body['valid_from']} позже valid_to {body['valid_to']}")
    if target == "atom" and f"atm:{plan.record_id}" in body.get("derived_from", []):
        raise RecordError(f"{plan.label}: derived_from: атом не может быть выведен из самого себя")
    _check_sources(conn, body, plan.label)
    plan.body = body


def _check_sources(conn, body: dict, label: str) -> None:
    """Источник ведёт на существующую версию объекта, и digest тот же, что у версии: у файла — хэш его копии,
    у страницы сайта и переписки digest нет."""
    for i, source in enumerate(body.get("sources", [])):
        object_id, n = source["object"].split(":", 1)[1], source["object_version"]
        row = conn.execute("SELECT digest FROM object_version WHERE object_id = %s AND n = %s",
                           (object_id, n)).fetchone()
        if row is None:
            raise RecordError(f"{label}: sources[{i}]: у объекта {source['object']} нет версии {n}")
        if source.get("digest") != row[0]:
            raise RecordError(f"{label}: sources[{i}]: digest {source.get('digest') or 'не указан'} не совпадает "
                              f"с версией {n} объекта ({row[0] or 'без файла — digest не нужен'})")


def _unchanged(conn, plan: _Planned) -> tuple[uuid.UUID, int] | None:
    """Ревизия с тем же телом, после которой новая не нужна: текущая или последняя ждущая проверки, новее текущей.

    Ждущая проверки годится, только если и новое тело ждёт проверки: принятое без проверки должно стать текущим."""
    t = plan.item.target
    rows = conn.execute(
        f"(SELECT id, n, content_hash, review_state FROM {t}_current WHERE {t}_id = %(id)s) UNION ALL "
        f"(SELECT id, n, content_hash, review_state FROM {t}_revision WHERE {t}_id = %(id)s "
        f"AND review_state = 'pending' AND n > coalesce((SELECT n FROM {t}_current WHERE {t}_id = %(id)s), 0) "
        "ORDER BY n DESC LIMIT 1)", {"id": plan.record_id}).fetchall()
    for revision_id, n, existing_hash, state in rows:
        if existing_hash == plan.content_hash and (state != "pending" or plan.item.review_state == "pending"):
            return revision_id, n
    return None


def _write_revision(conn, plan: _Planned, cs: uuid.UUID, agent: str, reason: str | None, at: datetime) -> Revision:
    item, record_id, body, content_hash = plan.item, plan.record_id, plan.body, plan.content_hash
    target = item.target
    if item.record_id is not None and item.status is not None:
        set_status_locked(conn, target, record_id, item.status, agent=agent, reason=reason, at=at)
    same = _unchanged(conn, plan)
    if same is not None:
        return Revision(target, record_id, same[0], same[1], content_hash, created=False)
    n = conn.execute(f"SELECT coalesce(max(n), 0) + 1 FROM {target}_revision WHERE {target}_id = %s",
                     (record_id,)).fetchone()[0]
    revision_id = uuid7()
    conn.execute(
        f"INSERT INTO {target}_revision (id, {target}_id, n, schema_version, payload, content_hash, changeset_id, "
        "valid_from, valid_to, recorded_at, review_state) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (revision_id, record_id, n, SCHEMA_VERSION[target], Jsonb(body), content_hash, cs,
         body.get("valid_from"), body.get("valid_to"), at, item.review_state))
    if target == "atom":
        for entity_id in _ids(body, "about[]"):
            conn.execute("INSERT INTO atom_about (revision_id, entity_id) VALUES (%s, %s)", (revision_id, entity_id))
        for atom_id in _ids(body, "derived_from[]"):
            conn.execute("INSERT INTO atom_derived (revision_id, atom_id) VALUES (%s, %s)", (revision_id, atom_id))
    for position, source in enumerate(body.get("sources", [])):
        conn.execute(
            "INSERT INTO source (id, atom_revision_id, entity_revision_id, position, object_id, object_version, "
            "selectors, quote, edition_id, role) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (uuid7(), revision_id if target == "atom" else None, revision_id if target == "entity" else None, position,
             source["object"].split(":", 1)[1], source["object_version"],
             Jsonb(source["selectors"]) if source.get("selectors") else None, source.get("quote"),
             source["edition"].split(":", 1)[1] if source.get("edition") else None, source.get("role")))
    try:
        _refresh(conn, target, record_id)
        search.refresh_record(conn, target, record_id)
    except RecordError as e:
        raise RecordError(f"{plan.label}: {e}") from e
    return Revision(target, record_id, revision_id, n, content_hash, created=True)


def _refresh(conn, target: Target, record_id: uuid.UUID) -> None:
    """Проекция текущей ревизии в записи: key, вид или класс; у редакции — срок действия.

    Текущей ревизии нет (новая запись отклонена) — ключ и срок редакции освобождаются."""
    row = conn.execute(f"SELECT payload FROM {target}_current WHERE {target}_id = %s", (record_id,)).fetchone()
    if row is None:
        conn.execute(f"UPDATE {target} SET key = NULL WHERE id = %s", (record_id,))
        if target == "entity":
            conn.execute("DELETE FROM edition WHERE entity_id = %s", (record_id,))
        return
    body = row[0]
    try:
        if target == "atom":
            conn.execute("UPDATE atom SET key = %s, kind = %s WHERE id = %s", (body.get("key"), body["kind"], record_id))
            return
        conn.execute("UPDATE entity SET key = %s, entity_class = %s WHERE id = %s",
                     (body.get("key"), body["entity_class"], record_id))
        conn.execute("DELETE FROM edition WHERE entity_id = %s", (record_id,))
        if body["entity_class"] == "edition" and body.get("edition_of"):
            edition_of = body["edition_of"].split(":", 1)[1]
            if edition_of == str(record_id):
                raise RecordError("редакция не может быть редакцией самой себя")
            start, end = body.get("valid_from"), body.get("valid_to")
            valid = Range(date.fromisoformat(start), date.fromisoformat(end) if end else None, "[]") if start else None
            conn.execute("INSERT INTO edition (entity_id, edition_of, valid) VALUES (%s, %s, %s)",
                         (record_id, edition_of, valid))
    except psycopg.errors.UniqueViolation as e:
        raise RecordError(f"ключ {body.get('key')!r} уже занят другой записью") from e
    except psycopg.errors.ExclusionViolation as e:
        raise RecordError("срок действия пересекается с другой редакцией того же документа") from e


def _log_status(conn, target, record_id, status, agent, reason, at) -> None:
    conn.execute("INSERT INTO status_log (id, target, record_id, status, agent, reason, changed_at) "
                 "VALUES (%s, %s, %s, %s, %s, %s, %s)", (uuid7(), target, record_id, status, agent, reason, at))


def _node(ref: str) -> tuple[str, str]:
    prefix, rest = ref.split(":", 1)
    return TARGET[prefix], rest


@dataclass
class _LinkPlan:
    payload: dict
    src_kind: str
    src: str
    dst_kind: str
    dst: str
    ends: list[tuple[str, str]]        # у симметричной — оба направления


def _plan_link(conn, payload: dict, refs: dict, label: str) -> _LinkPlan:
    """Концы связи → UUID, проверка вида связи и пары концов; ошибка — с меткой links[i]."""
    rel = payload["rel"]
    try:
        try:
            src_kind, src = _node(resolve_ref(conn, payload["src"], refs))
            dst_kind, dst = _node(resolve_ref(conn, payload["dst"], refs))
        except RecordError as e:
            raise RecordError(f"связь {rel}: {e}") from e
        concept = conn.execute("SELECT data FROM concept WHERE scheme = 'rel' AND code = %s", (rel,)).fetchone()
        if concept is None:
            raise RecordError(f"неизвестный вид связи {rel!r}")
        if concept[0].get("via_field"):
            raise RecordError(f"связь {rel} задаётся полем {concept[0]['via_field']} атома, а не связью")
        pairs = concept[0].get("pairs", [])
        if f"{src_kind}>{dst_kind}" not in pairs:
            raise RecordError(f"связь {rel}: {src_kind} → {dst_kind} не допускается (можно: {', '.join(pairs)})")
        if src == dst:
            raise RecordError(f"связь {rel}: запись не может ссылаться на себя")
    except RecordError as e:
        raise RecordError(f"{label}: {e}") from e
    ends = [(src, dst)] + ([(dst, src)] if concept[0].get("symmetric") else [])
    return _LinkPlan(payload, src_kind, src, dst_kind, dst, ends)


def _write_link(conn, plan: _LinkPlan, cs: uuid.UUID, agent: str, at: datetime) -> uuid.UUID:
    payload, rel = plan.payload, plan.payload["rel"]
    existing = _active_link(conn, rel, plan.ends)
    if existing is not None:
        return existing
    link_id = uuid7()
    try:
        with conn.transaction():             # точка сохранения: одновременный дубль не обрывает весь пакет
            conn.execute(
                "INSERT INTO link (id, rel, src_atom, src_entity, dst_atom, dst_entity, note, qualifiers, confidence, "
                "changeset_id, agent, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (link_id, rel, plan.src if plan.src_kind == "atom" else None,
                 plan.src if plan.src_kind == "entity" else None, plan.dst if plan.dst_kind == "atom" else None,
                 plan.dst if plan.dst_kind == "entity" else None,
                 Jsonb(payload["note"]) if payload.get("note") else None,
                 Jsonb(payload["qualifiers"]) if payload.get("qualifiers") else None,
                 payload.get("confidence"), cs, agent, at))
    except psycopg.errors.UniqueViolation:
        existing = _active_link(conn, rel, plan.ends)     # такую же связь только что записал соседний писатель
        if existing is None:
            raise
        return existing
    return link_id


def _active_link(conn, rel: str, ends: list[tuple[str, str]]) -> uuid.UUID | None:
    for a, b in ends:
        row = conn.execute("SELECT id FROM link WHERE rel = %s AND coalesce(src_atom, src_entity) = %s "
                           "AND coalesce(dst_atom, dst_entity) = %s AND retired_at IS NULL", (rel, a, b)).fetchone()
        if row is not None:
            return row[0]
    return None


def commit(conn: psycopg.Connection, items: Sequence[Item], links: Sequence[dict] = (), *, agent: str,
           activity: uuid.UUID | None = None, reason: str | None = None, check_report: dict | None = None) -> Committed:
    """Записать принятый пакет изменений целиком или не записать ничего (порядок — в описании модуля)."""
    _require_autocommit(conn)
    if not items and not links:
        raise RecordError("пустая пачка")
    refs: dict[str, str] = {}
    planned: list[_Planned] = []
    for i, item in enumerate(items):
        check_target(item.target)
        ref = item.payload.get("ref")
        if item.record_id is not None:
            record_id = as_uuid(item.record_id, f"items[{i}].record_id")
            label = ref or f"{PREFIX[item.target]}:{record_id}"
        else:
            record_id, label = uuid7(), ref or f"items[{i}]"
        if ref:
            if ref in refs:
                raise RecordError(f"{ref}: два раза в одной пачке")
            refs[ref] = f"{PREFIX[item.target]}:{record_id}"
        scheme = "kind" if item.target == "atom" else "entity_class"
        code = item.payload.get(scheme)
        if code is not None and conn.execute("SELECT 1 FROM concept WHERE scheme = %s AND code = %s",
                                             (scheme, code)).fetchone() is None:
            raise RecordError(f"{label}: {scheme} {code!r} — кода нет в загруженных пакетах")
        planned.append(_Planned(item, record_id, label))
    with conn.transaction():
        _ensure_agent(conn, agent)
        existing = sorted({(p.item.target, p.record_id) for p in planned if p.item.record_id is not None},
                          key=lambda pair: pair[1])
        marks = [_lock(conn, target, record_id) for target, record_id in existing]
        at = max([_now(), *marks])                   # часы — после блокировок: ожидание чужой записи не в счёт
        cs = _new_changeset(conn, agent=agent, activity=activity, reason=reason, state="approved",
                            check_report=check_report, at=at)
        result = Committed(cs, refs=refs)
        for p in planned:
            if p.item.record_id is None:
                _insert_record(conn, p.item, p.record_id, agent, at)
        for p in planned:
            _prepare_body(conn, p, refs)
        link_plans = [_plan_link(conn, payload, refs, f"links[{i}]") for i, payload in enumerate(links)]
        for p in planned:
            result.revisions.append(_write_revision(conn, p, cs, agent, reason, at))
        order = sorted(range(len(link_plans)), key=lambda i: (link_plans[i].payload["rel"], min(link_plans[i].ends)))
        written = {i: _write_link(conn, link_plans[i], cs, agent, at) for i in order}
        result.links = [written[i] for i in range(len(link_plans))]          # id — в порядке пачки
    return result


def reject(conn: psycopg.Connection, *, agent: str, check_report: dict, activity: uuid.UUID | None = None,
           reason: str | None = None) -> uuid.UUID:
    """Отклонённый пакет: записей не появляется, сам пакет хранится для статистики ошибок."""
    _require_autocommit(conn)
    with conn.transaction():
        _ensure_agent(conn, agent)
        return _new_changeset(conn, agent=agent, activity=activity, reason=reason, state="rejected",
                              check_report=check_report, at=_now())


def set_status_locked(conn, target: Target, record_id: uuid.UUID, status: str, *, agent: str, reason: str | None,
                      at: datetime) -> None:
    """Сменить статус записи, уже заблокированной в текущей транзакции; тот же статус — ничего не делает."""
    current = conn.execute(f"SELECT status FROM {target} WHERE id = %s", (record_id,)).fetchone()
    if current is None:
        raise RecordError(f"{PREFIX[target]}:{record_id}: такой записи нет")
    if current[0] == status:
        return
    conn.execute(f"UPDATE {target} SET status = %s, status_changed_at = %s WHERE id = %s", (status, at, record_id))
    _log_status(conn, target, record_id, status, agent, reason, at)


def set_status(conn: psycopg.Connection, target: Target, record_id: uuid.UUID, status: str, *, agent: str,
               reason: str | None = None) -> None:
    _require_autocommit(conn)
    check_target(target)
    record_id = as_uuid(record_id, "record_id")
    with conn.transaction():
        _ensure_agent(conn, agent)
        last = _lock(conn, target, record_id)
        at = max(_now(), last)
        set_status_locked(conn, target, record_id, status, agent=agent, reason=reason, at=at)


def decide(conn: psycopg.Connection, target: Target, revision_id: uuid.UUID, accept: bool, *, agent: str) -> None:
    """Решение человека по ревизии, ждущей проверки. Принятая становится текущей, если после неё нет более новой
    действующей ревизии; отклонённая текущей не бывает."""
    _require_autocommit(conn)
    check_target(target)
    revision_id = as_uuid(revision_id, "revision_id")
    with conn.transaction():
        _ensure_agent(conn, agent)
        row = conn.execute(f"SELECT {target}_id FROM {target}_revision WHERE id = %s", (revision_id,)).fetchone()
        if row is None:
            raise RecordError(f"ревизии {revision_id} нет")
        record_id = row[0]
        # как у писателей: проекция считается после чужой записи; решение не раньше записи, даже если часы ушли назад
        last = _lock(conn, target, record_id)
        at = max(_now(), last)
        try:
            conn.execute(f"UPDATE {target}_revision SET review_state = %s, reviewed_by = %s, reviewed_at = %s "
                         "WHERE id = %s", ("accepted" if accept else "declined", agent, at, revision_id))
        except psycopg.errors.RaiseException as e:
            raise RecordError(f"ревизия {revision_id} не ждёт проверки — решение по ней уже принято") from e
        try:
            _refresh(conn, target, record_id)
            search.refresh_record(conn, target, record_id)
        except RecordError as e:
            raise RecordError(f"{PREFIX[target]}:{record_id}: {e}") from e


def retire_link(conn: psycopg.Connection, link_id: uuid.UUID, *, agent: str, reason: str) -> uuid.UUID:
    """Вывести связь из оборота отдельным пакетом изменений; сама связь остаётся в истории."""
    _require_autocommit(conn)
    link_id = as_uuid(link_id, "link_id")
    with conn.transaction():
        _ensure_agent(conn, agent)
        row = conn.execute("SELECT created_at FROM link WHERE id = %s AND retired_at IS NULL FOR UPDATE",
                           (link_id,)).fetchone()
        if row is None:
            raise RecordError(f"связи {link_id} нет или она уже выведена из оборота")
        at = max(_now(), row[0])
        cs = _new_changeset(conn, agent=agent, activity=None, reason=reason, state="approved", check_report=None, at=at)
        conn.execute("UPDATE link SET retired_at = %s, retired_by = %s WHERE id = %s", (at, cs, link_id))
    return cs
