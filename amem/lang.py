"""Языки текста записей (docs/superpowers/specs/2026-11-09-amem-text-languages-design.md): слоты LangString,
порядок замены, язык вызова.

LANGS — слоты LangString схемы v1 (у LangString нужен хотя бы один). Текст на языке lang берётся из его слота,
а если там пусто — из следующего по LANGS; пустая строка и строка из пробелов — то же, что отсутствие. Без языка
(None) — порядок LANGS: ru, затем en.

Язык вызова — current(): его ставит на время вызова using(lang) — служба по Accept-Language (app.connection),
MCP по аргументу lang, CLI по --lang, а без них — Settings.lang (AMEM_LANG или lang в amem.toml); операции
amem/api.py его читают и передают библиотеке (lookup, recipes) явно.

FTS — конфигурация полнотекстового поиска PostgreSQL для слота: ru — russian (она же для языконезависимого текста:
ASCII-слова она ведёт английским стеммером), en — english. tsquery(expr) — запрос на любом из языков.
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar

LANGS = ("ru", "en")
FTS = {"ru": "russian", "en": "english"}

_current: ContextVar[str | None] = ContextVar("amem_lang", default=None)


class LangError(ValueError):
    """Язык не из LANGS."""


def check(value) -> str | None:
    """Язык параметра: ru или en (регистр и пробелы по краям не важны); None и «» — без языка. Иное — LangError."""
    if value is None or value == "":
        return None
    if isinstance(value, str) and value.strip().lower() in LANGS:
        return value.strip().lower()
    raise LangError(f"lang {value!r}: допустимы {', '.join(LANGS)}")


def from_header(header: str | None) -> str | None:
    """Язык из Accept-Language: поддерживаемый с наибольшим q, при равных — первый в заголовке; en-GB → en.
    q=0 и «*» язык не выбирают; нет поддерживаемого или заголовок не разобрать — None (порядок по умолчанию)."""
    if not isinstance(header, str):
        return None
    best, best_q = None, 0.0
    for part in header.split(","):
        tag, _, params = part.partition(";")
        q = 1.0
        for param in params.split(";"):
            key, _, value = param.partition("=")
            if key.strip().lower() == "q":
                try:
                    q = float(value.strip())
                except ValueError:
                    q = 0.0
        primary = tag.strip().lower().split("-", 1)[0]
        if primary in LANGS and q > best_q:          # NaN не больше ничего — такой язык не выбирается
            best, best_q = primary, q
    return best


def order(lang: str | None = None) -> tuple[str, ...]:
    """Слоты по порядку замены: lang, затем остальные по LANGS; без языка — LANGS."""
    lang = check(lang)
    return LANGS if lang is None else (lang, *(slot for slot in LANGS if slot != lang))


def pick(value, lang: str | None = None) -> str | None:
    """Текст LangString на языке lang с заменой по order(lang); строка — как есть; пустой LangString и не текст —
    None."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for slot in order(lang):
            text = value.get(slot)
            if isinstance(text, str) and text.strip():
                return text
    return None


def texts(value) -> list[tuple[str, str]]:
    """Непустые слоты LangString по LANGS: [(слот, текст)]; не LangString — пусто."""
    if not isinstance(value, dict):
        return []
    return [(slot, value[slot]) for slot in LANGS if isinstance(value.get(slot), str) and value[slot].strip()]


def sql(expr: str, lang: str | None = None) -> str:
    """SQL-выражение текста LangString (jsonb-выражение expr) по order(lang); пустой слот пропускается, как в pick.
    expr — только из кода, не из запроса: оно встраивается в текст SQL."""
    return "coalesce(" + ", ".join(f"CASE WHEN btrim({expr}->>'{slot}') <> '' THEN {expr}->>'{slot}' END"
                                   for slot in order(lang)) + ")"


def tsquery(param: str) -> str:
    """SQL запроса полнотекстового поиска на любом языке: websearch_to_tsquery каждой конфигурации FTS через ||.
    param — заполнитель psycopg (%(query)s или %s)."""
    return "(" + " || ".join(f"websearch_to_tsquery('{FTS[slot]}', {param})" for slot in LANGS) + ")"


def current() -> str | None:
    """Язык вызова (using); None — не задан."""
    return _current.get()


@contextlib.contextmanager
def using(lang: str | None) -> Iterator[str | None]:
    """Язык вызова на время блока; None — без языка (порядок по умолчанию)."""
    token = _current.set(check(lang))
    try:
        yield _current.get()
    finally:
        _current.reset(token)
