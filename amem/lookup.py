"""Чтение схемы v1: запись с текущей ревизией или «как было на момент», история, редакции на дату, связи;
объекты источников, их статус и источники ревизии.

Запись отдаётся словарём в формате model_v1.Atom / model_v1.Entity: тело ревизии + технические поля.
«На момент» (at) — время транзакции: что база знала тогда, включая решения проверки, принятые до этого момента.
at — только время с часовым поясом: время без пояса база прочла бы в поясе сеанса и ошиблась бы на часы.
"""
from __future__ import annotations

import posixpath
import uuid
from datetime import date, datetime

import psycopg
from psycopg.rows import dict_row

from .objects import object_uuid
from .records import PREFIX, RecordError, Target, as_uuid, check_target

# порядок ревизий «на момент»: 0 — действующая (none или принятая к этому моменту), 1 — ещё ждёт решения
_AS_OF_ORDER = """CASE WHEN r.review_state = 'none'
                       OR (r.review_state = 'accepted' AND r.reviewed_at <= %(at)s) THEN 0 ELSE 1 END"""


def _record(row: dict, target: Target) -> dict:
    return {
        **row["payload"],
        "id": str(row["record_id"]),
        "schema_version": row["schema_version"],
        "revision": row["n"],
        "content_hash": row["content_hash"],
        "status": row["status"],
        "review_state": row["review_state"],
        "created_at": row["created_at"].isoformat(),
        "recorded_at": row["recorded_at"].isoformat(),
        "changeset": str(row["changeset_id"]),
        "agent": row["agent"],
        **({"activity": str(row["activity"])} if row["activity"] else {}),
    }


def _uuid(value: uuid.UUID | str) -> str:
    return str(as_uuid(value))


def _moment(at: datetime | None) -> datetime | None:
    if at is not None and (not isinstance(at, datetime) or at.tzinfo is None):
        raise RecordError(f"at {at!r}: нужно время с часовым поясом (datetime с tzinfo)")
    return at


def get(conn: psycopg.Connection, target: Target, record_id: uuid.UUID | str, *,
        at: datetime | None = None) -> dict | None:
    """Запись с текущей ревизией; at — как база видела её в этот момент (статус и решение проверки — тоже)."""
    check_target(target)
    at = _moment(at)
    t = target
    if at is None:
        source, where, order = f"{t}_current", "", ""
        review, status = "r.review_state", "rec.status"
    else:
        source = f"{t}_revision"
        where = "AND r.recorded_at <= %(at)s AND NOT (r.review_state = 'declined' AND r.reviewed_at <= %(at)s)"
        order = f"ORDER BY {_AS_OF_ORDER}, r.n DESC"
        # решение, принятое после этого момента, тогда ещё не было принято
        review = ("CASE WHEN r.review_state IN ('accepted', 'declined') AND r.reviewed_at > %(at)s "
                  "THEN 'pending' ELSE r.review_state END")
        status = (f"(SELECT s.status FROM status_log s WHERE s.target = '{t}' AND s.record_id = r.{t}_id "
                  "AND s.changed_at <= %(at)s ORDER BY s.changed_at DESC, s.id DESC LIMIT 1)")
    sql = (f"SELECT r.{t}_id AS record_id, r.schema_version, r.n, r.content_hash, r.payload, "
           f"{review} AS review_state, r.recorded_at, r.changeset_id, {status} AS status, rec.created_at, "
           f"cs.agent, cs.activity FROM {source} r JOIN {t} rec ON rec.id = r.{t}_id "
           f"JOIN changeset cs ON cs.id = r.changeset_id WHERE r.{t}_id = %(id)s {where} {order} LIMIT 1")
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(sql, {"id": _uuid(record_id), "at": at}).fetchone()
    if row is None or row["status"] is None:
        return None
    return _record(row, target)


def history(conn: psycopg.Connection, target: Target, record_id: uuid.UUID | str) -> list[dict]:
    check_target(target)
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(f"SELECT id, n, content_hash, review_state, recorded_at, changeset_id "
                           f"FROM {target}_revision WHERE {target}_id = %s ORDER BY n", (_uuid(record_id),)).fetchall()


def by_key(conn: psycopg.Connection, target: Target, key: str) -> str | None:
    """Ключ → каноническая ссылка atm:/ent:<UUID> или None."""
    check_target(target)
    row = conn.execute(f"SELECT id FROM {target} WHERE key = %s", (key,)).fetchone()
    return f"{PREFIX[target]}:{row[0]}" if row else None


def editions_in_force(conn: psycopg.Connection, edition_of: uuid.UUID | str, on: date) -> list[uuid.UUID]:
    """Редакции документа, действующие на дату. Редакции без даты начала не учитываются."""
    rows = conn.execute("SELECT entity_id FROM edition WHERE edition_of = %s AND valid @> %s::date ORDER BY entity_id",
                        (_uuid(edition_of), on)).fetchall()
    return [r[0] for r in rows]


def links(conn: psycopg.Connection, node: uuid.UUID | str, *, at: datetime | None = None) -> list[dict]:
    """Связи, у которых запись — один из концов. at — действовавшие в тот момент; иначе — действующие сейчас.

    У связи — её происхождение: пакет, автор и время записи."""
    at = _moment(at)
    when = ("l.created_at <= %(at)s AND (l.retired_at IS NULL OR l.retired_at > %(at)s)" if at
            else "l.retired_at IS NULL")
    sql = ("SELECT l.id, l.rel, coalesce(l.src_atom, l.src_entity) AS src, "
           "CASE WHEN l.src_atom IS NULL THEN 'ent' ELSE 'atm' END AS src_prefix, "
           "coalesce(l.dst_atom, l.dst_entity) AS dst, "
           "CASE WHEN l.dst_atom IS NULL THEN 'ent' ELSE 'atm' END AS dst_prefix, l.note, l.qualifiers, l.confidence, "
           "l.changeset_id, l.agent, l.created_at "
           f"FROM link l WHERE (coalesce(l.src_atom, l.src_entity) = %(id)s OR coalesce(l.dst_atom, l.dst_entity) = %(id)s) "
           f"AND {when} ORDER BY l.id")
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(sql, {"id": _uuid(node), "at": at}).fetchall()
    return [{"id": str(r["id"]), "rel": r["rel"], "src": f"{r['src_prefix']}:{r['src']}",
             "dst": f"{r['dst_prefix']}:{r['dst']}", **({"note": r["note"]} if r["note"] else {}),
             **({"qualifiers": r["qualifiers"]} if r["qualifiers"] else {}),
             **({"confidence": r["confidence"]} if r["confidence"] is not None else {}),
             "changeset": str(r["changeset_id"]), "agent": r["agent"], "created_at": r["created_at"].isoformat()}
            for r in rows]


def revision_sources(conn: psycopg.Connection, target: Target, revision_id: uuid.UUID | str) -> list[dict]:
    """Источники ревизии в порядке тела: id строки source, объект и версия, место, роль; итог сверки — если был."""
    rid = as_uuid(revision_id, "revision_id")
    return revisions_sources(conn, target, [rid])[rid]


def revisions_sources(conn: psycopg.Connection, target: Target,
                      revision_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
    """Источники нескольких ревизий одним запросом: revision_id → список, как у revision_sources."""
    check_target(target)
    out: dict[uuid.UUID, list[dict]] = {as_uuid(r, "revision_id"): [] for r in revision_ids}
    if not out:
        return out
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            f"SELECT {target}_revision_id AS revision_id, id, position, object_id, object_version, selectors, quote, "
            f"edition_id, role, verdict, page, anchor, checked_at FROM source "
            f"WHERE {target}_revision_id = ANY(%s) ORDER BY {target}_revision_id, position",
            (list(out),)).fetchall()
    for r in rows:
        item = {"id": str(r["id"]), "position": r["position"], "object": f"obj:{r['object_id']}",
                "object_version": r["object_version"]}
        item |= {k: r[k] for k in ("selectors", "quote", "role", "verdict", "page", "anchor") if r[k] is not None}
        if r["edition_id"] is not None:
            item["edition"] = f"ent:{r['edition_id']}"
        if r["checked_at"] is not None:
            item["checked_at"] = r["checked_at"].isoformat()
        out[r["revision_id"]].append(item)
    return out


def get_object(conn: psycopg.Connection, object_id: uuid.UUID | str) -> dict | None:
    """Объект в формате model_v1.ObjectRecord: пути в папке документов и версии. id — UUID или obj:<UUID>."""
    oid = str(object_uuid(object_id))
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute("SELECT id, kind, original_name, media_type, format_puid, url, retrieved_at FROM object "
                          "WHERE id = %s", (oid,)).fetchone()
        if row is None:
            return None
        paths = [r["path"] for r in cur.execute("SELECT path FROM object_path WHERE object_id = %s ORDER BY path",
                                                 (oid,))]
        versions = cur.execute("SELECT n, digest, size, recorded_at FROM object_version WHERE object_id = %s "
                               "ORDER BY n", (oid,)).fetchall()
    out = {"id": str(row["id"]), "kind": row["kind"]}
    out |= {k: row[k] for k in ("original_name", "media_type", "format_puid", "url") if row[k] is not None}
    if row["retrieved_at"] is not None:
        out["retrieved_at"] = row["retrieved_at"].isoformat()
    if paths:
        out["logical_paths"] = paths
    out["versions"] = [{"n": v["n"], **({"digest": v["digest"], "size": v["size"]} if v["digest"] else {}),
                        "recorded_at": v["recorded_at"].isoformat()} for v in versions]
    return out


def object_by_path(conn: psycopg.Connection, path: str) -> str | None:
    """Путь в папке документов → ссылка obj:<UUID> или None; путь — как у objects.ingest («\\» — это «/»)."""
    key = posixpath.normpath(path.strip().replace("\\", "/"))
    row = conn.execute("SELECT object_id FROM object_path WHERE path = normalize(%s, NFC)", (key,)).fetchone()
    return f"obj:{row[0]}" if row else None


def object_status(conn: psycopg.Connection, object_id: uuid.UUID | str) -> dict | None:
    """Последняя отметка, что из объекта атомизировано: status, note, agent, changed_at; None — отметок нет."""
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute("SELECT status, note, agent, changed_at FROM object_status WHERE object_id = %s "
                          "ORDER BY changed_at DESC, id DESC LIMIT 1", (str(object_uuid(object_id)),)).fetchone()
    if row is None:
        return None
    return {"status": row["status"], **({"note": row["note"]} if row["note"] else {}), "agent": row["agent"],
            "changed_at": row["changed_at"].isoformat()}
