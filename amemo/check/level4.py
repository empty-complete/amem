"""Уровень 4 автопроверки — дубли (спецификация подпроекта 3, разд. 6).

Кандидаты — текущие записи базы того же вида атома (класса сущности) в рабочих статусах, кроме самой записи и
записей, которые правит эта же пачка (их новые тела сравниваются внутри пачки). Каналы:
- текст: лексемы подписи через «или» — до CANDIDATES кандидатов, схожесть — token_sort_ratio нормализованных
  подписей; у сущности — лучшая пара среди подписей и aliases;
- вектор: вектор поискового документа тела против свежих векторов активной модели, схожесть = 1 − cosine distance.
Внутри пачки записи сравниваются попарно, текстом: дубль отмечается у более поздней.

Итог по кандидату: duplicate (warning) — выше порога дубля в любом канале, related (info) — выше порога связи,
не больше RELATED. Без вектора работает только текст, причина — в возвращаемом degraded. База только читается;
журнал выдачи (retrieval) не пишется — это не поиск пользователя.
"""
from __future__ import annotations

import functools
import os
import re
import uuid

from rapidfuzz import fuzz

from .. import embed, lang, recipes, search
from ..records import PREFIX
from .level1 import CODE_FIELD, Batch, Prepared
from .report import Report

LEVEL = 4
DUP_TEXT = 90
DUP_VECTOR = 0.92
REL_TEXT = 60
REL_VECTOR = 0.80
CANDIDATES = 20
RELATED = 5
LIVE = ("draft", "needs_review", "auto_verified", "verified")
SUGGEST = {"atom": "merge", "entity": "same_as"}
_PUNCT = re.compile(r"[^\w\s]+")
_SPACE = re.compile(r"\s+")

# Текстовые кандидаты: лексемы подписи по конфигурациям всех языков (amemo.lang.FTS: индекс ведёт слоты ru и en
# разными стеммерами) — запрос «любое из слов» (simple, без повторного разбора).
# Имена таблицы и столбца кода — только из CODE_FIELD; self — NULL у новой записи, поэтому IS DISTINCT FROM.
_LEXEMES = " || ".join(f"to_tsvector('{config}', %(label)s)" for config in dict.fromkeys(lang.FTS.values()))
_TEXT_SQL = """
WITH q AS (SELECT to_tsquery('simple', string_agg(quote_literal(l), ' | ')) AS query
             FROM unnest(tsvector_to_array(""" + _LEXEMES + """)) l)
SELECT d.record_id, c.payload
  FROM q, search_document d
  JOIN {t} a ON a.id = d.record_id
  JOIN {t}_current c ON c.{t}_id = a.id
 WHERE q.query IS NOT NULL AND d.target = '{t}' AND a.{code} = %(code)s
   AND a.status = ANY(%(statuses)s) AND a.id IS DISTINCT FROM %(self)s
   AND d.search_vector @@ q.query
 ORDER BY ts_rank_cd(d.search_vector, q.query) DESC, d.record_id LIMIT {limit}
"""


def check(conn, batch: Batch, report: Report, *, provider=None,
          on_semantic_error: str = "raise") -> list[dict]:
    """Уровень 4 над пачкой: замечания — в report; результат — degraded (пусто, если вектор работал).

    EmbeddingError явного провайдера уходит наружу (on_semantic_error="raise"): его выбрал вызывающий, и молча
    ослаблять проверку нельзя. При "skip" (служба: provider один на запуск, а модель базы могли сменить) векторный
    канал пропускается с причиной provider_error в degraded, как у неявного провайдера, — текст работает."""
    check_semantic_error(on_semantic_error)
    items = [it for it in batch.items if it.ok and it.target in CODE_FIELD]
    edited = {(it.target, it.record_id) for it in items if it.record_id is not None}
    found: dict[str, dict[str, dict]] = {it.label: {} for it in items}      # метка → ref → кандидат
    for item in items:
        for record_id, payload in _text_rows(conn, item):
            if (item.target, record_id) not in edited:
                _offer(found[item.label], f"{PREFIX[item.target]}:{record_id}", "text", _text_score(item, payload))
    degraded = _vector_channel(conn, items, edited, found, provider,
                               raise_errors=on_semantic_error == "raise")
    for j, item in enumerate(items):
        for other in items[:j]:
            if other.target == item.target and other.code == item.code:
                _offer(found[item.label], other.label, "text", _text_score(item, other.payload))
    for item in items:
        _report(report, item, found[item.label])
    return degraded


# --- текст ---

def _normalize(text: str) -> str:
    text = _PUNCT.sub(" ", text.lower().replace("ё", "е"))
    return _SPACE.sub(" ", text).strip()


def _names(payload: dict, target: str) -> list[str]:
    """Подписи на всех языках, у сущности — и aliases; нормализованные, без пустых."""
    label = payload.get("label")
    names = [v for v in label.values() if isinstance(v, str)] if isinstance(label, dict) else []
    if target == "entity":
        names += [a for a in payload.get("aliases") or [] if isinstance(a, str)]
    return [n for n in map(_normalize, names) if n]


def _text_score(item: Prepared, payload: dict) -> float:
    mine, theirs = _names(item.payload, item.target), _names(payload, item.target)
    return max((fuzz.token_sort_ratio(a, b) for a in mine for b in theirs), default=0.0)


def _text_rows(conn, item: Prepared) -> list[tuple]:
    words = " ".join(_names(item.payload, item.target))
    if not words:
        return []
    sql = _TEXT_SQL.format(t=item.target, code=CODE_FIELD[item.target], limit=CANDIDATES)
    return conn.execute(sql, {"label": words, "code": item.code, "statuses": list(LIVE),
                              "self": item.record_id}).fetchall()


# --- вектор ---

def check_semantic_error(value: str) -> None:
    if value not in recipes.SEMANTIC_ERRORS:
        raise ValueError(f"on_semantic_error {value!r}: допустимы {', '.join(recipes.SEMANTIC_ERRORS)}")


@functools.cache
def _implicit():
    """Неявный провайдер — один на процесс: модель не загружается заново на каждый пакет."""
    return embed.get_provider()


def _provider(explicit):
    if explicit is not None:
        return embed.get_provider(explicit)
    if os.environ.get("AMEMO_BACKEND", "fastembed").strip().lower() == "none":
        return None                           # none проверяется при каждом вызове, мимо кэша
    return _implicit()


def _vector_channel(conn, items: list[Prepared], edited: set, found: dict, explicit, *,
                    raise_errors: bool = True) -> list[dict]:
    model = search._active_model(conn)
    if model is None:
        return _degraded("no_active_model")
    documents = [search.search_text(it.payload, it.target).document for it in items]
    try:
        selected = _provider(explicit)
        if selected is None:
            return _degraded("backend_disabled")
        recipes._check_query_provider(model, selected)
        wanted = [d for d in documents if d]
        vectors = iter(selected.embed(wanted))
    except embed.EmbeddingError:
        if explicit is not None and raise_errors:
            raise
        return _degraded("provider_error")
    for item, document in zip(items, documents):
        if not document:
            continue
        vector = next(vectors)
        filters = {"kind": item.code} if item.target == "atom" else {"entity_class": item.code}
        exclude = (item.target, item.record_id) if item.record_id is not None else None
        for row in search._vector(conn, vector, model[0], target=item.target, statuses=LIVE,
                                  exclude=exclude, **filters)[:CANDIDATES]:
            if (item.target, uuid.UUID(row["record_id"])) not in edited:
                _offer(found[item.label], row["ref"], "vector", 1.0 - row["source_rank"])
    return []


def _degraded(reason: str) -> list[dict]:
    return [{"level": LEVEL, "channel": "vector", "reason": reason}]


# --- итог ---

def _verdict(channel: str, score: float) -> str | None:
    dup, rel = (DUP_TEXT, REL_TEXT) if channel == "text" else (DUP_VECTOR, REL_VECTOR)
    return "duplicate" if score >= dup else "related" if score >= rel else None


def _offer(found: dict[str, dict], ref: str, channel: str, score: float) -> None:
    """Кандидат с итогом; из двух каналов остаётся более сильный итог (при равном — первый пришедший)."""
    verdict = _verdict(channel, score)
    if verdict is None:
        return
    current = found.get(ref)
    if current is None or (current["verdict"], verdict) == ("related", "duplicate"):
        found[ref] = {"ref": ref, "channel": channel, "score": round(float(score), 4), "verdict": verdict}


def _strength(cand: dict) -> float:
    """Общая шкала для порядка: текст в долях от 100, вектор как есть."""
    return cand["score"] / 100 if cand["channel"] == "text" else cand["score"]


def _report(report: Report, item: Prepared, found: dict[str, dict]) -> None:
    ordered = sorted(found.values(), key=lambda c: (-_strength(c), c["ref"]))
    dup = [{**_public(c), "suggest": SUGGEST[item.target]} for c in ordered if c["verdict"] == "duplicate"]
    rel = [_public(c) for c in ordered if c["verdict"] == "related"][:RELATED]
    if dup:
        report.add(LEVEL, "warning", "duplicate", item.label,
                   "Похоже на " + ", ".join(c["ref"] for c in dup)
                   + (": кандидат в same_as." if item.target == "entity" else ": кандидат в слияние."),
                   candidates=dup)
    if rel:
        report.add(LEVEL, "info", "related", item.label,
                   "Похожие записи ниже порога дубля: " + ", ".join(c["ref"] for c in rel) + ".", candidates=rel)


def _public(cand: dict) -> dict:
    return {k: cand[k] for k in ("ref", "channel", "score")}
