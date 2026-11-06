"""Миграции SQL, загрузка словарей и шаблонов, продолжение счётчика id, защита истории — на PostgreSQL 18 и 16."""
import shutil
import threading
import unicodedata
import uuid

import psycopg
import pytest

from amem import db, ids, packs
from v1_support import same_database

MIGRATIONS = ["0001_core.sql", "0002_objects.sql", "0003_packs.sql", "0004_hub.sql", "0005_search.sql",
              "0006_check.sql", "0007_ontology.sql", "0008_folders.sql"]


def test_migration_files_are_listed():
    """Новая миграция — сюда же: так её применение проверяют все тесты ниже."""
    assert sorted(p.name for p in db.SQL_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")) == MIGRATIONS


def test_migrate_applies_once(pg):
    assert db.migrate(pg) == MIGRATIONS
    assert db.migrate(pg) == []
    names = [r[0] for r in pg.execute("SELECT name FROM schema_migrations ORDER BY name")]
    assert names == MIGRATIONS


def test_migrate_needs_utf8_database():
    """База не в UTF8 отвергается до первой миграции, с понятной причиной: иначе упал бы уже 0001 на первой кириллице."""
    class Conn:
        autocommit = True
        info = type("Info", (), {"parameter_status": lambda _, name: "SQL_ASCII"})()
        executed: list = []

        def execute(self, sql, params=None):
            self.executed.append(sql)

    conn = Conn()
    with pytest.raises(db.MigrationError, match="кодировке UTF8, а не SQL_ASCII"):
        db.migrate(conn)
    assert conn.executed == []


def test_changed_migration_is_refused(pg, tmp_path, monkeypatch):
    sql_dir = tmp_path / "sql"
    shutil.copytree(db.SQL_DIR, sql_dir)
    monkeypatch.setattr(db, "SQL_DIR", sql_dir)
    db.migrate(pg)
    path = sql_dir / "0001_core.sql"
    path.write_text(path.read_text(encoding="utf-8") + "\n-- правка задним числом\n", encoding="utf-8")
    with pytest.raises(db.MigrationError, match="0001_core.sql: файл изменён"):
        db.migrate(pg)


def _concept_count():
    return len(packs.service_concepts()) + sum(len(p.concepts) for p in packs.load_packs())


def _template_count():
    return sum(len(p.templates) for p in packs.load_packs())


def test_load_vocab_fills_concepts_and_templates(pg):
    db.migrate(pg)
    db.load_vocab(pg)
    db.load_vocab(pg)                                   # повторно — без ошибок и без дублей
    assert pg.execute("SELECT count(*) FROM concept").fetchone()[0] == _concept_count()
    assert pg.execute("SELECT count(*) FROM template").fetchone()[0] == _template_count()
    about = pg.execute("SELECT data FROM concept WHERE scheme = 'rel' AND code = 'about'").fetchone()[0]
    assert about["pairs"] == ["atom>entity"] and about["via_field"] == "about"
    origins = dict(pg.execute("SELECT scheme, min(origin) FROM concept GROUP BY scheme").fetchall())
    assert origins["kind"] == "core" and origins["status"] == "schema"


def test_pack_wins_over_agent_concept(pg):
    db.migrate(pg)
    pg.execute("INSERT INTO concept (scheme, code, data, origin, updated_at) VALUES "
               "('kind', 'fact', '{\"scheme\": \"kind\"}', 'agent', now())")
    db.load_vocab(pg)
    data, origin = pg.execute("SELECT data, origin FROM concept WHERE scheme = 'kind' AND code = 'fact'").fetchone()
    assert origin == "core" and data["label"]["ru"] == "факт"


def test_template_changed_without_new_version_is_refused(pg, monkeypatch):
    db.migrate(pg)
    db.load_vocab(pg)
    loaded = packs.load_packs()
    core = next(p for p in loaded if p.name == "core")
    core.templates = [t.model_copy(update={"description": None}) if t.code == "has_label" else t
                      for t in core.templates]
    monkeypatch.setattr(packs, "load_packs", lambda: loaded)
    with pytest.raises(db.MigrationError, match="шаблон has_label 1.0.0: уже загружен с другим содержимым"):
        db.load_vocab(pg)


def test_seed_ids_continues_after_latest_id(pg, monkeypatch):
    monkeypatch.setattr(ids, "_last_ms", ids._last_ms)      # вернуть счётчик после теста
    monkeypatch.setattr(ids, "_seq", ids._seq)
    db.prepare(pg)
    future = uuid.UUID(int=ids.uuid7().int + (10 * 24 * 3600 * 1000 << 80))   # id на 10 дней вперёд
    pg.execute("INSERT INTO agent (id) VALUES ('model:claude')")
    pg.execute("INSERT INTO changeset (id, agent, state, created_at) VALUES (%s, 'model:claude', 'approved', now())",
               (future,))
    db.seed_ids(pg)
    assert ids.uuid7() > future


def test_prepare_is_committed_and_visible(pg):
    db.prepare(pg)
    with same_database(pg) as other:
        assert other.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == len(MIGRATIONS)
        assert other.execute("SELECT count(*) FROM concept").fetchone()[0] == _concept_count()


def test_write_functions_need_autocommit(pg):
    with same_database(pg) as plain:                    # psycopg по умолчанию — без autocommit
        with pytest.raises(db.MigrationError, match="autocommit"):
            db.migrate(plain)


def test_concurrent_migrations_apply_once(pg):
    results, errors = [], []

    def run():
        try:
            with same_database(pg, autocommit=True) as conn:
                results.append(db.migrate(conn))
        except Exception as e:                                  # noqa: BLE001 — ошибку потока проверяет тест
            errors.append(e)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert sorted(results) == [[], MIGRATIONS]


def test_missing_migration_file_is_refused(pg, tmp_path, monkeypatch):
    db.migrate(pg)
    monkeypatch.setattr(db, "SQL_DIR", tmp_path)                 # код «старее» базы
    with pytest.raises(db.MigrationError, match="нет в коде: 0001_core.sql"):
        db.migrate(pg)


PROTECTED = ["entity_revision", "atom_revision", "link", "changeset", "status_log", "atom_about", "atom_derived",
             "template", "object", "object_path", "object_version", "object_status", "source",
             "review_item", "verification", "import_history", "folder_log"]


@pytest.mark.parametrize("table", PROTECTED)
def test_truncate_is_forbidden(pg, table):
    db.migrate(pg)
    with pytest.raises(psycopg.errors.RaiseException, match=f"amem: TRUNCATE в таблице {table} запрещено"):
        pg.execute(f"TRUNCATE {table} CASCADE")


def _changeset_and_atom(pg):
    db.load_vocab(pg)                        # kind/entity_class/rel — внешние ключи на concept
    pg.execute("INSERT INTO agent (id) VALUES ('model:claude')")
    cs, atom = ids.uuid7(), ids.uuid7()
    pg.execute("INSERT INTO changeset (id, agent, state, created_at) VALUES (%s, 'model:claude', 'approved', now())",
               (cs,))
    pg.execute("INSERT INTO atom (id, kind, status, created_at, status_changed_at) "
               "VALUES (%s, 'fact', 'draft', now(), now())", (atom,))
    return cs, atom


def test_ids_must_be_uuid7(pg):
    db.migrate(pg)
    _changeset_and_atom(pg)
    with pytest.raises(psycopg.errors.CheckViolation):
        pg.execute("INSERT INTO changeset (id, agent, state, created_at) VALUES (%s, 'model:claude', 'approved', now())",
                   (uuid.uuid4(),))


def test_review_decision_needs_reviewer_on_insert(pg):
    db.migrate(pg)
    cs, atom = _changeset_and_atom(pg)
    with pytest.raises(psycopg.errors.CheckViolation):
        pg.execute("INSERT INTO atom_revision (id, atom_id, n, schema_version, payload, content_hash, changeset_id, "
                   "recorded_at, review_state) VALUES (%s, %s, 1, 'amem.atom/1', '{}', %s, %s, now(), 'accepted')",
                   (ids.uuid7(), atom, "sha256-c1:" + "0" * 64, cs))


def test_every_uuid_id_is_checked_for_uuid7(pg):
    """У каждой таблицы с id uuid — CHECK UUIDv7: один чужой id остановил бы сервер в seed_ids."""
    db.migrate(pg)
    tables = [r[0] for r in pg.execute(
        "SELECT c.table_name FROM information_schema.columns c JOIN information_schema.tables t "
        "ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
        "WHERE c.table_schema = current_schema() AND c.column_name = 'id' AND c.data_type = 'uuid' "
        "AND t.table_type = 'BASE TABLE' ORDER BY c.table_name")]
    checked = {r[0] for r in pg.execute(
        "SELECT t.relname FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
        "WHERE c.contype = 'c' AND t.relnamespace = current_schema()::regnamespace "
        "AND pg_get_constraintdef(c.oid) LIKE '%(id)::text ~ ''^[0-9a-f]{8}-[0-9a-f]{4}-7%'")}
    assert {"object", "object_status", "source"} <= set(tables)
    assert set(tables) - checked == set()


DIGEST = "sha256:" + "ab" * 32
NFD = unicodedata.normalize("NFD", "й.pdf")


def _objects(pg) -> dict:
    """Файл с путём, версией, текстом и отметкой; страница сайта и переписка с версией; файл и страница сайта без
    версий; ревизии атома и сущности с источником — строки, на которых проверяются ограничения таблиц объектов."""
    cs, atom = _changeset_and_atom(pg)
    world = {"file": ids.uuid7(), "web": ids.uuid7(), "message": ids.uuid7(), "bare": ids.uuid7(),
             "web_bare": ids.uuid7(), "revision": ids.uuid7(), "entity": ids.uuid7(), "entity_revision": ids.uuid7()}
    pg.execute("INSERT INTO object (id, kind, original_name, created_at) VALUES (%s, 'file', 'a.pdf', now())",
               (world["file"],))
    pg.execute("INSERT INTO object (id, kind, original_name, created_at) VALUES (%s, 'file', 'b.pdf', now())",
               (world["bare"],))
    pg.execute("INSERT INTO object (id, kind, url, retrieved_at, created_at) "
               "VALUES (%s, 'web', 'https://example.org/a', '2026-10-25', now())", (world["web"],))
    pg.execute("INSERT INTO object (id, kind, url, retrieved_at, created_at) "
               "VALUES (%s, 'web', 'https://example.org/c', '2026-10-25', now())", (world["web_bare"],))
    pg.execute("INSERT INTO object (id, kind, original_name, created_at) VALUES (%s, 'message', 'Письмо', now())",
               (world["message"],))
    pg.execute("INSERT INTO object_path (path, object_id, added_at) VALUES ('docs/a.pdf', %s, now())", (world["file"],))
    pg.execute("INSERT INTO object_version (object_id, kind, n, digest, size, recorded_at) "
               "VALUES (%s, 'file', 1, %s, 3, now())", (world["file"], DIGEST))
    for kind in ("web", "message"):
        pg.execute("INSERT INTO object_version (object_id, kind, n, recorded_at) VALUES (%s, %s, 1, now())",
                   (world[kind], kind))
    pg.execute("INSERT INTO object_text (digest, page, text) VALUES (%s, 1, 'страница')", (DIGEST,))
    pg.execute("INSERT INTO object_status (id, object_id, status, agent, changed_at) "
               "VALUES (%s, %s, 'parsed', 'model:claude', now())", (ids.uuid7(), world["file"]))
    pg.execute("INSERT INTO atom_revision (id, atom_id, n, schema_version, payload, content_hash, changeset_id, "
               "recorded_at, review_state) VALUES (%s, %s, 1, 'amem.atom/1', '{}', %s, %s, now(), 'none')",
               (world["revision"], atom, "sha256-c1:" + "0" * 64, cs))
    pg.execute("INSERT INTO source (id, atom_revision_id, position, object_id, object_version) "
               "VALUES (%s, %s, 0, %s, 1)", (ids.uuid7(), world["revision"], world["file"]))
    pg.execute("INSERT INTO entity (id, entity_class, status, created_at, status_changed_at) "
               "VALUES (%s, 'document', 'draft', now(), now())", (world["entity"],))
    pg.execute("INSERT INTO entity_revision (id, entity_id, n, schema_version, payload, content_hash, changeset_id, "
               "recorded_at, review_state) VALUES (%s, %s, 1, 'amem.entity/1', '{}', %s, %s, now(), 'none')",
               (world["entity_revision"], world["entity"], "sha256-c1:" + "1" * 64, cs))
    pg.execute("INSERT INTO source (id, entity_revision_id, position, object_id, object_version) "
               "VALUES (%s, %s, 0, %s, 1)", (ids.uuid7(), world["entity_revision"], world["file"]))
    return world


OBJECT_ROWS = {"object": "original_name", "object_path": "path", "object_version": "size", "object_status": "note"}


@pytest.mark.parametrize("op", ["UPDATE", "DELETE"])
@pytest.mark.parametrize("table", OBJECT_ROWS)
def test_object_rows_cannot_change(pg, table, op):
    """Объекты, их пути, версии и отметки не меняются и не удаляются: копия по ссылке источника — навсегда."""
    db.migrate(pg)
    _objects(pg)
    column = OBJECT_ROWS[table]
    sql = f"UPDATE {table} SET {column} = {column}" if op == "UPDATE" else f"DELETE FROM {table}"
    with pytest.raises(psycopg.errors.RaiseException, match=f"amem: {op} в таблице {table} запрещено"):
        pg.execute(sql)


def test_source_row_changes_only_by_check_result(pg):
    """Строку источника меняет только итог сверки с файлом; удалить её нельзя."""
    db.migrate(pg)
    _objects(pg)
    pg.execute("UPDATE source SET verdict = 'ok', page = 2, anchor = 'Таблица 1', checked_at = now()")
    with pytest.raises(psycopg.errors.RaiseException, match="только итог сверки"):
        pg.execute("UPDATE source SET quote = 'другая цитата'")
    with pytest.raises(psycopg.errors.RaiseException, match="нельзя удалить"):
        pg.execute("DELETE FROM source")


def _insert_object(kind, name=None, url=None, retrieved=None):
    return ("INSERT INTO object (id, kind, original_name, url, retrieved_at, created_at) "
            "VALUES (%(new)s, %(kind)s, %(name)s, %(url)s, %(retrieved)s, now())",
            {"kind": kind, "name": name, "url": url, "retrieved": retrieved})


def _insert_version(object_key, kind, n, digest=None, size=None):
    return ("INSERT INTO object_version (object_id, kind, n, digest, size, recorded_at) "
            "VALUES (%(object)s, %(kind)s, %(n)s, %(digest)s, %(size)s, now())",
            {"object_key": object_key, "kind": kind, "n": n, "digest": digest, "size": size})


def _insert_source(position=1, verdict=None, checked=False, page=None, anchor=None, revisions=("atom",), version=1,
                   edition=None):
    """revisions — чьи ревизии у источника: atom, entity, обе, ни одной; unknown / unknown_entity — ревизии нет."""
    return ("INSERT INTO source (id, atom_revision_id, entity_revision_id, position, object_id, object_version, "
            "verdict, page, anchor, edition_id, checked_at) VALUES (%(new)s, %(atom_ref)s, %(entity_ref)s, "
            "%(position)s, %(file)s, %(version)s, %(verdict)s, %(page)s, %(anchor)s, %(edition)s, "
            "CASE WHEN %(checked)s THEN now() END)",
            {"position": position, "verdict": verdict, "checked": checked, "page": page, "anchor": anchor,
             "revisions": revisions, "version": version, "edition": edition})


def _row(world, params):
    """Параметры вставки: новый id, строки из _objects и параметры случая."""
    row = {"new": ids.uuid7(), "missing": ids.uuid7(), "nfd": NFD, "digest": DIGEST, **world, **params}
    if "object_key" in row:
        row["object"] = world[row["object_key"]]
    revisions = row.get("revisions", ())
    row["atom_ref"] = (world["revision"] if "atom" in revisions else ids.uuid7() if "unknown" in revisions
                       else None)
    row["entity_ref"] = (world["entity_revision"] if "entity" in revisions else ids.uuid7()
                         if "unknown_entity" in revisions else None)
    return row


Check, Unique, Foreign = (psycopg.errors.CheckViolation, psycopg.errors.UniqueViolation,
                          psycopg.errors.ForeignKeyViolation)
# в каждом случае нарушено ровно одно правило — убранное ограничение не спрячется за соседним
VIOLATIONS = {
    "сайт без адреса": (*_insert_object("web", retrieved="2026-10-25"), Check),
    "пустой адрес": (*_insert_object("web", url="", retrieved="2026-10-25"), Check),
    "файл с адресом": (*_insert_object("file", name="c.pdf", url="https://example.org/c"), Check),
    "сайт без даты обращения": (*_insert_object("web", url="https://example.org/b"), Check),
    "переписка с датой обращения": (*_insert_object("message", name="Ещё письмо", retrieved="2026-10-25"), Check),
    "файл без имени": (*_insert_object("file"), Check),
    "пустое имя": (*_insert_object("file", name=""), Check),
    "имя не в NFC": (*_insert_object("file", name=NFD), Check),
    "адрес не в NFC": (*_insert_object("web", url="https://example.org/" + NFD, retrieved="2026-10-25"), Check),
    "второй сайт с тем же адресом": (*_insert_object("web", url="https://example.org/a", retrieved="2026-10-25"),
                                     Unique),
    "вторая переписка с тем же названием": (*_insert_object("message", name="Письмо"), Unique),
    "путь не в NFC": ("INSERT INTO object_path (path, object_id, added_at) VALUES (%(nfd)s, %(file)s, now())",
                      {}, Check),
    "пустой путь": ("INSERT INTO object_path (path, object_id, added_at) VALUES ('', %(file)s, now())", {}, Check),
    "путь у страницы сайта": ("INSERT INTO object_path (path, object_id, added_at) "
                              "VALUES ('docs/web.pdf', %(web)s, now())", {}, Foreign),
    "путь у второго объекта": ("INSERT INTO object_path (path, object_id, added_at) "
                               "VALUES ('docs/a.pdf', %(bare)s, now())", {}, Unique),
    "путь с видом сайта": ("INSERT INTO object_path (path, object_id, kind, added_at) "
                           "VALUES ('docs/web.pdf', %(web)s, 'web', now())", {}, Check),
    "digest без размера": (*_insert_version("bare", "file", 1, "sha256:" + "cd" * 32), Check),
    "файл без digest": (*_insert_version("bare", "file", 1), Check),
    "digest не sha256": (*_insert_version("bare", "file", 1, "sha256:XYZ", 3), Check),
    "тот же digest второй раз": (*_insert_version("bare", "file", 1, DIGEST, 3), Unique),
    "digest у страницы сайта": (*_insert_version("web_bare", "web", 1, "sha256:" + "cd" * 32, 3), Check),
    "размер у страницы сайта": (*_insert_version("web_bare", "web", 1, size=5), Check),
    "версия 0": (*_insert_version("bare", "file", 0, "sha256:" + "cd" * 32, 3), Check),
    "отрицательный размер": (*_insert_version("bare", "file", 1, "sha256:" + "cd" * 32, -1), Check),
    "вторая версия переписки": (*_insert_version("message", "message", 2), Check),
    "вид версии не тот": (*_insert_version("bare", "web", 1), Foreign),
    "страница 0 с текстом": ("INSERT INTO object_text (digest, page, text) VALUES (%(digest)s, 0, 'текст')", {},
                             Check),
    "отрицательная страница текста": ("INSERT INTO object_text (digest, page, text) VALUES (%(digest)s, -1, '')", {},
                                      Check),
    "текст неизвестного содержимого": ("INSERT INTO object_text (digest, page, text) "
                                       "VALUES ('sha256:' || repeat('e', 64), 1, 'текст')", {}, Foreign),
    "отметка неизвестного агента": ("INSERT INTO object_status (id, object_id, status, agent, changed_at) "
                                    "VALUES (%(new)s, %(file)s, 'parsed', 'model:nobody', now())", {}, Foreign),
    "отметка неизвестного объекта": ("INSERT INTO object_status (id, object_id, status, agent, changed_at) "
                                     "VALUES (%(new)s, %(missing)s, 'parsed', 'model:claude', now())", {}, Foreign),
    "источник без ревизии": (*_insert_source(revisions=()), Check),
    "источник двух ревизий": (*_insert_source(revisions=("atom", "entity")), Check),
    "источник неизвестной ревизии": (*_insert_source(revisions=("unknown",)), Foreign),
    "источник неизвестной ревизии сущности": (*_insert_source(revisions=("unknown_entity",)), Foreign),
    "итог сверки без времени": (*_insert_source(verdict="ok"), Check),
    "время сверки без итога": (*_insert_source(checked=True), Check),
    "страница без итога сверки": (*_insert_source(page=3), Check),
    "место без итога сверки": (*_insert_source(anchor="Таблица 1"), Check),
    "страница 0": (*_insert_source(verdict="ok", checked=True, page=0), Check),
    "тот же номер в ревизии": (*_insert_source(position=0), Unique),
    "тот же номер в ревизии сущности": (*_insert_source(position=0, revisions=("entity",)), Unique),
    "отрицательный номер источника": (*_insert_source(position=-1), Check),
    "версии объекта нет": (*_insert_source(version=5), Foreign),
    "редакции нет": (*_insert_source(edition=ids.uuid7()), Foreign),
}
VALID = [
    _insert_object("web", url="https://example.org/b", retrieved="2026-10-25"),
    _insert_object("message", name="Ещё письмо"),
    _insert_object("file", name="c.pdf"),
    _insert_object("file", name="a.pdf"),             # одноимённые файлы из разных папок — разные объекты
    _insert_object("file", name="Письмо"),            # имя уникально только у переписки
    _insert_version("bare", "file", 1, "sha256:" + "cd" * 32, 3),
    _insert_source(verdict="ok", checked=True, page=3, anchor="Таблица 1"),
    _insert_source(position=1, revisions=("entity",)),
]


@pytest.mark.parametrize("case", VIOLATIONS)
def test_object_constraints(pg, case):
    db.migrate(pg)
    world = _objects(pg)
    sql, params, error = VIOLATIONS[case]
    with pytest.raises(error):
        pg.execute(sql, _row(world, params))


def test_object_constraints_accept_valid_rows(pg):
    """Те же вставки с правильными значениями проходят: каждый случай выше отвергнут своим правилом."""
    db.migrate(pg)
    world = _objects(pg)
    for sql, params in VALID:
        pg.execute(sql, _row(world, params))
