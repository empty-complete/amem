"""Выдача retrieval и очки полезности: права, идемпотентность, затухание и RRF."""
import json
import math
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from amem import db, ids, lookup, recipes, records, search
from amem.records import Item

AGENT = "model:test"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def kb(pg):
    db.prepare(pg)
    return pg


def atom(key, label, *, codes=None):
    return Item("atom", {
        "ref": f"@{key}", "kind": "fact", "key": key,
        "label": {"ru": label}, "summary_plain": {"ru": label}, "codes": codes or [],
    })


def entity(key, label, *, codes=None):
    return Item("entity", {
        "ref": f"@{key}", "entity_class": "document", "key": key,
        "label": {"ru": label}, "codes": codes or [],
    })


def write(kb, *items):
    return records.commit(kb, list(items), agent=AGENT)


def make_activity(kb, *, at=NOW):
    activity = ids.uuid7()
    kb.execute("INSERT INTO activity (id, kind, label, started_at) VALUES (%s, 'task', 'Тест', %s)",
               (activity, at))
    return activity


def find(kb, query, **kwargs):
    kwargs.setdefault("agent", AGENT)
    kwargs.setdefault("now", NOW)
    return recipes.exact_fact(kb, query, **kwargs)


def utility():
    from amem import usefulness
    return usefulness


def use_count(kb):
    return kb.execute("SELECT count(*) FROM atom_use").fetchone()[0]


def test_text_search_records_origin_and_final_atom_ranks(kb):
    activity = make_activity(kb)
    written = write(kb,
                    atom("fact", "Общая марка", codes=["LOG-1"]),
                    entity("doc", "Общая марка", codes=["LOG-1"]))

    result = find(kb, "LOG-1", activity=activity)

    assert result["retrieval_id"]
    assert set(result) == {
        "recipe", "ranking_version", "channels", "semantic", "candidate_count",
        "embedding_coverage", "items", "retrieval_id",
    }
    row = kb.execute(
        "SELECT activity, recipe, query, agent, created_at, ranking_version FROM retrieval WHERE id = %s",
        (result["retrieval_id"],)).fetchone()
    assert row == (activity, "exact_fact", "LOG-1", AGENT, NOW, search.RANKING_V1["version"])
    expected = {
        item["ref"].split(":", 1)[1]: rank
        for rank, item in enumerate(result["items"], 1) if item["ref"].startswith("atm:")
    }
    stored = kb.execute("SELECT atom_id, rank FROM retrieval_item WHERE retrieval_id = %s",
                        (result["retrieval_id"],)).fetchall()
    assert {str(atom_id): rank for atom_id, rank in stored} == expected
    assert set(expected) == {str(written.revisions[0].record_id)}
    json.dumps(result)


def test_entity_only_search_creates_retrieval_without_atom_items(kb):
    write(kb, entity("doc", "Только сущность", codes=["ENT-1"]))

    result = find(kb, "ENT-1", target="entity")

    assert result["items"] and all(item["ref"].startswith("ent:") for item in result["items"])
    assert kb.execute("SELECT count(*) FROM retrieval").fetchone()[0] == 1
    assert kb.execute("SELECT count(*) FROM retrieval_item WHERE retrieval_id = %s",
                      (result["retrieval_id"],)).fetchone()[0] == 0


def test_empty_search_also_creates_one_retrieval(kb):
    result = find(kb, "пустой запрос без результата")

    assert result["items"] == []
    assert kb.execute("SELECT count(*) FROM retrieval").fetchone()[0] == 1
    assert kb.execute("SELECT count(*) FROM retrieval_item").fetchone()[0] == 0


def test_mark_helpful_rejects_whole_invalid_batch(kb):
    activity = make_activity(kb)
    other_activity = make_activity(kb)
    written = write(kb,
                    atom("first", "Общая полезность"),
                    atom("second", "Общая полезность"),
                    entity("entity", "Общая полезность"),
                    atom("foreign", "Чужой атом"))
    refs = {key: f"atm:{revision.record_id}" for key, revision in zip(
        ("first", "second", "entity", "foreign"), written.revisions)}
    refs["entity"] = f"ent:{written.revisions[2].record_id}"
    result = find(kb, "Общая полезность", activity=activity)
    retrieval_id = result["retrieval_id"]
    assert refs["first"] in {item["ref"] for item in result["items"]}
    assert refs["entity"] in {item["ref"] for item in result["items"]}
    assert refs["foreign"] not in {item["ref"] for item in result["items"]}

    invalid_calls = [
        ([refs["first"], refs["foreign"]], activity),
        ([refs["entity"]], activity),
        ([refs["first"]], other_activity),
        ([refs["first"]], None),
    ]
    for refs_to_mark, selected_activity in invalid_calls:
        with pytest.raises(ValueError):
            utility().mark_helpful(kb, retrieval_id, refs_to_mark,
                                   agent=AGENT, activity=selected_activity, now=NOW)
        assert use_count(kb) == 0

    without_activity = find(kb, "Общая полезность")
    with pytest.raises(ValueError):
        utility().mark_helpful(kb, without_activity["retrieval_id"], [refs["first"]],
                               agent=AGENT, activity=activity, now=NOW)
    assert use_count(kb) == 0


def test_repeated_marks_are_idempotent_per_activity_and_never_updated(kb):
    activity = make_activity(kb)
    other_activity = make_activity(kb)
    revision = write(kb, atom("fact", "Идемпотентность", codes=["IDEM-1"])).revisions[0]
    ref = f"atm:{revision.record_id}"
    first = find(kb, "IDEM-1", activity=activity)
    second = find(kb, "IDEM-1", activity=activity)
    other_task = find(kb, "IDEM-1", activity=other_activity)

    class QueryRecorder:
        def __init__(self, conn):
            self.conn = conn
            self.queries = []

        def execute(self, sql, params=None):
            self.queries.append(sql)
            return self.conn.execute(sql, params)

        def __getattr__(self, name):
            return getattr(self.conn, name)

    recorder = QueryRecorder(kb)
    for retrieval_id, selected_activity in (
            (first["retrieval_id"], activity),
            (first["retrieval_id"], activity),
            (second["retrieval_id"], activity),
            (other_task["retrieval_id"], other_activity)):
        utility().mark_helpful(recorder, retrieval_id, [ref],
                               agent=AGENT, activity=selected_activity, now=NOW)

    assert use_count(kb) == 2
    assert not any("UPDATE atom_use" in query.upper() for query in recorder.queries)
    rows = kb.execute("SELECT activity, retrieval_id FROM atom_use WHERE atom_id = %s ORDER BY activity",
                      (revision.record_id,)).fetchall()
    assert {(row[0], str(row[1])) for row in rows} == {
        (activity, first["retrieval_id"]), (other_activity, other_task["retrieval_id"]),
    }
    with pytest.raises(psycopg.errors.UniqueViolation):
        with kb.transaction():
            kb.execute("INSERT INTO atom_use (id, atom_id, retrieval_id, activity, agent, used_at) "
                       "VALUES (%s, %s, %s, %s, %s, %s)",
                       (ids.uuid7(), revision.record_id, first["retrieval_id"], activity, AGENT, NOW))
    assert use_count(kb) == 2


def test_decay_score_and_multiplier_match_independent_reference(kb):
    revision = write(kb, atom("fact", "Затухание", codes=["DECAY-1"])).revisions[0]
    ref = f"atm:{revision.record_id}"
    for days in (0, 180, 360):
        used_at = NOW - timedelta(days=days)
        activity = make_activity(kb, at=used_at)
        result = find(kb, "DECAY-1", activity=activity, now=used_at, usefulness=False)
        utility().mark_helpful(kb, result["retrieval_id"], [ref],
                               agent=AGENT, activity=activity, now=used_at)

    expected = sum(2 ** (-days / 180) for days in (0, 180, 360))
    assert utility().score(kb, revision.record_id, now=NOW) == pytest.approx(expected)
    assert utility().multiplier(expected) == pytest.approx(min(1.25, 1 + 0.05 * math.log1p(expected)))
    assert utility().multiplier(0) == 1


def test_future_mark_is_rejected_when_scoring(kb):
    revision = write(kb, atom("fact", "Будущее", codes=["FUTURE-1"])).revisions[0]
    ref = f"atm:{revision.record_id}"
    activity = make_activity(kb)
    result = find(kb, "FUTURE-1", activity=activity)
    utility().mark_helpful(kb, result["retrieval_id"], [ref],
                           agent=AGENT, activity=activity, now=NOW + timedelta(seconds=1))

    with pytest.raises(ValueError, match="будущ"):
        utility().score(kb, revision.record_id, now=NOW)


def candidate(ref, rank):
    target, record_id = ref.split(":", 1)
    return {"target": "atom", "record_id": record_id, "revision_id": record_id,
            "ref": ref, "rank": rank, "source_rank": None}


def test_rrf_applies_utility_after_sum_and_keeps_exact_code_first(kb):
    exact = "atm:00000000-0000-0000-0000-000000000001"
    popular = "atm:00000000-0000-0000-0000-000000000002"
    channels = {"code_exact": [candidate(exact, 50)],
                "code_prefix": [candidate(popular, 1), candidate(popular, 2)]}

    result = search._rrf(channels, {"code_exact": 4, "code_prefix": 2},
                         exact_fact=True, usefulness={popular: 1.25})

    assert [hit["ref"] for hit in result["hits"]] == [exact, popular]
    hits = {hit["ref"]: hit for hit in result["hits"]}
    assert hits[exact]["score"] == pytest.approx(4 / 110)
    assert hits[popular]["score"] == pytest.approx((2 / 61 + 2 / 62) * 1.25)


def test_ranking_uses_marks_but_disabled_mode_does_not_read_them(kb):
    activity = make_activity(kb)
    write(kb, atom("first", "Одинаковый запрос"), atom("second", "Одинаковый запрос"))
    baseline = find(kb, "Одинаковый запрос", activity=activity, usefulness=False)
    original_order = [item["ref"] for item in baseline["items"]]
    marked_ref = original_order[1]
    before = lookup.get(kb, "atom", marked_ref.split(":", 1)[1])
    utility().mark_helpful(kb, baseline["retrieval_id"], [marked_ref],
                           agent=AGENT, activity=activity, now=NOW)

    boosted = find(kb, "Одинаковый запрос", activity=activity)
    disabled = find(kb, "Одинаковый запрос", activity=activity, usefulness=False)

    assert [item["ref"] for item in boosted["items"]][0] == marked_ref
    assert [item["ref"] for item in disabled["items"]] == original_order
    assert [item["score"] for item in disabled["items"]] == [item["score"] for item in baseline["items"]]
    assert all(set(item) == {
        "ref", "revision", "label", "snippet", "status", "review_state", "score", "matches",
    } for item in boosted["items"])
    assert lookup.get(kb, "atom", marked_ref.split(":", 1)[1]) == before
    assert before["status"] == "draft" and before["review_state"] == "none"

    class NoUtilityReads:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, params=None):
            assert "atom_use" not in sql.lower()
            return self.conn.execute(sql, params)

        def __getattr__(self, name):
            return getattr(self.conn, name)

    result = recipes.exact_fact(NoUtilityReads(kb), "Одинаковый запрос", agent=AGENT,
                                activity=activity, usefulness=False, now=NOW)
    assert [item["ref"] for item in result["items"]] == original_order


def test_new_revision_keeps_atom_score_and_old_retrieval_atom_reference(kb):
    activity = make_activity(kb)
    original = write(kb, atom("fact", "Первая редакция", codes=["REV-1"])).revisions[0]
    result = find(kb, "REV-1", activity=activity)
    utility().mark_helpful(kb, result["retrieval_id"], [f"atm:{original.record_id}"],
                           agent=AGENT, activity=activity, now=NOW)
    score_before = utility().score(kb, original.record_id, now=NOW)

    revised = records.commit(kb, [Item("atom", {
        "kind": "fact", "key": "fact", "label": {"ru": "Вторая редакция"},
        "summary_plain": {"ru": "Вторая редакция"}, "codes": ["REV-1"],
    }, record_id=original.record_id)], agent=AGENT).revisions[0]

    assert revised.revision_id != original.revision_id
    assert utility().score(kb, original.record_id, now=NOW) == score_before
    atom_id = kb.execute("SELECT atom_id FROM retrieval_item WHERE retrieval_id = %s",
                         (result["retrieval_id"],)).fetchone()[0]
    assert atom_id == original.record_id
    columns = {row[0] for row in kb.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'retrieval_item'")}
    assert "revision_id" not in columns
