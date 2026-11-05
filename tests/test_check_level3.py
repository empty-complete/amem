"""Уровень 3 автопроверки (разд. 5 спецификации подпроекта 3): диапазон и единицы, словарь величин, согласие.

Тестовый пакет tests/packs/check даёт величины length, pressure, temperature. Соперники записываются через
records.commit, мимо проверки."""
import uuid

import pytest

from amem import db, records
from amem.check import Proposal, level1, level3
from amem.check.report import Report
from check_support import CHECK_PACK, atom, entity, value

AGENT = "model:tester"


def prop(body: dict) -> Proposal:
    return Proposal("entity" if "entity_class" in body else "atom", body, None)


def vals(*values, **fields) -> dict:
    return {"content": {"values": list(values)}, **fields}


def run(conn, *items):
    """Уровни 1 и 3 над пачкой; (замечания уровня 3 тройками, риски, отчёт)."""
    report = Report()
    batch = level1.check(conn, [i if isinstance(i, Proposal) else prop(i) for i in items], [], report)
    assert not [i for i in report.issues if i.severity == "violation"], report.issues
    risks = level3.check(conn, batch, report)
    return [(i.code, i.where) for i in report.issues if i.level == 3], risks, report


def stored(conn, *bodies, status=None) -> dict[str, uuid.UUID]:
    bodies = [{k: v for k, v in b.items() if k != "sources"} for b in bodies]       # источники записи не нужны
    result = records.commit(conn, [records.Item(prop(b).target, b) for b in bodies], [], agent=AGENT)
    ids = {n: uuid.UUID(r.split(":", 1)[1]) for n, r in result.refs.items()}
    if status:
        for name, rid in ids.items():
            if name.startswith("@a"):
                conn.execute("UPDATE atom SET status = %s WHERE id = %s", (status, rid))
    return ids


@pytest.fixture
def kb(pg, monkeypatch):
    monkeypatch.setenv("AMEM_PACKS", str(CHECK_PACK))
    db.prepare(pg)
    return pg


def one(*values, name="@a1", **fields) -> dict:
    return atom(name, **vals(*values), **fields)


# --- диапазон и единицы ---

@pytest.mark.parametrize("v, code", [
    (value("pressure", 150, "kPa"), "out_of_range"),
    (value("pressure", 3, "m"), "unit_mismatch"),
    (value("temperature", -100, "Cel"), "out_of_range"),
    (value("pressure", 0.05, "MPa"), None),
    (value("pressure", 50, "kPa"), None),
])
def test_range_and_units(kb, v, code):
    found, risks, _ = run(kb, one(v))
    assert [c for c, _ in found] == ([code] if code else [])
    assert risks == {}


def test_range_issue_has_exact_place(kb):
    found, _, _ = run(kb, one(value("pressure", 1, "kPa"), value("pressure", 150, "kPa")))
    assert found == [("out_of_range", "@a1: content.values[1].amount")]


def test_bounds_are_checked_too(kb):
    found, _, _ = run(kb, one(value("pressure", None, "kPa", lower_bound=10, upper_bound=500)))
    assert found == [("out_of_range", "@a1: content.values[0].upper_bound")]


# --- словарь величин ---

def test_unknown_property_with_vocabulary(kb):
    found, _, _ = run(kb, one(value("velocity", 3, "m/s")))
    assert found == [("unknown_property", "@a1: content.values[0].property")]


def test_free_codes_without_property_vocabulary(pg, monkeypatch):
    monkeypatch.delenv("AMEM_PACKS", raising=False)
    db.prepare(pg)
    assert pg.execute("SELECT count(*) FROM concept WHERE scheme = 'property'").fetchone()[0] == 0
    found, _, _ = run(pg, one(value("velocity", 3, "m/s")))
    assert found == []


# --- согласие ---

def rival(conn, v=None, status=None, **fields):
    v = v or value("pressure", 0.3, "kPa")
    ids = stored(conn, entity("@e"), atom("@a0", **vals(v), about=["@e"], **fields), status=status)
    return ids


def new(conn, ent, v, **fields):
    return run(conn, one(v, about=[f"ent:{ent}"], **fields))


def test_conflict_with_stored_atom(kb):
    ids = rival(kb)
    found, risks, report = new(kb, ids["@e"], value("pressure", 0.38, "kPa"))
    assert found == [("conflict", "@a1")]
    assert risks == {"@a1": ["conflict"]}
    [issue] = [i for i in report.issues if i.code == "conflict"]
    assert issue.details["atoms"] == [f"atm:{ids['@a0']}"]


def test_same_value_after_conversion_is_no_conflict(kb):
    ids = rival(kb)
    assert new(kb, ids["@e"], value("pressure", 300, "Pa"))[0] == []


def test_other_qualifiers_no_conflict(kb):
    q = lambda t: [{"property": "zone", "value_text": t}]       # noqa: E731
    ids = rival(kb, qualifiers=q("I"))
    assert new(kb, ids["@e"], value("pressure", 0.38, "kPa"), qualifiers=q("II"))[0] == []
    assert new(kb, ids["@e"], value("pressure", 0.38, "kPa"), qualifiers=q("I"))[0] == [("conflict", "@a1")]


def test_disjoint_terms_no_conflict(kb):
    ids = rival(kb, valid_from="2010-01-01", valid_to="2015-12-31")
    assert new(kb, ids["@e"], value("pressure", 0.38, "kPa"), valid_from="2020-01-01")[0] == []
    assert new(kb, ids["@e"], value("pressure", 0.38, "kPa"), valid_from="2015-06-01")[0] == [("conflict", "@a1")]


def test_other_entity_no_conflict(kb):
    rival(kb)
    other = stored(kb, entity("@e2"))["@e2"]
    assert new(kb, other, value("pressure", 0.38, "kPa"))[0] == []


def test_rejected_rival_ignored(kb):
    ids = rival(kb, status="rejected")
    assert new(kb, ids["@e"], value("pressure", 0.38, "kPa"))[0] == []


def test_conflict_inside_batch_by_name(kb):
    found, risks, report = run(
        kb, entity("@e"),
        atom("@a1", **vals(value("pressure", 0.3, "kPa")), about=["@e"]),
        atom("@a2", **vals(value("pressure", 0.4, "kPa")), about=["@e"]))
    assert sorted(found) == [("conflict", "@a1"), ("conflict", "@a2")]
    assert risks == {"@a1": ["conflict"], "@a2": ["conflict"]}
    assert [i.details["atoms"] for i in report.issues if i.where == "@a1"] == [["@a2"]]


def test_atom_without_about_not_compared(kb):
    rival(kb)
    found, risks, _ = run(kb, one(value("pressure", 0.38, "kPa")))
    assert found == [] and risks == {}


def test_editing_atom_does_not_conflict_with_itself(kb):
    ids = rival(kb)
    body = atom("@a0", **vals(value("pressure", 0.38, "kPa")), about=[f"ent:{ids['@e']}"])
    report = Report()
    batch = level1.check(kb, [Proposal("atom", body, ids["@a0"])], [], report)
    assert level3.check(kb, batch, report) == {}
