"""Именованные поисковые рецепты: компактная выдача без скрытого выбора ответа.

Каждый успешный поиск пишет retrieval с происхождением. Семантический канал либо действительно
выполняется активной моделью, либо явно пропускается с причиной; FTS остаётся доступен.
"""
from __future__ import annotations

import time

import psycopg

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
