"""Поисковая проекция меняется атомарно с текущей ревизией и полностью перестраивается."""
import pytest

from amem import db, lookup, records, search
from amem.records import Item

AGENT = "model:claude"
HUMAN = "person:filipp"


@pytest.fixture
def kb(pg):
    db.prepare(pg)
    return pg


def entity(**extra):
    return {"ref": "@project", "entity_class": "project", "key": "project",
            "label": {"ru": "Проект"}, "codes": ["ПР-1"], **extra}


def atom(**extra):
    return {"ref": "@fact", "kind": "fact", "key": "fact",
            "label": {"ru": "Ветровое давление"}, "summary_plain": {"ru": "Нормативное значение"},
            "codes": ["Вн-45", "Z50.0214"], "about": ["@project"], **extra}


def base(kb):
    return records.commit(kb, [Item("entity", entity()), Item("atom", atom())], agent=AGENT)


def projection(kb, target="atom"):
    return kb.execute(
        "SELECT record_id, revision_id, content_hash, document, codes, updated_at "
        "FROM search_document WHERE target = %s", (target,)).fetchone()


def test_commit_projects_atom_and_entity(kb):
    result = base(kb)
    for item in result.revisions:
        row = projection(kb, item.target)
        assert str(row[0]) == str(item.record_id)
        assert str(row[1]) == str(item.revision_id)
        assert row[2] == item.content_hash
    atom_row = projection(kb)
    assert "Ветровое давление" in atom_row[3]
    assert atom_row[4] == ["z50.0214", "вн-45"]
    assert {r[0] for r in kb.execute("SELECT code FROM search_code WHERE target = 'atom'")} == set(atom_row[4])
    assert kb.execute("SELECT search_vector @@ to_tsquery('russian', 'ветрового') "
                      "FROM search_document WHERE target = 'atom'").fetchone()[0]
    assert projection(kb, "entity")[4] == ["пр-1"]


def test_pending_does_not_replace_current_until_accepted(kb):
    result = base(kb)
    record_id = result.revisions[1].record_id
    changed = {key: value for key, value in atom().items() if key != "ref"}
    changed.update(label={"ru": "Снеговая нагрузка"}, codes=["СН-1"], about=["ent:project"])
    pending = records.commit(kb, [Item("atom", changed, record_id=record_id, review_state="pending")], agent=AGENT)
    assert projection(kb)[0:2] == (record_id, result.revisions[1].revision_id)
    assert "Ветровое давление" in projection(kb)[3]
    records.decide(kb, "atom", pending.revisions[0].revision_id, True, agent=HUMAN)
    assert projection(kb)[0:2] == (record_id, pending.revisions[0].revision_id)
    assert "Снеговая нагрузка" in projection(kb)[3]
    assert projection(kb)[4] == ["сн-1"]


def test_declined_revision_keeps_previous_projection(kb):
    result = base(kb)
    record_id = result.revisions[1].record_id
    changed = {key: value for key, value in atom().items() if key != "ref"}
    changed.update(label={"ru": "Отклонённый текст"}, about=["ent:project"])
    pending = records.commit(kb, [Item("atom", changed, record_id=record_id, review_state="pending")], agent=AGENT)
    records.decide(kb, "atom", pending.revisions[0].revision_id, False, agent=HUMAN)
    assert projection(kb)[1] == result.revisions[1].revision_id
    assert projection(kb)[3].startswith("Ветровое давление")


def test_declined_new_record_leaves_no_search_projection(kb):
    pending = records.commit(kb, [Item("atom", atom(about=[]), review_state="pending")], agent=AGENT)
    assert projection(kb) is not None
    records.decide(kb, "atom", pending.revisions[0].revision_id, False, agent=HUMAN)
    assert projection(kb) is None
    assert kb.execute("SELECT count(*) FROM search_code").fetchone()[0] == 0
    assert lookup.history(kb, "atom", pending.revisions[0].record_id)[0]["n"] == 1


def test_status_change_does_not_rewrite_revision_projection(kb):
    result = base(kb)
    before = projection(kb)
    records.set_status(kb, "atom", result.revisions[1].record_id, "verified", agent=HUMAN)
    assert projection(kb) == before
    assert lookup.get(kb, "atom", result.revisions[1].record_id)["status"] == "verified"


def snapshot(kb):
    return kb.execute(
        "SELECT target, record_id, revision_id, content_hash, document, search_vector, codes, updated_at "
        "FROM search_document ORDER BY target, record_id").fetchall()


def test_rebuild_restores_exact_projection_and_is_idempotent(kb):
    base(kb)
    expected = snapshot(kb)
    revisions = kb.execute("SELECT count(*) FROM atom_revision").fetchone()[0]
    kb.execute("UPDATE search_document SET document = 'испорчено' WHERE target = 'atom'")
    kb.execute("DELETE FROM search_code WHERE target = 'entity'")
    assert search.rebuild_search(kb) == 2
    assert snapshot(kb) == expected
    assert search.rebuild_search(kb) == 2
    assert snapshot(kb) == expected
    assert kb.execute("SELECT count(*) FROM atom_revision").fetchone()[0] == revisions


def test_projection_failure_rolls_back_whole_changeset(kb, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("проекция сломана")

    monkeypatch.setattr(search, "refresh_record", broken)
    with pytest.raises(RuntimeError, match="проекция сломана"):
        base(kb)
    assert kb.execute("SELECT count(*) FROM changeset").fetchone()[0] == 0
    assert kb.execute("SELECT count(*) FROM atom").fetchone()[0] == 0
    assert kb.execute("SELECT count(*) FROM search_document").fetchone()[0] == 0


def test_rejected_changeset_has_no_projection(kb):
    records.reject(kb, agent=AGENT, check_report={"level": 1})
    assert kb.execute("SELECT count(*) FROM search_document").fetchone()[0] == 0
