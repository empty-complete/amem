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

    default = around(kb, refs["@root"])
    first_level = {refs["@root"], refs["@peer"], refs["@a"]}
    assert default["depth"] == 1
    assert {node["ref"] for node in default["nodes"]} == first_level
    assert len(default["edges"]) == 2
    assert all(edge["from"] == refs["@root"] and edge["to"] in first_level for edge in default["edges"])
    assert {path["nodes"][-1] for path in default["paths"]} == {refs["@peer"], refs["@a"]}
    assert all(len(path["nodes"]) == 2 and len(path["edges"]) == 1 for path in default["paths"])

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
    only_depends = around(kb, refs["@root"], rels={"depends_on"})
    deprecated = around(kb, refs["@root"], statuses=["deprecated"])

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


def neighbours(result) -> set:
    return {node["ref"] for node in result["nodes"]} - {result["start"]}


def test_rels_filter_links_and_fields(kb):
    """rels — набор видов: и связей link, и полей about / derived_from; неверный набор — ошибка, а не пустой ответ."""
    refs = records.commit(kb, [entity("root"), atom("a", about=["@root"]), atom("b"), atom("c")], [
        {"rel": "depends_on", "src": "@b", "dst": "@root"},
        {"rel": "used_in", "src": "@c", "dst": "@root"},
    ], agent=AGENT).refs
    root = refs["@root"]

    assert neighbours(around(kb, root)) == {refs["@a"], refs["@b"], refs["@c"]}
    assert neighbours(around(kb, root, rels={"depends_on"})) == {refs["@b"]}
    assert neighbours(around(kb, root, rels=["about"])) == {refs["@a"]}
    assert neighbours(around(kb, root, rels=("depends_on", "used_in"))) == {refs["@b"], refs["@c"]}
    assert neighbours(around(kb, root, rels=frozenset({"about", "used_in"}))) == {refs["@a"], refs["@c"]}
    assert neighbours(around(kb, root, rels=["derived_from"])) == set()
    for bad, message in [("depends_on", "не строкой"), (5, "не строкой"), ([], "пустой"),
                         (["bogus"], "неизвестные виды связей bogus"), ([1], "строки"), ([["about"]], "строки")]:
        with pytest.raises(RecordError, match=message):
            around(kb, root, rels=bad)
    with pytest.raises(ValueError, match="не строкой"):                 # statuses — набор, как у других рецептов
        around(kb, root, statuses="deprecated")


def test_equal_paths_and_parallel_links_pick_smallest_edge_ids(kb):
    """Узел — один раз: из равных путей берётся путь с меньшей последовательностью id рёбер (а не с лучшей
    уверенностью), из параллельных связей — связь с меньшим id; лишние рёбра в выдачу не попадают."""
    refs = records.commit(kb, [entity("root"), atom("x"), atom("y"), atom("t"), atom("p")], agent=AGENT).refs

    def link(rel, src, dst, confidence=None):
        payload = {"rel": rel, "src": refs[src], "dst": refs[dst]}
        if confidence is not None:
            payload["confidence"] = confidence
        return str(records.commit(kb, [], [payload], agent=AGENT).links[0])

    # id связей растут со временем записи: root–y раньше root–x, а x–t раньше y–t
    link("depends_on", "@y", "@root", 0.2)
    link("depends_on", "@x", "@root", 0.9)
    link("depends_on", "@t", "@x", 0.9)
    y_t = link("depends_on", "@t", "@y", 0.2)
    first_parallel = link("used_in", "@p", "@root", 0.95)
    link("depends_on", "@p", "@root")

    result = around(kb, refs["@root"], depth=2)

    assert [edge["id"] for edge in result["edges"] if edge["to"] == refs["@t"]] == [y_t]
    assert path_to(result, refs["@t"])["nodes"] == [refs["@root"], refs["@y"], refs["@t"]]
    assert path_to(result, refs["@t"])["confidence"] == pytest.approx(0.2)
    assert [edge["id"] for edge in result["edges"] if edge["to"] == refs["@p"]] == [first_parallel]
    assert path_to(result, refs["@p"])["confidence"] == pytest.approx(0.95)
    assert len(result["nodes"]) == len(neighbours(result)) + 1 == 5
    assert len(result["edges"]) == len(result["paths"]) == 4


def test_mixed_structural_and_scored_path_takes_the_link_score(kb):
    """Структурное ребро не делает путь неизвестным: уверенность — минимум оценённых связей пути."""
    refs = records.commit(kb, [entity("root"), atom("a", about=["@root"]), atom("b")], [
        {"rel": "depends_on", "src": "@b", "dst": "@a", "confidence": 0.7},
    ], agent=AGENT).refs

    result = around(kb, refs["@root"], depth=2)

    path = path_to(result, refs["@b"])
    edges = {edge["id"]: edge for edge in result["edges"]}
    assert [edges[edge_id]["rel"] for edge_id in path["edges"]] == ["about", "depends_on"]
    assert path["confidence"] == pytest.approx(0.7)


def test_pending_and_declined_revisions_do_not_traverse(kb):
    """Поля ждущей проверки ревизии не ведут; запись без текущей ревизии (отклонена) — не сосед."""
    written = records.commit(kb, [entity("old"), entity("new"), atom("a", about=["@old"])], agent=AGENT)
    refs = written.refs
    payload = {**atom("a").payload, "about": [refs["@new"]]}
    payload.pop("ref")
    records.commit(kb, [Item("atom", payload, record_id=refs["@a"].split(":", 1)[1], review_state="pending")],
                   agent=AGENT)
    ghost = records.commit(kb, [Item("atom", {**atom("ghost").payload}, review_state="pending")], agent=AGENT)
    records.decide(kb, "atom", ghost.revisions[0].revision_id, False, agent="person:reviewer")
    records.commit(kb, [], [{"rel": "depends_on", "src": ghost.refs["@ghost"], "dst": refs["@old"]}], agent=AGENT)

    assert neighbours(around(kb, refs["@a"])) == {refs["@old"]}
    assert neighbours(around(kb, refs["@new"])) == set()
    assert neighbours(around(kb, refs["@old"])) == {refs["@a"]}


def test_evidence_role_counts_start_atom_and_sources_without_role(kb):
    """Источник без роли и стартовый атом без источников делают роль пути неизвестной, а не «primary»."""
    primary = source_object(kb, "primary")
    unrolled = source_object(kb, "unrolled")
    refs = records.commit(kb, [
        atom("start"), atom("strong", sources=[{**primary, "role": "primary"}]),
        atom("mixed", sources=[{**primary, "role": "primary"}, unrolled]),
        atom("plain", sources=[unrolled]), entity("hub"),
        atom("anchor", sources=[{**primary, "role": "primary"}]),
    ], [
        {"rel": "depends_on", "src": "@strong", "dst": "@start", "confidence": 0.9},
        {"rel": "used_in", "src": "@anchor", "dst": "@hub", "confidence": 0.9},
        {"rel": "used_in", "src": "@mixed", "dst": "@hub", "confidence": 0.8},
        {"rel": "used_in", "src": "@plain", "dst": "@hub", "confidence": 0.7},
    ], agent=AGENT).refs

    from_start = around(kb, refs["@start"])
    assert path_to(from_start, refs["@strong"])["evidence_role"] is None          # у старта источников нет
    from_anchor = around(kb, refs["@anchor"], depth=2)
    assert path_to(from_anchor, refs["@hub"])["evidence_role"] == "primary"       # сущность роль не меняет
    assert path_to(from_anchor, refs["@mixed"])["evidence_role"] is None
    assert path_to(from_anchor, refs["@plain"])["evidence_role"] is None


def test_order_within_a_level_follows_path_edge_ids(kb):
    """Порядок узлов уровня — по id рёбер пути, а не по ref соседа: у b ребро about новой ревизии позже, чем у a."""
    b = atom("b", about=["@root"])
    refs = records.commit(kb, [entity("root"), b, atom("a", about=["@root"])], agent=AGENT).refs
    revise(kb, b, refs["@b"], label={"ru": "b2"}, about=[refs["@root"]])

    result = around(kb, refs["@root"])

    assert [node["ref"] for node in result["nodes"][1:]] == [refs["@a"], refs["@b"]]
    assert [path["nodes"][-1] for path in result["paths"]] == [refs["@a"], refs["@b"]]
