"""Именованные поисковые рецепты: компактная выдача без скрытого выбора ответа.

Каждый успешный поиск пишет retrieval с происхождением, если вызов не попросил обратного (log=False — подсказки
хука, служебные запросы: отметить пользу такой выдачи нельзя, её нет в журнале). Семантический канал либо
действительно выполняется активной моделью, либо явно пропускается с причиной; FTS остаётся доступен.
"""
from __future__ import annotations

import time
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from . import embed, records, search, usefulness


def _availability(conn: psycopg.Connection, provider):
    model = search._active_model(conn)
    if model is None:
        return None, None, "no_active_model"
    selected = embed.get_provider(provider)
    if selected is None:
        return model, None, "backend_disabled"
    return model, selected, None


def _check_query_provider(model, provider: embed.EmbeddingProvider) -> None:
    expected = (model[1], model[2], model[4], model[3])
    actual = (getattr(provider, "name", None), getattr(provider, "version", None),
              getattr(provider, "backend", None), getattr(provider, "dims", None))
    if actual != expected:
        raise embed.EmbeddingError(
            f"provider не соответствует активной модели: ожидалось {expected!r}, получено {actual!r}")


def _timed(channel, function, durations):
    started = time.perf_counter()
    rows = function()
    durations[channel] = (time.perf_counter() - started) * 1000
    return rows


def _response(conn: psycopg.Connection, recipe: str, channels: dict, *, query: str, agent: str,
              activity, limit: int, include_record: bool, semantic: str, reasons: dict, model,
              durations_ms: dict, useful: bool, log: bool, now) -> dict:
    candidates = [row for rows in channels.values() if rows is not None for row in rows]
    multipliers = usefulness.multipliers(conn, candidates, now=now) if useful else None
    ranked = search._rrf(channels, search.RANKING_V1["recipes"][recipe], limit=limit,
                         exact_fact=recipe == "exact_fact", durations_ms=durations_ms,
                         usefulness=multipliers)
    cards = search._enrich(conn, ranked["hits"], include_record=include_record)
    items = [{**card, "score": hit["score"], "matches": hit["matches"]}
             for hit, card in zip(ranked["hits"], cards)]
    retrieval_id = usefulness.record_retrieval(
        conn, agent=agent, activity=activity, recipe=recipe, query=query,
        ranking_version=ranked["ranking_version"], hits=ranked["hits"], now=now) if log else None
    return {
        "recipe": recipe,
        "ranking_version": ranked["ranking_version"],
        "channels": {
            "used": ranked["used_channels"],
            "skipped": ranked["skipped_channels"],
            "reasons": reasons,
            "durations_ms": ranked["durations_ms"],
        },
        "semantic": semantic,
        "candidate_count": ranked["candidate_count"],
        "embedding_coverage": embed.embedding_coverage(conn, model[0]) if model is not None else None,
        "items": items,
        "retrieval_id": retrieval_id,
    }


def _history_moment(value, name: str):
    if value is not None and (not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None):
        raise records.RecordError(f"{name} {value!r}: нужно время с часовым поясом (datetime с tzinfo)")
    return value


def _history_ref(conn: psycopg.Connection, ref: str | None):
    """Проверить ref (UUID или ключ) даже для пустого интервала: отсутствующая запись — не пустая история,
    а RecordNotFound."""
    if ref is None:
        return None, None, None
    target, record_id = records.resolve(conn, ref)
    return target, record_id, f"{records.PREFIX[target]}:{record_id}"


def _history_interval(column: str, since, until) -> str:
    """Полуоткрытый интервал [since, until); имя столбца выбирает только код ниже."""
    clauses = []
    if since is not None:
        clauses.append(f"{column} >= %(since)s")
    if until is not None:
        clauses.append(f"{column} < %(until)s")
    return " AND ".join(clauses) or "TRUE"


def _json_equal(before, after) -> bool:
    """Сравнение JSON без питоновского True == 1; int и float остаются JSON-числами."""
    if isinstance(before, bool) or isinstance(after, bool):
        return type(before) is type(after) and before == after
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        return before == after
    if type(before) is not type(after):
        return False
    if isinstance(before, dict):
        return before.keys() == after.keys() and all(_json_equal(before[key], after[key]) for key in before)
    if isinstance(before, list):
        return len(before) == len(after) and all(_json_equal(a, b) for a, b in zip(before, after))
    return before == after


def _diff(before, after) -> list[dict]:
    """Рекурсивный diff JSON: RFC 6901-пути; массив — одно значение, отсутствующая сторона опущена."""
    changes = []

    def walk(old, new, path):
        if isinstance(old, dict) and isinstance(new, dict):
            for key in sorted(old.keys() | new.keys()):
                child = f"{path}/{key.replace('~', '~0').replace('/', '~1')}"
                if key not in old:
                    changes.append({"path": child, "after": new[key]})
                elif key not in new:
                    changes.append({"path": child, "before": old[key]})
                else:
                    walk(old[key], new[key], child)
            return
        if not _json_equal(old, new):
            change = {"path": path, "before": old, "after": new}
            changes.append(change)

    walk(before, after, "")
    changes.sort(key=lambda change: change["path"])
    return changes


WHO = ("all", "person", "model")


def _history_limit(limit) -> int | None:
    if limit is None:
        return None
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise records.RecordError(f"limit {limit!r}: нужно целое число от 1 или None")
    return limit


def _history_who(column: str, who: str) -> str:
    """Отбор по автору события — приставке агента (person: или model:); имя столбца выбирает только код ниже."""
    return "TRUE" if who == "all" else f"starts_with({column}, %(who)s)"


def what_changed(conn: psycopg.Connection, *, ref: str | None = None,
                 since: datetime | None = None, until: datetime | None = None,
                 limit: int | None = None, who: str = "all") -> dict:
    """События записи (ref — atm:/ent: с UUID или ключом) или всей базы за [since, until), без поиска и журнала
    retrieval. Порядок — по времени, затем по виду события и id.

    У каждого события agent — кто его сделал: у ревизии и новой связи — автор пакета, у решения о ревизии —
    решивший, у выведенной связи — автор пакета, который её вывел, у статуса и папки — сменивший их.
    who — person, model или all: события людей, моделей или все. limit — только самые новые limit событий (порядок
    тот же), None — все. Каждый источник событий читает не больше limit самых новых: иначе ради одной страницы
    читалась бы и сравнивалась вся история базы."""
    since = _history_moment(since, "since")
    until = _history_moment(until, "until")
    if since is not None and until is not None and since >= until:
        raise records.RecordError("since должен быть строго раньше until")
    if not isinstance(who, str) or who not in WHO:
        raise records.RecordError(f"who {who!r}: допустимы {', '.join(WHO)}")
    limit = _history_limit(limit)
    target, record_id, normalized_ref = _history_ref(conn, ref)
    params = {"since": since, "until": until, "record_id": record_id, "target": target, "limit": limit,
              "who": f"{who}:"}
    timed_events = []

    def add(kind, event_id, at, **fields):
        timed_events.append((at, {"type": kind, "id": str(event_id), "at": at.isoformat(), **fields}))

    with conn.cursor(row_factory=dict_row) as cur:
        for item_target in ("atom", "entity"):
            if target is not None and target != item_target:
                continue
            t = item_target                                  # только из закрытого набора выше
            scope = f"AND r.{t}_id = %(record_id)s" if target == t else ""
            # сначала limit новых ревизий, потом их предшественницы: тела старых ревизий не читаются
            rows = cur.execute(
                f"SELECT r.*, p.payload AS previous_payload, p.content_hash AS previous_content_hash FROM ("
                f"SELECT r.id, r.{t}_id AS record_id, r.n, r.payload, r.content_hash, r.valid_from, r.valid_to, "
                f"r.recorded_at, cs.agent FROM {t}_revision r JOIN changeset cs ON cs.id = r.changeset_id "
                f"WHERE {_history_interval('r.recorded_at', since, until)} AND {_history_who('cs.agent', who)} "
                f"{scope} ORDER BY r.recorded_at DESC, r.id DESC LIMIT %(limit)s) r "
                f"LEFT JOIN {t}_revision p ON p.{t}_id = r.record_id AND p.n = r.n - 1", params).fetchall()
            for row in rows:
                previous = row["previous_payload"]
                add("revision", row["id"], row["recorded_at"], ref=f"{records.PREFIX[t]}:{row['record_id']}",
                    revision=row["n"], agent=row["agent"], recorded_at=row["recorded_at"].isoformat(),
                    previous_content_hash=row["previous_content_hash"], content_hash=row["content_hash"],
                    valid_from=row["valid_from"].isoformat() if row["valid_from"] else None,
                    valid_to=row["valid_to"].isoformat() if row["valid_to"] else None,
                    changes=_diff(previous if previous is not None else {}, row["payload"]))
            rows = cur.execute(
                f"SELECT r.id, r.{t}_id AS record_id, r.n, r.review_state, r.reviewed_by, r.reviewed_at "
                f"FROM {t}_revision r WHERE r.reviewed_at IS NOT NULL "
                f"AND {_history_interval('r.reviewed_at', since, until)} AND {_history_who('r.reviewed_by', who)} "
                f"{scope} ORDER BY r.reviewed_at DESC, r.id DESC LIMIT %(limit)s", params).fetchall()
            for row in rows:
                add("review", row["id"], row["reviewed_at"], ref=f"{records.PREFIX[t]}:{row['record_id']}",
                    revision=row["n"], agent=row["reviewed_by"], review_state=row["review_state"],
                    reviewed_at=row["reviewed_at"].isoformat(), reviewed_by=row["reviewed_by"])

        changed_at = _history_interval("changed_at", since, until)
        scope = "AND target = %(target)s AND record_id = %(record_id)s" if target is not None else ""
        rows = cur.execute(
            f"SELECT id, target, record_id, status, agent, reason, changed_at FROM status_log "
            f"WHERE {changed_at} AND {_history_who('agent', who)} {scope} "
            "ORDER BY changed_at DESC, id DESC LIMIT %(limit)s", params).fetchall()
        for row in rows:
            add("status", row["id"], row["changed_at"],
                ref=f"{records.PREFIX[row['target']]}:{row['record_id']}", status=row["status"],
                changed_at=row["changed_at"].isoformat(), agent=row["agent"], reason=row["reason"])

        # переносы по папкам (amem/folders.py): from / to — путь или None («без папки»)
        rows = cur.execute(
            f"SELECT id, target, record_id, folder_from, folder_to, agent, changed_at FROM folder_log "
            f"WHERE {changed_at} AND {_history_who('agent', who)} {scope} "
            "ORDER BY changed_at DESC, id DESC LIMIT %(limit)s", params).fetchall()
        for row in rows:
            add("folder", row["id"], row["changed_at"],
                ref=f"{records.PREFIX[row['target']]}:{row['record_id']}",
                changed_at=row["changed_at"].isoformat(), agent=row["agent"],
                **{"from": row["folder_from"], "to": row["folder_to"]})

        if target == "atom":
            scope = "AND (l.src_atom = %(record_id)s OR l.dst_atom = %(record_id)s)"
        elif target == "entity":
            scope = "AND (l.src_entity = %(record_id)s OR l.dst_entity = %(record_id)s)"
        else:
            scope = ""
        ends = "l.id, l.rel, l.src_atom, l.src_entity, l.dst_atom, l.dst_entity"
        created = cur.execute(
            f"SELECT {ends}, l.created_at AS at, l.agent FROM link l "
            f"WHERE {_history_interval('l.created_at', since, until)} AND {_history_who('l.agent', who)} {scope} "
            "ORDER BY l.created_at DESC, l.id DESC LIMIT %(limit)s", params).fetchall()
        # вывел связь пакет retired_by — его автор, не автор связи
        retired = cur.execute(
            f"SELECT {ends}, l.retired_at AS at, rc.agent FROM link l JOIN changeset rc ON rc.id = l.retired_by "
            f"WHERE l.retired_at IS NOT NULL AND {_history_interval('l.retired_at', since, until)} "
            f"AND {_history_who('rc.agent', who)} {scope} "
            "ORDER BY l.retired_at DESC, l.id DESC LIMIT %(limit)s", params).fetchall()
        for kind, rows, moment in (("link_created", created, "created_at"), ("link_retired", retired, "retired_at")):
            for row in rows:
                src = f"{'atm' if row['src_atom'] is not None else 'ent'}:{row['src_atom'] or row['src_entity']}"
                dst = f"{'atm' if row['dst_atom'] is not None else 'ent'}:{row['dst_atom'] or row['dst_entity']}"
                add(kind, row["id"], row["at"], rel=row["rel"], src=src, dst=dst, agent=row["agent"],
                    **{moment: row["at"].isoformat()})

    timed_events.sort(key=lambda item: (item[0], item[1]["type"], item[1]["id"]))
    if limit is not None:
        timed_events = timed_events[-limit:]
    return {
        "recipe": "what_changed", "ref": normalized_ref,
        "since": since.isoformat() if since else None, "until": until.isoformat() if until else None,
        "events": [event for _, event in timed_events], "retrieval_id": None,
    }


def exact_fact(conn: psycopg.Connection, query: str, *, agent: str, activity=None,
               limit: int = 10, target=None, kind=None, entity_class=None, statuses=None,
               include_record: bool = False, provider: embed.EmbeddingProvider | None = None,
               usefulness: bool = True, log: bool = True, now=None) -> dict:
    """Найти марку или формулировку всеми четырьмя каналами, не выбирая один «лучший» ответ.

    kind и entity_class — код строкой или несколько кодов (search._codes); log=False — выдача не пишется
    в retrieval, retrieval_id равен None."""
    filters = {"target": target, "kind": search._codes(kind, "kind"),
               "entity_class": search._codes(entity_class, "entity_class"), "statuses": statuses}
    durations = {}
    channels = {
        "code_exact": _timed("code_exact", lambda: search._code_exact(conn, query, **filters), durations),
        "code_prefix": _timed("code_prefix", lambda: search._code_prefix(conn, query, **filters), durations),
        "fts": _timed("fts", lambda: search._fts(conn, query, **filters), durations),
        "vector": None,
    }
    model, selected, reason = _availability(conn, provider)
    if selected is not None and not query.strip():
        reason = "empty_query"
    if selected is not None and reason is None:
        _check_query_provider(model, selected)
        vector = selected.embed([query])[0]
        channels["vector"] = _timed(
            "vector", lambda: search._vector(conn, vector, model[0], **filters), durations)
    reasons = {"vector": reason} if reason is not None else {}
    return _response(conn, "exact_fact", channels, query=query, agent=agent, activity=activity,
                     limit=limit, include_record=include_record,
                     semantic="used" if channels["vector"] is not None else "unavailable",
                     reasons=reasons, model=model, durations_ms=durations, useful=usefulness, log=log, now=now)


def _source_document(conn: psycopg.Connection, ref: str):
    """Запись-образец similar (atm:/ent: с UUID или ключом) и поисковый документ её текущей ревизии."""
    target, record_id = records.resolve(conn, ref)
    table = target
    row = conn.execute(
        f"SELECT rec.id, r.id, d.document FROM {table} rec "
        f"LEFT JOIN {table}_current r ON r.{table}_id = rec.id "
        f"LEFT JOIN search_document d ON d.target = %(target)s AND d.record_id = rec.id "
        f"AND d.revision_id = r.id "
        f"WHERE rec.id = %(record_id)s",
        {"target": target, "record_id": record_id}).fetchone()
    if row is None:
        raise records.RecordNotFound(f"{ref}: такой записи нет")
    if row[1] is None:
        raise records.RecordError(f"{ref}: у записи нет текущей ревизии")
    if row[2] is None:
        raise records.RecordError(f"{ref}: нет поискового документа текущей ревизии")
    return target, record_id, row[2]


def similar(conn: psycopg.Connection, query: str, *, agent: str, activity=None,
            limit: int = 10, target=None, kind=None, entity_class=None, statuses=None,
            include_record: bool = False, provider: embed.EmbeddingProvider | None = None,
            usefulness: bool = True, log: bool = True, now=None) -> dict:
    """Найти похожие записи по тексту либо по atm:/ent: ссылке (UUID или ключ) на существующую запись.

    Фильтры и log — как у exact_fact."""
    if not isinstance(query, str):
        raise ValueError("запрос должен быть строкой")
    kind, entity_class = search._codes(kind, "kind"), search._codes(entity_class, "entity_class")
    source = None
    fts_query = query
    if query.startswith(("atm:", "ent:")):
        source = _source_document(conn, query)
        source_target, source_id, fts_query = source
        exclude = (source_target, source_id)
    else:
        exclude = None
    filters = {"target": target, "kind": kind, "entity_class": entity_class,
               "statuses": statuses, "exclude": exclude}
    durations = {}
    channels = {"vector": None, "fts": None}
    model, selected, reason = _availability(conn, provider)
    if selected is not None and not fts_query.strip():
        reason = "empty_query"
    if selected is not None and reason is None:
        if source is None:
            _check_query_provider(model, selected)
            vector = selected.embed([query])[0]
        else:
            stored = search._current_embedding(conn, source[0], source[1], model[0])
            if stored is None:
                reason = "source_embedding_missing"
                vector = None
            else:
                vector = stored[0]
        if vector is not None:
            channels["vector"] = _timed(
                "vector", lambda: search._vector(conn, vector, model[0], **filters), durations)
    channels["fts"] = _timed("fts", lambda: search._fts(conn, fts_query, **filters), durations)
    reasons = {"vector": reason} if reason is not None else {}
    return _response(conn, "similar", channels, query=query, agent=agent, activity=activity,
                     limit=limit, include_record=include_record,
                     semantic="used" if channels["vector"] is not None else "unavailable",
                     reasons=reasons, model=model, durations_ms=durations, useful=usefulness, log=log, now=now)


_GRAPH_STRUCTURAL = {"about", "derived_from"}
_GRAPH_ROLE_RANK = {"primary": 0, "secondary": 1, "derived": 2}


def _graph_node_rows(conn: psycopg.Connection, refs) -> dict:
    refs = list(refs)
    if not refs:
        return {}
    ids = [ref.split(":", 1)[1] for ref in refs]
    rows = []
    with conn.cursor(row_factory=dict_row) as cur:
        for target in ("atom", "entity"):
            kind = "kind" if target == "atom" else "entity_class"
            selected = cur.execute(
                f"SELECT %(target)s AS target, rec.id, rec.key, rec.{kind} AS kind, rec.status, "
                f"r.id AS revision_id, r.n AS revision FROM {target} rec "
                f"JOIN {target}_current r ON r.{target}_id = rec.id "
                f"WHERE rec.id = ANY(%(ids)s::uuid[]) AND r.{target}_id = ANY(%(ids)s::uuid[])",
                {"target": target, "ids": ids}).fetchall()
            rows.extend(selected)
    nodes = {}
    for row in rows:
        ref = f"{records.PREFIX[row['target']]}:{row['id']}"
        nodes[ref] = {
            "ref": ref, "target": row["target"], "key": row["key"],
            "kind" if row["target"] == "atom" else "entity_class": row["kind"],
            "status": row["status"], "revision": row["revision"], "_revision_id": row["revision_id"],
        }
    return nodes


def _graph_rels(conn: psycopg.Connection, rels) -> frozenset[str] | None:
    """Набор видов связей для обхода: None — все; иначе коды словаря rel (about и derived_from — тоже)."""
    if rels is None:
        return None
    if isinstance(rels, str) or not hasattr(rels, "__iter__"):
        raise records.RecordError("rels должен быть набором видов связей, не строкой")
    items = list(rels)
    if not all(isinstance(value, str) for value in items):
        raise records.RecordError("rels: виды связей — строки-коды")
    values = frozenset(items)
    if not values:
        raise records.RecordError("rels: пустой набор видов связей")
    known = {row[0] for row in conn.execute("SELECT code FROM concept WHERE scheme = 'rel'")}
    unknown = values - known
    if unknown:
        raise records.RecordError(f"rels: неизвестные виды связей {', '.join(sorted(unknown))}")
    return values


def _graph_edges(conn: psycopg.Connection, frontier, rels: frozenset[str] | None) -> list[dict]:
    """Активные link и структурные ребра только текущих ревизий, прилегающие к frontier."""
    ids = [ref.split(":", 1)[1] for ref in frontier]
    link_rels = None if rels is None else sorted(rels - _GRAPH_STRUCTURAL)
    params = {"ids": ids, "rels": link_rels}
    edges = []
    with conn.cursor(row_factory=dict_row) as cur:
        if link_rels is None or link_rels:
            condition = "AND l.rel = ANY(%(rels)s)" if link_rels is not None else ""
            rows = cur.execute(
                "SELECT l.id, l.rel, coalesce(l.src_atom, l.src_entity) AS src, "
                "CASE WHEN l.src_atom IS NULL THEN 'ent' ELSE 'atm' END AS src_prefix, "
                "coalesce(l.dst_atom, l.dst_entity) AS dst, "
                "CASE WHEN l.dst_atom IS NULL THEN 'ent' ELSE 'atm' END AS dst_prefix, "
                "l.qualifiers, l.confidence, l.changeset_id, l.agent, l.created_at FROM link l "
                "WHERE l.retired_at IS NULL AND (coalesce(l.src_atom, l.src_entity) = ANY(%(ids)s::uuid[]) "
                f"OR coalesce(l.dst_atom, l.dst_entity) = ANY(%(ids)s::uuid[])) {condition} ORDER BY l.id",
                params).fetchall()
            for row in rows:
                edges.append({
                    "id": str(row["id"]), "rel": row["rel"],
                    "src": f"{row['src_prefix']}:{row['src']}", "dst": f"{row['dst_prefix']}:{row['dst']}",
                    "changeset": str(row["changeset_id"]), "agent": row["agent"],
                    "created_at": row["created_at"].isoformat(), "confidence": row["confidence"],
                    **({"qualifiers": row["qualifiers"]} if row["qualifiers"] is not None else {}),
                })
        for field in sorted(_GRAPH_STRUCTURAL if rels is None else _GRAPH_STRUCTURAL & rels):
            table = "atom_about" if field == "about" else "atom_derived"
            other = "entity_id" if field == "about" else "atom_id"
            prefix = "ent" if field == "about" else "atm"
            # исходящие (поле атома из frontier) и входящие (поле другого атома ведёт во frontier); условие
            # на atom_id без OR — его PostgreSQL подставляет внутрь atom_current, а не читает все ревизии
            select = (f"SELECT r.atom_id, f.{other} AS other_id, r.id AS revision_id, r.changeset_id, cs.agent, "
                      f"r.recorded_at AS created_at FROM atom_current r JOIN {table} f ON f.revision_id = r.id "
                      f"JOIN changeset cs ON cs.id = r.changeset_id ")
            rows = cur.execute(
                f"{select} WHERE r.atom_id = ANY(%(ids)s::uuid[]) UNION "
                f"{select} WHERE f.{other} = ANY(%(ids)s::uuid[]) AND r.atom_id = ANY(ARRAY("
                f"SELECT ar.atom_id FROM {table} g JOIN atom_revision ar ON ar.id = g.revision_id "
                f"WHERE g.{other} = ANY(%(ids)s::uuid[]))) "
                "ORDER BY revision_id, other_id", params).fetchall()
            for row in rows:
                edges.append({
                    "id": f"{field}:{row['revision_id']}:{row['other_id']}", "rel": field,
                    "src": f"atm:{row['atom_id']}", "dst": f"{prefix}:{row['other_id']}",
                    "changeset": str(row["changeset_id"]), "agent": row["agent"],
                    "created_at": row["created_at"].isoformat(), "confidence": None,
                })
    return edges


def _graph_source_roles(conn: psycopg.Connection, nodes: dict) -> dict:
    revision_ids = [node["_revision_id"] for node in nodes.values() if node["target"] == "atom"]
    roles = {ref: [] for ref, node in nodes.items() if node["target"] == "atom"}
    if not revision_ids:
        return roles
    rows = conn.execute("SELECT atom_revision_id, role FROM source WHERE atom_revision_id = ANY(%s::uuid[]) "
                        "ORDER BY atom_revision_id, position", (revision_ids,)).fetchall()
    by_revision = {node["_revision_id"]: ref for ref, node in nodes.items() if node["target"] == "atom"}
    for revision_id, role in rows:
        roles[by_revision[revision_id]].append(role)
    return roles


def _path_confidence(path: dict, edges: dict):
    scored = [edges[edge_id] for edge_id in path["edges"] if edges[edge_id]["rel"] not in _GRAPH_STRUCTURAL]
    if not scored or any(edge["confidence"] is None for edge in scored):
        return None
    return min(edge["confidence"] for edge in scored)


def _path_evidence_role(path: dict, nodes: dict, roles: dict):
    weakest = None
    for ref in path["nodes"]:
        if nodes[ref]["target"] != "atom":
            continue
        atom_roles = roles[ref]
        if not atom_roles or any(role not in _GRAPH_ROLE_RANK for role in atom_roles):
            return None
        rank = max(_GRAPH_ROLE_RANK[role] for role in atom_roles)
        weakest = rank if weakest is None else max(weakest, rank)
    if weakest is None:
        return None
    return next(role for role, rank in _GRAPH_ROLE_RANK.items() if rank == weakest)


def around_entity(conn: psycopg.Connection, ref: str, *, depth: int = 1, rels=None, statuses=None) -> dict:
    """Кратчайшие пути от записи (ref — atm:/ent: с UUID или ключом) по link/about/derived_from; узел посещается
    один раз.

    rels — набор видов связей (about и derived_from — тоже), statuses — статусы соседей, как у других рецептов.
    При равной длине путь выбирается по последовательности id рёбер, затем по ref; рёбра вне дерева кратчайших
    путей (параллельные связи, связи между уже найденными узлами) не возвращаются."""
    if isinstance(depth, bool) or not isinstance(depth, int) or not 1 <= depth <= 3:
        raise records.RecordError("depth должен быть целым числом от 1 до 3")
    _, _, start = _history_ref(conn, ref)
    allowed_statuses = search._channel_statuses(statuses)
    rels = _graph_rels(conn, rels)
    nodes = _graph_node_rows(conn, [start])
    if start not in nodes:
        raise records.RecordError(f"{start}: у записи нет текущей ревизии")
    nodes[start]["depth"] = 0
    paths = {start: {"nodes": [start], "edges": []}}
    result_edges = []
    visited = {start}
    frontier = [start]

    for level in range(1, depth + 1):
        adjacent = _graph_edges(conn, frontier, rels)
        candidate_refs = {edge[end] for edge in adjacent for end in ("src", "dst")} - visited
        candidates_info = _graph_node_rows(conn, candidate_refs)
        frontier_set = set(frontier)
        candidates = []
        for edge in adjacent:
            for current, neighbor, direction in ((edge["src"], edge["dst"], "forward"),
                                                 (edge["dst"], edge["src"], "reverse")):
                if current not in frontier_set or neighbor in visited:
                    continue
                info = candidates_info.get(neighbor)
                if info is None or info["status"] not in allowed_statuses:
                    continue
                path_key = (*paths[current]["edges"], edge["id"])
                candidates.append((path_key, neighbor, current, edge, direction, info))
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        next_frontier = []
        for _, neighbor, current, edge, direction, info in candidates:
            if neighbor in visited:
                continue
            info["depth"] = level
            nodes[neighbor] = info
            oriented = {**edge, "from": current, "to": neighbor, "direction": direction}
            result_edges.append(oriented)
            paths[neighbor] = {"nodes": [*paths[current]["nodes"], neighbor],
                               "edges": [*paths[current]["edges"], edge["id"]]}
            visited.add(neighbor)
            next_frontier.append(neighbor)
        frontier = next_frontier
        if not frontier:
            break

    edge_by_id = {edge["id"]: edge for edge in result_edges}
    roles = _graph_source_roles(conn, nodes)
    public_paths = []
    for ref, path in paths.items():
        if ref == start:
            continue
        public_paths.append({**path, "confidence": _path_confidence(path, edge_by_id),
                             "evidence_role": _path_evidence_role(path, nodes, roles)})
    return {
        "recipe": "around_entity", "start": start, "depth": depth,
        "nodes": [{key: value for key, value in node.items() if not key.startswith("_")}
                  for node in nodes.values()],
        "edges": result_edges, "paths": public_paths, "retrieval_id": None,
    }
