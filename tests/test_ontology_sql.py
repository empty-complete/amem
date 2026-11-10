"""Миграция 0007: журнал import_history и проекция atom_property."""
import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

from amemo import db
from amemo.ids import uuid7
from amemo.records import Item, commit

AGENT = "model:claude"


@pytest.fixture
def kb(pg):
    db.prepare(pg)
    return pg


def _revision(kb):
    """Атом с одной ревизией: (id набора изменений, id ревизии)."""
    result = commit(kb, [Item("atom", {"ref": "@a", "kind": "fact", "key": "note.one",
                                       "label": {"ru": "Давление воздуха на уровне моря"}})], agent=AGENT)
    return result.changeset_id, result.revisions[0].revision_id


def _history(kb, cs, id=None, origin=None, record=None, n=1):
    row = (id or uuid7(), cs, "atom", record or uuid7(), origin or uuid7(), n, "sha256-c1:" + "0" * 64,
           Jsonb({}), AGENT)
    kb.execute("INSERT INTO import_history (id, changeset_id, target, record_id, origin_base, n, content_hash, "
               "payload, recorded_at, agent) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), %s) RETURNING id",
               row)
    return row


def test_import_history_is_append_only(kb):
    cs, _ = _revision(kb)
    hid = _history(kb, cs)[0]
    with pytest.raises(psycopg.errors.RaiseException, match="amemo:"):
        kb.execute("UPDATE import_history SET agent = 'model:other' WHERE id = %s", (hid,))
    with pytest.raises(psycopg.errors.RaiseException, match="amemo:"):
        kb.execute("DELETE FROM import_history WHERE id = %s", (hid,))


def test_import_history_checks(kb):
    cs, _ = _revision(kb)
    with pytest.raises(psycopg.errors.CheckViolation):
        _history(kb, cs, id=uuid.uuid4())                               # id — только UUIDv7
    origin, record = uuid7(), uuid7()
    _history(kb, cs, origin=origin, record=record, n=1)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _history(kb, cs, origin=origin, record=record, n=1)             # ревизия чужой базы — один раз
    _history(kb, cs, origin=uuid7(), record=record, n=1)                # та же запись из другой базы — можно
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _history(kb, uuid7())                                           # набор изменений — настоящий


def test_atom_property_is_rebuildable_projection(kb):
    """Ключ — ревизия; код величины свободный; проекцию можно стереть — триггеров неизменяемости нет."""
    _, rev = _revision(kb)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        kb.execute("INSERT INTO atom_property (revision_id, property) VALUES (%s, 'mass')", (uuid7(),))
    kb.execute("INSERT INTO atom_property (revision_id, property) VALUES (%s, 'not_in_vocab')", (rev,))
    with pytest.raises(psycopg.errors.UniqueViolation):
        kb.execute("INSERT INTO atom_property (revision_id, property) VALUES (%s, 'not_in_vocab')", (rev,))
    kb.execute("DELETE FROM atom_property")
    kb.execute("TRUNCATE atom_property")
