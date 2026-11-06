"""Профиль сущности и карточка amem.card/1 (спецификация 3c, разд. 3.4).

Карточка не хранится: для каждой величины профиля класса сущности берутся действующие атомы parameter о ней
(текущая ревизия, статус не rejected / deprecated / superseded), и по ним выводится состояние поля.
Умолчание профиля показывается, но значением не считается. Предки — по действующим связям part_of вверх.
Карточки «на момент» нет: у атомов нет выбора ревизии на момент (отложено до интерфейса истории).

Пограничные состояния: none + unknown → na; none + known → conflict; unknown + вопрос → asked; вопрос — атом
question со значением этой величины в value_state unknown. Значения с rank deprecated учитываются, только если
других нет, и в candidates не попадают. Из нескольких атомов с одним значением поле берёт признаки у лучшего:
сначала status verified, затем автор person:, затем более новая ревизия. У conflict atoms — те же атомы,
что в candidates (без deprecated и unknown).
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

import psycopg

from . import lookup
from .check import templates, units
from .records import as_uuid

RETIRED = ("rejected", "deprecated", "superseded")
FORMAT = "amem.card/1"
_VALUE_KEYS = ("amount", "unit", "value_text", "lower_bound", "upper_bound")
_REL_TOL = 1e-9                                     # относительная точность: значения ближе — одно значение


@dataclass(frozen=True)
class _Context:
    """Читается один раз на card(): активные шаблоны и единицы величин — общие для сущности и её предков."""
    active: dict[str, dict]
    prop_units: dict[str, str | None]


def rules_for_entity(conn: psycopg.Connection, entity_class: str) -> templates.Rules:
    """Сведённые правила (и профиль parameters) класса сущности по активным шаблонам."""
    return templates.rules_for(templates.active(conn), "entity", entity_class)


def _entity_uuid(ref: str) -> uuid.UUID:
    if not isinstance(ref, str) or not ref.startswith("ent:"):
        raise LookupError(f"{ref!r}: карточка строится только для сущности (ent:<UUID>)")
    return as_uuid(ref.split(":", 1)[1], "ref")


def _atoms_about(conn, entity_id: uuid.UUID) -> dict[str, list[dict]]:
    """Действующие атомы parameter и question о сущности, у текущей ревизии которых есть величины.

    atom_current — DISTINCT ON по всем ревизиям: условие соединения с atom_about внутрь вида не проникает, и
    без отбора atom_id заранее PostgreSQL читал бы все ревизии базы (как в recipes.graph)."""
    rows = conn.execute(
        "SELECT r.atom_id, r.id, r.payload, a.status, c.agent, a.kind "
        "FROM atom_current r JOIN atom a ON a.id = r.atom_id JOIN changeset c ON c.id = r.changeset_id "
        "WHERE r.atom_id = ANY(ARRAY(SELECT ar.atom_id FROM atom_about g "
        "JOIN atom_revision ar ON ar.id = g.revision_id WHERE g.entity_id = %(e)s)) "
        "AND EXISTS (SELECT 1 FROM atom_about ab WHERE ab.revision_id = r.id AND ab.entity_id = %(e)s) "
        "AND a.kind = ANY(%(kinds)s) AND a.status <> ALL(%(retired)s) "
        "AND EXISTS (SELECT 1 FROM atom_property p WHERE p.revision_id = r.id) ORDER BY r.atom_id",
        {"e": entity_id, "kinds": ["parameter", "question"], "retired": list(RETIRED)}).fetchall()
    out: dict[str, list[dict]] = {"parameter": [], "question": []}
    for r in rows:
        out[r[5]].append({"atom_id": r[0], "revision_id": r[1], "payload": r[2], "status": r[3], "agent": r[4]})
    return out


def _values(record: dict) -> list[dict]:
    return (record["payload"].get("content") or {}).get("values") or []


def _values_of(record: dict, prop: str) -> list[dict]:
    return [v for v in _values(record) if v.get("property") == prop]


def _state(v: dict) -> str:
    return v.get("value_state") or "known"


def _canonical(v: dict, unit: str | None) -> tuple:
    """Значение для сравнения: число в единице unit (если переводится), иначе как записано; или текст."""
    if v.get("amount") is not None:
        amount, own = float(v["amount"]), v.get("unit")
        if unit and own and own != unit:
            converted = units.convert(amount, own, unit)
            if converted is not None:
                amount, own = converted, unit
        return ("n", amount, own)
    return ("t", v.get("value_text"), v.get("lower_bound"), v.get("upper_bound"), v.get("unit"))


def _same(a: tuple, b: tuple) -> bool:
    if a[0] == b[0] == "n":
        return a[2] == b[2] and math.isclose(a[1], b[1], rel_tol=_REL_TOL)
    return a == b


def _one_value(canon: list[tuple]) -> bool:
    return all(_same(canon[0], c) for c in canon[1:])


def _best_key(record: dict) -> tuple:
    """Порядок выбора среди атомов с одним значением: verified, затем человек, затем новее (UUIDv7 больше)."""
    return (record["status"] == "verified", record["agent"].startswith("person:"), record["revision_id"])


def _candidate(record: dict, v: dict, sources: dict) -> dict:
    p = record["payload"]
    value = {k: v[k] for k in _VALUE_KEYS if v.get(k) is not None}
    if _state(v) != "known":
        value["value_state"] = _state(v)
    return {"atom": f"atm:{record['atom_id']}", "value": value,
            "status": record["status"], "by": record["agent"].split(":")[0], "basis": p.get("basis"),
            "rank": p.get("rank"), "confidence": p.get("confidence"),
            "source_role": next((s.get("role") for s in p.get("sources") or [] if s.get("role")), None),
            "sources": sources.get(record["revision_id"], [])}


def _field(rule: dict, origin: str | None, params: list[dict], questions: list[dict], prop_unit: str | None,
           sources: dict) -> dict:
    prop = rule["property"]
    out = {"property": prop, "required": bool(rule.get("required")), "group": rule.get("group"),
           "origin": rule.get("origin"), "rule": origin, "default": rule.get("default"), "ask": rule.get("ask"),
           "hint": rule.get("hint"), "when": rule.get("when"), "state": "missing", "value": None,
           "atoms": [], "candidates": []}
    pairs = [(r, v) for r in params for v in _values_of(r, prop)]
    # rank deprecated — значение отложено: учитывается, только если других нет; в candidates не попадает
    live = [(r, v) for r, v in pairs if r["payload"].get("rank") != "deprecated"] or pairs
    known = [(r, v) for r, v in live if _state(v) == "known"]
    none = [(r, v) for r, v in live if _state(v) == "none"]
    shown = [(r, v) for r, v in live if r["payload"].get("rank") != "deprecated"]
    out["atoms"] = list(dict.fromkeys(f"atm:{r['atom_id']}" for r, _ in pairs))
    if none and known:                              # «не относится» спорит со значением
        out["state"] = "conflict"
        out["candidates"] = [_candidate(r, v, sources) for r, v in shown if _state(v) != "unknown"]
        out["atoms"] = list(dict.fromkeys(c["atom"] for c in out["candidates"]))
        return out
    if none:                                        # none, возможно вместе с unknown
        out["state"] = "na"
        return out
    if not known:                                   # атомов нет или только unknown — документ величину не называет
        asked = [q for q in questions if any(_state(v) == "unknown" for v in _values_of(q, prop))]
        if asked:
            out["state"] = "asked"
            out["atoms"] += [f"atm:{q['atom_id']}" for q in asked]
        return out
    # единица сравнения: из словаря величин, иначе — единица первого значения поля
    unit = prop_unit or next((v.get("unit") for _, v in known if v.get("unit")), None)
    preferred = [(r, v) for r, v in known if r["payload"].get("rank") == "preferred"]
    deciding = preferred or known
    if not _one_value([_canonical(v, unit) for _, v in deciding]):   # различные значения, нет единственного preferred
        out["state"] = "conflict"
        out["candidates"] = [_candidate(r, v, sources) for r, v in shown if _state(v) == "known"]
        out["atoms"] = list(dict.fromkeys(c["atom"] for c in out["candidates"]))
        return out
    chosen = max(deciding, key=lambda rv: _best_key(rv[0]))
    c = _candidate(*chosen, sources)
    out["candidates"] = [_candidate(r, v, sources) for r, v in shown
                         if _state(v) == "known" and not (r is chosen[0] and v is chosen[1])]
    out.update({"state": "known", "value": c["value"], "atoms": [c["atom"]], "status": c["status"], "by": c["by"],
                "basis": c["basis"], "rank": c["rank"], "confidence": c["confidence"],
                "source_role": c["source_role"], "sources": c["sources"]})
    return out


def _profile(rules: templates.Rules) -> str | None:
    """Шаблон, давший правила профиля: последний по порядку применения среди parameter_origins."""
    if not rules.parameters:
        return None
    given = set(rules.parameter_origins.values())
    return next((name for name in reversed(rules.templates) if name in given), None)


def _one(conn, ctx: _Context, entity_id: uuid.UUID) -> dict:
    record = lookup.get(conn, "entity", entity_id)
    if record is None:
        raise LookupError(f"ent:{entity_id}: нет такой сущности")
    cls = record["entity_class"]
    rules = templates.rules_for(ctx.active, "entity", cls)
    about = _atoms_about(conn, entity_id)
    params, questions = about["parameter"], about["question"]
    sources = lookup.revisions_sources(conn, "atom", [r["revision_id"] for r in params])
    fields = [_field(rule, rules.parameter_origins.get(rule["property"]), params, questions,
                     ctx.prop_units.get(rule["property"]), sources) for rule in rules.parameters]
    covered = {f["property"] for f in fields}
    extra = [{"property": v["property"], **_candidate(r, v, sources)}
             for r in params for v in _values(r) if v.get("property") not in covered]
    states: dict[str, int] = {}
    for f in fields:
        states[f["state"]] = states.get(f["state"], 0) + 1
    return {
        "format": FORMAT,
        "entity": {"ref": f"ent:{entity_id}", "entity_class": cls, "label": record["label"],
                   "codes": record.get("codes") or [], "status": record["status"]},
        "profile": _profile(rules),
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

    Цикл part_of обрывается по посещённым; глубина не ограничена. Статус и автор значений не решают спор:
    черновик модели с другим значением даёт conflict и с проверенным значением человека — выбор делает только
    rank preferred (или отклонение лишнего атома)."""
    root = _entity_uuid(ref)
    ctx = _Context(active=templates.active(conn), prop_units=dict(conn.execute(
        "SELECT code, data->>'unit' FROM concept WHERE scheme = 'property'").fetchall()))
    out = _one(conn, ctx, root)
    if ancestors:
        seen, queue = {root}, _parents(conn, root)
        while queue:
            parent = queue.pop(0)
            if parent in seen:
                continue
            seen.add(parent)
            out["ancestors"].append(_one(conn, ctx, parent))
            queue.extend(_parents(conn, parent))
    return out
