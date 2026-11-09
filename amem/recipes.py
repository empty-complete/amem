"""Именованные поисковые рецепты: компактная выдача без скрытого выбора ответа.

Каждый успешный поиск пишет retrieval с происхождением, если вызов не попросил обратного (log=False — подсказки
хука, служебные запросы: отметить пользу такой выдачи нельзя, её нет в журнале). Семантический канал либо
действительно выполняется активной моделью, либо явно пропускается с причиной; FTS остаётся доступен.
"""
from __future__ import annotations

import importlib.util
import time
import uuid
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


def availability(conn: psycopg.Connection, provider: embed.EmbeddingProvider | None = None) -> dict:
    """Пойдёт ли смысловой канал у exact_fact и similar по тексту: {"semantic": "used" | "unavailable", "reason"}.

    reason у unavailable: no_active_model — в базе нет активной модели; backend_disabled — AMEM_BACKEND=none;
    backend_unknown — неизвестный AMEM_BACKEND; provider_mismatch — provider не той модели, что активна в базе
    (поиск по тексту тогда отвечает EmbeddingError); fastembed_missing — модель fastembed, а пакета нет. У used
    reason — None. Вектора не считаются: проверка дешёвая, служба зовёт её на каждый /session."""
    try:
        model, selected, reason = _availability(conn, provider)
    except embed.EmbeddingError:
        return {"semantic": "unavailable", "reason": "backend_unknown"}
    if selected is None:
        return {"semantic": "unavailable", "reason": reason}
    try:
        _check_query_provider(model, selected)
    except embed.EmbeddingError:
        return {"semantic": "unavailable", "reason": "provider_mismatch"}
    if selected.backend == "fastembed" and importlib.util.find_spec("fastembed") is None:
        return {"semantic": "unavailable", "reason": "fastembed_missing"}
    return {"semantic": "used", "reason": None}


SEMANTIC_ERRORS = ("raise", "skip")


def _select(conn: psycopg.Connection, provider, on_error: str):
    """_availability с выбором реакции на ошибку provider: raise — EmbeddingError наружу, skip — причина пропуска."""
    if on_error not in SEMANTIC_ERRORS:
        raise ValueError(f"on_semantic_error {on_error!r}: допустимы {', '.join(SEMANTIC_ERRORS)}")
    try:
        return _availability(conn, provider)
    except embed.EmbeddingError:
        if on_error == "raise":
            raise
        return search._active_model(conn), None, "backend_unknown"


def _query_vector(model, provider: embed.EmbeddingProvider, query: str, on_error: str):
    """Вектор запроса активной моделью → (вектор, None); при skip ошибка provider — (None, причина):
    provider_mismatch — provider не той модели, fastembed_missing — нет пакета fastembed, embedding_failed — прочий
    отказ модели (нет файлов в кэше, сбой счёта)."""
    try:
        _check_query_provider(model, provider)
    except embed.EmbeddingError:
        if on_error == "raise":
            raise
        return None, "provider_mismatch"
    try:
        return provider.embed([query])[0], None
    except embed.EmbeddingError:
        if on_error == "raise":
            raise
        missing = provider.backend == "fastembed" and importlib.util.find_spec("fastembed") is None
        return None, "fastembed_missing" if missing else "embedding_failed"


def _timed(channel, function, durations):
    started = time.perf_counter()
    rows = function()
    durations[channel] = (time.perf_counter() - started) * 1000
    return rows


def _response(conn: psycopg.Connection, recipe: str, channels: dict, *, query: str, agent: str,
              activity, limit: int, include_record: bool, semantic: str, reasons: dict, model,
              durations_ms: dict, useful: bool, log: bool, now, lang: str | None = None) -> dict:
    candidates = [row for rows in channels.values() if rows is not None for row in rows]
    multipliers = usefulness.multipliers(conn, candidates, now=now) if useful else None
    ranked = search._rrf(channels, search.RANKING_V1["recipes"][recipe], limit=limit,
                         exact_fact=recipe == "exact_fact", durations_ms=durations_ms,
                         usefulness=multipliers)
    cards = search._enrich(conn, ranked["hits"], include_record=include_record, lang=lang)
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


def diff(before, after) -> list[dict]:
    """Рекурсивный diff JSON: RFC 6901-пути; массив — одно значение, отсутствующая сторона опущена.
    Им же служба сравнивает текущую и предложенную ревизии у пункта очереди (edit, imported)."""
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
                    changes=diff(previous if previous is not None else {}, row["payload"]))
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
               usefulness: bool = True, log: bool = True, now=None, on_semantic_error: str = "raise",
               lang: str | None = None) -> dict:
    """Найти марку или формулировку всеми четырьмя каналами, не выбирая один «лучший» ответ.

    kind и entity_class — код строкой или несколько кодов (search._codes); log=False — выдача не пишется
    в retrieval, retrieval_id равен None. on_semantic_error — что делать, если provider не может посчитать вектор
    запроса (не та модель, нет fastembed, сбой модели, неизвестный AMEM_BACKEND): raise — EmbeddingError, skip —
    смысловой канал пропускается с причиной в channels.reasons.vector, остальные каналы отвечают как обычно.
    lang — язык фрагмента находки (amem.lang; None — ru, затем en); на поиск он не влияет: запрос идёт по всем
    слотам."""
    filters = {"target": target, "kind": search._codes(kind, "kind"),
               "entity_class": search._codes(entity_class, "entity_class"), "statuses": statuses}
    durations = {}
    channels = {
        "code_exact": _timed("code_exact", lambda: search._code_exact(conn, query, **filters), durations),
        "code_prefix": _timed("code_prefix", lambda: search._code_prefix(conn, query, **filters), durations),
        "fts": _timed("fts", lambda: search._fts(conn, query, **filters), durations),
        "vector": None,
    }
    model, selected, reason = _select(conn, provider, on_semantic_error)
    if selected is not None and not query.strip():
        reason = "empty_query"
    if selected is not None and reason is None:
        vector, reason = _query_vector(model, selected, query, on_semantic_error)
        if vector is not None:
            channels["vector"] = _timed(
                "vector", lambda: search._vector(conn, vector, model[0], **filters), durations)
    reasons = {"vector": reason} if reason is not None else {}
    return _response(conn, "exact_fact", channels, query=query, agent=agent, activity=activity,
                     limit=limit, include_record=include_record,
                     semantic="used" if channels["vector"] is not None else "unavailable",
                     reasons=reasons, model=model, durations_ms=durations, useful=usefulness, log=log, now=now,
                     lang=lang)


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
            usefulness: bool = True, log: bool = True, now=None, on_semantic_error: str = "raise",
            lang: str | None = None) -> dict:
    """Найти похожие записи по тексту либо по atm:/ent: ссылке (UUID или ключ) на существующую запись.

    Фильтры, log, on_semantic_error и lang — как у exact_fact: при skip похожие по тексту ищет один канал fts."""
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
    model, selected, reason = _select(conn, provider, on_semantic_error)
    if selected is not None and not fts_query.strip():
        reason = "empty_query"
    if selected is not None and reason is None:
        if source is None:
            vector, reason = _query_vector(model, selected, query, on_semantic_error)
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
                     reasons=reasons, model=model, durations_ms=durations, useful=usefulness, log=log, now=now,
                     lang=lang)


GRAPH_LIMIT = 300                    # узлов графа по умолчанию (around_entity, overview); контракт /graph — до 1000
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


def _graph_edges(conn: psycopg.Connection, frontier, rels: frozenset[str] | None, *, inner: bool = False) -> list[dict]:
    """Активные link и структурные ребра только текущих ревизий, прилегающие к frontier; inner — только рёбра,
    оба конца которых во frontier (обзор: рёбра между вернувшимися узлами)."""
    ids = [ref.split(":", 1)[1] for ref in frontier]
    join = "AND" if inner else "OR"
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
                f"{join} coalesce(l.dst_atom, l.dst_entity) = ANY(%(ids)s::uuid[])) {condition} ORDER BY l.id",
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
            if inner:
                query = (f"{select} WHERE r.atom_id = ANY(%(ids)s::uuid[]) AND f.{other} = ANY(%(ids)s::uuid[]) "
                         "ORDER BY revision_id, other_id")
            else:
                query = (f"{select} WHERE r.atom_id = ANY(%(ids)s::uuid[]) UNION "
                         f"{select} WHERE f.{other} = ANY(%(ids)s::uuid[]) AND r.atom_id = ANY(ARRAY("
                         f"SELECT ar.atom_id FROM {table} g JOIN atom_revision ar ON ar.id = g.revision_id "
                         f"WHERE g.{other} = ANY(%(ids)s::uuid[]))) "
                         "ORDER BY revision_id, other_id")
            rows = cur.execute(query, params).fetchall()
            for row in rows:
                edges.append({
                    "id": f"{field}:{row['revision_id']}:{row['other_id']}", "rel": field,
                    "src": f"atm:{row['atom_id']}", "dst": f"{prefix}:{row['other_id']}",
                    "changeset": str(row["changeset_id"]), "agent": row["agent"],
                    "created_at": row["created_at"].isoformat(), "confidence": None,
                })
    return edges


# структурные поля: таблица и столбец второго конца (atom_about → сущность, atom_derived → атом)
_GRAPH_FIELD_TABLES = {"about": ("atom_about", "entity_id"), "derived_from": ("atom_derived", "atom_id")}


def _graph_adjacent_sql(rels: frozenset[str] | None, *, ids: str = "%(ids)s::uuid[]") -> str:
    """Строки (near, far) — текущие рёбра, у которых конец near в массиве ids (параметр %(ids)s или подзапрос
    ARRAY(…) — выражение из кода, не из запроса): действующие link (с %(rels)s, если набор видов задан) и поля
    about/derived_from текущих ревизий. Ребро с обоими концами в ids — две строки, по одной на конец: так степень
    считает его у обоих. Таблицы и столбцы — из _GRAPH_FIELD_TABLES."""
    link_rels = None if rels is None else rels - _GRAPH_STRUCTURAL
    parts = []
    if link_rels is None or link_rels:
        condition = " AND l.rel = ANY(%(rels)s)" if link_rels is not None else ""
        for near, far in (("src", "dst"), ("dst", "src")):
            parts.append(f"SELECT coalesce(l.{near}_atom, l.{near}_entity) AS near, "
                         f"coalesce(l.{far}_atom, l.{far}_entity) AS far FROM link l WHERE l.retired_at IS NULL "
                         f"AND coalesce(l.{near}_atom, l.{near}_entity) = ANY({ids}){condition}")
    for field in sorted(_GRAPH_STRUCTURAL if rels is None else _GRAPH_STRUCTURAL & rels):
        table, other = _GRAPH_FIELD_TABLES[field]
        joined = f"FROM atom_current r JOIN {table} f ON f.revision_id = r.id"
        parts.append(f"SELECT r.atom_id AS near, f.{other} AS far {joined} WHERE r.atom_id = ANY({ids})")
        # входящие: условие на atom_id без OR — PostgreSQL подставляет его внутрь atom_current (см. _graph_edges)
        parts.append(f"SELECT f.{other} AS near, r.atom_id AS far {joined} WHERE f.{other} = ANY({ids}) "
                     f"AND r.atom_id = ANY(ARRAY(SELECT ar.atom_id FROM {table} g JOIN atom_revision ar "
                     f"ON ar.id = g.revision_id WHERE g.{other} = ANY({ids})))")
    return " UNION ALL ".join(parts) or "SELECT NULL::uuid AS near, NULL::uuid AS far WHERE false"


def _graph_marks(conn: psycopg.Connection, nodes: dict, degrees: dict | None = None) -> None:
    """degree — число текущих связей узла во всей базе (входящих и исходящих, с любыми соседями), одним агрегатом
    (degrees — уже посчитанные, UUID → число); pending — у записи есть открытый пункт очереди проверки (queued или
    claimed), одним запросом."""
    ids = [ref.split(":", 1)[1] for ref in nodes]
    if not ids:
        return
    if degrees is None:
        degrees = dict(conn.execute(f"SELECT near, count(*) FROM ({_graph_adjacent_sql(None)}) e GROUP BY near",
                                    {"ids": ids}).fetchall())
    pending = {row[0] for row in conn.execute(
        "SELECT DISTINCT record_id FROM review_item WHERE record_id = ANY(%s::uuid[]) "
        "AND state IN ('queued', 'claimed')", (ids,))}
    for ref, node in nodes.items():
        record_id = uuid.UUID(ref.split(":", 1)[1])
        node["degree"] = degrees.get(record_id, 0)
        node["pending"] = record_id in pending


def _graph_neighbours(conn: psycopg.Connection, frontier, rels: frozenset[str] | None, statuses) -> set[str]:
    """Соседи frontier по текущим рёбрам, у которых есть текущая ревизия и статус из statuses, — только ссылки:
    счёт узлов за пределом обхода (total) без путей и подписей."""
    ids = [ref.split(":", 1)[1] for ref in frontier]
    if not ids:
        return set()
    rows = conn.execute(
        f"WITH n AS (SELECT DISTINCT far AS id FROM ({_graph_adjacent_sql(rels)}) e) "
        "SELECT 'atm', a.id FROM atom a JOIN n ON n.id = a.id WHERE a.status = ANY(%(statuses)s) "
        "AND EXISTS (SELECT 1 FROM atom_revision r WHERE r.atom_id = a.id AND r.review_state <> 'declined') "
        "UNION ALL SELECT 'ent', e.id FROM entity e JOIN n ON n.id = e.id WHERE e.status = ANY(%(statuses)s) "
        "AND EXISTS (SELECT 1 FROM entity_revision r WHERE r.entity_id = e.id AND r.review_state <> 'declined')",
        {"ids": ids, "rels": None if rels is None else sorted(rels - _GRAPH_STRUCTURAL),
         "statuses": list(statuses)}).fetchall()
    return {f"{prefix}:{record_id}" for prefix, record_id in rows}


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


def around_entity(conn: psycopg.Connection, ref: str, *, depth: int = 1, rels=None, statuses=None,
                  limit: int | None = GRAPH_LIMIT) -> dict:
    """Кратчайшие пути от записи (ref — atm:/ent: с UUID или ключом) по link/about/derived_from; узел посещается
    один раз.

    rels — набор видов связей (about и derived_from — тоже), statuses — статусы соседей, как у других рецептов.
    При равной длине путь выбирается по последовательности id рёбер, затем по ref; рёбра вне дерева кратчайших
    путей (параллельные связи, связи между уже найденными узлами) не возвращаются.

    limit — сколько узлов (вместе с начальным) найти, не больше: обход останавливается на нём, ближние узлы —
    раньше дальних, в том же порядке, что без предела; truncated — были узлы сверх предела. None — без предела.
    total — сколько узлов было бы без предела: за пределом обход досчитывает только ссылки соседей, без путей.
    У узла degree — число его текущих связей во всей базе, pending — открытый пункт очереди проверки."""
    if isinstance(depth, bool) or not isinstance(depth, int) or not 1 <= depth <= 3:
        raise records.RecordError("depth должен быть целым числом от 1 до 3")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
        raise records.RecordError(f"limit {limit!r}: нужно целое число от 1 или None")
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
    truncated = False

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
        level_refs = {item[1] for item in candidates}
        next_frontier = []
        for _, neighbor, current, edge, direction, info in candidates:
            if neighbor in visited:
                continue
            if limit is not None and len(nodes) >= limit:
                truncated = True                     # узел сверх предела: обход дальше не идёт
                break
            info["depth"] = level
            nodes[neighbor] = info
            oriented = {**edge, "from": current, "to": neighbor, "direction": direction}
            result_edges.append(oriented)
            paths[neighbor] = {"nodes": [*paths[current]["nodes"], neighbor],
                               "edges": [*paths[current]["edges"], edge["id"]]}
            visited.add(neighbor)
            next_frontier.append(neighbor)
        frontier = next_frontier
        if truncated:
            seen = visited | level_refs
            reached = level_refs
            for _ in range(level + 1, depth + 1):
                reached = _graph_neighbours(conn, reached, rels, allowed_statuses) - seen
                seen |= reached
            total = len(seen)
            break
        if not frontier:
            break
    if not truncated:
        total = len(nodes)

    _graph_marks(conn, nodes)
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
        "edges": result_edges, "paths": public_paths, "truncated": truncated, "total": total, "retrieval_id": None,
    }


# Степень всех узлов базы — один агрегат по концам текущих рёбер: действующие link и поля about/derived_from текущих
# ревизий (то же, что _graph_adjacent_sql для набора узлов). Ребро даёт по единице обоим концам.
_OVERVIEW_DEGREE = (
    "cur AS MATERIALIZED (SELECT id, atom_id FROM atom_current), "
    "degree AS (SELECT id, count(*) AS n FROM ("
    "SELECT coalesce(src_atom, src_entity) AS id FROM link WHERE retired_at IS NULL "
    "UNION ALL SELECT coalesce(dst_atom, dst_entity) FROM link WHERE retired_at IS NULL "
    "UNION ALL SELECT c.atom_id FROM cur c JOIN atom_about f ON f.revision_id = c.id "
    "UNION ALL SELECT f.entity_id FROM cur c JOIN atom_about f ON f.revision_id = c.id "
    "UNION ALL SELECT c.atom_id FROM cur c JOIN atom_derived f ON f.revision_id = c.id "
    "UNION ALL SELECT f.atom_id FROM cur c JOIN atom_derived f ON f.revision_id = c.id) e GROUP BY id)")
_CURRENT_ENTITY = "EXISTS (SELECT 1 FROM entity_revision r WHERE r.entity_id = e.id AND r.review_state <> 'declined')"
# Узлы обзора: записи с текущей ревизией и статусом из набора. С проектом — атомы со статусом из набора, у текущей
# ревизии которых scope.project — этот проект (кандидаты — по индексу 0010, текущая ли ревизия — по cur), и сущности
# на другом конце текущего ребра хотя бы одного такого атома (смежность — по индексам рёбер, как в обходе): сущность,
# связанная только с атомом проекта вне фильтра статусов, в обзор не попадает.
_OVERVIEW_NODES = {
    False: (
        # cur — одна строка на атом: соединение, а не IN, — PostgreSQL 16 иначе идёт по индексу atom 50 тыс. раз
        "nodes AS (SELECT 'atm' AS prefix, a.id, a.created_at FROM atom a JOIN cur c ON c.atom_id = a.id "
        "WHERE a.status = ANY(%(statuses)s) "
        f"UNION ALL SELECT 'ent', e.id, e.created_at FROM entity e WHERE e.status = ANY(%(statuses)s) "
        f"AND {_CURRENT_ENTITY})"),
    True: (
        "project_atoms AS MATERIALIZED (SELECT r.atom_id AS id FROM atom_revision r JOIN atom a ON a.id = r.atom_id "
        "WHERE r.payload->'scope'->>'project' = %(project)s AND r.id IN (SELECT id FROM cur) "
        "AND a.status = ANY(%(statuses)s)), "
        "project_entities AS (SELECT far AS id FROM ("
        + _graph_adjacent_sql(None, ids="ARRAY(SELECT id FROM project_atoms)") + ") e), "
        "nodes AS (SELECT 'atm' AS prefix, a.id, a.created_at FROM atom a "
        "WHERE a.id IN (SELECT id FROM project_atoms) "
        "UNION ALL SELECT 'ent', e.id, e.created_at FROM entity e WHERE e.status = ANY(%(statuses)s) "
        f"AND e.id IN (SELECT id FROM project_entities) AND {_CURRENT_ENTITY})"),
}


# Отбор обзора: ranked — все узлы под фильтром по degree (при равенстве новые первыми) с номером и total; хабы —
# первые %(hubs)s; near — соседи хабов по текущим рёбрам (тем же, что считает degree). Предел заполняется по очереди:
# хабы, их соседи по degree, остальные по degree — иначе top-N по degree на базе с хабами — почти одни сущности,
# и линий между ними нет.
_OVERVIEW_PICK = (
    "ranked AS MATERIALIZED (SELECT n.prefix, n.id, coalesce(d.n, 0) AS degree, row_number() OVER ("
    "ORDER BY coalesce(d.n, 0) DESC, n.created_at DESC, n.id DESC) AS rank, count(*) OVER () AS total "
    "FROM nodes n LEFT JOIN degree d ON d.id = n.id), "
    "hubs AS MATERIALIZED (SELECT id FROM ranked WHERE rank <= %(hubs)s), "
    "near AS (SELECT DISTINCT far AS id FROM (" + _graph_adjacent_sql(None, ids="ARRAY(SELECT id FROM hubs)") + ") e) "
    "SELECT r.prefix, r.id, r.degree, r.total, r.rank FROM ranked r "
    "ORDER BY CASE WHEN r.rank <= %(hubs)s THEN 0 WHEN r.id IN (SELECT id FROM near) THEN 1 ELSE 2 END, r.rank "
    "LIMIT %(limit)s")


def overview(conn: psycopg.Connection, *, limit: int | None = GRAPH_LIMIT, project: str | None = None,
             statuses=None, rels=None) -> dict:
    """Обзор базы без начальной записи (небо на главной): текущие сущности и записи, не больше limit узлов (None —
    все). Отбор: хабы — limit // 4 узлов (не меньше одного) с наибольшим degree, затем их соседи по текущим рёбрам
    по degree, оставшиеся места — прочие узлы по degree; при равенстве degree — новые первыми (время создания записи,
    затем id). Так в выдаче есть и линии, а не одни хабы без связей между собой. Порядок выдачи — по degree тем же
    правилом.

    degree — число текущих связей узла во всей базе (входящих и исходящих, в том числе к узлам вне фильтра и вне
    выдачи), pending — открытый пункт очереди проверки. Рёбра — только между вернувшимися узлами. total — сколько
    узлов было бы без предела (с тем же project и статусами), truncated — total > limit. project — ent:<UUID или
    ключ>: атомы с scope.project этого проекта и сущности, связанные хотя бы с одним из них (атомы — под фильтром
    статусов). statuses — как у других рецептов, ко всем шагам отбора; rels — виды рёбер выдачи (как
    у around_entity), на отбор узлов и степень не влияют.

    Отбор — один запрос: степень агрегатом по всем рёбрам, номер по degree и total — оконными функциями, соседи
    хабов — по индексам рёбер, предел — в базе; в Python приходят только вернувшиеся узлы."""
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
        raise records.RecordError(f"limit {limit!r}: нужно целое число от 1 или None")
    allowed_statuses = search._channel_statuses(statuses)
    rels = _graph_rels(conn, rels)
    project_ref = None
    if project is not None:
        if not isinstance(project, str):
            raise records.RecordError("project должен быть ссылкой ent:<UUID или ключ>")
        target, _, project_ref = _history_ref(conn, project)
        if target != "entity":
            raise records.RecordError(f"project {project}: нужна сущность ent:, а не атом")
    rows = conn.execute(
        f"WITH {_OVERVIEW_DEGREE}, {_OVERVIEW_NODES[project_ref is not None]}, {_OVERVIEW_PICK}",
        {"statuses": list(allowed_statuses), "project": project_ref, "limit": limit,
         "hubs": max(1, limit // 4) if limit is not None else 0}).fetchall()
    rows.sort(key=lambda row: row[4])                             # выдача — по degree, как номер в ranked
    total = rows[0][3] if rows else 0
    refs = [f"{prefix}:{record_id}" for prefix, record_id, *_ in rows]
    found = _graph_node_rows(conn, refs)
    nodes = {ref: found[ref] for ref in refs if ref in found}
    _graph_marks(conn, nodes, {record_id: degree for _, record_id, degree, *_ in rows})
    edges = _graph_edges(conn, list(nodes), rels, inner=True) if nodes else []
    return {
        "recipe": "overview", "project": project_ref,
        "nodes": [{key: value for key, value in node.items() if not key.startswith("_")} for node in nodes.values()],
        "edges": edges, "truncated": limit is not None and total > limit, "total": total, "retrieval_id": None,
    }
