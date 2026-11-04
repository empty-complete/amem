"""Поисковая проекция: нормализация марок и детерминированный текст текущей ревизии.

Содержимое источников и технические ссылки сюда не копируются. Веса A–D сохраняются отдельно,
чтобы PostgreSQL мог ранжировать подпись выше пояснения, а пояснение — выше контекста.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

import psycopg

from . import sources

SEARCH_TEXT_VERSION = 1
Target = Literal["atom", "entity"]
_UUID = re.compile(r"(?:atm:|ent:|obj:)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


@dataclass(frozen=True)
class SearchText:
    weighted: dict[str, tuple[str, ...]]
    document: str
    codes: tuple[str, ...]


def normalize_code(value: str) -> str:
    """Марка для точного и префиксного поиска; дефис между буквами, в отличие от цитат, сохраняется."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("марка должна быть непустой строкой")
    # sources.normalize склеивает переносы слов. Сначала ставим вокруг тире пробелы:
    # для normalize это уже не перенос, а после нормализации пробелы вокруг марочных знаков убираем.
    protected = "".join(" - " if unicodedata.category(ch) == "Pd" or ch == "−" else ch
                        for ch in unicodedata.normalize("NFC", value))
    normalized, _ = sources.normalize(protected)
    normalized = re.sub(r"\s*-\s*", "-", normalized)
    normalized = re.sub(r"\s*\.\s*", ".", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        raise ValueError("марка должна быть непустой строкой")
    return normalized


def _lang(value) -> list[str]:
    if isinstance(value, dict) and isinstance(value.get("ru"), str):
        return [value["ru"]]
    return []


def _content_strings(value) -> list[str]:
    """Строки содержимого в стабильном порядке; порядок списков значим, порядок JSON-ключей — нет."""
    if isinstance(value, str):
        return [] if _UUID.fullmatch(value) else [value]
    if isinstance(value, dict):
        out = []
        for key in sorted(value):
            out.extend(_content_strings(value[key]))
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_content_strings(item))
        return out
    return []


def _fragments(values) -> tuple[str, ...]:
    out = []
    seen = set()
    for value in values:
        if not isinstance(value, str):
            continue
        text = unicodedata.normalize("NFC", value).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return tuple(out)


def search_text(payload: dict, target: Target) -> SearchText:
    """Тело ревизии → взвешенные части, плоский документ для эмбеддинга и нормализованные марки."""
    if target not in ("atom", "entity"):
        raise ValueError(f"неизвестный вид записи {target!r}")
    a = _lang(payload.get("label"))
    b = _lang(payload.get("summary_plain")) + _lang(payload.get("body")) if target == "atom" else []
    if target == "atom":
        c = _content_strings(payload.get("content", {}))
    else:
        c = _lang(payload.get("description"))
    raw_codes = payload.get("codes") or []
    # aliases в спецификации идут перед марками; порядок частей D фиксируем независимо от порядка полей.
    d = list(payload.get("aliases") or []) + list(raw_codes) + _lang(payload.get("retrieval_context"))
    weighted = {weight: _fragments(parts) for weight, parts in zip("ABCD", (a, b, c, d))}
    document = " ".join(fragment for weight in "ABCD" for fragment in weighted[weight])
    codes = tuple(sorted({normalize_code(code) for code in raw_codes if isinstance(code, str) and code.strip()}))
    return SearchText(weighted, document, codes)


def refresh_record(conn: psycopg.Connection, target: Target, record_id) -> None:
    """Проекция одной записи из её текущей ревизии; вызывается в транзакции записи и при перестройке."""
    if target not in ("atom", "entity"):
        raise ValueError(f"неизвестный вид записи {target!r}")
    with conn.transaction():
        row = conn.execute(
            f"SELECT id, payload, content_hash, recorded_at FROM {target}_current WHERE {target}_id = %s",
            (record_id,)).fetchone()
        if row is None:
            conn.execute("DELETE FROM search_code WHERE target = %s AND record_id = %s", (target, record_id))
            conn.execute("DELETE FROM search_document WHERE target = %s AND record_id = %s", (target, record_id))
            return
        revision_id, payload, content_hash, recorded_at = row
        text = search_text(payload, target)
        parts = {weight.lower(): " ".join(text.weighted[weight]) for weight in "ABCD"}
        vector = " || ".join(f"setweight(to_tsvector('russian', %({weight.lower()})s), '{weight}')"
                             for weight in "ABCD")
        params = {"target": target, "record_id": record_id, "revision_id": revision_id,
                  "content_hash": content_hash, "document": text.document, "codes": list(text.codes),
                  "updated_at": recorded_at, **parts}
        conn.execute(
            f"INSERT INTO search_document (target, record_id, revision_id, content_hash, document, search_vector, "
            f"codes, updated_at) VALUES (%(target)s, %(record_id)s, %(revision_id)s, %(content_hash)s, %(document)s, "
            f"{vector}, %(codes)s, %(updated_at)s) ON CONFLICT (target, record_id) DO UPDATE SET "
            "revision_id = EXCLUDED.revision_id, content_hash = EXCLUDED.content_hash, "
            "document = EXCLUDED.document, search_vector = EXCLUDED.search_vector, codes = EXCLUDED.codes, "
            "updated_at = EXCLUDED.updated_at", params)
        conn.execute("DELETE FROM search_code WHERE target = %s AND record_id = %s", (target, record_id))
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO search_code (target, record_id, code) VALUES (%s, %s, %s)",
                            [(target, record_id, code) for code in text.codes])


def rebuild_search(conn: psycopg.Connection) -> int:
    """Полностью перестроить производный поиск из текущих ревизий; исходные записи не меняются."""
    with conn.transaction():
        rows = []
        for target in ("atom", "entity"):
            rows.extend((target, row[0]) for row in conn.execute(
                f"SELECT {target}_id FROM {target}_current ORDER BY {target}_id").fetchall())
        conn.execute("DELETE FROM search_code")
        conn.execute("DELETE FROM search_document")
        for target, record_id in rows:
            refresh_record(conn, target, record_id)
        return len(rows)


_CHANNEL_LIMIT = 50
_REF_PREFIX = {"atom": "atm", "entity": "ent"}
_DEFAULT_STATUSES = ("draft", "needs_review", "auto_verified", "verified")
_STATUSES = _DEFAULT_STATUSES + ("rejected", "deprecated", "superseded")


def _channel_targets(target, kind, entity_class) -> tuple[Target, ...]:
    if target is not None and target not in _REF_PREFIX:
        raise ValueError(f"неизвестный вид записи {target!r}")
    targets = (target,) if target is not None else ("atom", "entity")
    return tuple(t for t in targets if not (t == "atom" and entity_class is not None)
                 and not (t == "entity" and kind is not None))


def _channel_statuses(statuses) -> tuple[str, ...]:
    if statuses is None:
        return _DEFAULT_STATUSES
    if isinstance(statuses, str):
        raise ValueError("statuses должен быть последовательностью статусов, не строкой")
    values = tuple(dict.fromkeys(statuses))
    unknown = set(values) - set(_STATUSES)
    if unknown:
        raise ValueError(f"неизвестные статусы: {', '.join(sorted(unknown))}")
    return values


def _like_prefix(value: str) -> str:
    """Префикс LIKE: специальные символы запроса остаются обычными символами марки."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _lexical_channel(conn: psycopg.Connection, query: str, channel: str, *, target=None,
                     kind=None, entity_class=None, statuses=None) -> list[dict]:
    if not isinstance(query, str):
        raise ValueError("запрос должен быть строкой")
    if not query.strip():
        return []
    targets = _channel_targets(target, kind, entity_class)
    allowed_statuses = _channel_statuses(statuses)
    if not targets or not allowed_statuses:
        return []
    params = {"query": normalize_code(query) if channel != "fts" else query,
              "statuses": list(allowed_statuses)}
    if channel == "code_prefix":
        params["prefix"] = _like_prefix(params["query"])

    selects = []
    for current_target in targets:
        table = current_target                             # только из закрытого _REF_PREFIX
        conditions = [f"d.target = %(target_{table})s", "rec.status = ANY(%(statuses)s)"]
        params[f"target_{table}"] = table
        if table == "atom" and kind is not None:
            conditions.append("rec.kind = %(kind)s")
            params["kind"] = kind
        if table == "entity" and entity_class is not None:
            conditions.append("rec.entity_class = %(entity_class)s")
            params["entity_class"] = entity_class
        if channel == "code_exact":
            source_rank = "NULL::float"
            conditions.append("EXISTS (SELECT 1 FROM search_code c WHERE c.target = d.target "
                              "AND c.record_id = d.record_id AND c.code = %(query)s)")
        elif channel == "code_prefix":
            source_rank = "NULL::float"
            conditions.append("EXISTS (SELECT 1 FROM search_code c WHERE c.target = d.target "
                              "AND c.record_id = d.record_id AND c.code LIKE %(prefix)s ESCAPE '\\')")
            # Даже если у записи есть более длинная марка, точное совпадение получает вес только в code_exact.
            conditions.append("NOT EXISTS (SELECT 1 FROM search_code c WHERE c.target = d.target "
                              "AND c.record_id = d.record_id AND c.code = %(query)s)")
        elif channel == "fts":
            source_rank = "ts_rank_cd(d.search_vector, websearch_to_tsquery('russian', %(query)s))"
            conditions.append("d.search_vector @@ websearch_to_tsquery('russian', %(query)s)")
        else:
            raise ValueError(f"неизвестный лексический канал {channel!r}")
        selects.append(f"SELECT d.target, d.record_id, d.revision_id, {source_rank} AS source_rank "
                       f"FROM search_document d JOIN {table} rec ON rec.id = d.record_id "
                       f"WHERE {' AND '.join(conditions)}")
    order = "source_rank DESC, target, record_id" if channel == "fts" else "target, record_id"
    rows = conn.execute(f"SELECT * FROM ({' UNION ALL '.join(selects)}) found "
                        f"ORDER BY {order} LIMIT {_CHANNEL_LIMIT}", params).fetchall()
    return [{"target": row[0], "record_id": str(row[1]), "revision_id": str(row[2]),
             "ref": f"{_REF_PREFIX[row[0]]}:{row[1]}", "rank": rank, "source_rank": row[3]}
            for rank, row in enumerate(rows, 1)]


def _code_exact(conn: psycopg.Connection, query: str, **filters) -> list[dict]:
    return _lexical_channel(conn, query, "code_exact", **filters)


def _code_prefix(conn: psycopg.Connection, query: str, **filters) -> list[dict]:
    return _lexical_channel(conn, query, "code_prefix", **filters)


def _fts(conn: psycopg.Connection, query: str, **filters) -> list[dict]:
    return _lexical_channel(conn, query, "fts", **filters)


RANKING_V1 = {
    "version": "rrf-v1",
    "k": 60,
    "recipes": {
        "exact_fact": {"code_exact": 4, "code_prefix": 2, "fts": 1, "vector": 0.25},
        "similar": {"vector": 2, "fts": 0.5},
    },
}


def _rrf(channels: dict[str, list[dict] | None], weights: dict[str, float], *, limit: int = 10,
         exact_fact: bool = False, durations_ms: dict[str, float] | None = None) -> dict:
    """Слить ранжированные каналы по RRF; None означает пропущенный, а не пустой канал."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit должен быть целым числом от 1 до 100")

    used_channels = [channel for channel in weights if channels.get(channel) is not None]
    skipped_channels = [channel for channel in weights if channels.get(channel) is None]
    exact_refs = {row["ref"] for row in channels.get("code_exact") or []}
    merged = {}
    for channel, weight in weights.items():
        rows = channels.get(channel)
        if rows is None:
            continue
        for row in rows:
            ref = row["ref"]
            # Точная марка получает только вклад code_exact, даже при искусственно продублированном входе.
            if channel == "code_prefix" and ref in exact_refs:
                continue
            hit = merged.setdefault(ref, {
                "target": row["target"], "record_id": row["record_id"],
                "revision_id": row["revision_id"], "ref": ref, "score": 0.0, "matches": [],
            })
            rank = row["rank"]
            hit["score"] += weight / (RANKING_V1["k"] + rank)
            hit["matches"].append({"channel": channel, "rank": rank, "source_rank": row["source_rank"]})

    ordered = sorted(merged.values(), key=lambda hit: (
        0 if exact_fact and hit["ref"] in exact_refs else 1, -hit["score"], hit["ref"]))
    timings = durations_ms or {}
    return {
        "hits": ordered[:limit],
        "ranking_version": RANKING_V1["version"],
        "used_channels": used_channels,
        "skipped_channels": skipped_channels,
        "candidate_count": len(merged),
        "durations_ms": {channel: timings[channel] for channel in weights if channel in timings},
    }


def _snippet(document: str, limit: int = 240) -> str:
    if len(document) <= limit:
        return document
    return document[:limit].rsplit(" ", 1)[0] + "…"


def _enrich(conn: psycopg.Connection, candidates: list[dict], *, include_record=False) -> list[dict]:
    """Добавить к внутренним кандидатам только публичные поля карточки; очки здесь не раскрываются."""
    if not candidates:
        return []
    grouped = {}
    for candidate in candidates:
        target = candidate["target"]
        if target not in _REF_PREFIX:
            raise ValueError(f"неизвестный вид записи {target!r}")
        grouped.setdefault(target, []).append(candidate["record_id"])
    rows = {}
    for target, record_ids in grouped.items():
        result = conn.execute(
            f"SELECT d.target, d.record_id, d.document, r.n, r.review_state, rec.status, r.payload->'label' "
            f"FROM search_document d JOIN {target} rec ON rec.id = d.record_id "
            f"JOIN {target}_current r ON r.id = d.revision_id "
            f"WHERE d.target = %(target)s AND d.record_id = ANY(%(ids)s::uuid[])",
            {"target": target, "ids": record_ids}).fetchall()
        rows.update({(row[0], str(row[1])): row for row in result})

    if include_record:
        from . import lookup                       # records → search: импорт только по требованию
    cards = []
    for candidate in candidates:
        target, record_id = candidate["target"], candidate["record_id"]
        row = rows.get((target, record_id))
        if row is None:
            raise ValueError(f"поисковая проекция {candidate['ref']} не найдена")
        card = {"ref": candidate["ref"], "revision": row[3], "label": row[6],
                "snippet": _snippet(row[2]), "status": row[5], "review_state": row[4]}
        if include_record:
            card["record"] = lookup.get(conn, target, record_id)
        cards.append(card)
    return cards
