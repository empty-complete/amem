"""Каноническая форма тела ревизии и его хэш (спецификация, разд. 1, «Каноническая форма ревизии»).

Одинаковое содержание всегда даёт один хэш. Правила c1:
- нет входного поля ref; у источника нет path — его заменяет объект: object и object_version, у файла ещё digest
  (их ставит разбор источников, этап 2.2; у страницы сайта и переписки digest нет);
- все ссылки — только по UUID: atm:/ent:/obj: + UUIDv7 нужного вида, ключи и @имена уже разрешены;
- рекурсивно убраны null, пустые списки и пустые объекты — кроме строк таблицы (Table.rows),
  где пустая ячейка держит позицию; пустые строки остаются — непустоту проверяют шаблоны;
- все строки, и ключи, и значения, — в Unicode NFC: текст из PDF и имён файлов часто приходит в NFD,
  и одинаковые «й» и «ё» иначе дали бы разные хэши;
- целое больше 2^53 − 1 записывается числом с плавающей точкой. jsonb хранит самую короткую десятичную запись
  числа и возвращает большое число целым (1e23 → 100000000000000000000000) — такое целое допустимо;
  целое, которое не является такой записью числа с плавающей точкой, — ошибка: его не записать без потерь;
- ключи, совпавшие после NFC, — ошибка: иначе одно значение молча пропало бы.
Хэш — sha256 от JSON по RFC 8785 (JCS). Метка c1 в content_hash — версия этих правил:
если правила поменяются (c2), правила c1 остаются в коде, и хэш старой ревизии сверяется по правилам её метки.

На вход приходит тело, уже проверенное моделями model_v1 (строгий JSON): схему canonical заново не проверяет.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import rfc8785

CANON_VERSION = "c1"
UUID7 = "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
CANON_REF = re.compile(rf"(atm|ent|obj):({UUID7})")
MAX_SAFE_INT = 2 ** 53 - 1           # больше — RFC 8785 пишет только числом с плавающей точкой

# Поля-ссылки тела: путь → допустимая приставка. [] — каждый элемент списка.
# Совпадение с полями-ссылками схемы проверяет tests/test_canon.py.
REF_FIELDS = {
    "atom": {
        "about[]": "ent",
        "derived_from[]": "atm",
        "scope.project": "ent",
        "sources[].object": "obj",
        "sources[].edition": "ent",
        "content.formula.symbols[].term": "atm",
    },
    "entity": {
        "edition_of": "ent",
        "sources[].object": "obj",
        "sources[].edition": "ent",
    },
}


class CanonError(ValueError):
    pass


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _normalize(value: Any, problems: list[str], where: str = "") -> Any:
    """Копия значения: строки и ключи в NFC, большие целые — числом с плавающей точкой. Вход не меняется."""
    if isinstance(value, str):
        if "\x00" in value:
            problems.append(f"{where}: символ \\u0000 — PostgreSQL его не хранит")
        return _nfc(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and abs(value) > MAX_SAFE_INT:
        try:
            as_float = float(value)
        except OverflowError:
            problems.append(f"{where}: целое из {len(str(abs(value)))} цифр больше любого числа JSON")
            return value
        # jsonb возвращает самую короткую десятичную запись числа — такое целое и есть это число
        if int(Decimal(repr(as_float))) != value:
            problems.append(f"{where}: целое {value} не записать числом JSON без потерь")
        return as_float
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            nfc = _nfc(key)
            if nfc in out:
                problems.append(f"{where}: ключи {key!r} совпадают после приведения к NFC")
            out[nfc] = _normalize(item, problems, f"{where}.{nfc}" if where else nfc)
        return out
    if isinstance(value, list):
        return [_normalize(v, problems, f"{where}[{i}]") for i, v in enumerate(value)]
    return value


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            item = item if key == "rows" else _clean(item)      # строки таблицы — как есть
            if item is None or item == [] or item == {}:
                continue
            out[key] = item
        return out
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


def values_at(body: dict, path: str) -> Iterator[tuple[str, Any]]:
    """Значения по пути вида sources[].edition: пары (точный путь с номерами, значение).

    Нет поля — ничего. Где по пути ждали список ([]), а там одно значение, — отдаётся оно само."""
    def walk(node: Any, parts: list[str], where: str):
        if not parts:
            yield where, node
            return
        name, each = parts[0].removesuffix("[]"), parts[0].endswith("[]")
        if not isinstance(node, dict) or name not in node:
            return
        item = node[name]
        here = f"{where}.{name}" if where else name
        if each and isinstance(item, list):
            for i, element in enumerate(item):
                yield from walk(element, parts[1:], f"{here}[{i}]")
        else:
            yield from walk(item, parts[1:], here)

    yield from walk(body, path.split("."), "")


def canonical(payload: dict, target: str) -> dict:
    """Каноническое тело ревизии атома или сущности; CanonError — если ссылки или источники не разрешены."""
    if target not in REF_FIELDS:
        raise CanonError(f"неизвестный вид записи {target!r}: нужен atom или entity")
    problems: list[str] = []
    body = _clean(_normalize({k: v for k, v in payload.items() if k != "ref"}, problems))
    for i, source in enumerate(body.get("sources", [])):
        if "object" not in source:
            problems.append(f"sources[{i}]: нет object — источник не разрешён в объект")
        elif "object_version" not in source:
            problems.append(f"sources[{i}]: нет object_version")
        source.pop("path", None)
    for path, prefix in REF_FIELDS[target].items():
        for where, ref in values_at(body, path):
            m = CANON_REF.fullmatch(ref) if isinstance(ref, str) else None
            if not m or m.group(1) != prefix:
                problems.append(f"{where}: ссылка {ref!r} — нужна {prefix}:<UUIDv7>")
    if problems:
        raise CanonError("; ".join(problems))
    return body


def content_hash(body: dict) -> str:
    """Хэш канонического тела. Тело, прочитанное из jsonb, даёт тот же хэш: числа и строки приводятся заново."""
    problems: list[str] = []
    data = _normalize(body, problems)
    if problems:
        raise CanonError("; ".join(problems))
    try:
        text = rfc8785.dumps(data)
    except rfc8785.CanonicalizationError as e:
        raise CanonError(f"тело не записать по RFC 8785: {e}") from e
    return f"sha256-{CANON_VERSION}:" + hashlib.sha256(text).hexdigest()
