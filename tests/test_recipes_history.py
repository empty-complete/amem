"""Рецепт what_changed: битемпоральная история, рекурсивный diff и отсутствие поискового журнала."""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from amem import db, ids, recipes, records
from amem.records import Item, RecordError

AGENT = "model:test"
HUMAN = "person:filipp"


@pytest.fixture
def kb(pg):
    db.prepare(pg)
    return pg


def atom(key, *, content=None, valid_from=None, valid_to=None):
    payload = {
        "ref": f"@{key}", "kind": "fact", "key": key,
        "label": {"ru": key}, "summary_plain": {"ru": key}, "codes": [],
    }
    if content is not None:
        payload["content"] = content
    if valid_from is not None:
        payload["valid_from"] = valid_from
    if valid_to is not None:
        payload["valid_to"] = valid_to
    return Item("atom", payload)


def update(item, record_id, **changes):
    payload = {**item.payload, **changes}
    payload.pop("ref", None)
    return Item("atom", payload, record_id=record_id)


def changed(kb, ref=None, since=None, until=None):
    return recipes.what_changed(kb, ref=ref, since=since, until=until)


def events_of(result, kind):
    return [event for event in result["events"] if event["type"] == kind]


def test_interval_requires_aware_ordered_bounds_and_is_half_open(kb):
    aware = datetime.now(timezone.utc)
    naive = datetime.now()
    for since, until in ((naive, aware), (aware, naive), (aware, aware),
                         (aware, aware - timedelta(seconds=1))):
        with pytest.raises(RecordError, match="часовым поясом|since.*until"):
            changed(kb, since=since, until=until)

    written = records.commit(kb, [atom("boundary")], agent=AGENT)
    recorded_at = kb.execute("SELECT recorded_at FROM atom_revision WHERE id = %s",
                             (written.revisions[0].revision_id,)).fetchone()[0]

    included = changed(kb, since=recorded_at, until=recorded_at + timedelta(microseconds=1))
    excluded = changed(kb, since=recorded_at - timedelta(microseconds=1), until=recorded_at)
    assert len(events_of(included, "revision")) == 1
    assert excluded["events"] == []
    assert changed(kb)["recipe"] == "what_changed"       # необязательные границы — без ограничений


def test_ref_limits_history_and_missing_ref_is_an_error(kb):
    first = records.commit(kb, [atom("first"), atom("second")], agent=AGENT).revisions
    records.commit(kb, [update(atom("second"), first[1].record_id, label={"ru": "new"})], agent=AGENT)

    result = changed(kb, ref=f"atm:{first[0].record_id}")

    assert result["ref"] == f"atm:{first[0].record_id}"
    assert result["events"]
    assert {event["ref"] for event in result["events"]} == {f"atm:{first[0].record_id}"}
    assert [event["revision"] for event in events_of(result, "revision")] == [1]
    with pytest.raises(RecordError, match="такой записи нет"):
        changed(kb, ref=f"atm:{ids.uuid7()}")


def test_revision_review_and_sequential_diffs_use_transaction_time(kb):
    first = records.commit(kb, [atom("history", content={
        "array": [1, 2], "nested": {"value": 1}, "removed": "old",
    })], agent=AGENT).revisions[0]
    pending_item = update(atom("history"), first.record_id,
                          label={"ru": "new"},
                          content={"array": [1, 3], "nested": {"value": 2}, "added_null": None},
                          valid_from="2001-01-01", valid_to="2001-12-31")
    pending_item.review_state = "pending"
    second = records.commit(kb, [pending_item], agent=AGENT).revisions[0]
    records.decide(kb, "atom", second.revision_id, accept=True, agent=HUMAN)
    third = records.commit(kb, [update(atom("history"), first.record_id, summary_plain={"ru": "third"})],
                           agent=AGENT).revisions[0]

    result = changed(kb, ref=f"atm:{first.record_id}")
    revisions = events_of(result, "revision")
    reviews = events_of(result, "review")

    assert [event["revision"] for event in revisions] == [1, 2, 3]
    second_event = revisions[1]
    assert second_event["id"] == str(second.revision_id)
    assert second_event["previous_content_hash"] == first.content_hash
    assert second_event["content_hash"] == second.content_hash
    assert revisions[2]["previous_content_hash"] == second.content_hash
    assert revisions[2]["content_hash"] == third.content_hash
    assert second_event["valid_from"] == "2001-01-01" and second_event["valid_to"] == "2001-12-31"
    assert second_event["at"] == second_event["recorded_at"]
    assert "payload" not in second_event and "previous_payload" not in second_event
    paths = [change["path"] for change in second_event["changes"]]
    assert paths == sorted(paths)
    changes = {change["path"]: change for change in second_event["changes"]}
    # null в каноническом теле удаляется; его отличие от отсутствия проверяет чистый _diff ниже.
    assert changes["/content/removed"] == {"path": "/content/removed", "before": "old"}
    assert changes["/content/array"] == {
        "path": "/content/array", "before": [1, 2], "after": [1, 3],
    }
    assert changes["/content/nested/value"] == {
        "path": "/content/nested/value", "before": 1, "after": 2,
    }
    assert len(reviews) == 1
    assert reviews[0]["review_state"] == "accepted"
    assert reviews[0]["reviewed_by"] == HUMAN
    assert reviews[0]["at"] == reviews[0]["reviewed_at"]

    recorded_at = datetime.fromisoformat(second_event["recorded_at"])
    in_recording_interval = changed(kb, ref=f"atm:{first.record_id}",
                                    since=recorded_at, until=recorded_at + timedelta(microseconds=1))
    assert [event["revision"] for event in events_of(in_recording_interval, "revision")] == [2], \
        "valid time 2001 года не должен подменять transaction time"


def test_recursive_diff_distinguishes_missing_null_and_treats_array_as_value():
    before = {
        "array": [1, 2], "nested": {"change": 1, "remove": "old"},
        "null": None, "same": {"x": [1]}, "tilde~key": 1,
    }
    after = {
        "array": [1, 3], "nested": {"change": 2, "add_null": None},
        "null": None, "same": {"x": [1]}, "tilde~key": 2, "slash/key": True,
    }
    before_copy, after_copy = copy.deepcopy(before), copy.deepcopy(after)

    assert recipes._diff(before, after) == [
        {"path": "/array", "before": [1, 2], "after": [1, 3]},
        {"path": "/nested/add_null", "after": None},
        {"path": "/nested/change", "before": 1, "after": 2},
        {"path": "/nested/remove", "before": "old"},
        {"path": "/slash~1key", "after": True},
        {"path": "/tilde~0key", "before": 1, "after": 2},
    ]
    assert recipes._diff(1, 2) == [{"path": "", "before": 1, "after": 2}]
    assert before == before_copy and after == after_copy


def test_recursive_diff_sorts_by_escaped_json_pointer():
    assert recipes._diff({"/": 1, "0": 1}, {"/": 2, "0": 2}) == [
        {"path": "/0", "before": 1, "after": 2},
        {"path": "/~1", "before": 1, "after": 2},
    ]


def test_status_link_creation_and_retirement_include_either_end(kb):
    written = records.commit(kb, [
        atom("source"),
        Item("entity", {"ref": "@target", "entity_class": "document", "key": "target", "label": {"ru": "target"}}),
        atom("unrelated"),
    ], agent=AGENT)
    source_ref, target_ref = written.refs["@source"], written.refs["@target"]
    source_id = source_ref.split(":", 1)[1]
    link_id = records.commit(kb, [], [{"rel": "depends_on", "src": source_ref, "dst": target_ref}],
                             agent=AGENT).links[0]
    records.set_status(kb, "atom", source_id, "verified", agent=HUMAN, reason="проверено")
    records.retire_link(kb, link_id, agent=HUMAN, reason="устарела")

    at_target = changed(kb, ref=target_ref)
    at_source = changed(kb, ref=source_ref)
    at_unrelated = changed(kb, ref=written.refs["@unrelated"])
    created = events_of(at_target, "link_created")
    retired = events_of(at_target, "link_retired")

    assert len(created) == len(retired) == 1
    for event in created + retired:
        assert event["id"] == str(link_id)
        assert event["src"] == source_ref and event["dst"] == target_ref
        assert event["rel"] == "depends_on"
    assert created[0]["at"] == created[0]["created_at"]
    assert retired[0]["at"] == retired[0]["retired_at"]
    assert events_of(at_source, "link_created") == created
    assert events_of(at_source, "link_retired") == retired
    assert not events_of(at_unrelated, "link_created") and not events_of(at_unrelated, "link_retired")
    statuses = [event for event in events_of(at_source, "status") if event["status"] == "verified"]
    assert len(statuses) == 1
    assert statuses[0]["ref"] == source_ref and statuses[0]["agent"] == HUMAN
    assert statuses[0]["reason"] == "проверено" and statuses[0]["at"] == statuses[0]["changed_at"]
    assert not events_of(at_target, "status") or all(event["ref"] == target_ref
                                                     for event in events_of(at_target, "status"))


def test_declined_review_remains_a_separate_history_event(kb):
    first = records.commit(kb, [atom("declined")], agent=AGENT).revisions[0]
    pending = update(atom("declined"), first.record_id, label={"ru": "rejected"})
    pending.review_state = "pending"
    second = records.commit(kb, [pending], agent=AGENT).revisions[0]
    records.decide(kb, "atom", second.revision_id, accept=False, agent=HUMAN)

    result = changed(kb, ref=f"atm:{first.record_id}")

    assert [event["revision"] for event in events_of(result, "revision")] == [1, 2]
    assert [event["review_state"] for event in events_of(result, "review")] == ["declined"]
    assert events_of(result, "review")[0]["id"] == str(second.revision_id)


def test_events_have_deterministic_order_json_types_and_no_retrieval(kb):
    before = kb.execute("SELECT count(*) FROM retrieval").fetchone()[0]
    written = records.commit(kb, [atom("one"), atom("two")], agent=AGENT)

    result = changed(kb)

    assert result["recipe"] == "what_changed" and result["retrieval_id"] is None
    assert result["since"] is None and result["until"] is None
    assert len(events_of(result, "revision")) == 2
    assert len(events_of(result, "status")) == 2
    order = [(datetime.fromisoformat(event["at"]), event["type"], event["id"]) for event in result["events"]]
    assert order == sorted(order)
    assert all(isinstance(event["id"], str) and isinstance(event["at"], str) for event in result["events"])
    json.dumps(result)
    assert kb.execute("SELECT count(*) FROM retrieval").fetchone()[0] == before
    assert {event["ref"] for event in events_of(result, "revision")} == {
        f"atm:{written.revisions[0].record_id}", f"atm:{written.revisions[1].record_id}",
    }
