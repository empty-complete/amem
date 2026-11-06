"""Проекция atom_property: заполняется при записи, перестраивается, совпадает с телами."""
from amem import db, records
from amem.records import Item
from check_support import atom, entity, value


def _rows(pg):
    return set(pg.execute("SELECT r.atom_id, p.property FROM atom_property p "
                          "JOIN atom_current r ON r.id = p.revision_id").fetchall())


def _expected(pg):
    rows = pg.execute("SELECT atom_id, payload FROM atom_current").fetchall()
    return {(atom_id, v["property"]) for atom_id, payload in rows
            for v in (payload.get("content") or {}).get("values") or []}


def _param(label, *values):
    body = atom(label, kind="parameter", sources=[], content={"values": list(values)})
    body["basis"] = "author"
    return body


def test_projection_follows_current_revision(pg):
    db.prepare(pg)
    body = _param("Масса и длина", value("mass", 3, "kg"), value("length", 2, "m"))
    done = records.commit(pg, [Item("atom", body)], agent="person:alice")
    rid = done.revisions[0].record_id
    assert _rows(pg) == {(rid, "mass"), (rid, "length")} == _expected(pg)
    body2 = {**body, "content": {"values": [value("mass", 4, "kg")]}}
    records.commit(pg, [Item("atom", body2, record_id=rid)], agent="person:alice")
    assert _rows(pg) == {(rid, "mass")} == _expected(pg)


def test_repeated_property_is_one_row(pg):
    db.prepare(pg)
    body = _param("Две массы", value("mass", 3, "kg"), value("mass", 5, "kg"))
    rid = records.commit(pg, [Item("atom", body)], agent="person:alice").revisions[0].record_id
    assert _rows(pg) == {(rid, "mass")}


def test_atom_without_values_has_no_rows(pg):
    db.prepare(pg)
    body = atom("Без величин", sources=[])
    body["basis"] = "author"
    records.commit(pg, [Item("atom", body)], agent="person:alice")
    assert _rows(pg) == set()


def test_rebuild_projections_is_idempotent(pg):
    db.prepare(pg)
    records.commit(pg, [Item("atom", _param("Масса", value("mass", 3, "kg")))], agent="person:alice")
    pg.execute("DELETE FROM atom_property")
    assert records.rebuild_projections(pg) == 1
    assert _rows(pg) == _expected(pg)
    records.rebuild_projections(pg)
    assert _rows(pg) == _expected(pg)


def test_rebuild_drops_stale_property_rows(pg):
    db.prepare(pg)
    rid = records.commit(pg, [Item("atom", _param("Масса", value("mass", 3, "kg")))],
                         agent="person:alice").revisions[0].record_id
    rev = pg.execute("SELECT id FROM atom_current WHERE atom_id = %s", (rid,)).fetchone()[0]
    pg.execute("INSERT INTO atom_property (revision_id, property) VALUES (%s, 'stale')", (rev,))
    records.rebuild_projections(pg)
    assert _rows(pg) == {(rid, "mass")}


def test_rebuild_adds_missing_about_and_derived(pg):
    """atom_about и atom_derived защищены от удаления: перестройка только добавляет недостающие строки."""
    db.prepare(pg)
    done = records.commit(pg, [Item("entity", entity("@doc")),
                               Item("atom", {**_param("@base", value("mass", 3, "kg")), "about": ["@doc"]}),
                               Item("atom", {**_param("@calc", value("mass", 6, "kg")),
                                             "derived_from": ["@base"]})], agent="person:alice")
    about = set(pg.execute("SELECT * FROM atom_about").fetchall())
    derived = set(pg.execute("SELECT * FROM atom_derived").fetchall())
    assert len(about) == 1 and len(derived) == 1
    # имитация базы, где строки проекции потеряны: снять защиту только на время подготовки
    for table in ("atom_about", "atom_derived"):
        pg.execute(f"ALTER TABLE {table} DISABLE TRIGGER {table}_immutable")
        pg.execute(f"DELETE FROM {table}")
        pg.execute(f"ALTER TABLE {table} ENABLE TRIGGER {table}_immutable")
    assert records.rebuild_projections(pg) == 2
    assert set(pg.execute("SELECT * FROM atom_about").fetchall()) == about
    assert set(pg.execute("SELECT * FROM atom_derived").fetchall()) == derived
    records.rebuild_projections(pg)                                    # повтор не дублирует и не падает
    assert set(pg.execute("SELECT * FROM atom_about").fetchall()) == about
    assert len(done.revisions) == 3
