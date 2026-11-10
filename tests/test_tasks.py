"""Задачи агентам (подпроект 4, часть 4d; спецификация разд. 6a.5–6a.6): постановка, аренда, возврат, закрытие,
отмена, права и миграция 0012 — на настоящей базе (PostgreSQL 18 и 16)."""
import shutil
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from amemo import api, backup, db, objects, tasks
from amemo.ids import uuid7

PERSON = "person:ann"
MODEL = "model:parser"
OTHER = "model:other"
T0 = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def kb(pg, monkeypatch):
    monkeypatch.setenv("AMEMO_BACKEND", "none")
    db.prepare(pg)
    return pg


@pytest.fixture
def note(kb, store, docs):
    """Версия файла заметки в базе."""
    return objects.ingest(kb, store, docs, "Заметки/узел.md", agent=PERSON)


def test_create_is_open_and_idempotent(kb, note):
    task, created = tasks.create(kb, "parse", note.object_id, note.n, agent=PERSON, note="разобрать узел", now=T0)
    assert created and task["state"] == "open" and task["created_by"] == PERSON and task["note"] == "разобрать узел"
    assert task["id"].version == 7 and task["claimed_by"] is None and task["claimed_until"] is None
    again, created = tasks.create(kb, "parse", note.object_id, note.n, agent=MODEL, now=T0)
    assert not created and again["id"] == task["id"]
    assert kb.execute("SELECT count(*) FROM task").fetchone()[0] == 1
    claimed = tasks.claim(kb, task["id"], agent=MODEL, now=T0)                  # взятая — всё ещё незакрытая
    assert tasks.create(kb, "parse", note.object_id, note.n, agent=PERSON, now=T0)[0]["id"] == claimed["id"]
    tasks.done(kb, task["id"], agent=MODEL, now=T0)
    fresh, created = tasks.create(kb, "parse", note.object_id, note.n, agent=PERSON, now=T0)
    assert created and fresh["id"] != task["id"]                                 # закрытая — новая задача


def test_create_needs_existing_file_version(kb, note):
    with pytest.raises(tasks.TaskError) as e:
        tasks.create(kb, "parse", note.object_id, note.n + 1, agent=PERSON)
    assert e.value.code == "not_found"
    with pytest.raises(tasks.TaskError) as e:
        tasks.create(kb, "parse", uuid7(), 1, agent=PERSON)
    assert e.value.code == "not_found"
    with pytest.raises(tasks.TaskError) as e:
        tasks.create(kb, "summarize", note.object_id, note.n, agent=PERSON)
    assert e.value.code == "invalid"
    with pytest.raises(tasks.TaskError) as e:
        tasks.create(kb, "parse", note.object_id, note.n, agent="bot")
    assert e.value.code == "invalid"


def test_claim_lease_and_expiry(kb, note):
    task, _ = tasks.create(kb, "parse", note.object_id, note.n, agent=PERSON, now=T0)
    claimed = tasks.claim(kb, task["id"], agent=MODEL, now=T0)
    assert claimed["state"] == "claimed" and claimed["claimed_by"] == MODEL
    assert claimed["claimed_until"] == T0 + timedelta(minutes=30) == T0 + tasks.LEASE
    with pytest.raises(tasks.TaskError) as e:
        tasks.claim(kb, task["id"], agent=OTHER, now=T0 + timedelta(minutes=29))
    assert e.value.code == "claimed" and MODEL in str(e.value)
    assert tasks.claim(kb, agent=OTHER, now=T0 + timedelta(minutes=29)) is None      # свободных нет
    renewed = tasks.claim(kb, task["id"], agent=MODEL, now=T0 + timedelta(minutes=10))
    assert renewed["claimed_until"] == T0 + timedelta(minutes=40)                    # своя — аренда продлена
    later = T0 + timedelta(minutes=41)
    [listed] = tasks.list_(kb, now=later)
    assert (listed["state"], listed["claimed_by"], listed["claimed_until"]) == ("open", None, None)
    assert [t["id"] for t in tasks.list_(kb, state="open", now=later)] == [task["id"]]
    taken = tasks.claim(kb, agent=OTHER, now=later)                                  # истёкшую берёт другой
    assert taken["id"] == task["id"] and taken["claimed_by"] == OTHER
    with pytest.raises(tasks.TaskError) as e:
        tasks.done(kb, task["id"], agent=MODEL, now=later)
    assert e.value.code == "claimed"


def test_release_only_by_holder_even_after_expiry(kb, note):
    task, _ = tasks.create(kb, "parse", note.object_id, note.n, agent=PERSON, now=T0)
    tasks.claim(kb, task["id"], agent=MODEL, now=T0)
    later = T0 + tasks.LEASE + timedelta(minutes=1)
    with pytest.raises(tasks.TaskError) as e:
        tasks.release(kb, task["id"], agent=OTHER, now=later)                       # аренда истекла, но не его
    assert e.value.code == "forbidden" and MODEL in str(e.value)
    assert kb.execute("SELECT state, claimed_by FROM task").fetchone() == ("claimed", MODEL)
    released = tasks.release(kb, task["id"], agent=MODEL, now=later)                # держатель — и после истечения
    assert (released["state"], released["claimed_by"]) == ("open", None)
    assert kb.execute("SELECT state, claimed_by FROM task").fetchone() == ("open", None)


def test_release_done_and_closed(kb, note):
    task, _ = tasks.create(kb, "parse", note.object_id, note.n, agent=PERSON, now=T0)
    tasks.claim(kb, task["id"], agent=MODEL, now=T0)
    with pytest.raises(tasks.TaskError) as e:
        tasks.release(kb, task["id"], agent=OTHER, now=T0)
    assert e.value.code == "claimed"
    released = tasks.release(kb, task["id"], agent=MODEL, now=T0)
    assert (released["state"], released["claimed_by"]) == ("open", None)
    assert tasks.release(kb, task["id"], agent=MODEL, now=T0)["state"] == "open"     # повтор — без изменений
    with pytest.raises(tasks.TaskError) as e:
        tasks.done(kb, task["id"], agent=MODEL, now=T0)
    assert e.value.code == "invalid"                                                 # не взята
    tasks.claim(kb, task["id"], agent=MODEL, now=T0)
    result = {"refs": ["atm:019a0000-0000-7000-8000-000000000001"], "note": "три атома"}
    closed = tasks.done(kb, task["id"], agent=MODEL, result=result, now=T0 + timedelta(minutes=5))
    assert (closed["state"], closed["result"], closed["done_at"]) == ("done", result, T0 + timedelta(minutes=5))
    stored = tasks.get(kb, task["id"])
    assert stored["state"] == "done" and stored["result"] == result and stored["claimed_by"] == MODEL
    for action in (tasks.done, tasks.release, tasks.claim):
        with pytest.raises(tasks.TaskError) as e:
            action(kb, task["id"], agent=MODEL)
        assert e.value.code == "closed"
    with pytest.raises(tasks.TaskError) as e:
        tasks.cancel(kb, task["id"], agent=PERSON)
    assert e.value.code == "closed"


def test_cancel_by_creator_or_person(kb, note, store, docs):
    task, _ = tasks.create(kb, "parse", note.object_id, note.n, agent=MODEL, now=T0)
    with pytest.raises(tasks.TaskError) as e:
        tasks.cancel(kb, task["id"], agent=OTHER)
    assert e.value.code == "forbidden"
    cancelled = tasks.cancel(kb, task["id"], agent=MODEL, now=T0)
    assert cancelled["state"] == "cancelled" and cancelled["done_at"] == T0
    other = objects.ingest(kb, store, docs, "заметка.md", agent=PERSON)
    task, _ = tasks.create(kb, "parse", other.object_id, other.n, agent=MODEL, now=T0)
    tasks.claim(kb, task["id"], agent=OTHER, now=T0)
    assert tasks.cancel(kb, task["id"], agent=PERSON)["state"] == "cancelled"        # человек — любую
    assert tasks.list_(kb) == []                                                      # без state — незакрытые
    assert [t["state"] for t in tasks.list_(kb, state="cancelled")] == ["cancelled", "cancelled"]


def test_claim_and_done_are_for_the_model(kb, note):
    task, _ = tasks.create(kb, "parse", note.object_id, note.n, agent=PERSON)
    for action in (tasks.claim, tasks.release, tasks.done):
        with pytest.raises(tasks.TaskError) as e:
            action(kb, task["id"], agent=PERSON)
        assert e.value.code == "forbidden"
    with pytest.raises(tasks.TaskError) as e:
        tasks.claim(kb, "не-uuid", agent=MODEL)
    assert e.value.code == "invalid"
    with pytest.raises(tasks.TaskError) as e:
        tasks.claim(kb, uuid7(), agent=MODEL)
    assert e.value.code == "not_found"


def test_list_filters_and_agent_view(kb, note, store, docs):
    other = objects.ingest(kb, store, docs, "заметка.md", agent=PERSON)
    first, _ = tasks.create(kb, "parse", note.object_id, note.n, agent=PERSON, now=T0)
    second, _ = tasks.create(kb, "parse", other.object_id, other.n, agent=PERSON, now=T0 + timedelta(seconds=1))
    tasks.claim(kb, second["id"], agent=OTHER, now=T0)
    assert [t["id"] for t in tasks.list_(kb, now=T0)] == [second["id"], first["id"]]         # от новых
    assert [t["id"] for t in tasks.list_(kb, object_id=other.object_id, now=T0)] == [second["id"]]
    assert [t["id"] for t in tasks.list_(kb, state="claimed", now=T0)] == [second["id"]]
    assert [t["id"] for t in tasks.list_(kb, agent=MODEL, now=T0)] == [first["id"]]          # чужая взятая — нет
    assert [t["id"] for t in tasks.list_(kb, agent=OTHER, now=T0)] == [second["id"], first["id"]]
    tasks.cancel(kb, first["id"], agent=PERSON, now=T0)
    assert [t["id"] for t in tasks.list_(kb, now=T0)] == [second["id"]]                       # закрытые — по state
    assert [t["id"] for t in tasks.list_(kb, state="cancelled", now=T0)] == [first["id"]]
    with pytest.raises(tasks.TaskError):
        tasks.list_(kb, state="busy")


def test_api_task_operations(kb, note):
    made, created = api.task_create(kb, agent=PERSON, kind="parse", object=f"obj:{note.object_id}",
                                    version=str(note.n), note="узел <private>скрытое</private>")
    assert created and set(made) == {"task_id"}
    [view] = api.task_list(kb, object=str(note.object_id))
    assert view["id"] == made["task_id"] and view["object"] == str(note.object_id) and view["note"] == "узел "
    assert set(view) == {"id", "kind", "object", "version", "note", "state", "created_by", "claimed_by",
                         "claimed_until"}
    for bad in ({"kind": None}, {"kind": "x"}, {"object": "мусор"}, {"version": 0}, {"version": None},
                {"note": "x" * (api.TASK_NOTE_MAX + 1)}):
        args = {"kind": "parse", "object": str(note.object_id), "version": note.n, **bad}
        with pytest.raises(api.BadRequest):
            api.task_create(kb, agent=PERSON, **args)
    claimed = api.task_claim(kb, agent=MODEL)
    assert claimed["id"] == made["task_id"] and claimed["state"] == "claimed" and claimed["created_at"]
    with pytest.raises(api.BadRequest):
        api.task_done(kb, made["task_id"], agent=MODEL, result=["atm:x"])
    out = api.task_done(kb, made["task_id"], agent=MODEL, result={"refs": [], "note": "a<private>b</private>"})
    done = out["task"]
    assert done["state"] == "done" and done["result"] == {"refs": [], "note": "a"}
    assert [(w["code"], w["path"]) for w in out["warnings"]] == [("private_removed", "note")]
    with pytest.raises(api.BadRequest):
        api.task_list(kb, state="busy")


# --- миграция 0012 ---

def test_migration_0012_over_base_with_data(pg, tmp_path, monkeypatch, store, docs):
    """База на 0011 с объектом: 0012 добавляет пустую таблицу task, задачи ставятся о прежних версиях; task — в
    счётчиках бэкапа."""
    old = tmp_path / "sql"
    shutil.copytree(db.SQL_DIR, old)
    (old / "0012_tasks.sql").unlink()
    (old / "0013_rename_amemo.sql").unlink()        # база на 0011: обе позже
    with monkeypatch.context() as m:
        m.setattr(db, "SQL_DIR", old)
        db.prepare(pg)
        version = objects.ingest(pg, store, docs, "Заметки/узел.md", agent=PERSON)
    assert db.prepare(pg) == ["0012_tasks.sql", "0013_rename_amemo.sql"]
    assert pg.execute("SELECT count(*) FROM task").fetchone()[0] == 0
    task, created = tasks.create(pg, "parse", version.object_id, version.n, agent=PERSON)
    assert created and "task" in backup.COUNTED
    with pytest.raises(psycopg.errors.CheckViolation):
        pg.execute("INSERT INTO task (id, kind, object_id, version, state, created_by, created_at) "
                   "VALUES (%s, 'parse', %s, %s, 'open', %s, now())",
                   ("00000000-0000-4000-8000-000000000000", version.object_id, version.n, PERSON))
    with pytest.raises(psycopg.errors.CheckViolation):
        pg.execute("UPDATE task SET state = 'claimed' WHERE id = %s", (task["id"],))     # claimed без держателя
    with pytest.raises(psycopg.errors.CheckViolation):
        pg.execute("UPDATE task SET state = 'done' WHERE id = %s", (task["id"],))        # done без done_at
    with pytest.raises(psycopg.errors.UniqueViolation):
        pg.execute("INSERT INTO task (id, kind, object_id, version, state, created_by, created_at) "
                   "VALUES (%s, 'parse', %s, %s, 'open', %s, now())", (uuid7(), version.object_id, version.n, PERSON))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        pg.execute("INSERT INTO task (id, kind, object_id, version, state, created_by, created_at) "
                   "VALUES (%s, 'parse', %s, 99, 'open', %s, now())", (uuid7(), version.object_id, PERSON))
