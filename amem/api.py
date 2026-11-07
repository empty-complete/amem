"""Операции в форме ответов HTTP-контракта v1 (docs/api/http-v1.openapi.yaml) — без Starlette.

Их зовут служба HTTP (amem/service/http_v1.py), MCP и CLI, поэтому три входа не расходятся. Операция получает
соединение (autocommit, как db.connect), хранилище объектов или каталог бэкапов, агента и простые аргументы — числа
и флаги можно строками, как они приходят в запросе, — и отдаёт словарь, готовый к JSON, в форме схемы контракта.

Параметры проверяются по контракту (пределы, перечисления, формат) до вызова библиотеки: неверный — BadRequest
(400 у службы). Пустой список фильтра (kind, status, entity_class, rels) — «без фильтра», как параметр, которого
в запросе нет; пустой range листа — окно по умолчанию библиотеки. Текст поиска проходит private.strip до поиска
и журнала выдачи.

Подписи записей — lookup.labels одним запросом на ответ (label — русская подпись показанной ревизии); запись,
которой нет, подписывается своей ссылкой. Записи называются atm:/ent:<UUID>, объекты — голым UUID, как id
в ObjectView: так их и передаёт интерфейс в /objects/{id} и в about=obj:<id>.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from . import __version__, backup, db, folders, lookup, objects, private, profile, recipes, records, review, \
    usefulness, vocab
from .model_v1 import Status
from .ocfl_store import ObjectStore, StoreError

STATUSES = tuple(s.value for s in Status)
TARGETS = ("atom", "entity")
WHO = recipes.WHO
REVIEW_OPEN = ("queued", "claimed")
GRAPH_NODES = 500                   # узлов графа в ответе, не больше: дальше — truncated
ANCESTORS_DEPTH = 32                # цепочка part_of длиннее — обрывается (циклы обрываются по посещённым)
# файлы версий, которые браузер показывает сам; остальное отдаётся на скачивание (application/octet-stream)
INLINE_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "text/plain"})
_REF = re.compile(r"(atm|ent):.+")
_INT = re.compile(r"[+-]?[0-9]+")


class BadRequest(ValueError):
    """Параметр операции вне контракта: предел, перечисление, формат. У службы — 400 bad_request."""


# --- разбор параметров ---

def _int(value, name: str, *, low: int, high: int | None = None, default: int | None = None) -> int | None:
    """Целое из аргумента или строки запроса; None — default. Вне [low, high] — BadRequest."""
    if value is None or value == "":
        return default
    if isinstance(value, str) and _INT.fullmatch(value.strip()):
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise BadRequest(f"{name} {value!r}: нужно целое число")
    if value < low or (high is not None and value > high):
        bounds = f"от {low} до {high}" if high is not None else f"от {low}"
        raise BadRequest(f"{name} {value}: нужно целое число {bounds}")
    return value


def _bool(value, name: str, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false", "1", "0"):
        return value.strip().lower() in ("true", "1")
    raise BadRequest(f"{name} {value!r}: нужно true или false")


def _enum(value, name: str, allowed, *, default: str | None = None) -> str | None:
    if value is None or value == "":
        return default
    if value not in allowed:
        raise BadRequest(f"{name} {value!r}: допустимы {', '.join(allowed)}")
    return value


def _codes(values, name: str) -> list[str] | None:
    """Набор кодов фильтра: строка — один код; пустой набор — без фильтра (None)."""
    if values is None:
        return None
    if isinstance(values, str):
        values = [values]
    try:
        items = list(values)
    except TypeError:
        raise BadRequest(f"{name}: нужен список кодов") from None
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise BadRequest(f"{name}: код {item!r} — нужна непустая строка")
    return list(dict.fromkeys(items)) or None


def _statuses(values) -> list[str] | None:
    statuses = _codes(values, "status")
    unknown = sorted(set(statuses or ()) - set(STATUSES))
    if unknown:
        raise BadRequest(f"status: неизвестные статусы {', '.join(unknown)}; допустимы {', '.join(STATUSES)}")
    return statuses


def _ref(value, name: str = "ref") -> str:
    if not isinstance(value, str) or not _REF.fullmatch(value):
        raise BadRequest(f"{name} {value!r}: нужна ссылка atm:<UUID или ключ> или ent:<UUID или ключ>")
    return value


def _moment(value, name: str) -> datetime | None:
    """Время ISO 8601 с часовым поясом; без пояса база прочла бы его в поясе сеанса."""
    if value is None or value == "":
        return None
    moment = value
    if isinstance(value, str):
        # «+03:00» в строке запроса без %2B приходит как « 03:00»: «+» там — пробел
        text = re.sub(r"([Tt ][0-9:.,]+) ([0-9]{2}(?::?[0-9]{2})?)$", r"\1+\2", value.strip())
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            raise BadRequest(f"{name} {value!r}: нужно время ISO 8601, например 2026-11-07T09:00:00Z") from None
    if not isinstance(moment, datetime) or moment.tzinfo is None or moment.utcoffset() is None:
        raise BadRequest(f"{name} {value!r}: нужно время с часовым поясом (…Z или …+03:00)")
    return moment


def _text(value) -> str | None:
    """Подпись из LangString: ru, иначе en, иначе первая; строка — как есть."""
    if isinstance(value, dict):
        return value.get("ru") or value.get("en") or next((v for v in value.values() if isinstance(v, str)), None)
    return value if isinstance(value, str) else None


def _iso(value) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def _object_id(value) -> uuid.UUID:
    """id объекта из пути запроса: UUID или obj:<UUID>."""
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str):
        raise BadRequest(f"id {value!r}: нужен UUID объекта")
    try:
        return uuid.UUID(value[4:] if value.startswith("obj:") else value)
    except ValueError:
        raise BadRequest(f"id {value!r}: нужен UUID объекта (или obj:<UUID>)") from None


# --- подписи ---

def _labels(conn: psycopg.Connection, refs) -> dict[str, dict]:
    """RefLabel для ссылок (atm:/ent:) одним запросом: ref, label, kind или entity_class."""
    refs = list(dict.fromkeys(r for r in refs if isinstance(r, str)))
    found = lookup.labels(conn, refs) if refs else {}
    out = {}
    for ref in refs:
        info = found.get(ref)
        label = {"ref": ref, "label": (info or {}).get("label") or ref}
        for key in ("kind", "entity_class"):
            if info and info.get(key):
                label[key] = info[key]
        out[ref] = label
    return out


def _kind_or_class(label: dict | None) -> str | None:
    return (label or {}).get("kind") or (label or {}).get("entity_class")


# --- сессия ---

def session(conn: psycopg.Connection, *, agent: str, can_write: bool, provider=None) -> dict:
    """Session: кто вошёл, какая база, есть ли смысловой поиск."""
    base = conn.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()
    return {"agent": agent, "base": base[0] if base else None, "base_name": db.base_name(conn),
            "amem_version": __version__, "semantic": recipes.availability(conn, provider)["semantic"],
            "can_write": can_write}


# --- поиск ---

def search(conn: psycopg.Connection, q, *, agent: str, kind=None, status=None, entity_class=None, target=None,
           limit=None, provider=None) -> dict:
    """SearchResult рецепта exact_fact; выдача пишется в retrieval от имени agent."""
    if not isinstance(q, str):
        raise BadRequest("q: нужен текст запроса")
    result = recipes.exact_fact(
        conn, private.strip(q), agent=agent, limit=_int(limit, "limit", low=1, high=100, default=10),
        target=_enum(target, "target", TARGETS), kind=_codes(kind, "kind"),
        entity_class=_codes(entity_class, "entity_class"), statuses=_statuses(status), provider=provider)
    return _search_result(conn, result)


def similar(conn: psycopg.Connection, *, agent: str, ref=None, q=None, limit=None, provider=None) -> dict:
    """SearchResult рецепта similar — по ссылке на запись (ref) или по тексту (q), ровно одно из двух."""
    if (ref in (None, "")) == (q in (None, "")):
        raise BadRequest("similar: нужен ровно один из параметров ref (atm:/ent:) или q (текст)")
    if ref not in (None, ""):
        query = _ref(ref)
    else:
        if not isinstance(q, str):
            raise BadRequest("q: нужен текст запроса")
        query = private.strip(q)
        if query.startswith(("atm:", "ent:")):
            raise BadRequest("q: похожие на запись ищутся по параметру ref, а не по тексту atm:/ent:")
    result = recipes.similar(conn, query, agent=agent, limit=_int(limit, "limit", low=1, high=100, default=10),
                             provider=provider)
    return _search_result(conn, result)


def _search_result(conn: psycopg.Connection, result: dict) -> dict:
    items = result["items"]
    labels = _labels(conn, [item["ref"] for item in items])
    about = _current_about(conn, items)
    about_labels = _labels(conn, [ref for refs in about.values() for ref in refs])
    hits = []
    for item in items:
        label = labels[item["ref"]]
        hit = {"ref": item["ref"], "revision": item["revision"], "label": _text(item["label"]) or label["label"],
               "snippet": item["snippet"], "status": item["status"], "review_state": item["review_state"]}
        for key in ("kind", "entity_class"):
            if key in label:
                hit[key] = label[key]
        hit["about"] = [about_labels[ref] for ref in about.get(item["ref"], [])]
        hit["score"] = item["score"]
        hit["matches"] = [{"channel": m["channel"], "rank": m["rank"], "source_rank": m["source_rank"]}
                          for m in item["matches"]]
        hits.append(hit)
    coverage = result["embedding_coverage"]          # {total, covered, …} активной модели → доля; пустая база — 1
    if isinstance(coverage, dict):
        coverage = coverage["covered"] / coverage["total"] if coverage["total"] else 1.0
    return {"recipe": result["recipe"], "ranking_version": result["ranking_version"], "channels": result["channels"],
            "semantic": result["semantic"], "candidate_count": result["candidate_count"],
            "embedding_coverage": coverage, "items": hits,
            "retrieval_id": str(result["retrieval_id"]) if result["retrieval_id"] is not None else None}


def _current_about(conn: psycopg.Connection, items: list[dict]) -> dict[str, list[str]]:
    """about ревизий выдачи (атомы): ref → ссылки ent: по порядку тела."""
    atoms = [(item["ref"].split(":", 1)[1], item["revision"]) for item in items if item["ref"].startswith("atm:")]
    if not atoms:
        return {}
    rows = conn.execute(
        "SELECT r.atom_id, r.payload->'about' FROM atom_revision r "
        "JOIN unnest(%s::uuid[], %s::int[]) AS q(id, n) ON r.atom_id = q.id AND r.n = q.n",
        ([a for a, _ in atoms], [n for _, n in atoms])).fetchall()
    return {f"atm:{atom_id}": [ref for ref in (about or []) if isinstance(ref, str)] for atom_id, about in rows}


# --- папки и списки ---

def folder_tree(conn: psycopg.Connection) -> dict:
    """FolderTree: реестр папок со счётчиками по вложенности."""
    return folders.tree(conn)


def record_list(conn: psycopg.Connection, *, folder=None, kind=None, status=None, tag=None, about=None, limit=None,
                cursor=None) -> dict:
    """RecordList: сводки записей под фильтром, страница по курсору; about — ent:… или объект (obj:<UUID>, UUID)."""
    for name, value in (("folder", folder), ("tag", tag), ("about", about), ("cursor", cursor)):
        if value is not None and not isinstance(value, str):
            raise BadRequest(f"{name} {value!r}: нужна строка")
    page = lookup.list_records(conn, folder=folder or None, kinds=_codes(kind, "kind"), statuses=_statuses(status),
                               tag=tag or None, about=about or None,
                               limit=_int(limit, "limit", low=1, high=lookup.LIST_LIMIT, default=50),
                               cursor=cursor or None)
    labels = _labels(conn, [ref for item in page["items"] for ref in item["about"]])
    items = [{**item, "about": [labels[ref] for ref in item["about"] if isinstance(ref, str)]}
             for item in page["items"]]
    return {"items": items, "next_cursor": page["next_cursor"], "total": page["total"]}


# --- запись ---

def record(conn: psycopg.Connection, ref) -> dict:
    """RecordView: показанная ревизия записи (текущая; у записи, чьи ревизии все отклонены, — последняя), источники,
    открытые пункты очереди и полезность."""
    target, record_id = records.resolve(conn, _ref(ref))          # нет записи — RecordNotFound (404)
    t = target
    current = lookup.get(conn, target, record_id)
    with conn.cursor(row_factory=dict_row) as cur:
        if current is not None:
            shown = cur.execute(f"SELECT id, n, payload FROM {t}_revision WHERE {t}_id = %s AND n = %s",
                                (record_id, current["revision"])).fetchone()
            shown |= {"review_state": current["review_state"], "recorded_at": current["recorded_at"],
                      "agent": current["agent"], "status": current["status"], "folder": current["folder"]}
        else:
            # текущей ревизии нет (все отклонены): список записей и подписи показывают последнюю — и здесь она
            shown = lookup.history(conn, target, record_id)[-1]
            shown |= cur.execute(f"SELECT status, folder FROM {t} WHERE id = %s", (record_id,)).fetchone()
            shown["recorded_at"] = shown["recorded_at"].isoformat()
    payload = shown["payload"]
    canonical = f"{records.PREFIX[target]}:{record_id}"
    about = [r for r in payload.get("about") or [] if isinstance(r, str)] if target == "atom" else []
    chain = _ancestors(conn, about[0] if about else (canonical if target == "entity" else None))
    items = [row for state in REVIEW_OPEN for row in review.items(conn, state=state, record=canonical, limit=500)]
    labels = _labels(conn, [canonical, *about, *chain])
    score = None
    if target == "atom":
        try:
            score = usefulness.score(conn, record_id)
        except ValueError:                       # отметка из будущего (часы ушли назад) — польза не считается
            score = None
    return {
        "ref": canonical, "target": target, "revision": shown["n"], "payload": payload, "status": shown["status"],
        "review_state": shown["review_state"], "recorded_at": shown["recorded_at"], "agent": shown["agent"],
        "folder": shown["folder"], "about": [labels[r] for r in about], "ancestors": [labels[r] for r in chain],
        "sources": _sources(conn, target, shown["id"]),
        "open_items": [_review_item(row, labels) for row in sorted(items, key=lambda r: (r["created_at"], r["id"]))],
        "usefulness": score,
    }


def _ancestors(conn: psycopg.Connection, entity_ref: str | None) -> list[str]:
    """Цепочка part_of сущности вверх, от корня, без неё самой; у нескольких родителей — первый по id."""
    if entity_ref is None or not entity_ref.startswith("ent:"):
        return []
    try:
        current = uuid.UUID(entity_ref[4:])
    except ValueError:
        return []
    seen, chain = {current}, []
    for _ in range(ANCESTORS_DEPTH):
        row = conn.execute("SELECT dst_entity FROM link WHERE rel = 'part_of' AND src_entity = %s "
                           "AND dst_entity IS NOT NULL AND retired_at IS NULL ORDER BY dst_entity LIMIT 1",
                           (current,)).fetchone()
        if row is None or row[0] in seen:
            break
        current = row[0]
        seen.add(current)
        chain.append(f"ent:{current}")
    return chain[::-1]


def _sources(conn: psycopg.Connection, target: str, revision_id) -> list[dict]:
    """SourceView источников ревизии: объект (голый UUID), его имя, вид и тип, место, роль, итог сверки (или null)."""
    rows = lookup.revision_sources(conn, target, revision_id)
    ids = list(dict.fromkeys(row["object"].split(":", 1)[1] for row in rows))
    known = {}
    if ids:
        with conn.cursor(row_factory=dict_row) as cur:
            known = {str(o["id"]): o for o in cur.execute(
                "SELECT id, kind, original_name, url, media_type FROM object WHERE id = ANY(%s::uuid[])", (ids,))}
    out = []
    for row in rows:
        object_id = row["object"].split(":", 1)[1]
        obj = known.get(object_id, {})
        view = {"object": object_id}
        if obj.get("original_name") or obj.get("url"):
            view["object_name"] = obj.get("original_name") or obj.get("url")
        if obj.get("kind"):
            view["object_kind"] = obj["kind"]
        if obj.get("media_type"):
            view["media_type"] = obj["media_type"]
        view |= {"object_version": row["object_version"], "selectors": row.get("selectors") or []}
        for key in ("quote", "role", "page", "anchor", "edition", "checked_at"):
            if key in row:
                view[key] = row[key]
        view["verdict"] = row.get("verdict")
        out.append(view)
    return out


def _review_item(row: dict, labels: dict[str, dict]) -> dict:
    """ReviewItem из строки review.items: подпись и вид записи, время — ISO 8601."""
    label = labels.get(row["ref"])
    item = {"id": str(row["id"]), "ref": row["ref"]}
    if label is not None:
        item["label"] = label["label"]
        if _kind_or_class(label):
            item["kind_or_class"] = _kind_or_class(label)
    item |= {"reason": row["reason"], "state": row["state"], "details": row["details"],
             "created_at": _iso(row["created_at"]), "created_by": row["created_by"], "author": row["author"],
             "claimed_by": row["claimed_by"], "claimed_until": _iso(row["claimed_until"]),
             "closed_at": _iso(row["closed_at"])}
    return item


def history(conn: psycopg.Connection, ref) -> dict:
    """ChangesResult по записи: все её события по времени."""
    return _changes(conn, recipes.what_changed(conn, ref=_ref(ref)))


def changes(conn: psycopg.Connection, *, since=None, until=None, who=None, limit=None) -> dict:
    """ChangesResult по базе за [since, until): самые новые limit событий, по времени."""
    since, until = _moment(since, "since"), _moment(until, "until")
    if since is not None and until is not None and since >= until:
        raise BadRequest("since должен быть строго раньше until")
    return _changes(conn, recipes.what_changed(conn, since=since, until=until,
                                               who=_enum(who, "who", WHO, default="all"),
                                               limit=_int(limit, "limit", low=1, high=500, default=100)))


def _changes(conn: psycopg.Connection, result: dict) -> dict:
    """События what_changed с подписью записи. У событий связи ref — запись истории (по базе — начало связи)."""
    events = []
    for event in result["events"]:
        if "ref" not in event and "src" in event:
            event = {**event, "ref": result["ref"] or event["src"]}
        events.append(event)
    labels = _labels(conn, [event["ref"] for event in events if "ref" in event])
    for event in events:
        if event.get("ref") in labels:
            event["label"] = labels[event["ref"]]["label"]
    return {"ref": result["ref"], "since": result["since"], "until": result["until"], "events": events}


def links(conn: psycopg.Connection, ref) -> list[dict]:
    """LinkView[]: действующие связи записи с подписью другого конца."""
    target, record_id = records.resolve(conn, _ref(ref))
    own = f"{records.PREFIX[target]}:{record_id}"
    rows = lookup.links(conn, record_id)
    labels = _labels(conn, [row["dst"] if row["src"] == own else row["src"] for row in rows])
    out = []
    for row in rows:
        out_going = row["src"] == own
        out.append({"id": row["id"], "rel": row["rel"], "direction": "out" if out_going else "in",
                    "other": labels[row["dst"] if out_going else row["src"]], "note": row.get("note"),
                    "confidence": row.get("confidence"), "agent": row["agent"], "created_at": row["created_at"]})
    return out


# --- карточка и граф ---

def card(conn: psycopg.Connection, ref, *, ancestors=None) -> dict:
    """Card (amem.card/1): поля профиля с подписями величин; предки свёрнуты в RefLabel, от корня."""
    full = profile.card(conn, _ref(ref), ancestors=_bool(ancestors, "ancestors", default=True))
    properties = {code: _text(data.get("label")) for code, data in conn.execute(
        "SELECT code, data FROM concept WHERE scheme = 'property' AND code = ANY(%s)",
        ([f["property"] for f in full["fields"]],)).fetchall()}
    fields = []
    for field in full["fields"]:
        field = {**field, **{key: _text(field.get(key)) for key in ("ask", "hint", "when")}}
        if properties.get(field["property"]):
            field["label"] = properties[field["property"]]
        fields.append(field)

    def entity(view: dict) -> dict:
        return {"ref": view["ref"], "label": _text(view["label"]) or view["ref"],
                "entity_class": view["entity_class"]}

    return {**full, "entity": entity(full["entity"]), "fields": fields,
            "ancestors": [entity(parent["entity"]) for parent in reversed(full["ancestors"])]}


def graph(conn: psycopg.Connection, ref, *, depth=None, rels=None, status=None) -> dict:
    """GraphResult: кратчайшие пути от записи до depth шагов; больше GRAPH_NODES узлов — ближние и truncated."""
    found = recipes.around_entity(conn, _ref(ref), depth=_int(depth, "depth", low=1, high=3, default=1),
                                  rels=_codes(rels, "rels"), statuses=_statuses(status))
    nodes = found["nodes"]            # по удалению от начала: обрезка оставляет ближние
    truncated = len(nodes) > GRAPH_NODES
    nodes = nodes[:GRAPH_NODES]
    kept = {node["ref"] for node in nodes}
    labels = _labels(conn, kept)
    families = vocab.families(conn)
    out_nodes = []
    for node in nodes:
        code = node.get("kind") or node.get("entity_class")
        family = families.get(code, vocab.DEFAULT_FAMILY) if node["target"] == "atom" else "object"
        out_nodes.append({"ref": node["ref"], "label": labels[node["ref"]]["label"], "kind_or_class": code,
                          "family": family, "status": node["status"], "depth": node["depth"]})
    edges = [{"src": edge["src"], "dst": edge["dst"], "rel": edge["rel"], "confidence": edge["confidence"]}
             for edge in found["edges"] if edge["src"] in kept and edge["dst"] in kept]
    return {"ref": found["start"], "nodes": out_nodes, "edges": edges, "truncated": truncated}


# --- объекты ---

def object_view(conn: psycopg.Connection, object_id) -> dict:
    """ObjectView: объект, версии с числом цитат, отметка, цитаты текущих ревизий, страницы и листы."""
    oid = _object_id(object_id)
    view = lookup.object_view(conn, oid)
    if view is None:
        raise objects.ObjectError(f"obj:{oid}: такого объекта нет", code="not_found")
    labels = _labels(conn, [c["record"] for c in view["cited_by"]])
    citations = [{**c, "record": labels[c["record"]]} for c in view["cited_by"]]
    counts: dict[int, int] = {}
    for c in citations:
        counts[c["version"]] = counts.get(c["version"], 0) + 1
    versions = [{"n": v["n"], "digest": v.get("digest"), "size": v.get("size"), "recorded_at": v["recorded_at"],
                 "cited_by": counts.get(v["n"], 0)} for v in view["versions"]]
    return {**view, "media_type": view.get("media_type"), "url": view.get("url"),
            "logical_paths": view.get("logical_paths", []), "versions": versions, "cited_by": citations}


@dataclass(frozen=True)
class Content:
    """Файл версии для раздачи: путь копии в хранилище, тип, имя и как отдавать."""
    path: Path
    media_type: str
    filename: str | None
    inline: bool          # тип из белого списка — как есть; иначе application/octet-stream на скачивание


def object_content(conn: psycopg.Connection, store: ObjectStore, object_id, n) -> Content:
    """Копия файла версии n из хранилища. Нет объекта, версии или копии (сайт, переписка) — ObjectError not_found."""
    oid = _object_id(object_id)
    n = _int(n, "n", low=1)
    row = conn.execute("SELECT o.original_name, o.media_type, v.digest FROM object o "
                       "JOIN object_version v ON v.object_id = o.id WHERE o.id = %s AND v.n = %s", (oid, n)).fetchone()
    if row is None:
        raise objects.ObjectError(f"obj:{oid}: нет объекта или версии {n}", code="not_found")
    name, media_type, digest = row
    if digest is None:
        raise objects.ObjectError(f"obj:{oid}: у версии {n} нет файла (страница сайта или переписка)",
                                  code="not_found")
    try:
        path = store.content(oid, n)
    except StoreError as e:
        # база знает копию, а хранилища нет: не подключена папка данных или копию удалили вручную
        raise objects.ObjectError(f"obj:{oid}: копии версии {n} нет в хранилище ({e})", code="not_found") from e
    media = (media_type or "").partition(";")[0].strip().lower()
    inline = media in INLINE_TYPES
    return Content(path, media if inline else "application/octet-stream", name, inline)


def object_text(conn: psycopg.Connection, store: ObjectStore, object_id, n, *, page=None) -> dict:
    """Текст версии по страницам ({pages}); у файла без текста и у версии без файла — пустой список.
    page — одна страница (с 1); нет такой — ObjectError not_found."""
    oid, n = _object_id(object_id), _int(n, "n", low=1)
    page = _int(page, "page", low=1)
    try:
        pages = objects.text(conn, store, oid, n) or []
    except StoreError as e:
        raise objects.ObjectError(f"obj:{oid}: копии версии {n} нет в хранилище ({e})", code="not_found") from e
    if page is not None:
        if page > len(pages):
            raise objects.ObjectError(f"obj:{oid}: у версии {n} нет страницы {page} (страниц {len(pages)})",
                                      code="not_found")
        pages = [pages[page - 1]]
    return {"pages": pages}


def object_sheet(conn: psycopg.Connection, store: ObjectStore, object_id, n, *, name, cell_range=None) -> dict:
    """Ячейки листа xlsx: {name, range, rows}; пустой range — окно по умолчанию (A1:L40 по данным)."""
    oid, n = _object_id(object_id), _int(n, "n", low=1)
    if not isinstance(name, str) or not name:
        raise BadRequest("name: нужно имя листа")
    if cell_range is not None and not isinstance(cell_range, str):
        raise BadRequest(f"range {cell_range!r}: нужна запись A1, например B2:D10")
    try:
        return objects.sheet(conn, store, oid, n, name, cell_range or None)
    except StoreError as e:
        raise objects.ObjectError(f"obj:{oid}: копии версии {n} нет в хранилище ({e})", code="not_found") from e


# --- словарь, база, бэкапы ---

def vocab_entries(conn: psycopg.Connection, scheme) -> list[dict]:
    """VocabEntry[] схемы словаря (kind, entity_class, property, rel, …); неизвестная схема — пустой список."""
    if not isinstance(scheme, str) or not scheme:
        raise BadRequest("scheme: нужно имя схемы словаря")
    return vocab.entries(conn, scheme)


def base(conn: psycopg.Connection) -> dict:
    """Base: id и имя базы, загруженные пакеты (последняя версия каждого), счётчики и открытые пункты очереди."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()
    with conn.cursor(row_factory=dict_row) as cur:
        packs = cur.execute("SELECT DISTINCT ON (name) name, version, digest FROM pack "
                            "ORDER BY name, loaded_at DESC, version DESC").fetchall()
        counts = cur.execute(
            "SELECT (SELECT count(*) FROM atom) AS atoms, (SELECT count(*) FROM entity) AS entities, "
            "(SELECT count(*) FROM object) AS objects, (SELECT count(*) FROM link WHERE retired_at IS NULL) AS links, "
            "(SELECT count(*) FROM review_item WHERE state = ANY(%s)) AS review_open", (list(REVIEW_OPEN),)).fetchone()
    review_open = counts.pop("review_open")
    return {"base_id": row[0] if row else None, "name": db.base_name(conn), "amem_version": __version__,
            "packs": packs, "counts": counts, "review_open": review_open}


def backup_list(backup_dir: Path) -> list[dict]:
    """Backup[]: готовые копии по времени — имя, время, размер; пути на диске наружу не отдаются."""
    return [{"name": b["name"], "created_at": b["created_at"], "size": b["size"]}
            for b in backup.backups(Path(backup_dir))]
