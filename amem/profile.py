"""Профиль сущности и карточка amem.card/1 (спецификация 3c, разд. 3.4).

Карточка не хранится: для каждой величины профиля класса сущности берутся действующие атомы parameter о ней
(текущая ревизия, статус не rejected / deprecated / superseded), и по ним выводится состояние поля.
Умолчание профиля показывается, но значением не считается. Предки — по действующим связям part_of вверх.
Карточки «на момент» нет: у атомов нет выбора ревизии на момент (отложено до интерфейса истории).
"""
from __future__ import annotations

import uuid

import psycopg

from . import lookup
from .check import templates, units
from .records import as_uuid

RETIRED = ("rejected", "deprecated", "superseded")
FORMAT = "amem.card/1"
_VALUE_KEYS = ("amount", "unit", "value_text", "lower_bound", "upper_bound")


def rules_for_entity(conn: psycopg.Connection, entity_class: str) -> templates.Rules:
    """Сведённые правила (и профиль parameters) класса сущности по активным шаблонам."""
    return templates.rules_for(templates.active(conn), "entity", entity_class)


def _entity_uuid(ref: str) -> uuid.UUID:
    if not isinstance(ref, str) or not ref.startswith("ent:"):
        raise LookupError(f"{ref!r}: карточка строится только для сущности (ent:<UUID>)")
    return as_uuid(ref.split(":", 1)[1], "ref")


def _atoms_about(conn, entity_id: uuid.UUID, kind: str) -> list[dict]:
    """Действующие атомы вида kind о сущности, у текущей ревизии которых есть величины (проекция atom_property)."""
    rows = conn.execute(
        "SELECT r.atom_id, r.id, r.payload, a.status, c.agent "
        "FROM atom_current r JOIN atom a ON a.id = r.atom_id "
        "JOIN atom_about ab ON ab.revision_id = r.id JOIN changeset c ON c.id = r.changeset_id "
        "WHERE ab.entity_id = %s AND a.kind = %s AND a.status <> ALL(%s) "
        "AND EXISTS (SELECT 1 FROM atom_property p WHERE p.revision_id = r.id) ORDER BY r.atom_id",
        (entity_id, kind, list(RETIRED))).fetchall()
    return [{"atom_id": r[0], "revision_id": r[1], "payload": r[2], "status": r[3], "agent": r[4]} for r in rows]


def _values(record: dict) -> list[dict]:
    return (record["payload"].get("content") or {}).get("values") or []


def _values_of(record: dict, prop: str) -> list[dict]:
    return [v for v in _values(record) if v.get("property") == prop]


def _canonical(v: dict, unit: str | None) -> tuple:
    """Значение для сравнения: число в единице величины (если переводится), иначе как записано; или текст."""
    if v.get("amount") is not None:
        amount, own = v["amount"], v.get("unit")
        if unit and own and own != unit:
            converted = units.convert(amount, own, unit)
            if converted is not None:
                amount, own = converted, unit
        return ("n", round(float(amount), 9), own)
    return ("t", v.get("value_text"), v.get("lower_bound"), v.get("upper_bound"), v.get("unit"))


def _candidate(conn, record: dict, v: dict) -> dict:
    p = record["payload"]
    return {"atom": f"atm:{record['atom_id']}", "value": {k: v[k] for k in _VALUE_KEYS if v.get(k) is not None},
            "status": record["status"], "by": record["agent"].split(":")[0], "basis": p.get("basis"),
            "rank": p.get("rank"), "confidence": p.get("confidence"),
            "source_role": next((s.get("role") for s in p.get("sources") or [] if s.get("role")), None),
            "sources": lookup.revision_sources(conn, "atom", record["revision_id"])}


def _field(conn, rule: dict, origin: str | None, params: list[dict], questions: list[dict],
           prop_unit: str | None) -> dict:
    prop = rule["property"]
    out = {"property": prop, "required": bool(rule.get("required")), "group": rule.get("group"),
           "origin": rule.get("origin"), "rule": origin, "default": rule.get("default"), "ask": rule.get("ask"),
           "hint": rule.get("hint"), "when": rule.get("when"), "state": "missing", "value": None,
           "atoms": [], "candidates": []}
    pairs = [(r, v) for r in params for v in _values_of(r, prop)]
    if not pairs:
        if any(_values_of(q, prop) for q in questions):
            out["state"] = "asked"
            out["atoms"] = [f"atm:{q['atom_id']}" for q in questions if _values_of(q, prop)]
        return out
    out["atoms"] = list(dict.fromkeys(f"atm:{r['atom_id']}" for r, _ in pairs))
    if all(v.get("value_state") == "none" for _, v in pairs):
        out["state"] = "na"
        return out
    known = [(r, v) for r, v in pairs if v.get("value_state", "known") == "known"]
    if not known:                                   # только unknown — документ величину не называет
        return out
    # rank deprecated — значение отложено: учитывается, только если других нет
    live = [(r, v) for r, v in known if r["payload"].get("rank") != "deprecated"] or known
    preferred = [(r, v) for r, v in live if r["payload"].get("rank") == "preferred"]
    deciding = preferred or live
    chosen = deciding[0] if len({_canonical(v, prop_unit) for _, v in deciding}) == 1 else None
    if chosen is None:                              # различные значения и нет единственного preferred
        out["state"] = "conflict"
        out["candidates"] = [_candidate(conn, r, v) for r, v in live]
        out["atoms"] = [c["atom"] for c in out["candidates"]]
        return out
    c = _candidate(conn, *chosen)
    out["candidates"] = [_candidate(conn, r, v) for r, v in live if not (r is chosen[0] and v is chosen[1])]
    out.update({"state": "known", "value": c["value"], "atoms": [c["atom"]], "status": c["status"], "by": c["by"],
                "basis": c["basis"], "rank": c["rank"], "confidence": c["confidence"],
                "source_role": c["source_role"], "sources": c["sources"]})
    return out


def _one(conn, entity_id: uuid.UUID) -> dict:
    record = lookup.get(conn, "entity", entity_id)
    if record is None:
        raise LookupError(f"ent:{entity_id}: нет такой сущности")
    active = templates.active(conn)
    cls = record["entity_class"]
    rules = templates.rules_for(active, "entity", cls)
    prop_units = dict(conn.execute("SELECT code, data->>'unit' FROM concept WHERE scheme = 'property'").fetchall())
    params = _atoms_about(conn, entity_id, "parameter")
    questions = _atoms_about(conn, entity_id, "question")
    fields = [_field(conn, rule, rules.parameter_origins.get(rule["property"]), params, questions,
                     prop_units.get(rule["property"])) for rule in rules.parameters]
    covered = {f["property"] for f in fields}
    extra = [{"property": v["property"], **_candidate(conn, r, v)}
             for r in params for v in _values(r) if v.get("property") not in covered]
    # профиль — шаблон класса (applies_to); без parameters профиля нет
    own = next((f"{name}@{t['version']}" for name, t in active.items()
                if t["target"] == "entity" and t.get("applies_to") == cls), None)
    states: dict[str, int] = {}
    for f in fields:
        states[f["state"]] = states.get(f["state"], 0) + 1
    return {
        "format": FORMAT,
        "entity": {"ref": f"ent:{entity_id}", "entity_class": cls, "label": record["label"],
                   "codes": record.get("codes") or [], "status": record["status"]},
        "profile": own if rules.parameters else None,
        "templates": list(rules.templates),
        "fields": fields,
        "extra": extra,
        "summary": {"states": states,
                    "blockers_open": sum(1 for f in fields if f["required"] and f["state"] not in ("known", "na")),
                    "with_basis": [f["property"] for f in fields if f.get("basis")]},
        "ancestors": [],
    }


def _parents(conn, entity_id: uuid.UUID) -> list[uuid.UUID]:
    rows = conn.execute("SELECT DISTINCT dst_entity FROM link WHERE rel = 'part_of' AND src_entity = %s "
                        "AND dst_entity IS NOT NULL AND retired_at IS NULL ORDER BY dst_entity",
                        (entity_id,)).fetchall()
    return [r[0] for r in rows]


def card(conn: psycopg.Connection, ref: str, *, ancestors: bool = True) -> dict:
    """Карточка сущности формата amem.card/1; ancestors — карточки предков по part_of, обход в ширину.

    Цикл part_of обрывается по посещённым; глубина не ограничена."""
    root = _entity_uuid(ref)
    out = _one(conn, root)
    if ancestors:
        seen, queue = {root}, _parents(conn, root)
        while queue:
            parent = queue.pop(0)
            if parent in seen:
                continue
            seen.add(parent)
            out["ancestors"].append(_one(conn, parent))
            queue.extend(_parents(conn, parent))
    return out
