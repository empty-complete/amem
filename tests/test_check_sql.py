"""Миграция 0006: активные шаблоны, очередь проверки, вердикты и сброс кэша текста docx/xlsx."""
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest

from amem import db, packs
from amem.ids import uuid7
from amem.records import Item, commit

AGENT = "model:claude"
HUMAN = "person:reviewer"
EXAMPLE = Path(__file__).parent / "packs" / "example"


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture
def kb(pg):
    db.prepare(pg)
    return pg


def _atom(kb, key="note.one"):
    """Атом с одной ревизией: (id записи, id ревизии)."""
    result = commit(kb, [Item("atom", {"ref": "@a", "kind": "fact", "key": key,
                                       "label": {"ru": "Давление воздуха на уровне моря"}})], agent=AGENT)
    rev = result.revisions[0]
    return rev.record_id, rev.revision_id


def _item(kb, rev, record, reason="semantic", **extra):
    values = {"id": uuid7(), "target": "atom", "record_id": record, "atom_revision_id": rev, "reason": reason,
              "state": "queued", "created_at": _now(), "created_by": AGENT, **extra}
    kb.execute(f"INSERT INTO review_item ({', '.join(values)}) VALUES ({', '.join(['%s'] * len(values))})",
               list(values.values()))
    return values["id"]


def _set(kb, item, **cols):
    sets = ", ".join(f"{c} = %s" for c in cols)
    kb.execute(f"UPDATE review_item SET {sets} WHERE id = %s", [*cols.values(), item])


def _claim(kb, item):
    _set(kb, item, state="claimed", claimed_by=AGENT, claimed_until=_now() + timedelta(minutes=5))


def _release(kb, item):
    _set(kb, item, state="queued", claimed_by=None, claimed_until=None)


def _close(kb, item, state="done"):
    _set(kb, item, state=state, claimed_by=None, claimed_until=None, closed_at=_now())


def test_tables_exist_and_active_templates_filled(kb):
    names = {r[0] for r in kb.execute("SELECT table_name FROM information_schema.tables "
                                      "WHERE table_schema = current_schema()")}
    assert {"template_active", "review_item", "verification"} <= names
    active = dict(kb.execute("SELECT code, version FROM template_active").fetchall())
    core = {t.code: t.version for t in packs.load_packs([packs.CORE_PACK])[0].templates}
    assert {"has_label", "has_source", "has_value", "decision"} <= set(active)
    assert all(active[code] == core[code] for code in ("has_label", "has_source", "has_value", "decision"))


def test_active_templates_follow_loaded_packs(kb, monkeypatch):
    monkeypatch.setenv("AMEM_PACKS", str(EXAMPLE))
    db.load_vocab(kb)
    assert kb.execute("SELECT count(*) FROM template_active WHERE code = 'idea'").fetchone()[0] == 1
    monkeypatch.delenv("AMEM_PACKS")
    db.load_vocab(kb)
    assert kb.execute("SELECT count(*) FROM template_active WHERE code = 'idea'").fetchone()[0] == 0
    assert kb.execute("SELECT count(*) FROM template WHERE code = 'idea'").fetchone()[0] >= 1


def test_item_of_foreign_revision_is_refused(kb):
    record, _ = _atom(kb)
    _, other_rev = _atom(kb, "note.two")
    with pytest.raises(psycopg.errors.RaiseException, match="amem:"):
        _item(kb, other_rev, record)


def test_entity_item_checks_record_of_revision(kb):
    first, second = (commit(kb, [Item("entity", {"ref": "@e", "entity_class": "document", "key": key,
                                                 "label": {"ru": "Справочник величин"}})], agent=AGENT).revisions[0]
                     for key in ("doc.one", "doc.two"))
    values = {"target": "entity", "reason": "semantic", "state": "queued", "created_at": _now(), "created_by": AGENT}

    def insert(record, rev):
        row = {"id": uuid7(), "record_id": record, "entity_revision_id": rev, **values}
        kb.execute(f"INSERT INTO review_item ({', '.join(row)}) VALUES ({', '.join(['%s'] * len(row))})",
                   list(row.values()))

    with pytest.raises(psycopg.errors.RaiseException, match="amem:"):
        insert(first.record_id, second.revision_id)
    insert(second.record_id, second.revision_id)


@pytest.mark.parametrize("state", ["claimed", "done"])
def test_item_must_start_queued(kb, state):
    record, rev = _atom(kb)
    extra = ({"claimed_by": AGENT, "claimed_until": _now() + timedelta(minutes=5)} if state == "claimed"
             else {"closed_at": _now()})
    with pytest.raises(psycopg.errors.RaiseException, match="amem:"):
        _item(kb, rev, record, state=state, **extra)


def test_allowed_transitions(kb):
    record, rev = _atom(kb)
    item = _item(kb, rev, record)
    _claim(kb, item)
    _release(kb, item)
    _claim(kb, item)
    _claim(kb, item)                         # продление срока
    _close(kb, item)
    assert kb.execute("SELECT state FROM review_item WHERE id = %s", (item,)).fetchone()[0] == "done"


@pytest.mark.parametrize("closed, then", [("done", "queued"), ("obsolete", "claimed")])
def test_closed_item_stays_closed(kb, closed, then):
    record, rev = _atom(kb)
    item = _item(kb, rev, record)
    _close(kb, item, closed)
    extra = ({"claimed_by": AGENT, "claimed_until": _now() + timedelta(minutes=5)} if then == "claimed" else {})
    with pytest.raises(psycopg.errors.RaiseException, match="amem:"):
        _set(kb, item, state=then, closed_at=None, **extra)


def test_queued_cannot_stay_queued(kb):
    record, rev = _atom(kb)
    item = _item(kb, rev, record)
    with pytest.raises(psycopg.errors.RaiseException, match="amem:"):
        _set(kb, item, state="queued")


@pytest.mark.parametrize("column, value", [("reason", "audit"), ("details", '{"x": 1}'),
                                           ("created_at", datetime(2020, 1, 1, tzinfo=timezone.utc))])
def test_item_body_cannot_change(kb, column, value):
    record, rev = _atom(kb)
    item = _item(kb, rev, record)
    with pytest.raises(psycopg.errors.RaiseException, match="amem:"):
        _set(kb, item, **{column: value})


@pytest.mark.parametrize("sql", ["DELETE FROM review_item", "TRUNCATE review_item CASCADE",
                                 "DELETE FROM verification", "TRUNCATE verification"])
def test_delete_and_truncate_are_forbidden(kb, sql):
    record, rev = _atom(kb)
    item = _item(kb, rev, record)
    _verdict(kb, item)
    with pytest.raises(psycopg.errors.RaiseException, match="amem:"):
        kb.execute(sql)


def test_open_item_is_unique_per_revision_and_reason(kb):
    record, rev = _atom(kb)
    first = _item(kb, rev, record)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _item(kb, rev, record)
    _item(kb, rev, record, reason="warning")             # другая причина — другой пункт
    _close(kb, first)
    _item(kb, rev, record)                               # прежний закрыт — можно поставить снова


def _verdict(kb, item, **extra):
    values = {"id": uuid7(), "review_item_id": item, "method": "llm_judge", "outcome": "confirmed",
              "confidence": 0.9, "agent": AGENT, "created_at": _now(), **extra}
    kb.execute(f"INSERT INTO verification ({', '.join(values)}) VALUES ({', '.join(['%s'] * len(values))})",
               list(values.values()))
    return values["id"]


def test_verification_constraints(kb):
    record, rev = _atom(kb)
    item = _item(kb, rev, record)
    with pytest.raises(psycopg.errors.CheckViolation):
        _verdict(kb, item, confidence=None)                              # llm_judge без уверенности
    with pytest.raises(psycopg.errors.CheckViolation):
        _verdict(kb, item, confidence=1.5)
    with pytest.raises(psycopg.errors.CheckViolation):
        _verdict(kb, item, method="human", confidence=None)              # человек — только person:
    kb.execute("INSERT INTO agent (id) VALUES (%s)", (HUMAN,))
    with pytest.raises(psycopg.errors.CheckViolation):
        _verdict(kb, item, agent=HUMAN)                                  # person: — только человек
    verdict = _verdict(kb, item, method="human", confidence=None, agent=HUMAN)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _verdict(kb, item)                                               # один вердикт на пункт
    with pytest.raises(psycopg.errors.RaiseException, match="amem:"):
        kb.execute("UPDATE verification SET note = 'позже' WHERE id = %s", (verdict,))


def test_migration_drops_text_cache_of_docx_and_xlsx(pg, tmp_path, monkeypatch):
    for old in sorted(db.SQL_DIR.glob("000[1-5]_*.sql")):
        shutil.copy(old, tmp_path / old.name)
    real = db.SQL_DIR
    monkeypatch.setattr(db, "SQL_DIR", tmp_path)
    assert db.migrate(pg)[-1] == "0005_search.sql"
    digests = {}
    for i, name in enumerate(["a.docx", "b.xlsx", "c.pdf", "D.XLSM"]):
        oid, digest = uuid7(), f"sha256:{i:064x}"
        digests[name] = digest
        pg.execute("INSERT INTO object (id, kind, original_name, created_at) VALUES (%s, 'file', %s, now())",
                   (oid, name))
        pg.execute("INSERT INTO object_version (object_id, kind, n, digest, size, recorded_at) "
                   "VALUES (%s, 'file', 1, %s, 0, now())", (oid, digest))
        pg.execute("INSERT INTO object_text (digest, page, text) VALUES (%s, 0, '')", (digest,))
    # у docx есть и настоящая страница: сброс трогает только page = 0
    pg.execute("INSERT INTO object_text (digest, page, text) VALUES (%s, 1, 'Давление')", (digests["a.docx"],))
    monkeypatch.setattr(db, "SQL_DIR", real)
    assert db.migrate(pg)[0] == "0006_check.sql"          # дальше — следующие миграции
    left = {r[0] for r in pg.execute("SELECT digest FROM object_text WHERE page = 0")}
    assert left == {digests["c.pdf"]}
    assert pg.execute("SELECT text FROM object_text WHERE page = 1").fetchall() == [("Давление",)]
