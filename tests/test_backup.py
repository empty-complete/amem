"""Бэкап на PostgreSQL 18 и 16: дамп с манифестом из одного снимка, пароль только в окружении процесса, атомарные
пары, ротация, полный снимок с копией OCFL и границы путей. Нужен клиент PostgreSQL 18 (AMEM_PG_BIN или PATH)."""
import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from amem import backup, db, ids, objects, recipes, records, usefulness
from amem.backup import BackupError
from amem.ocfl_store import ObjectStore
from amem.records import Item
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
    assert data["format"] == 1 and data["kind"] == "amem.pg_dump" and data["file"] == dump.name
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
    role, secret = f"amem_bk_{uuid.uuid4().hex[:8]}", f"Pw-{uuid.uuid4().hex}"
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

    def crash(path, data):
        raise OSError("сбой процесса при записи манифеста")

    monkeypatch.setattr(backup, "_write_json", crash)
    with pytest.raises(OSError):
        backup.create(src, folder, now=NOW + timedelta(seconds=1))           # дамп есть, манифеста нет
    monkeypatch.undo()
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
    assert len(backup.backups(folder)) == 4          # старые копии не тронуты, новая — лишь дописана
    assert backup.rotate(folder, keep=2) == ["2026-11-05T08-00-01Z", "2026-11-05T08-00-02Z"]
    assert junk.exists()
    for keep in (0, -1, True, "2"):
        with pytest.raises(BackupError, match="keep"):
            backup.rotate(folder, keep=keep)


def test_snapshot_links_dump_and_objects_by_base_id(pgdb, tmp_path, docs):
    src = pgdb()
    filled = fill(src, tmp_path / "data" / "objects", docs)
    (tmp_path / "data" / ".env").write_text("AMEM_PG_PASSWORD=secret\n", encoding="utf-8")
    (tmp_path / "data" / "models").mkdir()

    made = backup.snapshot(src, tmp_path / "data" / "objects", tmp_path / "snap", now=NOW)

    root = tmp_path / "snap" / "2026-11-05T08-00-00Z"
    assert made["path"] == str(root) and not (tmp_path / "snap" / "2026-11-05T08-00-00Z.tmp").exists()
    assert sorted(p.name for p in root.iterdir()) == ["manifest.json", "objects", "pg"]
    data = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert data["kind"] == "amem.snapshot" and data["base_id"] == filled["base_id"]
    assert data["dump"]["manifest"] == "pg/2026-11-05T08-00-00Z.json"
    assert backup.check(root / "pg" / "2026-11-05T08-00-00Z.json")["base_id"] == filled["base_id"]
    assert data["objects"]["file_versions"] == 1
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
    monkeypatch.setenv("AMEM_PG_BIN", str(tmp_path))
    with pytest.raises(BackupError, match="нужна версия 18"):
        backup._tool("pg_dump")
    monkeypatch.setenv("AMEM_PG_BIN", str(tmp_path / "нет"))
    with pytest.raises(BackupError, match="нужен клиент PostgreSQL 18"):
        backup._tool("pg_dump")
