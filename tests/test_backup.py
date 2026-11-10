"""Бэкап на PostgreSQL 18: дамп с манифестом из одного снимка, пароль только в окружении процесса, атомарные
пары, ротация, полный снимок с копией OCFL и границы путей. Нужен клиент PostgreSQL 18 (AMEMO_PG_BIN или PATH)."""
import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from amemo import backup, db, ids, objects, recipes, records, usefulness
from amemo.backup import BackupError
from amemo.ocfl_store import ObjectStore
from amemo.records import Item
from ocfl_check import validate

AGENT = "model:test"
PDF = "НД/СП 99.pdf"
NOW = datetime(2026, 11, 5, 8, 0, 0, tzinfo=timezone.utc)


def fill(dsn: str, store_root, docs) -> dict:
    """Маленькая база: сущность, атомы с источником-файлом, связь, отметка полезности."""
    with db.connect(dsn) as conn:
        db.prepare(conn)
        store = ObjectStore(store_root)
        resolved = objects.resolve_sources(conn, store, docs, {"sources": [{"path": PDF, "quote": "Таблица 1.1"}]},
                                           agent=AGENT)
        written = records.commit(conn, [
            Item("entity", {"ref": "@doc", "entity_class": "document", "key": "sp99", "label": {"ru": "СП 99"}}),
            Item("atom", {"ref": "@wind", "kind": "fact", "key": "wind", "label": {"ru": "Ветровое давление района"},
                          "summary_plain": {"ru": "Давление ветра"}, "about": ["@doc"],
                          "sources": resolved["sources"]}),
            Item("atom", {"ref": "@note", "kind": "lesson", "key": "note", "label": {"ru": "Кронштейн на анкерах"},
                          "summary_plain": {"ru": "Крепление"}}),
        ], [{"rel": "depends_on", "src": "@note", "dst": "@wind", "confidence": 0.8}], agent=AGENT)
        task = ids.uuid7()
        conn.execute("INSERT INTO activity (id, kind, label, started_at) VALUES (%s, 'task', 'Бэкап', now())", (task,))
        found = recipes.exact_fact(conn, "Ветровое давление", agent=AGENT, activity=task)
        usefulness.mark_helpful(conn, found["retrieval_id"], [written.refs["@wind"]], agent=AGENT, activity=task)
        return {"refs": written.refs, "base_id": conn.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()[0]}


def with_user(dsn: str, user: str, password: str) -> str:
    return make_conninfo(**{**conninfo_to_dict(dsn), "user": user, "password": password})


def test_dump_and_manifest_describe_one_snapshot(pgdb, tmp_path, docs):
    src = pgdb()
    filled = fill(src, tmp_path / "objects", docs)

    made = backup.create(src, tmp_path / "bk", now=NOW)

    dump, manifest = tmp_path / "bk" / "2026-11-05T08-00-00Z.dump", tmp_path / "bk" / "2026-11-05T08-00-00Z.json"
    assert made["dump"] == str(dump) and made["manifest"] == str(manifest)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["format"] == 1 and data["kind"] == "amemo.pg_dump" and data["file"] == dump.name
    assert data["size"] == dump.stat().st_size and data["sha256"] == backup._sha256(dump)
    assert data["base_id"] == filled["base_id"] and data["created_at"] == NOW.isoformat()
    assert data["pg_dump_version"].startswith("pg_dump (PostgreSQL) 18")
    with psycopg.connect(src) as conn:
        assert data["server_version"] == conn.execute("SHOW server_version").fetchone()[0]
        assert data["migrations"] == [{"name": n, "sha256": h} for n, h in
                                      conn.execute("SELECT name, sha256 FROM schema_migrations ORDER BY name")]
        for table in backup.COUNTED:
            assert data["counts"][table] == conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0], table
    assert data["counts"]["atom"] == 2 and data["counts"]["atom_use"] == 1 and data["counts"]["object_version"] == 1
    assert data["search_text_version"] == backup.SEARCH_TEXT_VERSION
    assert data["probe"]["ref"] in {filled["refs"]["@wind"], filled["refs"]["@note"]}
    listed = subprocess.run([backup._tool("pg_restore"), "--list", str(dump)], capture_output=True, text=True)
    assert listed.returncode == 0 and "TABLE public atom_revision" in listed.stdout
    assert backup.check(manifest)["sha256"] == data["sha256"]


def test_password_is_only_in_the_process_environment(pgdb, tmp_path, docs, monkeypatch):
    src = pgdb()
    fill(src, tmp_path / "objects", docs)
    role, secret = f"amemo_bk_{uuid.uuid4().hex[:8]}", f"Pw-{uuid.uuid4().hex}"
    with psycopg.connect(src, autocommit=True) as admin:
        admin.execute(f"CREATE ROLE {role} LOGIN SUPERUSER PASSWORD '{secret}'")
    calls = []
    real_run = subprocess.run

    def spy(argv, **kwargs):
        calls.append((list(argv), dict(kwargs.get("env") or {})))
        return real_run(argv, **kwargs)

    try:
        monkeypatch.setattr(backup.subprocess, "run", spy)
        made = backup.create(with_user(src, role, secret), tmp_path / "bk", now=NOW)
        dumps = [(argv, env) for argv, env in calls if os.path.basename(argv[0]) == "pg_dump" and "--version" not in argv]
        assert len(dumps) == 1
        argv, env = dumps[0]
        assert not any(secret in arg for arg in argv) and env["PGPASSWORD"] == secret
        assert secret not in open(made["manifest"], encoding="utf-8").read()

        def failing(argv, **kwargs):
            if "--version" in argv:
                return real_run(argv, **kwargs)
            return subprocess.CompletedProcess(argv, 1, "", f"connection failed: password {secret} rejected")

        monkeypatch.setattr(backup.subprocess, "run", failing)
        with pytest.raises(BackupError, match=r"pg_dump: pg_dump завершился с кодом 1") as error:
            backup.create(with_user(src, role, secret), tmp_path / "bk", now=NOW + timedelta(seconds=1))
        assert secret not in str(error.value) and "***" in str(error.value)
        assert not list((tmp_path / "bk").glob("2026-11-05T08-00-01Z*"))          # сбой не оставил пары и .tmp
    finally:
        monkeypatch.undo()
        with psycopg.connect(src, autocommit=True) as admin:
            admin.execute(f"DROP ROLE IF EXISTS {role}")


def test_existing_copy_is_not_overwritten_and_partial_pairs_are_not_copies(pgdb, tmp_path, docs, monkeypatch):
    src = pgdb()
    fill(src, tmp_path / "objects", docs)
    folder = tmp_path / "bk"
    first = backup.create(src, folder, now=NOW)
    before = open(first["dump"], "rb").read()
    with pytest.raises(BackupError, match="уже есть"):
        backup.create(src, folder, now=NOW)
    assert open(first["dump"], "rb").read() == before

    def crash(path, data, **kwargs):
        raise OSError("сбой при записи манифеста")

    monkeypatch.setattr(backup, "_write_json", crash)
    with pytest.raises(OSError):
        backup.create(src, folder, now=NOW + timedelta(seconds=1))
    monkeypatch.undo()
    assert not list(folder.glob("2026-11-05T08-00-01Z*"))                    # дамп без манифеста убран
    (folder / "2026-11-05T08-00-01Z.dump").write_bytes(b"dump")               # дамп без манифеста после сбоя
    (folder / "2026-11-05T08-00-02Z.dump.tmp").write_bytes(b"half")             # оборванный дамп
    (folder / "2026-11-05T08-00-03Z.dump").write_bytes(b"x")
    (folder / "2026-11-05T08-00-03Z.json").write_text("{broken", encoding="utf-8")   # битый манифест
    (folder / "2026-11-05T08-00-04Z.json").write_text(json.dumps({**json.loads(open(first["manifest"]).read()),
                                                                 "file": "2026-11-05T08-00-04Z.dump"}))  # без дампа
    assert [item["name"] for item in backup.backups(folder)] == ["2026-11-05T08-00-00Z"]
    with pytest.raises(BackupError, match="нет дампа"):
        backup.check(folder / "2026-11-05T08-00-04Z.json")


def test_rotation_keeps_last_complete_pairs_and_runs_only_after_a_good_copy(pgdb, tmp_path, docs, monkeypatch):
    src = pgdb()
    fill(src, tmp_path / "objects", docs)
    folder = tmp_path / "bk"
    for i in range(4):
        backup.create(src, folder, keep=3, now=NOW + timedelta(seconds=i))
    junk = folder / "2026-11-05T07-00-00Z.dump.tmp"
    junk.write_bytes(b"half")
    assert [item["name"] for item in backup.backups(folder)] == [
        "2026-11-05T08-00-01Z", "2026-11-05T08-00-02Z", "2026-11-05T08-00-03Z"]
    assert not (folder / "2026-11-05T08-00-00Z.dump").exists()

    def bad_check(path):
        raise BackupError("новая копия не прошла проверку")

    monkeypatch.setattr(backup, "check", bad_check)
    with pytest.raises(BackupError, match="не прошла проверку"):
        backup.create(src, folder, keep=1, now=NOW + timedelta(seconds=10))
    monkeypatch.undo()
    assert len(backup.backups(folder)) == 3          # старые копии не тронуты, не прошедшая проверку — удалена
    assert not list(folder.glob("2026-11-05T08-00-10Z*"))
    assert backup.rotate(folder, keep=2) == ["2026-11-05T08-00-01Z"]
    assert junk.exists()
    for keep in (0, -1, True, "2"):
        with pytest.raises(BackupError, match="keep"):
            backup.rotate(folder, keep=keep)


def test_snapshot_links_dump_and_objects_by_base_id(pgdb, tmp_path, docs):
    src = pgdb()
    filled = fill(src, tmp_path / "data" / "objects", docs)
    (tmp_path / "data" / ".env").write_text("AMEMO_PG_PASSWORD=secret\n", encoding="utf-8")
    (tmp_path / "data" / "models").mkdir()

    made = backup.snapshot(src, tmp_path / "data" / "objects", tmp_path / "snap", now=NOW)

    root = tmp_path / "snap" / "2026-11-05T08-00-00Z"
    assert made["path"] == str(root) and not (tmp_path / "snap" / "2026-11-05T08-00-00Z.tmp").exists()
    assert sorted(p.name for p in root.iterdir()) == ["manifest.json", "objects", "pg"]
    data = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert data["kind"] == "amemo.snapshot" and data["base_id"] == filled["base_id"]
    assert data["dump"]["manifest"] == "pg/2026-11-05T08-00-00Z.json"
    assert backup.check(root / "pg" / "2026-11-05T08-00-00Z.json")["base_id"] == filled["base_id"]
    with psycopg.connect(src) as conn:
        versions = [{"object": str(o), "n": n, "digest": d} for o, n, d in
                    conn.execute("SELECT object_id, n, digest FROM object_version WHERE digest IS NOT NULL")]
    assert data["objects"]["file_versions"] == versions and len(versions) == 1
    files = {item["path"] for item in data["objects"]["files"]}
    assert files == {p.relative_to(root / "objects").as_posix() for p in (root / "objects").rglob("*") if p.is_file()}
    assert "0=ocfl_1.1" in files and not any(".env" in f or "models" in f for f in files)
    ok, log = validate(root / "objects")
    assert ok, log
    with psycopg.connect(src) as conn:
        object_id, n, digest = conn.execute("SELECT object_id, n, digest FROM object_version").fetchone()
    assert "sha256:" + backup._sha256(ObjectStore(root / "objects").content(object_id, n)) == digest
    with pytest.raises(BackupError, match="уже есть"):
        backup.snapshot(src, tmp_path / "data" / "objects", tmp_path / "snap", now=NOW)


def test_snapshot_failure_leaves_no_ready_directory(pgdb, tmp_path, docs):
    src = pgdb()
    fill(src, tmp_path / "objects", docs)
    (tmp_path / "objects" / "outside").symlink_to(tmp_path)
    with pytest.raises(BackupError, match="символическая ссылка"):
        backup.snapshot(src, tmp_path / "objects", tmp_path / "snap", now=NOW)
    assert list((tmp_path / "snap").iterdir()) == []
    (tmp_path / "objects" / "outside").unlink()
    shutil.rmtree(tmp_path / "objects")
    with pytest.raises(BackupError, match="корня хранилища нет"):
        backup.snapshot(src, tmp_path / "objects", tmp_path / "snap", now=NOW)
    assert list((tmp_path / "snap").iterdir()) == []


@pytest.mark.parametrize("file", ["../2026-11-05T08-00-00Z.dump", "/etc/passwd", "sub/x.dump", "", None])
def test_manifest_file_cannot_point_outside_its_folder(pgdb, tmp_path, docs, file):
    src = pgdb()
    fill(src, tmp_path / "objects", docs)
    made = backup.create(src, tmp_path / "bk", now=NOW)
    manifest = tmp_path / "bk" / "evil.json"
    manifest.write_text(json.dumps({**json.loads(open(made["manifest"]).read()), "file": file}), encoding="utf-8")
    with pytest.raises(BackupError, match="не имя файла|выходит|недопустимый"):
        backup.check(manifest)


def test_tool_must_be_postgresql_18(tmp_path, monkeypatch):
    fake = tmp_path / "pg_dump"
    fake.write_text("#!/bin/sh\necho 'pg_dump (PostgreSQL) 16.4'\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("AMEMO_PG_BIN", str(tmp_path))
    with pytest.raises(BackupError, match="нужна версия 18"):
        backup._tool("pg_dump")
    monkeypatch.setenv("AMEMO_PG_BIN", str(tmp_path / "нет"))
    with pytest.raises(BackupError, match="нужен клиент PostgreSQL 18"):
        backup._tool("pg_dump")


def test_default_rotation_keeps_fourteen_ready_copies(tmp_path):
    """По умолчанию остаются 14 последних готовых пар; .tmp и манифест без дампа в счёт не идут."""
    for i in range(16):
        name = (NOW + timedelta(minutes=i)).strftime("%Y-%m-%dT%H-%M-%SZ")
        (tmp_path / f"{name}.dump").write_bytes(b"x" * i)
        (tmp_path / f"{name}.json").write_text(json.dumps({"kind": "amemo.pg_dump", "format": 1,
                                                           "file": f"{name}.dump", "size": i}), encoding="utf-8")
    (tmp_path / "2026-11-05T09-00-00Z.dump.tmp").write_bytes(b"half")
    (tmp_path / "2026-11-05T09-01-00Z.json").write_text(json.dumps({"kind": "amemo.pg_dump", "format": 1,
                                                                    "file": "2026-11-05T09-01-00Z.dump", "size": 1}))
    removed = backup.rotate(tmp_path)
    assert removed == ["2026-11-05T08-00-00Z", "2026-11-05T08-01-00Z"]
    assert len(backup.backups(tmp_path)) == backup.KEEP == 14
    assert (tmp_path / "2026-11-05T09-00-00Z.dump.tmp").exists() and (tmp_path / "2026-11-05T09-01-00Z.json").exists()


def tools(tmp_path, **scripts) -> Path:
    """Папка с обёртками клиента PostgreSQL: по умолчанию — настоящие, scripts — свои тела shell для pg_dump и т. п.
    В теле $REAL — путь к настоящей программе."""
    real = Path(os.environ["AMEMO_PG_BIN"]) if os.environ.get("AMEMO_PG_BIN") else None
    folder = tmp_path / "pgbin"
    folder.mkdir()
    for name in ("pg_dump", "pg_restore", "psql"):
        path = real / name if real else Path(shutil.which(name))
        body = scripts.get(name, 'exec "$REAL" "$@"')
        (folder / name).write_text(f'#!/bin/sh\nREAL="{path}"\n'
                                   f'case "$1" in --version) exec "$REAL" "$@";; esac\n{body}\n', encoding="utf-8")
        (folder / name).chmod(0o755)
    return folder


def test_rotation_never_removes_the_new_copy_when_the_clock_went_back(pgdb, tmp_path, docs):
    src = pgdb()
    fill(src, tmp_path / "objects", docs)
    backup.create(src, tmp_path / "bk", keep=1, now=NOW + timedelta(days=1))
    made = backup.create(src, tmp_path / "bk", keep=1, now=NOW)
    assert os.path.exists(made["dump"]) and os.path.exists(made["manifest"])
    assert [item["name"] for item in backup.backups(tmp_path / "bk")] == ["2026-11-05T08-00-00Z"]


def test_truncated_dump_is_not_a_ready_copy(pgdb, tmp_path, docs):
    src = pgdb()
    fill(src, tmp_path / "objects", docs)
    made = backup.create(src, tmp_path / "bk", now=NOW)
    with open(made["dump"], "r+b") as f:
        f.truncate(os.path.getsize(made["dump"]) - 1)
    assert backup.backups(tmp_path / "bk") == []


def test_dump_survives_idle_in_transaction_timeout(pgdb, tmp_path, docs, monkeypatch):
    """Транзакция снимка ждёт pg_dump дольше таймаута простоя базы — и не обрывается."""
    src = pgdb()
    fill(src, tmp_path / "objects", docs)
    with psycopg.connect(src, autocommit=True) as conn:
        dbname = conn.info.dbname
        conn.execute(f'ALTER DATABASE "{dbname}" SET idle_in_transaction_session_timeout = \'1s\'')
    monkeypatch.setenv("AMEMO_PG_BIN", str(tools(tmp_path, pg_dump='sleep 3; exec "$REAL" "$@"')))
    made = backup.create(src, tmp_path / "bk", now=NOW)
    assert backup.check(made["manifest"])["counts"]["atom"] == 2


def test_dump_and_counts_come_from_one_snapshot(pgdb, tmp_path, docs, monkeypatch):
    """Атом, записанный после снимка, но до pg_dump, не попадает ни в дамп, ни в числа манифеста."""
    src, dst = pgdb(), pgdb()
    fill(src, tmp_path / "objects", docs)
    real_facts = backup._facts

    def facts_then_write(conn):
        found = real_facts(conn)
        with db.connect(src) as other:
            records.commit(other, [Item("atom", {"kind": "fact", "label": {"ru": "Позже снимка"}})], agent=AGENT)
        return found

    monkeypatch.setattr(backup, "_facts", facts_then_write)
    made = backup.create(src, tmp_path / "bk", now=NOW)
    monkeypatch.undo()
    assert made["counts"]["atom"] == 2
    assert backup.restore(made["manifest"], dst)["counts"]["atom"] == 2


def test_snapshot_refuses_a_folder_that_is_not_an_ocfl_root(pgdb, tmp_path, docs):
    src = pgdb()
    fill(src, tmp_path / "data" / "objects", docs)
    (tmp_path / "data" / ".env").write_text("SECRET=1\n", encoding="utf-8")
    with pytest.raises(BackupError, match="не корень OCFL"):
        backup.snapshot(src, tmp_path / "data", tmp_path / "snap", now=NOW)
    assert not (tmp_path / "snap").exists()


def test_snapshot_refuses_special_files_and_missing_versions(pgdb, tmp_path, docs):
    src = pgdb()
    fill(src, tmp_path / "objects", docs)
    fifo = tmp_path / "objects" / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(BackupError, match="не файл и не папка"):
        backup.snapshot(src, tmp_path / "objects", tmp_path / "snap", now=NOW)
    fifo.unlink()
    with psycopg.connect(src) as conn:
        object_id, n = conn.execute("SELECT object_id, n FROM object_version WHERE digest IS NOT NULL").fetchone()
    ObjectStore(tmp_path / "objects").content(object_id, n).unlink()          # копия версии пропала из хранилища
    with pytest.raises(BackupError, match=f"снимок: (нет )?верси[яи] {n} объекта obj:{object_id}"):
        backup.snapshot(src, tmp_path / "objects", tmp_path / "snap", now=NOW)
    assert list((tmp_path / "snap").iterdir()) == []
