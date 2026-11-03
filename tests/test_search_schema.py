"""Техническое хранилище поиска: проекции, вектора и журналы полезности."""
import psycopg
import pytest

from amem import db, ids


TABLES = {"search_document", "search_code", "embedding_model", "embedding",
          "retrieval", "retrieval_item", "atom_use"}


def test_search_storage_and_vector_exist(pg):
    db.migrate(pg)
    found = {r[0] for r in pg.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")}
    assert TABLES <= found
    assert pg.execute("SELECT vector_dims('[0,1,0]'::halfvec)").fetchone()[0] == 3


def test_search_indexes_have_expected_access_methods(pg):
    db.migrate(pg)
    rows = pg.execute(
        "SELECT c.relname, pg_get_indexdef(i.indexrelid) FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indexrelid "
        "WHERE c.relnamespace = current_schema()::regnamespace").fetchall()
    defs = {name: definition for name, definition in rows}
    assert "USING gin" in defs["search_document_fts"]
    assert "search_vector" in defs["search_document_fts"]
    assert "USING gin" in defs["search_document_codes"]
    assert "USING btree" in defs["search_code_exact"]
    assert "text_pattern_ops" in defs["search_code_prefix"]
    for dims in (384, 1024):
        definition = defs[f"embedding_hnsw_{dims}"]
        assert "USING hnsw" in definition
        assert f"halfvec({dims})" in definition
        assert "halfvec_cosine_ops" in definition
        assert f"dims = {dims}" in definition


def test_only_one_active_embedding_model(pg):
    db.migrate(pg)
    for n, active in ((1, True), (2, False)):
        pg.execute(
            "INSERT INTO embedding_model (id, name, version, dims, backend, active, created_at) "
            "VALUES (%s, 'test', %s, 384, 'fake', %s, now())",
            (ids.uuid7(), str(n), active))
    with pytest.raises(psycopg.errors.UniqueViolation):
        with pg.transaction():
            pg.execute(
                "INSERT INTO embedding_model (id, name, version, dims, backend, active, created_at) "
                "VALUES (%s, 'test', '3', 384, 'fake', true, now())", (ids.uuid7(),))


def test_usefulness_constraints_and_immutable_trigger_exist(pg):
    db.migrate(pg)
    rank_checks = pg.execute(
        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
        "WHERE t.relnamespace = current_schema()::regnamespace AND t.relname = 'retrieval_item' "
        "AND c.contype = 'c'").fetchall()
    assert any("rank" in definition and "0" in definition for (definition,) in rank_checks)
    unique_defs = pg.execute(
        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
        "WHERE t.relnamespace = current_schema()::regnamespace AND t.relname = 'atom_use' "
        "AND c.contype = 'u'").fetchall()
    assert any("activity" in definition and "atom_id" in definition for (definition,) in unique_defs)
    triggers = {r[0] for r in pg.execute(
        "SELECT tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
        "WHERE c.relnamespace = current_schema()::regnamespace AND c.relname = 'atom_use' AND NOT t.tgisinternal")}
    assert {"atom_use_immutable", "atom_use_no_truncate"} <= triggers
