"""Рецепт around_entity: BFS по текущему графу, кратчайшие пути и слабейшие доказательства."""
import json

import pytest

from amem import db, ids, recipes, records, usefulness
from amem.records import Item, RecordError

AGENT = "model:test"


@pytest.fixture
def kb(pg):
    db.prepare(pg)
    return pg


def atom(key, *, about=(), derived_from=(), sources=(), status=None):
    return Item("atom", {
        "ref": f"@{key}", "kind": "fact", "key": key,
        "label": {"ru": key}, "summary_plain": {"ru": key}, "codes": [],
        "about": list(about), "derived_from": list(derived_from), "sources": list(sources),
    }, status=status)


def entity(key, *, sources=(), status=None):
    return Item("entity", {
        "ref": f"@{key}", "entity_class": "document", "key": key,
        "label": {"ru": key}, "sources": list(sources),
    }, status=status)


def revise(kb, item, ref, **changes):
    payload = {**item.payload, **changes}
    payload.pop("ref", None)
    return records.commit(kb, [Item(item.target, payload, record_id=ref.split(":", 1)[1])],
                          agent=AGENT).revisions[0]


def source_object(kb, label):
    object_id = ids.uuid7()
    kb.execute("INSERT INTO object (id, kind, original_name, created_at) VALUES (%s, 'message', %s, now())",
               (object_id, label))
    kb.execute("INSERT INTO object_version (object_id, kind, n, recorded_at) VALUES (%s, 'message', 1, now())",
               (object_id,))
    return {"object": f"obj:{object_id}", "object_version": 1}


def around(kb, ref, **kwargs):
    return recipes.around_entity(kb, ref, **kwargs)


def path_to(result, ref):
    return next(path for path in result["paths"] if path["nodes"][-1] == ref)


def test_bfs_uses_both_directions_current_fields_and_shortest_paths(kb):
    written = records.commit(kb, [
        entity("root"), entity("peer"),
        atom("a", about=["@root"], derived_from=["@base"]), atom("base"),
        atom("b"), atom("c", derived_from=["@d"]), atom("d"),
    ], [
        {"rel": "same_as", "src": "@peer", "dst": "@root", "confidence": 0.8},
        {"rel": "depends_on", "src": "@b", "dst": "@a", "confidence": 0.9},
        {"rel": "contradicts", "src": "@b", "dst": "@c", "confidence": 0.7},
        {"rel": "depends_on", "src": "@c", "dst": "@a", "confidence": 0.6},
    ], agent=AGENT)
    refs = written.refs

    result = around(kb, refs["@root"], depth=3)

    depths = {node["ref"]: node["depth"] for node in result["nodes"]}
    assert depths == {
        refs["@root"]: 0, refs["@peer"]: 1, refs["@a"]: 1,
        refs["@base"]: 2, refs["@b"]: 2, refs["@c"]: 2, refs["@d"]: 3,
    }
    assert len(result["nodes"]) == len(depths) == 7
    assert [node["ref"] for node in result["nodes"]].count(refs["@root"]) == 1
    assert all(path["nodes"][-1] != refs["@root"] for path in result["paths"])
    assert path_to(result, refs["@c"])["nodes"] == [refs["@root"], refs["@a"], refs["@c"]]
    assert len(path_to(result, refs["@d"])["edges"]) == 3
    peer_edge = next(edge for edge in result["edges"] if edge["to"] == refs["@peer"])
    assert peer_edge["rel"] == "same_as" and peer_edge["direction"] == "reverse"
    b_edge = next(edge for edge in result["edges"] if edge["to"] == refs["@b"])
    assert (b_edge["src"], b_edge["dst"]) == (refs["@b"], refs["@a"])
    assert (b_edge["from"], b_edge["to"], b_edge["direction"]) == (refs["@a"], refs["@b"], "reverse")
    assert refs["@d"] not in {node["ref"] for node in around(kb, refs["@root"], depth=2)["nodes"]}
    json.dumps(result)


def test_depth_rel_status_and_missing_start(kb):
    written = records.commit(kb, [entity("root"), atom("a"), atom("b", status="deprecated")], [
        {"rel": "depends_on", "src": "@a", "dst": "@root"},
        {"rel": "see_also", "src": "@b", "dst": "@root", "note": {"ru": "связь"}},
    ], agent=AGENT)
    refs = written.refs

    default = around(kb, refs["@root"])
    only_depends = around(kb, refs["@root"], rel="depends_on")
    deprecated = around(kb, refs["@root"], status="deprecated")

    assert {node["ref"] for node in default["nodes"]} == {refs["@root"], refs["@a"]}
    assert {node["ref"] for node in only_depends["nodes"]} == {refs["@root"], refs["@a"]}
    assert {node["ref"] for node in deprecated["nodes"]} == {refs["@root"], refs["@b"]}
    assert all(edge["rel"] == "depends_on" for edge in only_depends["edges"])
    for depth in (0, 4, -1, True, "2"):
        with pytest.raises(RecordError, match="depth"):
            around(kb, refs["@root"], depth=depth)
    with pytest.raises(RecordError, match="такой записи нет"):
        around(kb, f"ent:{ids.uuid7()}")
    with pytest.raises(RecordError, match="ref|UUID"):
        around(kb, "ent:not-a-uuid")


def test_old_revision_fields_and_retired_links_do_not_traverse(kb):
    old_about = atom("old_about", about=["@root"])
    old_derived = atom("old_derived", derived_from=["@base"])
    linked = atom("linked")
    written = records.commit(kb, [entity("root"), atom("base"), old_about, old_derived, linked], [
        {"rel": "depends_on", "src": "@linked", "dst": "@root"},
    ], agent=AGENT)
    refs = written.refs
    revise(kb, old_about, refs["@old_about"], about=[])
    revise(kb, old_derived, refs["@old_derived"], derived_from=[])
    records.retire_link(kb, written.links[0], agent=AGENT, reason="больше не действует")

    result = around(kb, refs["@root"], depth=3)

    assert [node["ref"] for node in result["nodes"]] == [refs["@root"]]
    assert result["edges"] == [] and result["paths"] == []


def test_deterministic_order_and_edge_provenance(kb):
    written = records.commit(kb, [
        entity("root"), atom("b", about=["@root"]), atom("a", about=["@root"]), atom("c"),
    ], agent=AGENT)
    refs = written.refs
    revisions = {f"atm:{revision.record_id}": revision for revision in written.revisions[1:3]}
    linked = records.commit(kb, [], [{
        "rel": "depends_on", "src": refs["@a"], "dst": refs["@c"],
        "confidence": 0.9, "qualifiers": {"stage": "test"},
    }], agent=AGENT)

    result = around(kb, refs["@root"], depth=2)

    structural_ids = {
        ref: f"about:{revisions[ref].revision_id}:{refs['@root'].split(':', 1)[1]}" for ref in revisions
    }
    expected_first = sorted(revisions, key=lambda ref: (structural_ids[ref], ref))
    assert [node["ref"] for node in result["nodes"][1:3]] == expected_first
    assert [path["nodes"][-1] for path in result["paths"][:2]] == expected_first
    for edge in result["edges"][:2]:
        ref = edge["src"]
        revision = revisions[ref]
        row = kb.execute("SELECT recorded_at FROM atom_revision WHERE id = %s", (revision.revision_id,)).fetchone()
        assert edge["id"] == structural_ids[ref]
        assert edge["rel"] == "about" and edge["direction"] == "reverse"
        assert edge["changeset"] == str(written.changeset_id) and edge["agent"] == AGENT
        assert edge["created_at"] == row[0].isoformat()
        assert edge["confidence"] is None and "qualifiers" not in edge
    explicit = next(edge for edge in result["edges"] if edge["id"] == str(linked.links[0]))
    row = kb.execute("SELECT changeset_id, agent, created_at FROM link WHERE id = %s", (linked.links[0],)).fetchone()
    assert explicit["src"] == refs["@a"] and explicit["dst"] == refs["@c"]
    assert explicit["direction"] == ("forward" if explicit["from"] == explicit["src"] else "reverse")
    assert explicit["changeset"] == str(row[0]) and explicit["agent"] == row[1]
    assert explicit["created_at"] == row[2].isoformat()
    assert explicit["confidence"] == pytest.approx(0.9)
    assert explicit["qualifiers"] == {"stage": "test"}


def test_path_confidence_is_weakest_link_and_structural_edges_have_no_score(kb):
    written = records.commit(kb, [
        entity("root"), atom("a"), atom("b"), atom("c"), atom("d", about=["@root"]),
        atom("e", derived_from=["@d"]),
    ], [
        {"rel": "depends_on", "src": "@a", "dst": "@root", "confidence": 0.9},
        {"rel": "depends_on", "src": "@b", "dst": "@a", "confidence": 0.4},
        {"rel": "depends_on", "src": "@c", "dst": "@b"},
    ], agent=AGENT)
    refs = written.refs

    result = around(kb, refs["@root"], depth=3)

    assert path_to(result, refs["@a"])["confidence"] == pytest.approx(0.9)
    assert path_to(result, refs["@b"])["confidence"] == pytest.approx(0.4)
    assert path_to(result, refs["@b"])["confidence"] != pytest.approx((0.9 + 0.4) / 2)
    assert path_to(result, refs["@c"])["confidence"] is None
    assert path_to(result, refs["@d"])["confidence"] is None
    assert path_to(result, refs["@e"])["confidence"] is None
    structural = [edge for edge in result["edges"] if edge["rel"] in {"about", "derived_from"}]
    assert len(structural) == 2 and all(edge["confidence"] is None for edge in structural)


def test_path_evidence_role_uses_current_atom_sources_and_ignores_usefulness(kb):
    primary = source_object(kb, "primary")
    secondary = source_object(kb, "secondary")
    derived = source_object(kb, "derived")
    unsupported = atom("unsupported")
    written = records.commit(kb, [
        entity("root"), entity("middle"),
        atom("a", sources=[{**primary, "role": "primary"}, {**secondary, "role": "secondary"}]),
        atom("b", sources=[{**derived, "role": "derived"}]),
        atom("c", sources=[{**primary, "role": "primary"}]), unsupported,
    ], [
        {"rel": "depends_on", "src": "@a", "dst": "@root", "confidence": 0.9},
        {"rel": "depends_on", "src": "@b", "dst": "@a", "confidence": 0.8},
        {"rel": "used_in", "src": "@c", "dst": "@middle", "confidence": 0.7},
        {"rel": "part_of", "src": "@middle", "dst": "@root", "confidence": 0.6},
        {"rel": "depends_on", "src": "@unsupported", "dst": "@root", "confidence": 0.5},
    ], agent=AGENT)
    refs = written.refs

    before = around(kb, refs["@root"], depth=3)

    assert path_to(before, refs["@a"])["evidence_role"] == "secondary"
    assert path_to(before, refs["@b"])["evidence_role"] == "derived"
    assert path_to(before, refs["@c"])["evidence_role"] == "primary"  # middle — сущность без источников
    assert path_to(before, refs["@unsupported"])["evidence_role"] is None

    activity = ids.uuid7()
    kb.execute("INSERT INTO activity (id, kind, label, started_at) VALUES (%s, 'task', 'Граф', now())", (activity,))
    retrieval = recipes.exact_fact(kb, "b", agent=AGENT, activity=activity)
    usefulness.mark_helpful(kb, retrieval["retrieval_id"], [refs["@b"]], agent=AGENT, activity=activity)
    after = around(kb, refs["@root"], depth=3)
    assert [(path["confidence"], path["evidence_role"]) for path in after["paths"]] == [
        (path["confidence"], path["evidence_role"]) for path in before["paths"]
    ]

    old_b = atom("b", sources=[{**derived, "role": "derived"}])
    revise(kb, old_b, refs["@b"], sources=[])
    current = around(kb, refs["@root"], depth=3)
    assert path_to(current, refs["@b"])["evidence_role"] is None
    json.dumps(current)
