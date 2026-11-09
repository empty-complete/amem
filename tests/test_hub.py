"""Задел под хаб баз: base_id в meta и provenance.origin_base у атома (спека, разд. 5)."""
import re


from amem import db, records
from amem.ids import uuid7
from amem.records import Item
from v1_support import changed, json_errors, pydantic_errors, same_database

AGENT = "model:claude"
UUID7 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def test_base_id_created_once_and_stable(pg):
    db.prepare(pg)
    first = pg.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()[0]
    assert UUID7.fullmatch(first)
    db.prepare(pg)                                   # повторный запуск не меняет идентичность
    with same_database(pg) as other:                 # и виден с другого подключения
        assert other.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()[0] == first


def test_origin_base_accepted_and_stored(pg):
    db.prepare(pg)
    origin = str(uuid7())
    result = records.commit(pg, [Item("atom", {"kind": "fact", "label": {"ru": "Переехал из хаба"},
                                               "provenance": {"origin_base": origin}, "sources": []})], agent=AGENT)
    body = pg.execute("SELECT payload FROM atom_revision WHERE id = %s",
                      (result.revisions[0].revision_id,)).fetchone()[0]
    assert body["provenance"] == {"origin_base": origin}

    # отсутствие origin_base — валидно: обычный атом без переноса
    other = records.commit(pg, [Item("atom", {"kind": "fact", "label": {"ru": "Домашний"}, "sources": []})],
                           agent=AGENT)
    body = pg.execute("SELECT payload FROM atom_revision WHERE id = %s",
                      (other.revisions[0].revision_id,)).fetchone()[0]
    assert "provenance" not in body


def test_origin_base_validated_by_schema():
    good = changed("atom_fact.yaml", lambda d: d.update(provenance={"origin_base": str(uuid7())}))
    assert pydantic_errors("AtomPayload", good) == []
    assert json_errors("AtomPayload", good) == []
    bad = changed("atom_fact.yaml", lambda d: d.update(provenance={"origin_base": "не-uuid"}))
    assert pydantic_errors("AtomPayload", bad)
    assert json_errors("AtomPayload", bad)
    # origin_base — строка-идентификатор, а не ссылка: префикс ent:/atm: не принимается
    ref = changed("atom_fact.yaml", lambda d: d.update(provenance={"origin_base": f"ent:{uuid7()}"}))
    assert pydantic_errors("AtomPayload", ref)
    assert json_errors("AtomPayload", ref)
