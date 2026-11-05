"""Уровень 3 автопроверки — здравый смысл (спецификация подпроекта 3, разд. 5).

Проверяются величины атомов (content.values[]):
- словарь величин: код, которого нет в загруженной схеме property, — unknown_property (если схема не пуста);
- диапазон: amount и границы переводятся в единицу понятия; вне [plausible_min, plausible_max] — out_of_range,
  перевести нельзя — unit_mismatch;
- согласие: атомы об одной сущности с той же величиной, теми же уточнениями и пересекающимися сроками, но другим
  значением, — conflict (замечание и риск). Соперники — текущие атомы базы в рабочих статусах и атомы пачки.

База только читается. Ссылки about, не нашедшие записи, пропускаются: ref_unknown уже дал уровень 1.
"""
from __future__ import annotations

import json
import uuid

from .. import canon
from ..records import PREFIX, TARGET
from . import units
from .level1 import UUID7, Batch, Prepared
from .report import Report

LEVEL = 3
LIVE = ("draft", "needs_review", "auto_verified", "verified")      # статусы атомов-соперников
EPS = 1e-9
Fingerprint = tuple[tuple, frozenset, tuple]       # (величина и единица), уточнения, срок


def check(conn, batch: Batch, report: Report) -> dict[str, list[str]]:
    """Уровень 3 над пачкой: замечания — в report; результат — метка записи → риски (здесь только conflict)."""
    run = _Level3(conn, batch, report)
    return run.run()


class _Level3:
    def __init__(self, conn, batch: Batch, report: Report):
        self.conn, self.batch, self.report = conn, batch, report
        self.properties = {code: data for code, data in conn.execute(
            "SELECT code, data FROM concept WHERE scheme = 'property'").fetchall()}
        self.atoms = [it for it in batch.items if it.ok and it.target == "atom"]
        self.names = {it.label: i for i, it in enumerate(batch.items)}
        self.found: dict[str, uuid.UUID | None] = {}

    def add(self, code: str, where: str, message: str, **details) -> None:
        self.report.add(LEVEL, "warning", code, where, message, **details)

    def run(self) -> dict[str, list[str]]:
        for item in self.atoms:
            for where, value in canon.values_at(item.payload, "content.values[]"):
                if isinstance(value, dict):
                    self.vocabulary(item.label, where, value)
        return self.agreement()

    # --- словарь и диапазон ---

    def vocabulary(self, label: str, where: str, value: dict) -> None:
        prop = value.get("property")
        if not self.properties:
            return                                  # словаря величин нет: коды свободны
        concept = self.properties.get(prop)
        if concept is None:
            self.add("unknown_property", f"{label}: {where}.property",
                     f"Величины {prop!r} нет в словаре property — кандидат в новое понятие.", property=prop)
            return
        low, high, base = concept.get("plausible_min"), concept.get("plausible_max"), concept.get("unit")
        unit = value.get("unit")
        if (low is None and high is None) or base is None or unit is None:
            return
        for field in ("amount", "lower_bound", "upper_bound"):
            x = value.get(field)
            if x is None:
                continue
            converted = x if unit == base else units.convert(x, unit, base)
            if converted is None:
                self.add("unit_mismatch", f"{label}: {where}.unit",
                         f"Единицу {unit} нельзя перевести в {base} — единицу величины {prop}.",
                         property=prop, unit=unit, expected=base)
                return
            if low is not None and converted < low or high is not None and converted > high:
                self.add("out_of_range", f"{label}: {where}.{field}",
                         f"{prop}: {x} {unit} (это {converted:g} {base}) вне диапазона {low}–{high} {base}.",
                         property=prop, value=x, unit=unit, converted=converted, plausible_min=low,
                         plausible_max=high)

    # --- согласие ---

    def entity(self, ref) -> tuple | None:
        """Тождество сущности по ссылке about: запись базы или запись пачки без id; нет такой — None."""
        if not isinstance(ref, str):
            return None
        if ref.startswith("@"):
            i = self.names.get(ref)
            if i is None:
                return None
            item = self.batch.items[i]
            if item.target != "entity":
                return None
            return ("db", item.record_id) if item.record_id else ("item", i)
        if ref not in self.found:
            prefix, _, rest = ref.partition(":")
            found = None
            if TARGET.get(prefix) == "entity":
                by = "id" if UUID7.fullmatch(rest) else "key"
                row = self.conn.execute(f"SELECT id FROM entity WHERE {by} = %s", (rest,)).fetchone()
                found = row[0] if row else None
            self.found[ref] = found
        return None if self.found[ref] is None else ("db", self.found[ref])

    def about(self, item: Prepared) -> set[tuple]:
        refs = item.payload.get("about") or []
        return {e for e in map(self.entity, refs) if e is not None}

    def agreement(self) -> dict[str, list[str]]:
        mine = {it.label: self.about(it) for it in self.atoms}
        entities = {e[1] for about in mine.values() for e in about if e[0] == "db"}
        rivals = self.stored(entities) if entities else []
        edited = {it.record_id for it in self.atoms if it.record_id}
        risks: dict[str, list[str]] = {}
        for item in self.atoms:
            if not mine[item.label]:
                continue
            own = _facts(item.payload)
            found: dict[str, None] = {}
            for atom_id, payload, about in rivals:
                if atom_id == item.record_id or atom_id in edited:
                    continue                     # правка заменяет текущую ревизию: сама себе соперник не нужна
                if mine[item.label] & about and _differ(own, _facts(payload)):
                    found[f"{PREFIX['atom']}:{atom_id}"] = None
            for other in self.atoms:
                if other is not item and mine[item.label] & mine[other.label] and _differ(own, _facts(other.payload)):
                    found[other.label] = None
            if found:
                risks[item.label] = ["conflict"]
                self.add("conflict", item.label,
                         "Другое значение той же величины у той же сущности при тех же условиях: "
                         + ", ".join(found) + ".", atoms=list(found))
        return risks

    def stored(self, entities: set) -> list[tuple[uuid.UUID, dict, set]]:
        """Текущие ревизии атомов в рабочих статусах об этих сущностях: (id атома, тело, их сущности)."""
        rows = self.conn.execute(
            "SELECT c.atom_id, c.payload, ab.entity_id FROM atom_about ab "
            "JOIN atom_current c ON c.id = ab.revision_id JOIN atom a ON a.id = c.atom_id "
            "WHERE ab.entity_id = ANY(%s) AND a.status = ANY(%s)", (list(entities), list(LIVE))).fetchall()
        merged: dict[uuid.UUID, tuple[dict, set]] = {}
        for atom_id, payload, entity_id in rows:
            merged.setdefault(atom_id, (payload, set()))[1].add(("db", entity_id))
        return [(atom_id, payload, about) for atom_id, (payload, about) in merged.items()]


def _canon(items) -> frozenset:
    return frozenset(json.dumps(q, sort_keys=True, ensure_ascii=False) for q in items or [])


def _facts(payload: dict) -> dict[str, list[tuple]]:
    """Величины тела: код величины → [(числа в единице значения, единица, value_text, условия, срок)]."""
    term = (payload.get("valid_from"), payload.get("valid_to"))
    top = _canon(payload.get("qualifiers"))
    result: dict[str, list[tuple]] = {}
    for _, v in canon.values_at(payload, "content.values[]"):
        if isinstance(v, dict) and isinstance(v.get("property"), str):
            nums = (v.get("amount"), v.get("lower_bound"), v.get("upper_bound"))
            result.setdefault(v["property"], []).append(
                (nums, v.get("unit"), v.get("value_text"), top | _canon(v.get("qualifiers")), term))
    return result


def _overlap(a: tuple, b: tuple) -> bool:
    """Сроки пересекаются; нет границы — открытый конец (даты ISO сравниваются как строки)."""
    return (a[0] is None or b[1] is None or a[0] <= b[1]) and (b[0] is None or a[1] is None or b[0] <= a[1])


def _same(x, y) -> bool:
    if x is None or y is None:
        return x is None and y is None
    return abs(x - y) <= EPS * max(abs(x), abs(y), 1e-300) or x == y


def _equal(a: tuple, b: tuple) -> bool | None:
    """Значения равны (True), различаются (False) или несравнимы (None: единицы не переводятся)."""
    if a[2] != b[2]:
        return False
    nums = b[0]
    if a[1] != b[1] and any(n is not None for n in nums):
        if a[1] is None or b[1] is None:
            return None
        converted = tuple(None if n is None else units.convert(n, b[1], a[1]) for n in nums)
        if any(c is None for n, c in zip(nums, converted) if n is not None):
            return None
        nums = converted
    return all(_same(x, y) for x, y in zip(a[0], nums))


def _differ(mine: dict[str, list[tuple]], other: dict[str, list[tuple]]) -> bool:
    """Есть значение, которому при тех же условиях и сроке нет равного у соперника, но есть другое."""
    for prop, own in mine.items():
        for a in own:
            verdicts = [_equal(a, b) for b in other.get(prop, []) if a[3] == b[3] and _overlap(a[4], b[4])]
            if False in verdicts and True not in verdicts:
                return True
    return False
