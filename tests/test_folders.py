"""Папки (подпроект 4, часть 4.0): правила пути, перенос без ревизии, журнал, реестр, переименование, дерево,
четыре папки новой базы и события folder в what_changed — на PostgreSQL 18 и 16."""
import json
import shutil
import threading
import time
import unicodedata
from datetime import datetime, timezone

import psycopg
import pytest

from amem import db, folders, ids, lookup, recipes, records
from amem.folders import FolderError
from amem.records import Item, RecordError
from v1_support import same_database

MODEL = "model:test"
HUMAN = "person:tester"
DEFAULTS = {"Проекты", "Области", "Ресурсы", "Архив"}
PAST = datetime(2001, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def kb(pg):
    db.prepare(pg)
    return pg


def atom(kb, label="Ветровая нагрузка", key=None) -> str:
    payload = {"kind": "fact", "label": {"ru": label}, "sources": [], **({"key": key} if key else {})}
    done = records.commit(kb, [Item("atom", payload)], agent=MODEL)
    return f"atm:{done.revisions[0].record_id}"


def entity(kb, key, label="Проект Альфа") -> str:
    done = records.commit(kb, [Item("entity", {"entity_class": "project", "key": key, "label": {"ru": label}})],
                          agent=MODEL)
    return f"ent:{done.revisions[0].record_id}"


def registry(kb) -> set[str]:
    return {r[0] for r in kb.execute("SELECT path FROM folder")}


def folder_of(kb, ref) -> str | None:
    target, record_id = records.TARGET[ref[:3]], ref[4:]
    return kb.execute(f"SELECT folder FROM {target} WHERE id = %s", (record_id,)).fetchone()[0]


def log(kb, ref) -> list[tuple]:
    return kb.execute("SELECT target, folder_from, folder_to, agent FROM folder_log WHERE record_id = %s "
                      "ORDER BY changed_at, id", (ref[4:],)).fetchall()


def code(excinfo) -> str:
    return excinfo.value.code


# --- check: правила пути ---


def test_check_accepts_path():
    assert folders.check("Проекты/Альфа") == "Проекты/Альфа"
    assert folders.check("Мои проекты/2026") == "Мои проекты/2026"         # пробел внутри сегмента — можно
    assert folders.check("я" * 100) == "я" * 100
    eight = "/".join("abcdefgh")
    assert folders.check(eight) == eight
    assert folders.check("a-b/-c/d-") == "a-b/-c/d-"                         # «-» — только целым сегментом
    assert folders.check("a\u200db/a\u200cb") == "a\u200db/a\u200cb"     # ZWJ и ZWNJ нужны письменностям


def test_check_normalizes_nfc_and_trims_segments():
    nfd = unicodedata.normalize("NFD", "Йод")
    assert nfd != "Йод"
    assert folders.check(f"  Проекты / {nfd}\t") == "Проекты/Йод"


BAD_PATHS = {
    "пустой путь": "",
    "пустой сегмент": "Проекты//Альфа",
    "сегмент из пробелов": "Проекты/  /Альфа",
    "«/» в конце": "Проекты/",
    "«/» в начале": "/Проекты",
    "точка": "Проекты/./Альфа",
    "две точки": "Проекты/..",
    "управляющий символ": "Проекты/Аль\x07фа",
    "перевод строки внутри": "Про\nекты",
    "сегмент из 101 знака": "я" * 101,
    "9 уровней": "/".join("abcdefghi"),
    "путь «-»": "-",
    "путь «-» с пробелами": " - ",
    "сегмент «-» первым": "-/x",
    "сегмент «-» в середине": "a/ - /b",
    "сегмент «-» последним": "a/-",
    "пробел нулевой ширины": "\u200b",
    "пробел нулевой ширины в конце": "Архив\u200b",
    "смена направления письма": "a\u202eb",
    "метка порядка байтов": "\ufeffАрхив",
}


@pytest.mark.parametrize("case", BAD_PATHS)
def test_check_rejects(case):
    with pytest.raises(FolderError) as e:
        folders.check(BAD_PATHS[case])
    assert code(e) == "invalid"


def test_register_checks_every_parent(kb):
    """Реестр не примет путь в обход check: «-» в родителе потом не удалить и не показать в контракте."""
    for bad in ("-/x", "a/-/b", "a/\u200b/b"):
        with pytest.raises(FolderError) as e:
            with kb.transaction():
                folders._register(kb, [bad], MODEL, datetime.now(timezone.utc))
        assert code(e) == "invalid"
    for call in (lambda: folders.create(kb, "-/x", agent=HUMAN), lambda: folders.move(kb, atom(kb), "a/-/b",
                                                                                      agent=MODEL)):
        with pytest.raises(FolderError) as e:
            call()
        assert code(e) == "invalid"
    assert registry(kb) == DEFAULTS


def test_check_rejects_non_string():
    with pytest.raises(FolderError) as e:
        folders.check(["Проекты"])
    assert code(e) == "invalid"
    assert isinstance(e.value, ValueError)


# --- move: перенос без ревизии ---


def test_move_changes_folder_without_revision(kb):
    ref = atom(kb)
    before = kb.execute("SELECT id, n, content_hash FROM atom_revision WHERE atom_id = %s", (ref[4:],)).fetchall()
    result = folders.move(kb, ref, "Проекты/Альфа/Узлы", agent=MODEL)       # переносить вправе и модель
    assert result == {"ref": ref, "from": None, "to": "Проекты/Альфа/Узлы", "moved": True}
    json.dumps(result)
    assert folder_of(kb, ref) == "Проекты/Альфа/Узлы"
    assert kb.execute("SELECT id, n, content_hash FROM atom_revision WHERE atom_id = %s",
                      (ref[4:],)).fetchall() == before
    assert kb.execute("SELECT count(*) FROM changeset").fetchone()[0] == 1   # только пакет записи атома
    assert log(kb, ref) == [("atom", None, "Проекты/Альфа/Узлы", MODEL)]
    assert {"Проекты", "Проекты/Альфа", "Проекты/Альфа/Узлы"} <= registry(kb)
    creators = dict(kb.execute("SELECT path, created_by FROM folder WHERE path LIKE 'Проекты/%'").fetchall())
    assert creators == {"Проекты/Альфа": MODEL, "Проекты/Альфа/Узлы": MODEL}


def test_move_to_none_and_back_logs_each_step(kb):
    ref = atom(kb)
    folders.move(kb, ref, "Ресурсы", agent=HUMAN)
    assert folders.move(kb, ref, None, agent=HUMAN) == {"ref": ref, "from": "Ресурсы", "to": None, "moved": True}
    assert folder_of(kb, ref) is None
    assert log(kb, ref) == [("atom", None, "Ресурсы", HUMAN), ("atom", "Ресурсы", None, HUMAN)]


def test_move_to_same_folder_changes_nothing(kb):
    ref = atom(kb)
    folders.move(kb, ref, "Архив", agent=MODEL)
    assert folders.move(kb, ref, " Архив ", agent=MODEL) == {"ref": ref, "from": "Архив", "to": "Архив",
                                                            "moved": False}
    assert folders.move(kb, atom(kb, "Другая"), None, agent=MODEL)["moved"] is False
    assert len(log(kb, ref)) == 1


def test_move_entity_by_key(kb):
    ref = entity(kb, "alpha")
    result = folders.move(kb, "ent:alpha", "Проекты", agent=MODEL)
    assert result["ref"] == ref and folder_of(kb, ref) == "Проекты"
    assert log(kb, ref) == [("entity", None, "Проекты", MODEL)]


def test_move_rejects_bad_path_and_unknown_record(kb):
    ref = atom(kb)
    with pytest.raises(FolderError) as e:
        folders.move(kb, ref, "-", agent=MODEL)
    assert code(e) == "invalid"
    for bad in (f"atm:{ids.uuid7()}", "ent:no_such_key", "obj:x", "мусор", "@a"):
        with pytest.raises(RecordError):
            folders.move(kb, bad, "Архив", agent=MODEL)
    assert folder_of(kb, ref) is None and log(kb, ref) == []


def test_move_time_not_earlier_than_last_change(kb, monkeypatch):
    """Часы ушли назад: перенос не раньше последнего изменения записи, а статус — не раньше переноса."""
    ref = atom(kb)
    recorded = kb.execute("SELECT recorded_at FROM atom_revision WHERE atom_id = %s", (ref[4:],)).fetchone()[0]
    with monkeypatch.context() as m:
        m.setattr(folders, "_now", lambda: PAST)
        folders.move(kb, ref, "Архив", agent=MODEL)              # не раньше ревизии
    folders.move(kb, ref, "Ресурсы", agent=MODEL)                # по настоящим часам — позже ревизии
    monkeypatch.setattr(folders, "_now", lambda: PAST)
    folders.move(kb, ref, "Проекты", agent=MODEL)                # не раньше прошлого переноса
    times = [r[0] for r in kb.execute("SELECT changed_at FROM folder_log WHERE record_id = %s ORDER BY id",
                                      (ref[4:],))]
    assert times[0] >= recorded and times[1] > recorded and times[2] >= times[1]
    monkeypatch.setattr(records, "_now", lambda: PAST)
    records.set_status(kb, "atom", ref[4:], "needs_review", agent=MODEL)
    status_at = kb.execute("SELECT changed_at FROM status_log WHERE record_id = %s AND status = 'needs_review'",
                           (ref[4:],)).fetchone()[0]
    assert status_at >= times[2]                                 # и статус — не раньше переноса


def _wait_until_blocked(conn, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if conn.execute("SELECT count(*) FROM pg_stat_activity WHERE pid <> pg_backend_pid() "
                        "AND datname = current_database() AND wait_event_type = 'Lock'").fetchone()[0]:
            return
        time.sleep(0.02)
    raise AssertionError("соседнее соединение так и не встало в ожидание")


def test_move_waits_for_delete_of_its_folder(kb, monkeypatch):
    """Удаление проверило, что папка пуста, и ещё не удалило её: перенос в неё ждёт. Иначе запись легла бы
    в папку, которой нет в реестре."""
    ref = atom(kb)
    folders.create(kb, "Черновики", agent=HUMAN)
    paused, go = threading.Event(), threading.Event()
    has_content = folders._has_content

    def check_then_pause(conn, path):
        found = has_content(conn, path)
        if threading.current_thread().name == "delete":
            paused.set()
            go.wait(10)
        return found

    monkeypatch.setattr(folders, "_has_content", check_then_pause)
    errors = []

    def thread(name, job):
        def run():
            try:
                with same_database(kb, autocommit=True) as conn:
                    job(conn)
            except Exception as e:          # noqa: BLE001 — ошибку проверяет тест
                errors.append((name, e))
        return threading.Thread(target=run, name=name)

    deleting = thread("delete", lambda c: folders.delete(c, "Черновики"))
    moving = thread("move", lambda c: folders.move(c, ref, "Черновики", agent=MODEL))
    deleting.start()
    assert paused.wait(10)
    moving.start()
    _wait_until_blocked(kb)
    go.set()
    deleting.join(20)
    moving.join(20)
    assert errors == []
    assert folder_of(kb, ref) == "Черновики" and "Черновики" in registry(kb)


# --- create и delete ---


def test_create_adds_folder_with_parents(kb):
    result = folders.create(kb, "Ресурсы/Справочники/Стекло", agent=HUMAN)
    assert result["path"] == "Ресурсы/Справочники/Стекло" and result["name"] == "Стекло"
    json.dumps(result)
    assert {"Ресурсы/Справочники", "Ресурсы/Справочники/Стекло"} <= registry(kb)
    assert kb.execute("SELECT created_by FROM folder WHERE path = 'Ресурсы/Справочники/Стекло'").fetchone()[0] == HUMAN


def test_create_existing_is_exists(kb):
    folders.create(kb, "Ресурсы/Справочники", agent=HUMAN)
    for path in ("Ресурсы/Справочники", " Ресурсы / Справочники ", "Проекты"):
        with pytest.raises(FolderError) as e:
            folders.create(kb, path, agent=HUMAN)
        assert code(e) == "exists"
    with pytest.raises(FolderError) as e:
        folders.create(kb, "a/../b", agent=HUMAN)
    assert code(e) == "invalid"


def test_delete_removes_only_empty_folder(kb):
    folders.create(kb, "Проекты/Альфа", agent=HUMAN)
    ref = atom(kb)
    folders.move(kb, ref, "Ресурсы", agent=MODEL)
    for path in ("Проекты", "Ресурсы"):                      # вложенная папка; запись
        with pytest.raises(FolderError) as e:
            folders.delete(kb, path)
        assert code(e) == "not_empty"
    entity_ref = entity(kb, "beta")
    folders.move(kb, entity_ref, "Области/Стройка", agent=MODEL)
    with pytest.raises(FolderError) as e:
        folders.delete(kb, "Области")                       # сущность во вложенной папке
    assert code(e) == "not_empty"

    assert folders.delete(kb, "Проекты/Альфа") == {"path": "Проекты/Альфа"}
    folders.delete(kb, "Проекты")
    folders.move(kb, ref, None, agent=MODEL)
    folders.delete(kb, "Ресурсы")
    assert registry(kb) == {"Архив", "Области", "Области/Стройка"}
    with pytest.raises(FolderError) as e:
        folders.delete(kb, "Проекты")
    assert code(e) == "not_found"


# --- rename ---


def test_rename_moves_subfolders_and_records(kb):
    folders.create(kb, "a/x/пусто", agent=HUMAN)
    top, deep, ent = atom(kb, "Верх"), atom(kb, "Глубже"), entity(kb, "gamma")
    folders.move(kb, top, "a", agent=MODEL)
    folders.move(kb, deep, "a/x", agent=MODEL)
    folders.move(kb, ent, "a/x", agent=MODEL)
    creator = kb.execute("SELECT created_by, created_at FROM folder WHERE path = 'a/x/пусто'").fetchone()

    result = folders.rename(kb, "a", "b/c", agent=HUMAN)
    assert result == {"from": "a", "to": "b/c", "folders": 3, "records": 3}
    json.dumps(result)
    assert registry(kb) == DEFAULTS | {"b", "b/c", "b/c/x", "b/c/x/пусто"}
    assert kb.execute("SELECT created_by, created_at FROM folder WHERE path = 'b/c/x/пусто'").fetchone() == creator
    assert (folder_of(kb, top), folder_of(kb, deep), folder_of(kb, ent)) == ("b/c", "b/c/x", "b/c/x")
    assert log(kb, top)[-1] == ("atom", "a", "b/c", HUMAN)
    assert log(kb, deep)[-1] == ("atom", "a/x", "b/c/x", HUMAN)
    assert log(kb, ent)[-1] == ("entity", "a/x", "b/c/x", HUMAN)
    assert kb.execute("SELECT count(*) FROM folder_log").fetchone()[0] == 6


def test_rename_adds_no_revisions_or_changesets(kb):
    refs = [atom(kb, f"Запись {i}") for i in range(3)] + [entity(kb, "zeta")]
    for ref in refs:
        folders.move(kb, ref, "a/x", agent=MODEL)
    counts = "SELECT (SELECT count(*) FROM atom_revision), (SELECT count(*) FROM entity_revision), " \
             "(SELECT count(*) FROM changeset), (SELECT count(*) FROM status_log)"
    before = kb.execute(counts).fetchone()
    assert folders.rename(kb, "a", "b", agent=HUMAN)["records"] == 4
    assert kb.execute(counts).fetchone() == before
    assert {folder_of(kb, ref) for ref in refs} == {"b/x"}


def test_rename_of_large_folder_is_quick(kb):
    """2 000 записей вперемешку (атомы и сущности): блокировки — конвейером по возрастанию id, остальное — пакетно."""
    folders.create(kb, "Большая/Внутри", agent=HUMAN)
    atom_ids, entity_ids = [], []
    for i in range(2000):
        (atom_ids if i % 3 else entity_ids).append(ids.uuid7())
    kb.execute("INSERT INTO atom (id, kind, status, created_at, status_changed_at, folder) "
               "SELECT unnest(%s::uuid[]), 'fact', 'draft', now(), now(), 'Большая/Внутри'", (atom_ids,))
    kb.execute("INSERT INTO entity (id, entity_class, status, created_at, status_changed_at, folder) "
               "SELECT unnest(%s::uuid[]), 'project', 'draft', now(), now(), 'Большая'", (entity_ids,))
    started = time.monotonic()
    result = folders.rename(kb, "Большая", "Архив/Большая", agent=HUMAN)
    elapsed = time.monotonic() - started
    assert result == {"from": "Большая", "to": "Архив/Большая", "folders": 2, "records": 2000}
    assert elapsed < 5, f"переименование 2 000 записей заняло {elapsed:.1f} с"
    placed = kb.execute("SELECT folder, count(*) FROM (SELECT folder FROM atom UNION ALL SELECT folder FROM entity) r "
                        "GROUP BY folder").fetchall()
    assert dict(placed) == {"Архив/Большая/Внутри": len(atom_ids), "Архив/Большая": len(entity_ids)}
    logged = kb.execute("SELECT target, count(*), count(DISTINCT record_id), min(agent), max(agent) FROM folder_log "
                        "GROUP BY target ORDER BY target").fetchall()
    assert logged == [("atom", len(atom_ids), len(atom_ids), HUMAN, HUMAN),
                      ("entity", len(entity_ids), len(entity_ids), HUMAN, HUMAN)]


def test_rename_refuses_taken_path_descendant_and_missing(kb):
    folders.create(kb, "a/x", agent=HUMAN)
    ref = atom(kb)
    folders.move(kb, ref, "c", agent=MODEL)
    kb.execute("UPDATE atom SET folder = 'Вне/реестра' WHERE id = %s", (atom(kb, "Вне")[4:],))
    cases = {"Проекты": "exists", "c": "exists", "a": "exists",                # «a» — сам путь
             "Вне": "exists", "Вне/реестра": "exists",                          # пути записи без строки реестра
             "a/x": "invalid", "a/x/y": "invalid", "a/y": "invalid", "-": "invalid"}
    for new, expected in cases.items():
        with pytest.raises(FolderError) as e:
            folders.rename(kb, "a", new, agent=HUMAN)
        assert code(e) == expected, new
    with pytest.raises(FolderError) as e:
        folders.rename(kb, "нет такой", "d", agent=HUMAN)
    assert code(e) == "not_found"
    assert registry(kb) == DEFAULTS | {"a", "a/x", "c"}
    assert folder_of(kb, ref) == "c" and len(log(kb, ref)) == 1


def test_rename_refuses_too_deep_result(kb):
    folders.create(kb, "a/x", agent=HUMAN)
    ref = atom(kb)
    folders.move(kb, ref, "a/x", agent=MODEL)
    seven = "/".join("pqrstuv")
    with pytest.raises(FolderError) as e:
        folders.rename(kb, "a", f"{seven}/w", agent=HUMAN)          # a/x стала бы девятым уровнем
    assert code(e) == "invalid"
    assert folder_of(kb, ref) == "a/x" and "a/x" in registry(kb)
    folders.rename(kb, "a", seven, agent=HUMAN)                      # восьмой уровень — можно
    assert folder_of(kb, ref) == f"{seven}/x"


# --- tree ---


def _names(nodes) -> list[str]:
    return [n["name"] for n in nodes]


def test_tree_of_new_base_has_four_empty_folders(kb):
    tree = folders.tree(kb)
    assert tree == {"folders": [{"path": p, "name": p, "count": 0, "children": []}
                                for p in ("Архив", "Области", "Проекты", "Ресурсы")],
                    "unfiled": 0, "total": 0}


def test_tree_counts_nested_records_and_shows_empty(kb):
    folders.create(kb, "Ресурсы/Пусто", agent=HUMAN)
    for name in ("Гамма", "Яблоко", "бета", "ель", "Альфа", "Ёлка", "Ель"):
        folders.create(kb, f"Проекты/{name}", agent=HUMAN)
    folders.move(kb, atom(kb, "один"), "Проекты", agent=MODEL)
    folders.move(kb, atom(kb, "два"), "Проекты/Альфа", agent=MODEL)
    folders.move(kb, entity(kb, "delta"), "Проекты/Альфа/Узлы", agent=MODEL)
    atom(kb, "без папки")
    kb.execute("UPDATE atom SET folder = 'Вне/реестра' WHERE id = (SELECT atom_id FROM atom_revision "
               "WHERE payload->'label'->>'ru' = 'без папки')")           # путь записи без строки реестра
    atom(kb, "ещё без папки")

    tree = folders.tree(kb)
    json.dumps(tree)
    assert tree["unfiled"] == 1 and tree["total"] == 5
    top = {n["path"]: n for n in tree["folders"]}
    assert _names(tree["folders"]) == ["Архив", "Вне", "Области", "Проекты", "Ресурсы"]
    projects = top["Проекты"]
    assert projects["count"] == 3
    # по имени без учёта регистра, ё как е (как в поиске); при равенстве — как есть
    assert _names(projects["children"]) == ["Альфа", "бета", "Гамма", "Ёлка", "Ель", "ель", "Яблоко"]
    alpha = projects["children"][0]
    assert (alpha["path"], alpha["count"]) == ("Проекты/Альфа", 2)
    assert alpha["children"] == [{"path": "Проекты/Альфа/Узлы", "name": "Узлы", "count": 1, "children": []}]
    assert top["Ресурсы"]["children"] == [{"path": "Ресурсы/Пусто", "name": "Пусто", "count": 0, "children": []}]
    assert top["Вне"]["count"] == 1 and top["Вне"]["children"][0]["path"] == "Вне/реестра"
    assert tree["total"] == tree["unfiled"] + sum(n["count"] for n in tree["folders"])


# --- db.prepare: четыре папки новой базы ---


def test_prepare_creates_four_folders_once(kb):
    rows = dict(kb.execute("SELECT path, created_by FROM folder").fetchall())
    assert rows == {path: folders.INIT_AGENT for path in DEFAULTS}
    db.prepare(kb)
    assert kb.execute("SELECT count(*) FROM folder").fetchone()[0] == 4
    folders.delete(kb, "Архив")
    db.prepare(kb)
    assert registry(kb) == DEFAULTS - {"Архив"}                   # удалённая пользователем не возвращается


def test_existing_base_gets_no_default_folders(pg, tmp_path, monkeypatch):
    """База, у которой base_id появился до миграции 0008, папок по умолчанию не получает."""
    old = tmp_path / "sql"
    shutil.copytree(db.SQL_DIR, old)
    (old / "0008_folders.sql").unlink()
    (old / "0009_record_list.sql").unlink()
    (old / "0010_graph_overview.sql").unlink()
    (old / "0011_object_text_ocr.sql").unlink()
    (old / "0012_tasks.sql").unlink()
    with monkeypatch.context() as m:
        m.setattr(db, "SQL_DIR", old)
        db.migrate(pg)
        db.load_vocab(pg)
        pg.execute("INSERT INTO meta (key, value) VALUES ('base_id', %s)", (json.dumps(str(ids.uuid7())),))
    assert db.prepare(pg) == ["0008_folders.sql", "0009_record_list.sql", "0010_graph_overview.sql",
                              "0011_object_text_ocr.sql", "0012_tasks.sql"]
    assert registry(pg) == set()


def test_migrations_0008_0009_over_base_with_data(pg, tmp_path, monkeypatch):
    """База на 0007 с записями: prepare применяет 0008 и 0009 по порядку, папок по умолчанию нет, списки работают."""
    old = tmp_path / "sql"
    shutil.copytree(db.SQL_DIR, old)
    (old / "0008_folders.sql").unlink()
    (old / "0009_record_list.sql").unlink()
    (old / "0010_graph_overview.sql").unlink()
    (old / "0011_object_text_ocr.sql").unlink()
    (old / "0012_tasks.sql").unlink()
    with monkeypatch.context() as m:
        m.setattr(db, "SQL_DIR", old)
        db.migrate(pg)
        db.load_vocab(pg)
        pg.execute("INSERT INTO meta (key, value) VALUES ('base_id', %s)", (json.dumps(str(ids.uuid7())),))
        made = records.commit(pg, [Item("atom", {"kind": "fact", "label": {"ru": "Ветер"}, "sources": []}),
                                   Item("entity", {"entity_class": "project", "label": {"ru": "Альфа"}})],
                              agent=MODEL)
    assert db.prepare(pg) == ["0008_folders.sql", "0009_record_list.sql", "0010_graph_overview.sql",
                              "0011_object_text_ocr.sql", "0012_tasks.sql"]
    assert registry(pg) == set()
    refs = {f"{records.PREFIX[r.target]}:{r.record_id}" for r in made.revisions}
    page = lookup.list_records(pg)
    assert {i["ref"] for i in page["items"]} == refs and page["total"] == 2
    assert all(i["folder"] is None for i in page["items"])
    assert folders.tree(pg) == {"folders": [], "unfiled": 2, "total": 2}


# --- what_changed: события folder ---


def test_what_changed_has_folder_events(kb):
    ref = atom(kb)
    start = datetime.now(timezone.utc)
    folders.move(kb, ref, "Проекты", agent=MODEL)
    folders.rename(kb, "Проекты", "Проекты 2026", agent=HUMAN)
    events = [e for e in recipes.what_changed(kb, ref=ref)["events"] if e["type"] == "folder"]
    assert [(e["ref"], e["from"], e["to"], e["agent"]) for e in events] == [
        (ref, None, "Проекты", MODEL), (ref, "Проекты", "Проекты 2026", HUMAN)]
    assert all(datetime.fromisoformat(e["at"]) >= start and e["changed_at"] == e["at"] for e in events)
    whole = recipes.what_changed(kb, since=start)["events"]
    assert [e["id"] for e in whole if e["type"] == "folder"] == [e["id"] for e in events]
    assert not [e for e in recipes.what_changed(kb, ref=atom(kb, "Другая"))["events"] if e["type"] == "folder"]
    json.dumps(whole)
    second = datetime.fromisoformat(events[1]["at"])
    before = recipes.what_changed(kb, ref=ref, until=second)["events"]
    assert [e["id"] for e in before if e["type"] == "folder"] == [events[0]["id"]]        # until — не включая
    after = recipes.what_changed(kb, ref=ref, since=second)["events"]
    assert [e["id"] for e in after if e["type"] == "folder"] == [events[1]["id"]]


# --- таблицы ---


def test_folder_log_is_immutable(kb):
    ref = atom(kb)
    folders.move(kb, ref, "Архив", agent=MODEL)
    for sql in ("UPDATE folder_log SET folder_to = 'Ресурсы'", "DELETE FROM folder_log"):
        with pytest.raises(psycopg.errors.RaiseException, match="amem: .* в таблице folder_log запрещено"):
            kb.execute(sql)


@pytest.mark.parametrize("value", ["", "я" * 901])
@pytest.mark.parametrize("table", ["atom", "entity", "folder"])
def test_folder_columns_refuse_empty_and_too_long(kb, table, value):
    if table == "folder":
        sql = "INSERT INTO folder (path, created_at, created_by) VALUES (%s, now(), 'model:amem-init')"
        params = (value,)
    else:
        ref = atom(kb) if table == "atom" else entity(kb, "eps")
        sql, params = f"UPDATE {table} SET folder = %s WHERE id = %s", (value, ref[4:])
    with pytest.raises(psycopg.errors.CheckViolation):
        kb.execute(sql, params)


def test_folder_columns_compare_as_is(kb):
    """COLLATE "C": сравнение «как есть», и префикс starts_with идёт по индексу при любой локали базы."""
    rows = kb.execute("SELECT table_name, column_name, collation_name FROM information_schema.columns "
                      "WHERE table_schema = current_schema() AND column_name IN ('folder', 'path', 'folder_from', "
                      "'folder_to') AND table_name IN ('atom', 'entity', 'folder', 'folder_log')").fetchall()
    assert {(t, c): coll for t, c, coll in rows} == {
        ("atom", "folder"): "C", ("entity", "folder"): "C", ("folder", "path"): "C",
        ("folder_log", "folder_from"): "C", ("folder_log", "folder_to"): "C"}


@pytest.mark.parametrize("table, column", [("atom", "folder"), ("entity", "folder"), ("folder", "path")])
def test_prefix_query_can_use_index(kb, table, column):
    kb.execute("SET enable_seqscan = off")
    try:
        plan = "\n".join(r[0] for r in kb.execute(
            f"EXPLAIN SELECT 1 FROM {table} WHERE {column} = %(p)s OR starts_with({column}, %(p)s || '/')",
            {"p": "Проекты"}))
    finally:
        kb.execute("RESET enable_seqscan")
    # префикс — диапазоном по индексу; без COLLATE "C" вышел бы полный проход индекса с фильтром
    assert "Seq Scan" not in plan and f"Index Cond: (({column} >= 'Проекты/'::text)" in plan, plan


def test_folder_log_refuses_move_to_same_folder(kb):
    ref = atom(kb)
    with pytest.raises(psycopg.errors.CheckViolation):
        kb.execute("INSERT INTO folder_log (id, target, record_id, folder_from, folder_to, agent, changed_at) "
                   "VALUES (%s, 'atom', %s, 'Архив', 'Архив', 'model:amem-init', now())", (ids.uuid7(), ref[4:]))
