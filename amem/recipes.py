"""Именованные поисковые рецепты: компактная выдача без скрытого выбора ответа.

Каждый успешный поиск пишет retrieval с происхождением. Семантический канал либо действительно
выполняется активной моделью, либо явно пропускается с причиной; FTS остаётся доступен.
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
              durations_ms: dict, useful: bool, now) -> dict:
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
        ranking_version=ranked["ranking_version"], hits=ranked["hits"], now=now)
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
    """Проверить ref даже для пустого интервала: отсутствующая запись — не пустая история."""
    if ref is None:
        return None, None, None
    try:
        prefix, value = ref.split(":", 1)
        target = records.TARGET[prefix]
    except (AttributeError, ValueError, KeyError) as e:
        raise records.RecordError(f"ref {ref!r}: нужна ссылка atm:<UUID> или ent:<UUID>") from e
    record_id = records.as_uuid(value, what="ref")
    if conn.execute(f"SELECT 1 FROM {target} WHERE id = %s", (record_id,)).fetchone() is None:
        raise records.RecordError(f"{ref}: такой записи нет")
    return target, record_id, f"{prefix}:{record_id}"


def _history_interval(column: str, since, until) -> str:
    """Полуоткрытый интервал [since, until); имя столбца выбирает только код ниже."""
    clauses = []
    if since is not None:
        clauses.append(f"{column} >= %(since)s")
    if until is not None:
        clauses.append(f"{column} < %(until)s")
    return " AND ".join(clauses) or "TRUE"


def _history_in(value, since, until) -> bool:
    return (since is None or value >= since) and (until is None or value < until)


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
    return changes


def what_changed(conn: psycopg.Connection, *, ref: str | None = None,
                 since: datetime | None = None, until: datetime | None = None) -> dict:
    """События записи или всей базы за [since, until), без поиска и журнала retrieval."""
    since = _history_moment(since, "since")
    until = _history_moment(until, "until")
    if since is not None and until is not None and since >= until:
        raise records.RecordError("since должен быть строго раньше until")
    target, record_id, normalized_ref = _history_ref(conn, ref)
    params = {"since": since, "until": until, "record_id": record_id, "target": target}
    timed_events = []

    def add(kind, event_id, at, **fields):
        timed_events.append((at, {"type": kind, "id": str(event_id), "at": at.isoformat(), **fields}))

    with conn.cursor(row_factory=dict_row) as cur:
        for item_target in ("atom", "entity"):
            recorded = _history_interval("r.recorded_at", since, until)
            reviewed = _history_interval("r.reviewed_at", since, until)
            scope = f"AND r.{item_target}_id = %(record_id)s" if target == item_target else ""
            if target is not None and target != item_target:
                continue
            rows = cur.execute(
                f"SELECT r.id, r.{item_target}_id AS record_id, r.n, r.payload, r.content_hash, "
                f"r.valid_from, r.valid_to, r.recorded_at, r.review_state, r.reviewed_by, r.reviewed_at, "
                f"p.payload AS previous_payload, p.content_hash AS previous_content_hash "
                f"FROM {item_target}_revision r "
                f"LEFT JOIN {item_target}_revision p ON p.{item_target}_id = r.{item_target}_id AND p.n = r.n - 1 "
                f"WHERE ({recorded} OR {reviewed}) {scope}", params).fetchall()
            item_ref = f"{records.PREFIX[item_target]}:"
            for row in rows:
                event_ref = f"{item_ref}{row['record_id']}"
                if _history_in(row["recorded_at"], since, until):
                    previous = row["previous_payload"]
                    add("revision", row["id"], row["recorded_at"], ref=event_ref, revision=row["n"],
                        recorded_at=row["recorded_at"].isoformat(),
                        previous_content_hash=row["previous_content_hash"], content_hash=row["content_hash"],
                        valid_from=row["valid_from"].isoformat() if row["valid_from"] else None,
                        valid_to=row["valid_to"].isoformat() if row["valid_to"] else None,
                        changes=_diff(previous if previous is not None else {}, row["payload"]))
                if row["reviewed_at"] is not None and _history_in(row["reviewed_at"], since, until):
                    add("review", row["id"], row["reviewed_at"], ref=event_ref, revision=row["n"],
                        review_state=row["review_state"], reviewed_at=row["reviewed_at"].isoformat(),
                        reviewed_by=row["reviewed_by"])

        changed_at = _history_interval("changed_at", since, until)
        scope = "AND target = %(target)s AND record_id = %(record_id)s" if target is not None else ""
        rows = cur.execute(
            f"SELECT id, target, record_id, status, agent, reason, changed_at FROM status_log "
            f"WHERE {changed_at} {scope}", params).fetchall()
        for row in rows:
            add("status", row["id"], row["changed_at"],
                ref=f"{records.PREFIX[row['target']]}:{row['record_id']}", status=row["status"],
                changed_at=row["changed_at"].isoformat(), agent=row["agent"], reason=row["reason"])

        created = _history_interval("created_at", since, until)
        retired = _history_interval("retired_at", since, until)
        if target == "atom":
            scope = "AND (src_atom = %(record_id)s OR dst_atom = %(record_id)s)"
        elif target == "entity":
            scope = "AND (src_entity = %(record_id)s OR dst_entity = %(record_id)s)"
        else:
            scope = ""
        rows = cur.execute(
            f"SELECT id, rel, src_atom, src_entity, dst_atom, dst_entity, created_at, retired_at "
            f"FROM link WHERE ({created} OR {retired}) {scope}", params).fetchall()
        for row in rows:
            src = f"{'atm' if row['src_atom'] is not None else 'ent'}:{row['src_atom'] or row['src_entity']}"
            dst = f"{'atm' if row['dst_atom'] is not None else 'ent'}:{row['dst_atom'] or row['dst_entity']}"
            if _history_in(row["created_at"], since, until):
                add("link_created", row["id"], row["created_at"], rel=row["rel"], src=src, dst=dst,
                    created_at=row["created_at"].isoformat())
            if row["retired_at"] is not None and _history_in(row["retired_at"], since, until):
                add("link_retired", row["id"], row["retired_at"], rel=row["rel"], src=src, dst=dst,
                    retired_at=row["retired_at"].isoformat())

    events = [event for _, event in sorted(timed_events, key=lambda item: (item[0], item[1]["type"], item[1]["id"]))]
    return {
        "recipe": "what_changed", "ref": normalized_ref,
        "since": since.isoformat() if since else None, "until": until.isoformat() if until else None,
        "events": events, "retrieval_id": None,
    }


def exact_fact(conn: psycopg.Connection, query: str, *, agent: str, activity=None,
               limit: int = 10, target=None, kind=None, entity_class=None, statuses=None,
               include_record: bool = False, provider: embed.EmbeddingProvider | None = None,
               usefulness: bool = True, now=None) -> dict:
    """Найти марку или формулировку всеми четырьмя каналами, не выбирая один «лучший» ответ."""
    filters = {"target": target, "kind": kind, "entity_class": entity_class, "statuses": statuses}
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
                     reasons=reasons, model=model, durations_ms=durations, useful=usefulness, now=now)


def _source_document(conn: psycopg.Connection, ref: str):
    prefix, value = ref.split(":", 1)
    target = records.TARGET[prefix]
    record_id = records.as_uuid(value, what="ref")
    table = target
    row = conn.execute(
        f"SELECT rec.id, r.id, d.document FROM {table} rec "
        f"LEFT JOIN {table}_current r ON r.{table}_id = rec.id "
        f"LEFT JOIN search_document d ON d.target = %(target)s AND d.record_id = rec.id "
        f"AND d.revision_id = r.id "
        f"WHERE rec.id = %(record_id)s",
        {"target": target, "record_id": record_id}).fetchone()
    if row is None:
        raise records.RecordError(f"{ref}: такой записи нет")
    if row[1] is None:
        raise records.RecordError(f"{ref}: у записи нет текущей ревизии")
    if row[2] is None:
        raise records.RecordError(f"{ref}: нет поискового документа текущей ревизии")
    return target, record_id, row[2]


def similar(conn: psycopg.Connection, query: str, *, agent: str, activity=None,
            limit: int = 10, target=None, kind=None, entity_class=None, statuses=None,
            include_record: bool = False, provider: embed.EmbeddingProvider | None = None,
            usefulness: bool = True, now=None) -> dict:
    """Найти похожие записи по тексту либо по atm:/ent: ссылке на существующую запись."""
    if not isinstance(query, str):
        raise ValueError("запрос должен быть строкой")
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
                     reasons=reasons, model=model, durations_ms=durations, useful=usefulness, now=now)
