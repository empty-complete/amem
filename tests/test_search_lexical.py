"""Лексические каналы: марки, русский FTS, фильтры до LIMIT и компактная выдача."""
import pytest

from amem import db, lookup, records, search
from amem.records import Item

AGENT = "model:claude"
HUMAN = "person:filipp"


@pytest.fixture
def kb(pg):
    db.prepare(pg)
    return pg


def project(ref="@project", key="project", entity_class="project", codes=None):
    return {"ref": ref, "entity_class": entity_class, "key": key,
            "label": {"ru": key}, "codes": codes or []}


def atom(ref, codes, label="Проверка", kind="fact", about=None):
    return {"ref": ref, "kind": kind, "key": ref.removeprefix("@"), "label": {"ru": label},
            "summary_plain": {"ru": label}, "codes": codes, "about": about or []}


def write(kb, *items):
    return records.commit(kb, list(items), agent=AGENT)


def refs(rows):
    return [row["ref"] for row in rows]


def test_code_exact_normalizes_query_and_returns_stable_candidates(kb):
    result = write(kb, Item("entity", project()),
                   Item("atom", atom("@b", ["Вн-45"], "Вторая")),
                   Item("atom", atom("@a", ["ВН–45"], "Первая")))

    rows = search._code_exact(kb, "ВН - 45")

    assert refs(rows) == sorted(refs(rows))
    assert len(rows) == 2
    assert [row["rank"] for row in rows] == [1, 2]
    assert all(row["source_rank"] is None for row in rows)
    assert all(set(row) == {"target", "record_id", "revision_id", "ref", "rank", "source_rank"}
               for row in rows)
    by_ref = {row["ref"]: row for row in rows}
    for revision in result.revisions[1:]:
        row = by_ref[f"atm:{revision.record_id}"]
        assert row["target"] == "atom"
        assert row["record_id"] == str(revision.record_id)
        assert row["revision_id"] == str(revision.revision_id)


def test_code_prefix_excludes_records_with_an_exact_code(kb):
    write(kb,
          Item("atom", atom("@exact", ["Z50.0214"])),
          Item("atom", atom("@both", ["Вн-45", "Вн-45-А"])),
          Item("atom", atom("@prefix", ["Вн-45-Б"])))

    exact = search._code_exact(kb, "z50.0214")
    assert len(exact) == 1
    assert search._code_exact(kb, "Z50") == []
    assert refs(search._code_prefix(kb, "Z50.")) == refs(exact)

    prefix = search._code_prefix(kb, "ВН–45")
    assert len(prefix) == 1
    prefix_id = prefix[0]["record_id"]
    assert lookup.get(kb, "atom", prefix_id)["key"] == "prefix"
    assert lookup.get(kb, "atom", search._code_exact(kb, "Вн-45")[0]["record_id"])["key"] == "both"


def test_fts_uses_russian_websearch_and_empty_query_selects_nothing(kb):
    write(kb,
          Item("atom", atom("@wind", [], "Ветровое давление")),
          Item("atom", atom("@snow", [], "Снеговая нагрузка")),
          Item("atom", atom("@concrete", [], "Прочность бетона")))

    wind = search._fts(kb, "ветрового давления")
    assert len(wind) == 1
    assert lookup.get(kb, "atom", wind[0]["record_id"])["key"] == "wind"
    assert isinstance(wind[0]["source_rank"], float)

    either = search._fts(kb, '"ветровое давление" OR "снеговая нагрузка"')
    assert {lookup.get(kb, "atom", row["record_id"])["key"] for row in either} == {"wind", "snow"}
    assert [row["rank"] for row in either] == list(range(1, len(either) + 1))
    assert search._fts(kb, "") == []
    assert search._fts(kb, "   ") == []


def test_default_and_explicit_status_filters(kb):
    statuses = ["draft", "needs_review", "rejected", "deprecated", "superseded"]
    write(kb, *[Item("atom", atom(f"@{status}", ["FLT-1"]), status=status) for status in statuses])

    default = search._code_exact(kb, "flt-1")
    assert {lookup.get(kb, "atom", row["record_id"])["status"] for row in default} == {
        "draft", "needs_review"}

    hidden = search._code_exact(kb, "FLT-1", statuses=["rejected", "deprecated"])
    assert {lookup.get(kb, "atom", row["record_id"])["status"] for row in hidden} == {
        "rejected", "deprecated"}
    assert search._code_exact(kb, "FLT-1", statuses=[]) == []


def test_target_kind_and_entity_class_filters(kb):
    write(kb,
          Item("entity", project(codes=["TYPE-1"])),
          Item("entity", project("@software", "software", "software", ["TYPE-1"])),
          Item("atom", atom("@fact", ["TYPE-1"], kind="fact")),
          Item("atom", atom("@requirement", ["TYPE-1"], kind="requirement")))

    assert len(search._code_exact(kb, "TYPE-1", target="atom")) == 2
    requirement = search._code_exact(kb, "TYPE-1", kind="requirement")
    assert len(requirement) == 1 and lookup.get(kb, "atom", requirement[0]["record_id"])["kind"] == "requirement"
    software = search._code_exact(kb, "TYPE-1", entity_class="software")
    assert len(software) == 1
    assert lookup.get(kb, "entity", software[0]["record_id"])["entity_class"] == "software"
    assert search._code_exact(kb, "TYPE-1", target="entity", kind="fact") == []
    assert search._code_exact(kb, "TYPE-1", target="atom", entity_class="project") == []


def test_filters_are_applied_before_channel_limit(kb):
    write(kb,
          *[Item("atom", atom(f"@r{i}", ["LIM-1"]), status="rejected") for i in range(51)],
          Item("atom", atom("@wanted", ["LIM-1"]), status="draft"))

    default = search._code_exact(kb, "LIM-1")
    assert len(default) == 1
    assert lookup.get(kb, "atom", default[0]["record_id"])["key"] == "wanted"

    rejected = search._code_exact(kb, "LIM-1", statuses=["rejected"])
    assert len(rejected) == 50
    assert [row["rank"] for row in rejected] == list(range(1, 51))


def test_enrich_returns_compact_card_and_optional_original_record(kb):
    result = write(kb, Item("atom", atom("@pending", ["CRD-1"], "Карточка результата"),
                            status="needs_review", review_state="pending"))
    candidate = search._code_exact(kb, "CRD-1")[0]

    compact = search._enrich(kb, [candidate])[0]
    assert set(compact) == {"ref", "revision", "label", "snippet", "status", "review_state"}
    assert compact["ref"] == candidate["ref"]
    assert compact["revision"] == 1
    assert compact["label"] == {"ru": "Карточка результата"}
    assert "Карточка результата" in compact["snippet"]
    assert compact["status"] == "needs_review"
    assert compact["review_state"] == "pending"

    full = search._enrich(kb, [candidate], include_record=True)[0]
    assert full["record"] == lookup.get(kb, "atom", result.revisions[0].record_id)
    assert set(full) == set(compact) | {"record"}
    assert "score" not in full and "source_rank" not in full and "revision_id" not in full
