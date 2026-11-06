"""Низкоуровневые опоры подборок: запись с заданным id, принятие объекта с версиями и файлом."""
import hashlib
import uuid

import pytest

from amem import db, lookup, objects, records
from amem.ids import uuid7
from amem.records import Item

AGENT = "person:alice"


def note(text="Текст.", **extra) -> dict:
    """Заметка человека без документа: basis author снимает требование источника."""
    return {"kind": "note", "label": {"ru": "Заметка"}, "summary_plain": {"ru": text}, "basis": "author", **extra}


def test_keep_ids_creates_record_with_given_id(pg):
    db.prepare(pg)
    rid = uuid7()
    done = records.commit(pg, [Item("atom", note(), record_id=rid)], agent=AGENT, keep_ids=True)
    assert done.revisions[0].record_id == rid and done.revisions[0].n == 1 and done.revisions[0].created
    assert lookup.get(pg, "atom", rid)["label"] == {"ru": "Заметка"}
    log = pg.execute("SELECT status FROM status_log WHERE record_id = %s", (rid,)).fetchall()
    assert log == [("draft",)]                                   # статус новой записи — один раз, при создании


def test_keep_ids_new_record_with_ref_and_status(pg):
    db.prepare(pg)
    rid = uuid7()
    done = records.commit(pg, [Item("atom", note(ref="@n"), record_id=rid, status="verified")],
                          agent=AGENT, keep_ids=True)
    assert done.refs == {"@n": f"atm:{rid}"}
    assert pg.execute("SELECT status FROM atom WHERE id = %s", (rid,)).fetchone()[0] == "verified"


def test_without_keep_ids_unknown_record_id_is_error(pg):
    db.prepare(pg)
    with pytest.raises(records.RecordError, match="такой записи нет"):
        records.commit(pg, [Item("atom", note(), record_id=uuid7())], agent=AGENT)
    assert pg.execute("SELECT count(*) FROM atom").fetchone()[0] == 0


def test_keep_ids_existing_record_gets_new_revision(pg):
    db.prepare(pg)
    rid = uuid7()
    records.commit(pg, [Item("atom", note(), record_id=rid)], agent=AGENT, keep_ids=True)
    same = records.commit(pg, [Item("atom", note(), record_id=rid)], agent=AGENT, keep_ids=True)
    assert not same.revisions[0].created
    done = records.commit(pg, [Item("atom", note("Другой."), record_id=rid)], agent=AGENT, keep_ids=True)
    assert done.revisions[0].n == 2


def test_keep_ids_checks_id_format_and_other_target(pg):
    db.prepare(pg)
    with pytest.raises(records.RecordError, match="UUIDv7"):
        records.commit(pg, [Item("atom", note(), record_id=uuid.uuid4())], agent=AGENT, keep_ids=True)
    entity = records.commit(pg, [Item("entity", {"entity_class": "document", "label": {"ru": "Документ"}})],
                            agent=AGENT).revisions[0].record_id
    with pytest.raises(records.RecordError, match="уже занят"):
        records.commit(pg, [Item("atom", note(), record_id=entity)], agent=AGENT, keep_ids=True)
    assert pg.execute("SELECT count(*) FROM atom").fetchone()[0] == 0


def _file(tmp_path, name: str, raw: bytes):
    file = tmp_path / name
    file.write_bytes(raw)
    return file, "sha256:" + hashlib.sha256(raw).hexdigest()


def _record(oid, *versions) -> dict:
    return {"id": str(oid), "kind": "file", "original_name": "hello.txt", "media_type": "text/plain",
            "logical_paths": ["notes/hello.txt"],
            "versions": [{"n": n, "digest": d, "size": s, "recorded_at": "2026-01-01T00:00:00+00:00"}
                         for n, d, s in versions]}


def test_adopt_object_with_versions_and_file(pg, store, tmp_path):
    db.prepare(pg)
    oid = uuid7()
    file, digest = _file(tmp_path, "hello.txt", b"hello")
    record = _record(oid, (1, digest, 5))
    assert objects.adopt(pg, store, record, files={digest: file}, agent=AGENT) == []
    got = lookup.get_object(pg, oid)
    assert got["versions"][0]["digest"] == digest and got["logical_paths"] == ["notes/hello.txt"]
    assert store.head(oid) == 1 and store.content(oid, 1).read_bytes() == b"hello"
    assert objects.adopt(pg, store, record, files={}, agent=AGENT) == []          # повтор — ничего не меняет
    assert store.head(oid) == 1 and lookup.get_object(pg, oid) == got
    bad = _record(oid, (1, "sha256:" + "0" * 64, 5))
    with pytest.raises(objects.ObjectError, match="digest версии 1 не совпадает"):
        objects.adopt(pg, store, bad, files={}, agent=AGENT)
    with pytest.raises(objects.ObjectError, match="вид file, в подборке web"):
        objects.adopt(pg, store, {**record, "kind": "web"}, files={}, agent=AGENT)


def test_adopt_without_files_and_new_version_later(pg, store, tmp_path):
    db.prepare(pg)
    oid = uuid7()
    file1, d1 = _file(tmp_path, "v1.txt", b"one")
    file2, d2 = _file(tmp_path, "v2.txt", b"two!")
    objects.adopt(pg, store, _record(oid, (1, d1, 3)), files={}, agent=AGENT)
    assert store.head(oid) == 0                                    # версия без файла — без копии
    warnings = objects.adopt(pg, store, _record(oid, (1, d1, 3), (2, d2, 4)), files={d2: file2}, agent=AGENT)
    assert store.head(oid) == 0 and len(warnings) == 1 and "версии 2" in warnings[0]
    assert [v["n"] for v in lookup.get_object(pg, oid)["versions"]] == [1, 2]
    other = uuid7()                                                # обе версии с файлами — по порядку
    file3, d3 = _file(tmp_path, "v3.txt", b"three")
    file4, d4 = _file(tmp_path, "v4.txt", b"four")
    assert objects.adopt(pg, store, {**_record(other, (1, d3, 5), (2, d4, 4)), "logical_paths": []},
                         files={d3: file3, d4: file4}, agent=AGENT) == []
    assert store.head(other) == 2 and store.content(other, 2).read_bytes() == b"four"


def test_adopt_refuses_digest_of_other_object_and_bad_agent(pg, store, tmp_path):
    db.prepare(pg)
    _, digest = _file(tmp_path, "a.txt", b"same")
    first = uuid7()
    objects.adopt(pg, store, _record(first, (1, digest, 4)), files={}, agent=AGENT)
    with pytest.raises(objects.ObjectError, match="digest .* уже у объекта"):
        objects.adopt(pg, store, {**_record(uuid7(), (1, digest, 4)), "logical_paths": []}, files={}, agent=AGENT)
    with pytest.raises(objects.ObjectError, match="агент"):
        objects.adopt(pg, store, _record(uuid7(), (1, digest, 4)), files={}, agent="alice")
    assert pg.execute("SELECT count(*) FROM object").fetchone()[0] == 1


def test_adopt_path_of_other_object_is_warning(pg, store, tmp_path):
    db.prepare(pg)
    _, d1 = _file(tmp_path, "a.txt", b"a")
    _, d2 = _file(tmp_path, "b.txt", b"b")
    objects.adopt(pg, store, _record(uuid7(), (1, d1, 1)), files={}, agent=AGENT)
    oid = uuid7()
    warnings = objects.adopt(pg, store, _record(oid, (1, d2, 1)), files={}, agent=AGENT)
    assert len(warnings) == 1 and "notes/hello.txt" in warnings[0]
    assert "logical_paths" not in lookup.get_object(pg, oid)


def test_adopt_new_version_queues_source_changed(pg, store, docs, tmp_path):
    """Новая версия известного объекта — как у ingest: ревизии со ссылкой на прежнюю получают source_changed."""
    from check_support import atom
    from amem import check
    db.prepare(pg)
    result = check.submit(pg, store, docs, [check.Proposal("atom", atom("@a"))], agent=AGENT)
    oid = lookup.get_object(pg, lookup.object_by_path(pg, "Заметки/узел.md"))
    file, digest = _file(tmp_path, "узел.md", "# Узел\nНовый текст.\n".encode())
    record = {**oid, "versions": [*oid["versions"], {"n": 2, "digest": digest, "size": file.stat().st_size,
                                                     "recorded_at": "2026-01-02T00:00:00+00:00"}]}
    objects.adopt(pg, store, record, files={digest: file}, agent=AGENT)
    assert store.head(oid["id"]) == 2
    reasons = [r for (r,) in pg.execute("SELECT reason FROM review_item WHERE closed_at IS NULL")]
    assert "source_changed" in reasons, result


def test_adopt_without_files_then_ingest_works(pg, store, docs, tmp_path):
    """Подборка без файлов создаёт корень хранилища: ingest после неё не принимает его за неподключённый том."""
    db.prepare(pg)
    _, digest = _file(tmp_path, "a.txt", b"remote")
    objects.adopt(pg, store, _record(uuid7(), (1, digest, 6)), files={}, agent=AGENT)
    assert objects.ingest(pg, store, docs, "Заметки/узел.md", agent=AGENT).created
