"""Восстановление на PostgreSQL 18 и 16: дамп и полный снимок — в пустую базу и папку; тот же base_id, миграции, записи,
отметки и поисковая выдача; старый источник открывает прежнюю версию файла; verify — настоящее пробное восстановление.
Нужен клиент PostgreSQL 18 (AMEM_PG_BIN или PATH)."""
import json
import shutil
from pathlib import Path
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from amem import backup, db, embed, ids, lookup, objects, recipes, records, search
from amem.backup import BackupError
from amem.ocfl_store import ObjectStore
from amem.records import Item
from conftest import FakeProvider
from ocfl_check import validate
from test_backup import AGENT, NOW, PDF, fill

def rows(conn, sql):
    return conn.execute(sql).fetchall()


def projection(conn):
    return rows(conn, "SELECT target, record_id, revision_id, content_hash, document, search_vector::text, codes "
                      "FROM search_document ORDER BY target, record_id") + rows(conn, "SELECT * FROM search_code ORDER BY 1, 2, 3")


def vectors_of(conn):
    return rows(conn, "SELECT target, revision_id, model_id, text_hash, vec::text FROM embedding ORDER BY 1, 2, 3")


LATER = datetime.now(timezone.utc) + timedelta(days=1)          # одно «сейчас» для счёта полезности до и после


def search_items(conn, query, provider):
    result = recipes.exact_fact(conn, query, agent=AGENT, provider=provider, usefulness=True, now=LATER)
    return [(item["ref"], round(item["score"], 9)) for item in result["items"]], result["semantic"]


def test_dump_restores_records_marks_and_search(pgdb, tmp_path, docs):
    src, dst = pgdb(), pgdb()
    filled = fill(src, tmp_path / "objects", docs)
    provider = FakeProvider()
    with db.connect(src) as conn:
        model = embed.register_model(conn, provider)
        embed.sync_embeddings(conn, model["id"], provider)
        embed.activate_model(conn, model["id"])
        before_search = search_items(conn, "Ветровое давление", provider)
        before_projection = projection(conn)
        vectors = vectors_of(conn)
    made = backup.create(src, tmp_path / "bk", now=NOW)

    report = backup.restore(made["manifest"], dst)

    assert report["base_id"] == filled["base_id"] and report["counts"] == made["counts"]
    assert report["migrations"] == [m["name"] for m in made["migrations"]]
    with db.connect(dst) as conn:
        assert vectors_of(conn) == vectors
        assert search_items(conn, "Ветровое давление", provider) == before_search
        assert before_search[1] == "used"
        assert projection(conn) == before_projection
        search.rebuild_search(conn)                                     # перестройка не меняет проекцию
        assert projection(conn) == before_projection
        conn.execute("DELETE FROM embedding")                           # производные вектора потеряны
        provider.calls.clear()
        embed.sync_embeddings(conn, model["id"], provider)
        assert provider.calls and vectors_of(conn) == vectors
        assert backup._facts(conn)["counts"] == made["counts"]          # знания не изменились


def test_snapshot_restore_opens_the_old_file_version(pgdb, tmp_path, docs):
    src, dst = pgdb(), pgdb()
    fill(src, tmp_path / "objects", docs)
    old = (docs / PDF).read_bytes()
    (docs / PDF).write_bytes(old + "\n% ред. 2".encode())
    with db.connect(src) as conn:
        newer = objects.ingest(conn, ObjectStore(tmp_path / "objects"), docs, PDF, agent=AGENT)
        assert newer.n == 2
        wind = conn.execute("SELECT id FROM atom WHERE key = 'wind'").fetchone()[0]
        [old_revision] = lookup.history(conn, "atom", wind)
    snap = backup.snapshot(src, tmp_path / "objects", tmp_path / "snap", now=NOW)

    report = backup.restore(snap["path"], dst, objects_root=tmp_path / "restored" / "objects")

    assert report["objects"]["file_versions"] == 2
    ok, log = validate(tmp_path / "restored" / "objects")
    assert ok, log
    store = ObjectStore(tmp_path / "restored" / "objects")
    with db.connect(dst) as conn:
        [source] = lookup.revision_sources(conn, "atom", old_revision["id"])
        assert source["object_version"] == 1
        assert store.content(source["object"].split(":", 1)[1], 1).read_bytes() == old
        assert store.content(source["object"].split(":", 1)[1], 2).read_bytes() == old + "\n% ред. 2".encode()


def test_restore_refuses_unsafe_targets_before_writing(pgdb, tmp_path, docs, monkeypatch):
    src, busy, empty = pgdb(), pgdb(), pgdb()
    fill(src, tmp_path / "objects", docs)
    with db.connect(busy) as conn:
        db.prepare(conn)
    made = backup.create(src, tmp_path / "bk", now=NOW)
    snap = backup.snapshot(src, tmp_path / "objects", tmp_path / "snap", now=NOW + timedelta(seconds=1))
    called = []
    real_run = backup._run

    def spy(argv, env, password, stage):
        called.append(stage)
        return real_run(argv, env, password, stage)

    monkeypatch.setattr(backup, "_run", spy)

    with pytest.raises(BackupError, match="целевая база не пустая"):
        backup.restore(made["manifest"], busy)
    (tmp_path / "taken").mkdir()
    (tmp_path / "taken" / "file").write_text("x", encoding="utf-8")
    with pytest.raises(BackupError, match="папка объектов не пустая"):
        backup.restore(snap["path"], empty, objects_root=tmp_path / "taken")
    with pytest.raises(BackupError, match="в дампе без снимка нет хранилища"):
        backup.restore(made["manifest"], empty, objects_root=tmp_path / "new")

    broken = tmp_path / "broken"
    shutil.copytree(tmp_path / "bk", broken)
    dump = broken / "2026-11-05T08-00-00Z.dump"
    raw = bytearray(dump.read_bytes())
    raw[len(raw) // 2] ^= 0xFF
    dump.write_bytes(bytes(raw))
    with pytest.raises(BackupError, match="не совпадает с манифестом"):
        backup.restore(broken / "2026-11-05T08-00-00Z.json", empty)

    foreign = tmp_path / "foreign.json"
    foreign.write_text(json.dumps({**json.loads(open(made["manifest"]).read()), "kind": "other"}), encoding="utf-8")
    with pytest.raises(BackupError, match="неизвестный формат"):
        backup.restore(foreign, empty)
    partial = tmp_path / "bk" / "partial.json"
    data = json.loads(open(made["manifest"]).read())
    del data["base_id"]
    partial.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(BackupError, match="нет base_id"):
        backup.restore(partial, empty)

    tampered = tmp_path / "tampered"
    shutil.copytree(snap["path"], tampered)
    manifest = json.loads((tampered / "manifest.json").read_text(encoding="utf-8"))
    some = next(item for item in manifest["objects"]["files"] if "/content/" in item["path"])
    (tampered / "objects" / some["path"]).write_bytes(b"other")
    with pytest.raises(BackupError, match="не совпадает с манифестом"):
        backup.restore(tampered, empty, objects_root=tmp_path / "new")
    escaping = tmp_path / "escaping"
    shutil.copytree(snap["path"], escaping)
    manifest["objects"]["files"].append({"path": "../../etc/passwd", "size": 1, "sha256": "0" * 64})
    (escaping / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BackupError, match="выходит за корень"):
        backup.restore(escaping, empty, objects_root=tmp_path / "new")
    sneaky = tmp_path / "sneaky"                                   # «..» нельзя, даже если путь остаётся внутри
    shutil.copytree(snap["path"], sneaky)
    inner = json.loads((sneaky / "manifest.json").read_text(encoding="utf-8"))
    inner["objects"]["files"][0]["path"] = "extensions/../" + inner["objects"]["files"][0]["path"]
    (sneaky / "manifest.json").write_text(json.dumps(inner), encoding="utf-8")
    with pytest.raises(BackupError, match="выходит за корень"):
        backup.restore(sneaky, empty, objects_root=tmp_path / "new")
    extra = tmp_path / "extra"
    shutil.copytree(snap["path"], extra)
    (extra / "objects" / "лишний.txt").write_text("x", encoding="utf-8")
    with pytest.raises(BackupError, match="лишние или недостающие"):
        backup.restore(extra, empty, objects_root=tmp_path / "new")

    assert called == []                                           # до pg_restore ни один отказ не дошёл
    assert not (tmp_path / "new").exists()
    with psycopg.connect(empty) as conn:
        assert conn.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'").fetchone()[0] == 0


def test_verify_restores_into_a_temporary_database_and_searches(pgdb, tmp_path, docs):
    src = pgdb()
    fill(src, tmp_path / "objects", docs)
    made = backup.create(src, tmp_path / "bk", now=NOW)
    snap = backup.snapshot(src, tmp_path / "objects", tmp_path / "snap", now=NOW + timedelta(seconds=1))
    with psycopg.connect(src) as conn:
        counts = backup._facts(conn)["counts"]
    temporary = "SELECT datname FROM pg_database WHERE datname LIKE 'amem\\_verify\\_%' ORDER BY 1"
    with psycopg.connect(src) as conn:
        before = conn.execute(temporary).fetchall()

    for source in (made["manifest"], snap["path"]):
        report = backup.verify(source, src)
        assert report["search"]["found"] is True and report["search"]["probe"]["query"]
        assert report["counts"] == made["counts"]

    with psycopg.connect(src) as conn:
        assert backup._facts(conn)["counts"] == counts                   # рабочая база не изменилась
        assert conn.execute(temporary).fetchall() == before                 # временных баз не осталось
    assert sorted(p.name for p in (tmp_path / "snap").iterdir()) == [Path(snap["path"]).name]   # снимок не тронут

    broken = tmp_path / "broken"
    shutil.copytree(tmp_path / "bk", broken)
    dump = broken / "2026-11-05T08-00-00Z.dump"
    dump.write_bytes(dump.read_bytes()[:-100])
    with pytest.raises(BackupError, match="verify: восстановление: .*не совпадает с манифестом") as error:
        backup.verify(broken / "2026-11-05T08-00-00Z.json", src)
    assert "password" not in str(error.value)
    with psycopg.connect(src) as conn:
        assert conn.execute(temporary).fetchall() == before                 # временных баз не осталось


def test_failed_database_restore_leaves_no_objects_folder(pgdb, tmp_path, docs, monkeypatch):
    """Объекты встают на место только после восстановленной и сверенной базы: сбой базы не оставляет полуготовой папки."""
    src, dst = pgdb(), pgdb()
    fill(src, tmp_path / "objects", docs)
    snap = backup.snapshot(src, tmp_path / "objects", tmp_path / "snap", now=NOW)

    def broken(*args, **kwargs):
        raise BackupError("pg_restore: сбой посреди восстановления")

    monkeypatch.setattr(backup, "_run", broken)
    monkeypatch.setattr(backup, "_restore_via_sql", broken)
    with pytest.raises(BackupError, match="сбой посреди восстановления"):
        backup.restore(snap["path"], dst, objects_root=tmp_path / "restored" / "objects")
    assert list((tmp_path / "restored").iterdir()) == []


def test_restored_counts_must_match_the_manifest(pgdb, tmp_path, docs):
    """Манифест с другими числами записей (дамп тот же) — восстановление останавливается сверкой после pg_restore."""
    src, dst = pgdb(), pgdb()
    fill(src, tmp_path / "objects", docs)
    made = backup.create(src, tmp_path / "bk", now=NOW)
    data = json.loads(open(made["manifest"], encoding="utf-8").read())
    data["counts"]["atom"] += 1
    edited = tmp_path / "bk" / "edited.json"
    edited.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(BackupError, match="counts не совпадает с манифестом"):
        backup.restore(edited, dst)
