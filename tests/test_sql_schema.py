"""SQL сходится со схемой LinkML. SQL пишется вручную, поэтому его согласие держат эти проверки:
- перечни в CHECK совпадают с перечислениями схемы, и каждый перечень в базе либо сверяется, либо явно служебный;
- у каждого технического поля записей и у каждого поля источника есть столбец;
- формат content_hash в CHECK таблиц ревизий — тот же шаблон, что в схеме;
- список симметричных видов в индексе link_active — тот же, что в словаре rel."""
import re

import pytest

from amemo import db, packs
from v1_support import schema_attrs, schema_yaml

ENUM_COLUMNS = [
    ("atom", "status", "Status"),
    ("entity", "status", "Status"),
    ("atom_revision", "review_state", "ReviewState"),
    ("entity_revision", "review_state", "ReviewState"),
    ("changeset", "state", "ChangesetState"),
    ("activity", "kind", "ActivityKind"),
    ("status_log", "status", "Status"),
    ("template", "target", "TemplateTarget"),
    ("object", "kind", "ObjectKind"),
    ("object_status", "status", "ObjectStatus"),
    ("source", "role", "SourceRole"),
    ("source", "verdict", "SourceVerdict"),
    ("review_item", "reason", "ReviewReason"),
    ("review_item", "state", "ReviewItemState"),
    ("verification", "method", "VerificationMethod"),
    ("verification", "outcome", "VerificationOutcome"),
]
# перечни, которых нет в схеме LinkML: служебные значения базы
NOT_ENUM = {("status_log", "target"), ("search_document", "target"), ("search_code", "target"),
            ("embedding", "target"), ("review_item", "target"), ("import_history", "target"),
            ("folder_log", "target"),
            ("object_text", "text_source"),     # откуда текст страницы в кэше — деталь хранения, не модели
            ("task", "state")}     # задачи агентам — состояние службы (TaskView); kind из одного значения — не список

# поля записей схемы, которых нет в теле ревизии, → где они хранятся (у концов связи — пара столбцов)
RECORD_COLUMNS = {
    "Atom": {"id": "atom.id", "schema_version": "atom_revision.schema_version", "revision": "atom_revision.n",
             "content_hash": "atom_revision.content_hash", "status": "atom.status", "folder": "atom.folder",
             "review_state": "atom_revision.review_state", "created_at": "atom.created_at",
             "recorded_at": "atom_revision.recorded_at", "changeset": "atom_revision.changeset_id",
             "agent": "changeset.agent", "activity": "changeset.activity"},
    "Entity": {"id": "entity.id", "schema_version": "entity_revision.schema_version", "revision": "entity_revision.n",
               "content_hash": "entity_revision.content_hash", "status": "entity.status", "folder": "entity.folder",
               "review_state": "entity_revision.review_state", "created_at": "entity.created_at",
               "recorded_at": "entity_revision.recorded_at", "changeset": "entity_revision.changeset_id",
               "agent": "changeset.agent", "activity": "changeset.activity"},
    "Link": {"id": "link.id", "rel": "link.rel", "src": ("link.src_atom", "link.src_entity"),
             "dst": ("link.dst_atom", "link.dst_entity"), "note": "link.note", "qualifiers": "link.qualifiers",
             "confidence": "link.confidence", "created_at": "link.created_at", "changeset": "link.changeset_id",
             "agent": "link.agent", "retired_at": "link.retired_at"},
    "Changeset": {"id": "changeset.id", "agent": "changeset.agent", "activity": "changeset.activity",
                  "reason": "changeset.reason", "state": "changeset.state", "check_report": "changeset.check_report",
                  "created_at": "changeset.created_at"},
    "Activity": {"id": "activity.id", "kind": "activity.kind", "label": "activity.label",
                 "started_at": "activity.started_at", "ended_at": "activity.ended_at"},
    "Agent": {"id": "agent.id", "name": "agent.name"},
    "ObjectRecord": {"id": "object.id", "kind": "object.kind", "original_name": "object.original_name",
                     "media_type": "object.media_type", "format_puid": "object.format_puid", "url": "object.url",
                     "retrieved_at": "object.retrieved_at", "logical_paths": "object_path.path",
                     "versions": "object_version.object_id"},
    "ObjectVersion": {"n": "object_version.n", "digest": "object_version.digest", "size": "object_version.size",
                      "recorded_at": "object_version.recorded_at"},
}
PAYLOAD = {"Atom": "AtomPayload", "Entity": "EntityPayload", "Link": None, "Changeset": None, "Activity": None,
           "Agent": None, "ObjectRecord": None, "ObjectVersion": None}
# поля источника в теле ревизии → где они хранятся; path бывает только во входных данных
SOURCE_COLUMNS = {"object": "source.object_id", "object_version": "source.object_version",
                  "digest": "object_version.digest", "selectors": "source.selectors", "quote": "source.quote",
                  "edition": "source.edition_id", "role": "source.role"}
LITERAL = r"'([^']+)'::text"


def _check_defs(conn, table: str | None = None) -> list[tuple[str, str]]:
    """Ограничения CHECK текущей схемы: (таблица, текст определения)."""
    sql = ("SELECT t.relname, pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
           "WHERE c.contype = 'c' AND t.relnamespace = current_schema()::regnamespace")
    if table:
        return conn.execute(sql + " AND t.relname = %s", (table,)).fetchall()
    return conn.execute(sql).fetchall()


def _check_values(conn, table: str, column: str) -> set[str]:
    defs = [d for _, d in _check_defs(conn, table) if re.search(rf"\(\(?{column} = ANY", d)]
    assert len(defs) == 1, f"{table}.{column}: ждали одно ограничение-перечень, нашли {defs}"
    return set(re.findall(LITERAL, defs[0]))


@pytest.mark.parametrize("table, column, enum", ENUM_COLUMNS, ids=[f"{t}.{c}" for t, c, _ in ENUM_COLUMNS])
def test_check_lists_match_enums(pg, table, column, enum):
    db.migrate(pg)
    assert _check_values(pg, table, column) == set(schema_yaml()["enums"][enum]["permissible_values"])


def test_every_check_list_is_known(pg):
    """Новый перечень в CHECK (например, в миграции части 2.2) не останется без сверки со схемой."""
    db.migrate(pg)
    found = {(t, m) for t, d in _check_defs(pg) for m in re.findall(r"\(\(?(\w+) = ANY \(ARRAY\[", d)}
    assert found == {(t, c) for t, c, _ in ENUM_COLUMNS} | NOT_ENUM


def _columns(mapping: dict) -> set[str]:
    out = set()
    for where in mapping.values():
        out |= set(where) if isinstance(where, tuple) else {where}
    return out


@pytest.mark.parametrize("class_name", RECORD_COLUMNS)
def test_record_fields_have_columns(pg, class_name):
    """Каждое поле записи вне тела ревизии где-то хранится — новое поле схемы без столбца не пройдёт."""
    db.migrate(pg)
    fields = set(schema_attrs(class_name))
    if PAYLOAD[class_name]:
        fields -= set(schema_attrs(PAYLOAD[class_name]))
    assert fields == set(RECORD_COLUMNS[class_name])
    columns = {f"{t}.{c}" for t, c in pg.execute(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = current_schema()")}
    assert _columns(RECORD_COLUMNS[class_name]) <= columns


def test_source_fields_have_columns(pg):
    """Источник ревизии раскладывается в таблицу source — новое поле источника без столбца не пройдёт."""
    db.migrate(pg)
    assert set(schema_attrs("Source")) - {"path"} == set(SOURCE_COLUMNS)
    columns = {f"{t}.{c}" for t, c in pg.execute(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = current_schema()")}
    assert set(SOURCE_COLUMNS.values()) <= columns


@pytest.mark.parametrize("table, class_name", [("atom_revision", "Atom"), ("entity_revision", "Entity")])
def test_content_hash_check_matches_schema(pg, table, class_name):
    """Формат хэша ревизии в базе — тот же шаблон, что в схеме: хэши хранятся навсегда."""
    db.migrate(pg)
    patterns = [m.group(1) for _, d in _check_defs(pg, table)
                for m in [re.search(r"content_hash ~ '([^']+)'::text", d)] if m]
    assert patterns == [schema_attrs(class_name)["content_hash"]["pattern"]]


def test_symmetric_links_in_unique_index_match_vocab(pg):
    """Индекс link_active считает A→B и B→A одной связью ровно для симметричных видов словаря rel —
    в обоих выражениях CASE (least и greatest)."""
    db.migrate(pg)
    row = pg.execute("SELECT pg_get_indexdef(i.indexrelid) FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                     "WHERE c.relname = 'link_active' AND c.relnamespace = current_schema()::regnamespace").fetchone()
    assert row, "нет индекса link_active"
    symmetric = {c.code for c in packs.load_pack(packs.CORE_PACK).concepts if c.scheme == "rel" and c.symmetric}
    whens = row[0].split("ELSE")[:-1]
    assert len(whens) == 2, row[0]
    assert [set(re.findall(LITERAL, part)) for part in whens] == [symmetric, symmetric]


def test_trigger_functions_use_amemo_names(pg):
    """Триггерные функции — amemo_*: старых имён atomdb_* в базе не остаётся."""
    db.migrate(pg)
    names = {r[0] for r in pg.execute(
        "SELECT proname FROM pg_proc WHERE pronamespace = current_schema()::regnamespace")}
    assert {n for n in names if n.startswith("atomdb_")} == set()
    assert {"amemo_forbid_change", "amemo_revision_review", "amemo_link_retire", "amemo_source_check"} <= names
