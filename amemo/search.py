"""Поисковая проекция: нормализация марок и детерминированный текст текущей ревизии.

Содержимое источников и технические ссылки сюда не копируются. Веса A–D сохраняются отдельно,
чтобы PostgreSQL мог ранжировать подпись выше пояснения, а пояснение — выше контекста.

Языки (amemo.lang): слоты ru и языконезависимый текст (содержимое, aliases, марки) индексируются конфигурацией
russian, слоты en — english; запрос идёт на обеих (lang.tsquery). Документ эмбеддинга — по весам сначала ru, затем
en: у записи без en он тот же, что до появления слота en в индексе, и векторы не пересчитываются. Фрагмент находки
строится из текста на языке выдачи (shown_text). PROJECTION — версия проекции: db.prepare перестраивает поиск
базы, у которой meta.search_projection меньше (ensure_projection).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

import psycopg
from psycopg.types.json import Jsonb

from . import lang as lang_, sources

SEARCH_TEXT_VERSION = 1
PROJECTION = 2                       # 2 — слоты en в индексе (english); meta.search_projection
PROJECTION_LOCK = 0x616D656D00000002  # pg_advisory_xact_lock перестройки при старте: «amemo» + 2
Target = Literal["atom", "entity"]
_UUID = re.compile(r"(?:atm:|ent:|obj:)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


@dataclass(frozen=True)
class SearchText:
    weighted: dict[str, tuple[str, ...]]     # конфигурация russian: слоты ru и языконезависимый текст
    document: str
    codes: tuple[str, ...]
    english: dict[str, tuple[str, ...]]      # конфигурация english: слоты en (без фрагментов, что уже в weighted)


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


def _slot(value, slot: str) -> list[str]:
    if isinstance(value, dict) and isinstance(value.get(slot), str):
        return [value[slot]]
    return []


def _content_strings(value, shown: bool = False, lang: str | None = None) -> list[str]:
    """Строки содержимого в стабильном порядке; порядок списков значим, порядок JSON-ключей — нет.
    shown — текст на одном языке: у вложенного LangString (только ключи ru, en) — один слот по lang.pick."""
    if isinstance(value, str):
        return [] if _UUID.fullmatch(value) else [value]
    if isinstance(value, dict):
        if shown and value and set(value) <= set(lang_.LANGS):
            text = lang_.pick(value, lang)
            return [text] if text else []
        out = []
        for key in sorted(value):
            out.extend(_content_strings(value[key], shown, lang))
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_content_strings(item, shown, lang))
        return out
    return []


def _parts(payload: dict, target: Target, text) -> tuple[list[str], list[str], list[str], list[str]]:
    """LangString-поля тела по весам A–D; text(LangString) → строки одного слота или выбранного языка."""
    a = text(payload.get("label"))
    b = text(payload.get("summary_plain")) + text(payload.get("body")) if target == "atom" else []
    c = text(payload.get("description")) if target == "entity" else []
    return a, b, c, text(payload.get("retrieval_context"))


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
    a, b, c, d = _parts(payload, target, lambda value: _slot(value, "ru"))
    if target == "atom":
        c = _content_strings(payload.get("content", {}))
    raw_codes = payload.get("codes") or []
    # aliases в спецификации идут перед марками; порядок частей D фиксируем независимо от порядка полей.
    d = list(payload.get("aliases") or []) + list(raw_codes) + d
    weighted = {weight: _fragments(parts) for weight, parts in zip("ABCD", (a, b, c, d))}
    english = {weight: tuple(f for f in _fragments(parts) if f not in weighted[weight])
               for weight, parts in zip("ABCD", _parts(payload, target, lambda value: _slot(value, "en")))}
    document = " ".join(fragment for weight in "ABCD" for fragment in (*weighted[weight], *english[weight]))
    codes = tuple(sorted({normalize_code(code) for code in raw_codes if isinstance(code, str) and code.strip()}))
    return SearchText(weighted, document, codes, english)


def shown_text(payload: dict, target: Target, lang: str | None = None) -> str:
    """Текст записи на одном языке — каждое LangString-поле одним слотом по lang.pick(…, lang); порядок и состав —
    как у документа search_text. Из него строится фрагмент находки."""
    if target not in ("atom", "entity"):
        raise ValueError(f"неизвестный вид записи {target!r}")

    def text(value) -> list[str]:
        picked = lang_.pick(value, lang) if isinstance(value, dict) else None
        return [picked] if picked else []

    a, b, c, d = _parts(payload, target, text)
    if target == "atom":
        c = _content_strings(payload.get("content", {}), shown=True, lang=lang)
    d = list(payload.get("aliases") or []) + list(payload.get("codes") or []) + d
    return " ".join(fragment for parts in (a, b, c, d) for fragment in _fragments(parts))


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
        # конфигурация FTS → части по весам; ключ параметра — «конфигурация_вес», имена только из кода
        configs = {lang_.FTS["ru"]: text.weighted, lang_.FTS["en"]: text.english}
        parts = {f"{config}_{weight.lower()}": " ".join(weighted[weight])
                 for config, weighted in configs.items() for weight in "ABCD"}
        vector = " || ".join(f"setweight(to_tsvector('{config}', %({config}_{weight.lower()})s), '{weight}')"
                             for config in configs for weight in "ABCD")
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


def ensure_projection(conn: psycopg.Connection) -> bool:
    """Перестроить поиск, если версия проекции в базе (meta.search_projection) меньше PROJECTION; True — перестроен.
    Под рекомендательной блокировкой транзакции: две службы, стартующие разом, не строят проекцию вдвоём."""
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (PROJECTION_LOCK,))
        row = conn.execute("SELECT value FROM meta WHERE key = 'search_projection'").fetchone()
        if row is not None and isinstance(row[0], int) and row[0] >= PROJECTION:
            return False
        rebuild_search(conn)
        conn.execute("INSERT INTO meta (key, value) VALUES ('search_projection', %s) "
                     "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (Jsonb(PROJECTION),))
    return True


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


def _codes(value, name: str) -> tuple[str, ...] | None:
    """Фильтр kind или entity_class: одно значение строкой или несколько последовательностью; повторы убираются.
    None и пустой набор — без фильтра (как у lookup.list_records)."""
    if value is None:
        return None
    if isinstance(value, str):
        values = (value,)
    else:
        try:
            values = tuple(value)
        except TypeError:
            raise ValueError(f"{name} {value!r}: нужен код или последовательность кодов") from None
    for v in values:
        if not isinstance(v, str) or not v:
            raise ValueError(f"{name}: код {v!r} — нужна непустая строка")
    return tuple(dict.fromkeys(values)) or None


def _channel_targets(target, kinds, classes) -> tuple[Target, ...]:
    """Виды записей канала. kinds отбирает атомы, classes — сущности: заданный фильтр одного вида записей
    исключает другой вид, если для него фильтра нет; заданы оба — атомы этих видов и сущности этих классов."""
    if target is not None and target not in _REF_PREFIX:
        raise ValueError(f"неизвестный вид записи {target!r}")
    targets = (target,) if target is not None else ("atom", "entity")
    if kinds is None and classes is None:
        return targets
    return tuple(t for t in targets
                 if (t == "atom" and kinds is not None) or (t == "entity" and classes is not None))


def _kind_conditions(table: str, kinds, classes, conditions: list[str], params: dict) -> None:
    """Условие вида атома или класса сущности для ветки канала; table — только из закрытого _REF_PREFIX."""
    if table == "atom" and kinds is not None:
        conditions.append("rec.kind = ANY(%(kinds)s)")
        params["kinds"] = list(kinds)
    if table == "entity" and classes is not None:
        conditions.append("rec.entity_class = ANY(%(classes)s)")
        params["classes"] = list(classes)


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
                     kind=None, entity_class=None, statuses=None, exclude=None) -> list[dict]:
    if not isinstance(query, str):
        raise ValueError("запрос должен быть строкой")
    kinds, classes = _codes(kind, "kind"), _codes(entity_class, "entity_class")
    if not query.strip():
        return []
    targets = _channel_targets(target, kinds, classes)
    allowed_statuses = _channel_statuses(statuses)
    if not targets or not allowed_statuses:
        return []
    params = {"query": normalize_code(query) if channel != "fts" else query,
              "statuses": list(allowed_statuses)}
    if channel == "code_prefix":
        params["prefix"] = _like_prefix(params["query"])
    if exclude is not None:
        if exclude[0] not in _REF_PREFIX:
            raise ValueError(f"неизвестный вид записи {exclude[0]!r}")
        params["exclude_target"], params["exclude_record_id"] = exclude

    selects = []
    for current_target in targets:
        table = current_target                             # только из закрытого _REF_PREFIX
        conditions = [f"d.target = %(target_{table})s", "rec.status = ANY(%(statuses)s)"]
        params[f"target_{table}"] = table
        if exclude is not None:
            conditions.append("NOT (d.target = %(exclude_target)s AND d.record_id = %(exclude_record_id)s)")
        _kind_conditions(table, kinds, classes, conditions, params)
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
            source_rank = f"ts_rank_cd(d.search_vector, {lang_.tsquery('%(query)s')})"
            conditions.append(f"d.search_vector @@ {lang_.tsquery('%(query)s')}")
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


# Тот же preimage, что в embed.text_hash, но вычисляемый в SQL до отсечения топ-50.
_FRESH_TEXT_HASH = (
    "e.text_hash = %(hash_prefix)s || encode(sha256("
    "convert_to('amemo-search-text', 'UTF8') || decode('00', 'hex') || "
    "convert_to(%(text_version)s, 'UTF8') || decode('00', 'hex') || "
    "convert_to(d.document, 'UTF8')), 'hex')"
)


def _active_model(conn: psycopg.Connection):
    return conn.execute(
        "SELECT id, name, version, dims, backend, active, created_at FROM embedding_model "
        "WHERE active").fetchone()


def _hash_params() -> dict:
    return {"hash_prefix": f"sha256-s{SEARCH_TEXT_VERSION}:", "text_version": str(SEARCH_TEXT_VERSION)}


def _current_embedding(conn: psycopg.Connection, target: Target, record_id, model_id):
    """Свежий вектор именно текущей ревизии и активной модели; старую ревизию не подставлять."""
    if target not in _REF_PREFIX:
        raise ValueError(f"неизвестный вид записи {target!r}")
    from pgvector.psycopg import register_vector
    register_vector(conn)
    table = target
    return conn.execute(
        f"SELECT e.vec FROM search_document d JOIN {table}_current r ON r.id = d.revision_id "
        f"AND r.{table}_id = d.record_id JOIN embedding e ON e.target = d.target "
        f"AND e.revision_id = d.revision_id JOIN embedding_model m ON m.id = e.model_id AND m.active "
        f"WHERE d.target = %(target)s AND d.record_id = %(record_id)s AND m.id = %(model_id)s "
        f"AND e.dims = m.dims AND {_FRESH_TEXT_HASH}",
        {"target": target, "record_id": record_id, "model_id": model_id, **_hash_params()}).fetchone()


def _vector(conn: psycopg.Connection, vector, model_id, *, target=None, kind=None,
            entity_class=None, statuses=None, exclude=None) -> list[dict]:
    """Топ-50 по фактическому cosine distance среди свежих векторов активной модели."""
    kinds, classes = _codes(kind, "kind"), _codes(entity_class, "entity_class")
    targets = _channel_targets(target, kinds, classes)
    allowed_statuses = _channel_statuses(statuses)
    if not targets or not allowed_statuses:
        return []
    from pgvector import HalfVector
    from pgvector.psycopg import register_vector
    register_vector(conn)
    params = {"query_vector": vector if isinstance(vector, HalfVector) else HalfVector(vector),
              "model_id": model_id, "statuses": list(allowed_statuses), **_hash_params()}
    if exclude is not None:
        if exclude[0] not in _REF_PREFIX:
            raise ValueError(f"неизвестный вид записи {exclude[0]!r}")
        params["exclude_target"], params["exclude_record_id"] = exclude

    selects = []
    for current_target in targets:
        table = current_target
        conditions = [
            f"d.target = %(target_{table})s", "rec.status = ANY(%(statuses)s)",
            "m.id = %(model_id)s AND m.active", "e.dims = m.dims", _FRESH_TEXT_HASH,
        ]
        params[f"target_{table}"] = table
        if exclude is not None:
            conditions.append("NOT (d.target = %(exclude_target)s AND d.record_id = %(exclude_record_id)s)")
        _kind_conditions(table, kinds, classes, conditions, params)
        selects.append(
            f"SELECT d.target, d.record_id, d.revision_id, e.vec <=> %(query_vector)s AS source_rank "
            f"FROM search_document d JOIN {table} rec ON rec.id = d.record_id "
            f"JOIN {table}_current r ON r.id = d.revision_id AND r.{table}_id = d.record_id "
            f"JOIN embedding e ON e.target = d.target AND e.revision_id = d.revision_id "
            f"JOIN embedding_model m ON m.id = e.model_id WHERE {' AND '.join(conditions)}")

    # Все вызовы имеют хотя бы фильтр статуса. Iterative scan не даёт HNSW остановиться
    # на первых неподходящих векторах; окончательный порядок задаёт фактическое distance.
    with conn.transaction():
        conn.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
        rows = conn.execute(
            f"SELECT * FROM ({' UNION ALL '.join(selects)}) found "
            f"ORDER BY source_rank ASC, target, record_id LIMIT {_CHANNEL_LIMIT}", params).fetchall()
    return [{"target": row[0], "record_id": str(row[1]), "revision_id": str(row[2]),
             "ref": f"{_REF_PREFIX[row[0]]}:{row[1]}", "rank": rank, "source_rank": float(row[3])}
            for rank, row in enumerate(rows, 1)]


RANKING_V1 = {
    "version": "rrf-v1",
    "k": 60,
    "recipes": {
        "exact_fact": {"code_exact": 4, "code_prefix": 2, "fts": 1, "vector": 0.25},
        "similar": {"vector": 2, "fts": 0.5},
    },
}


def _rrf(channels: dict[str, list[dict] | None], weights: dict[str, float], *, limit: int = 10,
         exact_fact: bool = False, durations_ms: dict[str, float] | None = None,
         usefulness: dict[str, float] | None = None) -> dict:
    """Слить каналы по RRF, затем применить полезность и только после этого отсортировать."""
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

    if usefulness:
        for hit in merged.values():
            hit["score"] *= usefulness.get(hit["ref"], 1)
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


def _enrich(conn: psycopg.Connection, candidates: list[dict], *, include_record=False,
            lang: str | None = None) -> list[dict]:
    """Добавить к внутренним кандидатам только публичные поля карточки; очки здесь не раскрываются.
    label — LangString ревизии целиком, snippet — из текста на языке lang с заменой (shown_text)."""
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
            f"SELECT d.target, d.record_id, d.document, r.n, r.review_state, rec.status, r.payload "
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
        card = {"ref": candidate["ref"], "revision": row[3], "label": row[6].get("label"),
                "snippet": _snippet(shown_text(row[6], target, lang)), "status": row[5], "review_state": row[4]}
        if include_record:
            card["record"] = lookup.get(conn, target, record_id)
        cards.append(card)
    return cards
