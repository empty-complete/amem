"""Словарь базы для интерфейсов: коды схемы с подписями и семья вида атома (спецификация подпроекта 4, разд. 1.2).

Семья вида (Concept.family) делит виды атомов надвое: source — знание из документа (факт, параметр, термин,
требование; в доменных пакетах — норма, формула), work — знание из работы (решение, урок, методика, вопрос,
заметка). По ней интерфейс группирует виды и раскрашивает граф. Вид без family — work: вид пакета, не разметившего
свои виды, не выдаётся за источник.

Читается таблица concept — то, что загрузил db.load_vocab (пакеты и служебные перечни схемы).
"""
from __future__ import annotations

import psycopg

FAMILIES = ("source", "work")
DEFAULT_FAMILY = "work"


class VocabError(ValueError):
    """Нет такого кода в словаре."""


def family(conn: psycopg.Connection, kind: str) -> str:
    """Семья вида атома: source или work (вид без family — work). Нет такого вида — VocabError."""
    row = conn.execute("SELECT data->>'family' FROM concept WHERE scheme = 'kind' AND code = %s", (kind,)).fetchone()
    if row is None:
        raise VocabError(f"вид атома {kind!r}: нет в словаре kind")
    return row[0] or DEFAULT_FAMILY


def families(conn: psycopg.Connection) -> dict[str, str]:
    """Семьи всех видов атомов одним запросом: {код вида: source | work}."""
    rows = conn.execute("SELECT code, data->>'family' FROM concept WHERE scheme = 'kind' ORDER BY code").fetchall()
    return {code: value or DEFAULT_FAMILY for code, value in rows}


def entries(conn: psycopg.Connection, scheme: str) -> list[dict]:
    """Понятия схемы по коду: code, label (ru, en), definition (или None), pack — откуда понятие (имя пакета,
    schema — служебный перечень схемы, agent — добавил агент), broader (или None); у вида атома ещё family.
    Схема без понятий — пустой список."""
    rows = conn.execute("SELECT code, data, origin FROM concept WHERE scheme = %s ORDER BY code",
                        (scheme,)).fetchall()
    out = []
    for code, data, origin in rows:
        entry = {"code": code, "label": data["label"], "definition": data.get("definition"), "pack": origin,
                 "broader": data.get("broader")}
        if scheme == "kind":
            entry["family"] = data.get("family") or DEFAULT_FAMILY
        out.append(entry)
    return out
