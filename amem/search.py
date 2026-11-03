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
