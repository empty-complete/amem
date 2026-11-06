"""Чтение схемы v1: запись с текущей ревизией или «как было на момент», история, редакции на дату, связи;
список записей и подписи для экранов; объекты источников, их статус и источники ревизии.

Запись отдаётся словарём в формате model_v1.Atom / model_v1.Entity: тело ревизии + технические поля.
Запись можно назвать UUID или ссылкой atm:/ent: с UUID или ключом (records.resolve).
«На момент» (at) — время транзакции: что база знала тогда, включая решения проверки, принятые до этого момента.
at — только время с часовым поясом: время без пояса база прочла бы в поясе сеанса и ошиблась бы на часы.
"""
from __future__ import annotations

import base64
import posixpath
import unicodedata
import uuid
from collections.abc import Iterable
from datetime import date, datetime

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import folders, search
from .objects import object_uuid
from .records import (PREFIX, TARGET, RecordError, RecordNotFound, Target, as_uuid, check_target, parse_ref,
                      resolve)

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


def _record_id(conn: psycopg.Connection, target: Target, value) -> str | None:
    """UUID записи для get и history: UUID, его строка или ссылка atm:/ent: с UUID или ключом.

    Ссылка на запись другого вида — RecordError; по ключу записи нет — None, как у UUID, которого нет."""
    if not (isinstance(value, str) and ":" in value):
        return _uuid(value)
    found, record_id, _ = parse_ref(value)
    if found != target:
        raise RecordError(f"{value}: ссылка на запись {found}, а нужна {target}")
    if record_id is not None:
        return str(record_id)
    try:
        return str(resolve(conn, value)[1])
    except RecordNotFound:
        return None


def _moment(at: datetime | None) -> datetime | None:
    if at is not None and (not isinstance(at, datetime) or at.tzinfo is None):
        raise RecordError(f"at {at!r}: нужно время с часовым поясом (datetime с tzinfo)")
    return at


def get(conn: psycopg.Connection, target: Target, record_id: uuid.UUID | str, *,
        at: datetime | None = None) -> dict | None:
    """Запись с текущей ревизией; at — как база видела её в этот момент (статус и решение проверки — тоже).

    record_id — UUID или ссылка atm:/ent: с UUID или ключом; записи нет — None."""
    check_target(target)
    at = _moment(at)
    record_id = _record_id(conn, target, record_id)
    if record_id is None:
        return None
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
        row = cur.execute(sql, {"id": record_id, "at": at}).fetchone()
    if row is None or row["status"] is None:
        return None
    return _record(row, target)


def history(conn: psycopg.Connection, target: Target, record_id: uuid.UUID | str) -> list[dict]:
    """Все ревизии записи по порядку: id, n, schema_version, content_hash, payload (каноническое тело),
    review_state, recorded_at, changeset_id, agent — подборка с историей берёт их отсюда как есть.

    record_id — как у get; записи нет — пустой список."""
    check_target(target)
    record_id = _record_id(conn, target, record_id)
    if record_id is None:
        return []
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(f"SELECT r.id, r.n, r.schema_version, r.content_hash, r.payload, r.review_state, "
                           f"r.recorded_at, r.changeset_id, cs.agent FROM {target}_revision r "
                           f"JOIN changeset cs ON cs.id = r.changeset_id WHERE r.{target}_id = %s ORDER BY r.n",
                           (record_id,)).fetchall()


def by_key(conn: psycopg.Connection, target: Target, key: str) -> str | None:
    """Ключ → каноническая ссылка atm:/ent:<UUID> или None."""
    check_target(target)
    row = conn.execute(f"SELECT id FROM {target} WHERE key = %s", (key,)).fetchone()
    return f"{PREFIX[target]}:{row[0]}" if row else None


LIST_LIMIT = 200            # записей на страницу списка, не больше; дальше — по курсору


def _shown(t: Target) -> str:
    """Ревизия, по которой запись показывается в списке и в подписях: текущая (как {t}_current — последняя none
    или accepted, иначе последняя pending), а у записи без текущей (её единственная ревизия отклонена) —
    последняя. Без этого такая запись выпала бы из списка, хотя дерево папок (folders.tree) её считает."""
    return (f"(SELECT x.id, x.payload, x.recorded_at, x.changeset_id FROM {t}_revision x WHERE x.{t}_id = rec.id "
            "ORDER BY x.review_state = 'declined', x.review_state = 'pending', x.n DESC LIMIT 1)")


def _codes(values, name: str) -> list[str] | None:
    """Набор кодов фильтра; пустой — без фильтра, как None (так приходит параметр запроса, которого нет)."""
    if values is None:
        return None
    if isinstance(values, str) or not isinstance(values, Iterable):
        raise RecordError(f"{name}: нужен набор кодов, а не {type(values).__name__}")
    items = list(values)
    if not all(isinstance(v, str) for v in items):
        raise RecordError(f"{name}: коды — строки")
    return list(dict.fromkeys(items)) or None


def _cursor(recorded_at: datetime, record_id: uuid.UUID) -> str:
    raw = f"{recorded_at.isoformat()}|{record_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _after(cursor) -> tuple[datetime, uuid.UUID] | None:
    """Курсор next_cursor → (recorded_at, id) последней записи прошлой страницы; None или «» — с начала."""
    if cursor is None or cursor == "":
        return None
    try:
        if not isinstance(cursor, str):
            raise ValueError("не строка")
        text = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        moment, _, record_id = text.partition("|")
        at = datetime.fromisoformat(moment)
        if at.tzinfo is None:
            raise ValueError("время без пояса")
        return at, uuid.UUID(record_id)
    except ValueError as e:            # и binascii.Error, и UnicodeDecodeError — подклассы ValueError
        raise RecordError(f"cursor {cursor!r}: не курсор списка записей — нужен next_cursor прошлой страницы") from e


def _list_branch(t: Target, *, path: str | None, kinds, statuses, tag, about_id) -> str:
    """SELECT сводок записей вида t под фильтром; значения фильтров — параметры запроса list_records."""
    kind = "kind" if t == "atom" else "entity_class"
    where = []
    if path == folders.NO_FOLDER:
        where.append("rec.folder IS NULL")
    elif path:
        where.append("(rec.folder = %(folder)s OR starts_with(rec.folder, %(folder)s || '/'))")
    if kinds:
        where.append(f"rec.{kind} = ANY(%(kinds)s::text[])")
    if statuses:
        where.append("rec.status = ANY(%(statuses)s::text[])")
    if tag:
        where.append("r.payload->'tags' @> %(tag)s")
    if about_id:
        # сначала атомы, у которых сущность была в about любой ревизии (по индексу atom_about_entity), затем —
        # есть ли она в показанной: условие на rec.id без этого PostgreSQL проверял бы все атомы базы
        where.append("rec.id = ANY(ARRAY(SELECT ar.atom_id FROM atom_about g "
                     "JOIN atom_revision ar ON ar.id = g.revision_id WHERE g.entity_id = %(about)s)) "
                     "AND EXISTS (SELECT 1 FROM atom_about ab WHERE ab.revision_id = r.id "
                     "AND ab.entity_id = %(about)s)")
    if t == "atom":
        about, tags = "coalesce(r.payload->'about', '[]')", "coalesce(r.payload->'tags', '[]')"
    else:
        about = tags = "'[]'::jsonb"
    return (f"SELECT '{t}' AS target, rec.id, rec.{kind} AS kind_or_class, rec.status, rec.folder, "
            f"r.payload->'label'->>'ru' AS label, {about} AS about, {tags} AS tags, r.recorded_at, cs.agent "
            f"FROM {t} rec CROSS JOIN LATERAL {_shown(t)} r JOIN changeset cs ON cs.id = r.changeset_id "
            f"WHERE {' AND '.join(where) or 'TRUE'}")


def list_records(conn: psycopg.Connection, *, folder: str | None = None, kinds: Iterable[str] | None = None,
                 statuses: Iterable[str] | None = None, tag: str | None = None, about: str | None = None,
                 limit: int = 50, cursor: str | None = None) -> dict:
    """Сводки записей для списка (панель папок, «Все записи»): новые сверху, страницами по курсору.

    Фильтры складываются (И):
    - folder — папка вместе с вложенными; «-» — записи без папки; None или «» — все;
    - kinds — коды вида атома или класса сущности (kind_or_class);
    - statuses — статусы; по умолчанию все, как в дереве папок: иначе счётчики папок и список разошлись бы;
    - tag — тег атома; about — сущность (ent: с UUID или ключом), о которой текущая ревизия атома. У сущностей
      нет ни тегов, ни about: с этими фильтрами их в списке нет.
    Пустой набор kinds или statuses — без фильтра, как None.

    Порядок — recorded_at показанной ревизии по убыванию, затем id; cursor — next_cursor прошлой страницы
    (непрозрачная строка), страницы идут без пропусков и повторов. Ответ: items, next_cursor (None — страница
    последняя), total — сколько записей под фильтром, в том же снимке, что и страница.
    Сводка: ref, target, label (ru), kind_or_class, status, folder, about (ссылки ent:), tags, recorded_at, agent."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= LIST_LIMIT:
        raise RecordError(f"limit {limit!r}: нужно целое число от 1 до {LIST_LIMIT}")
    kinds = _codes(kinds, "kinds")
    statuses = _codes(statuses, "statuses")
    unknown = set(statuses or ()) - set(search._STATUSES)
    if unknown:
        raise RecordError(f"statuses: неизвестные статусы {', '.join(sorted(unknown))}")
    if tag is not None and not isinstance(tag, str):
        raise RecordError(f"tag {tag!r}: нужна строка")
    tag = unicodedata.normalize("NFC", tag) if tag else None          # теги в теле ревизии — в NFC (canon)
    about_id = None
    if about is not None and about != "":
        if parse_ref(about)[0] != "entity":
            raise RecordError(f"about {about!r}: нужна ссылка на сущность ent:<UUID или ключ>")
        about_id = resolve(conn, about)[1]
    after = _after(cursor)
    path = folder if folder in (None, "", folders.NO_FOLDER) else folders.check(folder)

    filters = {"path": path, "kinds": kinds, "statuses": statuses, "tag": tag, "about_id": about_id}
    branches = [_list_branch(t, **filters) for t in TARGET.values() if t == "atom" or not (tag or about_id)]
    page_filter = "(b.recorded_at, b.id) < (%(after_at)s::timestamptz, %(after_id)s::uuid)" if after else "TRUE"
    # один запрос — один снимок: total и страница не расходятся; LEFT JOIN — total есть и у пустой страницы
    sql = (f"WITH base AS ({' UNION ALL '.join(branches)}) "
           "SELECT t.total, p.* FROM (SELECT count(*) AS total FROM base) t LEFT JOIN LATERAL ("
           f"SELECT * FROM base b WHERE {page_filter} ORDER BY b.recorded_at DESC, b.id DESC LIMIT %(take)s) p ON TRUE")
    params = {"folder": path, "kinds": kinds, "statuses": statuses, "tag": Jsonb([tag]) if tag else None,
              "about": about_id, "take": limit + 1,
              "after_at": after[0] if after else None, "after_id": after[1] if after else None}
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(sql, params).fetchall()
    page = [r for r in rows if r["id"] is not None]
    more = len(page) > limit
    page = page[:limit]
    items = [{"ref": f"{PREFIX[r['target']]}:{r['id']}", "target": r["target"], "label": r["label"],
              "kind_or_class": r["kind_or_class"], "status": r["status"], "folder": r["folder"],
              "about": r["about"], "tags": r["tags"], "recorded_at": r["recorded_at"].isoformat(),
              "agent": r["agent"]} for r in page]
    return {"items": items, "next_cursor": _cursor(page[-1]["recorded_at"], page[-1]["id"]) if more else None,
            "total": rows[0]["total"]}


def labels(conn: psycopg.Connection, refs: Iterable[str]) -> dict[str, dict]:
    """Подписи записей одним запросом: {ref: {label, kind | entity_class, status}} — подпись (ru) показанной
    ревизии (как в list_records), вид атома или класс сущности, статус.

    Ссылки — atm:/ent: с UUID или ключом; ключ ответа — ссылка как в запросе. Неизвестной или неверной ссылки
    в ответе нет: подписи нужны экрану, и одна битая ссылка не должна ронять весь ответ."""
    if isinstance(refs, str) or not isinstance(refs, Iterable):
        raise RecordError(f"refs: нужен набор ссылок, а не {type(refs).__name__}")
    by_id: dict[tuple[str, uuid.UUID], list[str]] = {}       # (вид, id) → ссылки запроса
    by_key: dict[tuple[str, str], list[str]] = {}            # (вид, ключ) → ссылки запроса
    for ref in refs:
        try:
            target, record_id, key = parse_ref(ref)
        except RecordError:
            continue
        found = by_id.setdefault((target, record_id), []) if record_id else by_key.setdefault((target, key), [])
        if ref not in found:
            found.append(ref)
    if not by_id and not by_key:
        return {}
    params, branches = {}, []
    for t in TARGET.values():
        params[f"{t}_ids"] = [record_id for target, record_id in by_id if target == t]
        params[f"{t}_keys"] = [key for target, key in by_key if target == t]
        kind = "kind" if t == "atom" else "entity_class"
        branches.append(f"SELECT '{t}', rec.id, rec.key, rec.{kind}, rec.status, r.payload->'label'->>'ru' "
                        f"FROM {t} rec CROSS JOIN LATERAL {_shown(t)} r "
                        f"WHERE rec.id = ANY(%({t}_ids)s::uuid[]) OR rec.key = ANY(%({t}_keys)s::text[])")
    out: dict[str, dict] = {}
    for target, record_id, key, code, status, label in conn.execute(" UNION ALL ".join(branches), params):
        info = {"label": label, "kind" if target == "atom" else "entity_class": code, "status": status}
        for ref in by_id.get((target, record_id), []) + by_key.get((target, key), []):
            out[ref] = dict(info)
    return out


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
                      revision_ids: Iterable[uuid.UUID | str]) -> dict[uuid.UUID, list[dict]]:
    """Источники нескольких ревизий одним запросом, как у revision_sources.

    На входе — UUID или строки; ключи ответа — uuid.UUID, по ключу на каждую запрошенную ревизию (без источников —
    пустой список)."""
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
