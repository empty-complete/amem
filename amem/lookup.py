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
    """Условие «ревизия r — та, по которой запись показывается в списке и в подписях»: у её записи нет ревизии
    лучше. Лучше — не отклонённая, затем не ждущая проверки, затем с большим n: это текущая ревизия ({t}_current —
    последняя none или accepted, иначе последняя pending), а у записи без текущей (её единственная ревизия
    отклонена) — последняя. Без этого такая запись выпала бы из списка, хотя дерево папок (folders.tree) её считает.

    Условие на одну ревизию, а не подзапрос на запись: страница идёт по индексу {t}_revision_recorded
    (миграция 0009) и проверяет только ревизии, дошедшие до неё; для подсчёта соединение выбирает PostgreSQL."""
    return (f"NOT EXISTS (SELECT 1 FROM {t}_revision y WHERE y.{t}_id = r.{t}_id AND "
            "(y.review_state <> 'declined', y.review_state <> 'pending', y.n) > "
            "(r.review_state <> 'declined', r.review_state <> 'pending', r.n))")


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


def _record_filters(t: Target, path: str | None, kinds, statuses) -> list[str]:
    """Условия фильтра на строку записи rec (папка, вид или класс, статус) — им не нужна ревизия."""
    where = []
    if path == folders.NO_FOLDER:
        where.append("rec.folder IS NULL")
    elif path:
        where.append("(rec.folder = %(folder)s OR starts_with(rec.folder, %(folder)s || '/'))")
    if kinds:
        where.append(f"rec.{'kind' if t == 'atom' else 'entity_class'} = ANY(%(kinds)s::text[])")
    if statuses:
        where.append("rec.status = ANY(%(statuses)s::text[])")
    return where


def _revision_filters(tag, about_id) -> list[str]:
    """Условия фильтра на показанную ревизию атома r: тег и about."""
    where = []
    if tag:
        where.append("r.payload->'tags' @> %(tag)s")
    if about_id:
        where.append("EXISTS (SELECT 1 FROM atom_about ab WHERE ab.revision_id = r.id AND ab.entity_id = %(about)s)")
    return where


def _list_page(t: Target, where: list[str], after) -> str:
    """Страница записей вида t: показанные ревизии под фильтром, по индексу (recorded_at, id записи) с конца."""
    kind = "kind" if t == "atom" else "entity_class"
    lists = ("coalesce(r.payload->'about', '[]') AS about, coalesce(r.payload->'tags', '[]') AS tags" if t == "atom"
             else "'[]'::jsonb AS about, '[]'::jsonb AS tags")
    if after:
        where = [*where, f"(r.recorded_at, r.{t}_id) < (%(after_at)s::timestamptz, %(after_id)s::uuid)"]
    return (f"(SELECT '{t}' AS target, r.{t}_id AS id, rec.{kind} AS kind_or_class, rec.status, rec.folder, "
            f"r.payload->'label'->>'ru' AS label, {lists}, r.recorded_at, cs.agent "
            f"FROM {t}_revision r JOIN {t} rec ON rec.id = r.{t}_id JOIN changeset cs ON cs.id = r.changeset_id "
            f"WHERE {' AND '.join([_shown(t), *where])} "
            f"ORDER BY r.recorded_at DESC, r.{t}_id DESC LIMIT %(take)s)")


def _list_total(targets: list[Target], path, kinds, statuses, revision_where: list[str]) -> str:
    """Сколько записей под фильтром. Без фильтров по ревизии — по строкам записей (у каждой записи ровно одна
    показанная ревизия, и искать её не нужно), иначе — по показанным ревизиям атомов."""
    if revision_where:
        record_where = _record_filters("atom", path, kinds, statuses)
        join = "JOIN atom rec ON rec.id = r.atom_id " if record_where else ""     # без фильтров записи — не нужна
        return (f"SELECT count(*) FROM atom_revision r {join}"
                f"WHERE {' AND '.join([_shown('atom'), *record_where, *revision_where])}")
    counts = []
    for t in targets:
        where = _record_filters(t, path, kinds, statuses)
        counts.append(f"(SELECT count(*) FROM {t} rec WHERE {' AND '.join(where) or 'TRUE'})")
    return f"SELECT {' + '.join(counts)}"


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
    (непрозрачная строка). Пока записи не меняются, страницы идут без пропусков и повторов. Курсор держится за
    recorded_at показанной ревизии, поэтому запись, у которой она сменилась, при листании переезжает: новая
    ревизия поднимает запись наверх — ещё не пролистанная, она пропадёт из оставшихся страниц, — а отклонение
    ревизии, ждущей проверки, может вернуть запись к прежней, более старой ревизии, и тогда она повторится.

    Ответ: items, next_cursor (None — страница последняя), total — сколько записей под фильтром. Страница
    и total читаются в одной транзакции REPEATABLE READ — из одного снимка базы.
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
    after = _after(cursor)
    path = folder if folder in (None, "", folders.NO_FOLDER) else folders.check(folder)
    params = {"folder": path, "kinds": kinds, "statuses": statuses, "tag": Jsonb([tag]) if tag else None,
              "take": limit + 1, "after_at": after[0] if after else None, "after_id": after[1] if after else None}

    # своя транзакция — REPEATABLE READ: страница и total из одного снимка; внутри чужой — её снимок
    own = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    with conn.transaction():
        if own:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        about_id = None
        if about is not None and about != "":
            if parse_ref(about)[0] != "entity":
                raise RecordError(f"about {about!r}: нужна ссылка на сущность ent:<UUID или ключ>")
            about_id = resolve(conn, about)[1]
        params["about"] = about_id
        revision_where = _revision_filters(tag, about_id)
        # у сущностей нет ни тегов, ни about: с этими фильтрами — только атомы
        targets = ["atom"] if revision_where else list(TARGET.values())
        pages = [_list_page(t, [*_record_filters(t, path, kinds, statuses), *revision_where], after) for t in targets]
        # prepare=False: план — под значения фильтров. Подготовленный запрос PostgreSQL со временем исполняет общим
        # планом, а редкому тегу или маленькой папке нужен другой путь (индекс фильтра), чем частому (обход по времени)
        with conn.cursor(row_factory=dict_row) as cur:
            rows = cur.execute(f"SELECT * FROM ({' UNION ALL '.join(pages)}) p "
                               "ORDER BY p.recorded_at DESC, p.id DESC LIMIT %(take)s", params,
                               prepare=False).fetchall()
        total = conn.execute(_list_total(targets, path, kinds, statuses, revision_where), params,
                             prepare=False).fetchone()[0]
    more = len(rows) > limit
    page = rows[:limit]
    items = [{"ref": f"{PREFIX[r['target']]}:{r['id']}", "target": r["target"], "label": r["label"],
              "kind_or_class": r["kind_or_class"], "status": r["status"], "folder": r["folder"],
              "about": r["about"], "tags": r["tags"], "recorded_at": r["recorded_at"].isoformat(),
              "agent": r["agent"]} for r in page]
    return {"items": items, "next_cursor": _cursor(page[-1]["recorded_at"], page[-1]["id"]) if more else None,
            "total": total}


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
                        f"FROM {t} rec JOIN {t}_revision r ON r.{t}_id = rec.id AND {_shown(t)} "
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


_SHEET_SUFFIXES = (".xlsx", ".xlsm")


def _citations(conn: psycopg.Connection, object_id: str) -> list[dict]:
    """Источники текущих ревизий, ссылающиеся на объект: запись, версия объекта, селекторы, цитата, итог сверки."""
    out = []
    with conn.cursor(row_factory=dict_row) as cur:
        for target in ("atom", "entity"):
            rows = cur.execute(
                f"SELECT r.{target}_id AS record_id, s.object_version, s.selectors, s.quote, s.verdict "
                f"FROM source s JOIN {target}_current r ON r.id = s.{target}_revision_id "
                f"WHERE s.object_id = %s ORDER BY r.{target}_id, s.object_version, s.position", (object_id,))
            for r in rows:
                item = {"record": f"{PREFIX[target]}:{r['record_id']}", "version": r["object_version"]}
                item |= {k: r[k] for k in ("selectors", "quote", "verdict") if r[k] is not None}
                out.append(item)
    return out


def object_view(conn: psycopg.Connection, object_id: uuid.UUID | str) -> dict | None:
    """Карточка объекта для сайта: get_object и поля status, cited_by, pages, sheets; None — объекта нет.

    status — строка последней отметки или None; cited_by — источники текущих ревизий; pages — число страниц
    из кэша текста последней версии или None, если текст не извлекали или его нет (на чтении не извлекаем);
    sheets — имена листов xlsx/xlsm (первая строка страницы извлечённого текста), у остальных None."""
    view = get_object(conn, object_id)
    if view is None:
        return None
    mark = object_status(conn, view["id"])
    view["status"] = mark["status"] if mark else None
    view["cited_by"] = _citations(conn, view["id"])
    pages = None
    digest = next((v["digest"] for v in reversed(view["versions"]) if "digest" in v), None)
    if digest:
        cached = conn.execute("SELECT page, text FROM object_text WHERE digest = %s ORDER BY page",
                              (digest,)).fetchall()
        if cached and cached[0][0] != 0:
            pages = [t for _, t in cached]
    view["pages"] = len(pages) if pages is not None else None
    names = [view.get("original_name", ""), *view.get("logical_paths", [])]
    is_book = any(n.lower().endswith(_SHEET_SUFFIXES) for n in names)
    view["sheets"] = [p.split("\n", 1)[0] for p in pages] if is_book and pages is not None else None
    return view
