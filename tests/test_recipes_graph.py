"""Рецепт around_entity: BFS по текущему графу, кратчайшие пути и слабейшие доказательства."""
import json

import pytest

from amemo import db, folders, ids, recipes, records, review, usefulness
from amemo.records import Item, RecordError, RecordNotFound

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


def test_limit_stops_the_walk_and_reports_truncated(kb):
    """limit — узлов в выдаче не больше, ближние раньше дальних, тот же порядок, что без предела; truncated —
    за пределом остались узлы."""
    written = records.commit(kb, [
        entity("root"), atom("a", about=["@root"]), atom("b", about=["@root"]), atom("c", derived_from=["@a"]),
    ], agent=AGENT)
    refs = written.refs
    full = around(kb, refs["@root"], depth=2)
    assert full["truncated"] is False and len(full["nodes"]) == 4
    assert around(kb, refs["@root"], depth=2, limit=4)["truncated"] is False      # ровно столько, сколько есть
    cut = around(kb, refs["@root"], depth=2, limit=3)
    assert cut["truncated"] is True
    assert [n["ref"] for n in cut["nodes"]] == [n["ref"] for n in full["nodes"]][:3]
    assert max(n["depth"] for n in cut["nodes"]) == 1 and len(cut["edges"]) == 2
    assert around(kb, refs["@root"], depth=2, limit=1)["nodes"] == full["nodes"][:1]
    assert (full["total"], cut["total"], around(kb, refs["@root"], depth=2, limit=1)["total"]) == (4, 4, 4)
    for bad in (0, -1, True, "3"):
        with pytest.raises(RecordError, match="limit"):
            around(kb, refs["@root"], limit=bad)


def test_limit_defaults_to_300_and_total_counts_nodes_past_the_limit(kb):
    """По умолчанию — 300 узлов; total за пределом — столько, сколько нашёл бы обход без предела, с теми же
    глубиной, видами связей и статусами."""
    hub = entity("hub")
    leaves = [atom(f"leaf{i}", about=["@hub"]) for i in range(305)]
    refs = records.commit(kb, [hub, *leaves, atom("far", derived_from=["@leaf0"]),
                               atom("old", derived_from=["@leaf1"], status="deprecated")], agent=AGENT).refs
    found = around(kb, refs["@hub"])
    assert (len(found["nodes"]), found["truncated"], found["total"]) == (300, True, 306)
    for kwargs in ({"depth": 2}, {"depth": 2, "rels": {"about"}}, {"depth": 3, "statuses": ["draft", "deprecated"]},
                   {"depth": 2, "rels": {"derived_from"}}):
        unlimited = around(kb, refs["@hub"], limit=None, **kwargs)
        for limit in (1, 5, 400):
            cut = around(kb, refs["@hub"], limit=limit, **kwargs)
            assert cut["total"] == len(unlimited["nodes"]), (kwargs, limit)
            assert cut["truncated"] is (len(unlimited["nodes"]) > limit)


def test_degree_counts_current_links_of_the_whole_base_and_pending_open_items(kb):
    """degree — текущие связи узла в базе, а не в выдаче: действующие link и поля текущих ревизий, в обе стороны;
    выведенная связь и поле старой ревизии не считаются. pending — открытый пункт очереди (queued, claimed)."""
    old = atom("old", about=["@root"])
    written = records.commit(kb, [
        entity("root"), entity("side"), atom("a", about=["@root", "@side"], derived_from=["@b"]), atom("b"), old,
        atom("lone"),
    ], [
        {"rel": "depends_on", "src": "@b", "dst": "@root"},
        {"rel": "see_also", "src": "@side", "dst": "@root"},
        {"rel": "depends_on", "src": "@lone", "dst": "@b"},
    ], agent=AGENT)
    refs = written.refs
    revise(kb, old, refs["@old"], about=[])
    records.retire_link(kb, written.links[2], agent=AGENT, reason="не действует")
    review.enqueue(kb, refs["@a"], "audit", agent="person:ann")
    review.enqueue(kb, refs["@root"], "audit", agent="person:ann")
    review.claim(kb, agent="person:ann", reasons=["audit"])                  # один пункт — claimed, второй — queued

    nodes = {n["ref"]: n for n in around(kb, refs["@root"], depth=1, rels={"about"})["nodes"]}
    assert nodes[refs["@root"]]["degree"] == 3                     # about от a, depends_on от b, see_also от side
    assert nodes[refs["@a"]]["degree"] == 3                        # два about и derived_from — хоть в выдаче одно
    assert (nodes[refs["@root"]]["pending"], nodes[refs["@a"]]["pending"]) == (True, True)
    whole = {n["ref"]: n for n in recipes.overview(kb)["nodes"]}
    assert {ref: n["degree"] for ref, n in whole.items()} == {
        refs["@root"]: 3, refs["@side"]: 2, refs["@a"]: 3, refs["@b"]: 2, refs["@old"]: 0, refs["@lone"]: 0}
    assert {ref for ref, n in whole.items() if n["pending"]} == {refs["@a"], refs["@root"]}
    for ref, node in whole.items():                                 # обзор и окрестность считают одинаково
        assert {n["ref"]: n["degree"] for n in around(kb, ref)["nodes"]}[ref] == node["degree"]
    item = kb.execute("SELECT id FROM review_item WHERE record_id = %s",
                      (records.resolve(kb, refs["@a"])[1],)).fetchone()[0]
    kb.execute("UPDATE review_item SET state = 'obsolete', closed_at = now(), claimed_by = NULL, "
               "claimed_until = NULL WHERE id = %s", (item,))
    assert {n["ref"] for n in recipes.overview(kb)["nodes"] if n["pending"]} == {refs["@root"]}


def overview_order(kb, nodes):
    """Ожидаемый порядок обзора: degree по убыванию, затем новые первыми (время создания, id)."""
    created = {}
    for target in ("atom", "entity"):
        for record_id, at in kb.execute(f"SELECT id, created_at FROM {target}").fetchall():
            created[f"{records.PREFIX[target]}:{record_id}"] = (at, record_id)
    return sorted(nodes, key=lambda ref: (nodes[ref], created[ref]), reverse=True)


def test_overview_orders_by_degree_newest_first_cuts_and_keeps_inner_edges(kb):
    first = records.commit(kb, [entity("hub"), entity("x"), atom("a", about=["@hub"]), atom("b", about=["@hub"])],
                           [{"rel": "depends_on", "src": "@a", "dst": "@x", "confidence": 0.5}], agent=AGENT).refs
    second = records.commit(kb, [atom("c", about=[first["@hub"]]), entity("y"), atom("z")],
                            [{"rel": "see_also", "src": "@y", "dst": first["@x"]}], agent=AGENT).refs
    refs = {**first, **second}
    full = recipes.overview(kb)
    degrees = {n["ref"]: n["degree"] for n in full["nodes"]}
    assert degrees == {refs["@hub"]: 3, refs["@x"]: 2, refs["@a"]: 2, refs["@b"]: 1, refs["@c"]: 1,
                       refs["@y"]: 1, refs["@z"]: 0}
    assert [n["ref"] for n in full["nodes"]] == overview_order(kb, degrees)
    assert [n["ref"] for n in full["nodes"]][:1] == [refs["@hub"]]
    assert (full["recipe"], full["project"], full["total"], full["truncated"]) == ("overview", None, 7, False)
    assert {(e["rel"], e["src"], e["dst"]) for e in full["edges"]} == {
        ("about", refs["@a"], refs["@hub"]), ("about", refs["@b"], refs["@hub"]), ("about", refs["@c"], refs["@hub"]),
        ("depends_on", refs["@a"], refs["@x"]), ("see_also", refs["@y"], refs["@x"])}
    assert "depth" not in full["nodes"][0] and {"pending", "degree", "status", "revision"} <= set(full["nodes"][0])

    cut = recipes.overview(kb, limit=3)
    order = [n["ref"] for n in full["nodes"]]
    # хаб — один (3 // 4, не меньше одного), дальше его соседи по degree: a, затем b или c — кто раньше в порядке
    near = [ref for ref in order if ref in {refs["@a"], refs["@b"], refs["@c"]}][:2]
    assert [n["ref"] for n in cut["nodes"]] == sorted([refs["@hub"], *near], key=order.index)
    assert (cut["total"], cut["truncated"]) == (7, True)
    kept = {n["ref"] for n in cut["nodes"]}
    assert cut["edges"] and all(e["src"] in kept and e["dst"] in kept for e in cut["edges"])
    assert recipes.overview(kb, limit=7)["truncated"] is False
    assert len(recipes.overview(kb, limit=None)["nodes"]) == 7
    only = recipes.overview(kb, rels={"see_also"})
    assert {e["rel"] for e in only["edges"]} == {"see_also"} and only["total"] == 7     # rels — только рёбра
    for bad in (0, -1, True, "3"):
        with pytest.raises(RecordError, match="limit"):
            recipes.overview(kb, limit=bad)


def test_overview_statuses_and_records_without_current_revision(kb):
    refs = records.commit(kb, [entity("hub"), atom("a", about=["@hub"]), atom("gone", about=["@hub"],
                                                                              status="deprecated")],
                          agent=AGENT).refs
    ghost = records.commit(kb, [Item("atom", {**atom("ghost").payload}, review_state="pending")], agent=AGENT)
    records.decide(kb, "atom", ghost.revisions[0].revision_id, False, agent="person:reviewer")

    default = recipes.overview(kb)
    assert {n["ref"] for n in default["nodes"]} == {refs["@hub"], refs["@a"]} and default["total"] == 2
    assert {n["ref"]: n["degree"] for n in default["nodes"]}[refs["@hub"]] == 2     # степень — со всеми соседями
    deprecated = recipes.overview(kb, statuses=["deprecated"])
    assert [n["ref"] for n in deprecated["nodes"]] == [refs["@gone"]] and deprecated["edges"] == []
    assert recipes.overview(kb, statuses=["draft", "deprecated"])["total"] == 3
    empty = recipes.overview(kb, statuses=["verified"])
    assert (empty["nodes"], empty["edges"], empty["total"], empty["truncated"]) == ([], [], 0, False)


def test_overview_of_a_project(kb):
    """project — атомы, у текущей ревизии которых scope.project — этот проект, и сущности, связанные с ними."""
    moved = atom("moved", about=["@e3"])
    moved.payload["scope"] = {"project": "@proj"}
    p1 = atom("p1", about=["@e1"])
    p1.payload["scope"] = {"project": "@proj"}
    p2 = atom("p2")
    p2.payload["scope"] = {"project": "@proj"}
    p3 = atom("p3", about=["@e5"], status="deprecated")        # атом проекта вне фильтра статусов по умолчанию
    p3.payload["scope"] = {"project": "@proj"}
    other = atom("other", about=["@e4"])
    other.payload["scope"] = {"project": "@else"}
    written = records.commit(kb, [
        Item("entity", {"ref": "@proj", "entity_class": "project", "key": "proj", "label": {"ru": "Проект"}}),
        Item("entity", {"ref": "@else", "entity_class": "project", "key": "else", "label": {"ru": "Другой"}}),
        entity("e1"), entity("e2"), entity("e3"), entity("e4"), entity("e5"), entity("lone"), p1, p2, p3, moved,
        other,
        atom("plain", about=["@e1"]),
    ], [{"rel": "used_in", "src": "@p2", "dst": "@e2"}, {"rel": "see_also", "src": "@e1", "dst": "@e4"}],
        agent=AGENT)
    refs = written.refs
    revise(kb, moved, refs["@moved"], about=[refs["@e3"]], scope={"project": refs["@else"]})      # текущая ревизия — уже другой проект

    found = recipes.overview(kb, project="ent:proj")
    assert found["project"] == refs["@proj"]
    assert {n["ref"] for n in found["nodes"]} == {refs["@p1"], refs["@p2"], refs["@e1"], refs["@e2"]}
    assert found["total"] == 4 and found["truncated"] is False
    assert {n["ref"]: n["degree"] for n in found["nodes"]}[refs["@e1"]] == 3       # about p1, plain и see_also
    assert {(e["src"], e["dst"]) for e in found["edges"]} == {(refs["@p1"], refs["@e1"]), (refs["@p2"], refs["@e2"])}
    assert recipes.overview(kb, project=refs["@proj"], limit=1)["total"] == 4
    wider = recipes.overview(kb, project="ent:proj", statuses=["draft", "deprecated"])
    assert {n["ref"] for n in wider["nodes"]} == {refs["@p1"], refs["@p2"], refs["@p3"], refs["@e1"], refs["@e2"],
                                                  refs["@e5"]}
    # сама e5 — черновик: под фильтром только deprecated остаётся один атом проекта
    assert {n["ref"] for n in recipes.overview(kb, project="ent:proj", statuses=["deprecated"])["nodes"]} == \
        {refs["@p3"]}
    assert {n["ref"] for n in recipes.overview(kb, project="ent:else")["nodes"]} == \
        {refs["@other"], refs["@moved"], refs["@e4"], refs["@e3"]}
    with pytest.raises(RecordError, match="сущность"):
        recipes.overview(kb, project=refs["@p1"])
    with pytest.raises(RecordNotFound):
        recipes.overview(kb, project="ent:no_such")
    assert recipes.overview(kb, project="ent:lone")["total"] == 0


def test_overview_takes_hubs_then_their_neighbours_so_the_sky_has_lines(kb):
    """Top-N по degree на базе с хабами — одни хабы без линий. Отбор: limit // 4 хабов, их соседи по degree,
    остальные места — прочие узлы по degree; выдача — по degree."""
    items = []
    for h in range(6):
        items.append(entity(f"hub{h}"))
        items.extend(atom(f"leaf{h}_{i}", about=[f"@hub{h}"]) for i in range(5))
    items.extend([atom("lone1"), atom("lone2")])
    refs = records.commit(kb, items, agent=AGENT).refs
    hubs = {refs[f"@hub{h}"] for h in range(6)}
    full = recipes.overview(kb, limit=None)
    order = [n["ref"] for n in full["nodes"]]
    assert set(order[:6]) == hubs and full["total"] == 38

    six = recipes.overview(kb, limit=6)                       # раньше — шесть хабов и ни одной линии
    picked = [n["ref"] for n in six["nodes"]]
    first = order[0]
    assert picked[0] == first and len(picked) == 6 and len(six["edges"]) == 5
    h = next(h for h in range(6) if refs[f"@hub{h}"] == first)
    assert set(picked[1:]) == {refs[f"@leaf{h}_{i}"] for i in range(5)}         # один хаб и его соседи
    assert all(e["dst"] == first and e["rel"] == "about" for e in six["edges"])
    assert [n["degree"] for n in six["nodes"]] == sorted((n["degree"] for n in six["nodes"]), reverse=True)

    twelve = recipes.overview(kb, limit=12)                   # три хаба и девять их соседей
    picked = {n["ref"] for n in twelve["nodes"]}
    assert len(picked & hubs) == 3 and set(order[:3]) <= picked and len(twelve["edges"]) == 9
    assert all(e["dst"] in picked & hubs for e in twelve["edges"])
    assert (twelve["total"], twelve["truncated"]) == (38, True)

    # соседей хабов меньше, чем мест: остаток — прочие узлы по degree
    many = recipes.overview(kb, limit=32)                     # 8 хабов: шесть хабов, 30 листьев — 32 места
    assert len(many["nodes"]) == 32 and hubs <= {n["ref"] for n in many["nodes"]}
    assert {refs["@lone1"], refs["@lone2"]}.isdisjoint({n["ref"] for n in many["nodes"]})
    assert len(recipes.overview(kb, limit=36)["edges"]) == 30                # все хабы и листья, без одиночек


def test_overview_filters_by_tags_kind_and_folder(kb):
    """Фильтры обзора, как у списка записей: теги — все сразу (с ними — и объекты, связанные с отобранными
    атомами), вид или класс, папка с вложенными и «-» — без папки."""
    sci1 = atom("sci1", about=["@e1"])
    sci1.payload["tags"] = ["наука"]
    sci2 = atom("sci2")
    sci2.payload["tags"] = ["наука", "ветер"]
    sci2.payload["kind"] = "lesson"
    plain = atom("plain", about=["@e2"])
    refs = records.commit(kb, [entity("e1"), entity("e2"), entity("lone"), sci1, sci2, plain], agent=AGENT).refs
    folders.move(kb, refs["@sci1"], "Наука/Ветер", agent=AGENT)

    def picked(**kw):
        return {n["ref"] for n in recipes.overview(kb, **kw)["nodes"]}

    assert picked(tags=["наука"]) == {refs["@sci1"], refs["@sci2"], refs["@e1"]}
    assert picked(tags=["наука", "ветер"]) == {refs["@sci2"]}
    assert picked(kinds=["lesson"]) == {refs["@sci2"]}
    assert picked(kinds=["document"]) == {refs["@e1"], refs["@e2"], refs["@lone"]}
    assert picked(folder="Наука") == {refs["@sci1"]}
    assert picked(folder="-") == {refs["@sci2"], refs["@plain"], refs["@e1"], refs["@e2"], refs["@lone"]}
    assert picked(tags=["наука"], kinds=["fact"]) == {refs["@sci1"]}          # вид сужает и объекты
    assert recipes.overview(kb, tags=["наука"])["total"] == 3
