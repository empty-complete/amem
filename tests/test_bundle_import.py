"""Импорт подборки: id сохраняются, повтор идемпотентен, расхождение — pending, trust, пакеты, коллизии, dry_run,
история, объекты и итоги сверки, связи, блокировки и сбои записи (спецификация 3c, разд. 4.3)."""
import hashlib
import json
import os
import threading
import time
from pathlib import Path

import pytest
from psycopg.pq import TransactionStatus

from amemo import bundle, canon, check, db, folders, lookup, objects, packs, records, review
from amemo.check import Proposal, level2
from amemo.ocfl_store import ObjectStore, StoreError
from check_support import atom, entity, source_md, value
from v1_support import same_database

PACKS = Path(__file__).with_name("packs")
PERSON, OTHER = "person:alice", "person:bob"
ENV = os.pathsep.join([str(PACKS / "quantities"), str(PACKS / "ontology")])


def _prepare(conn, monkeypatch, env=ENV):
    monkeypatch.setenv("AMEMO_PACKS", env)
    db.prepare(conn)


def _refs(r) -> dict[str, str]:
    return {rec["label"]: str(rec["record_id"]) for rec in r.records}


def _seed(conn, store, docs):
    """Датчик с ключом, его параметр с источником-файлом, заметка человека и связь заметки с параметром."""
    r = check.submit(conn, store, docs, [
        Proposal("entity", entity("@s", cls="sensor", key="sensor_1")),
        Proposal("atom", atom("@m", kind="parameter", about=["@s"], tags=["shared"],
                              sources=[source_md("заметка.md", "Масса 3 кг")],
                              content={"values": [value("mass", 3, "kg")]})),
        Proposal("atom", atom("@n", kind="note", body={"ru": "Общая."}, basis="author", tags=["shared"],
                              sources=None)),
    ], links=[{"rel": "see_also", "src": "@n", "dst": "@m", "note": {"ru": "связаны"}}], agent=PERSON)
    assert r.state == "approved", r.report
    return _refs(r)


def _export(conn, store, folder, **kw):
    kw.setdefault("with_files", True)
    return bundle.export(conn, store=store, folder=folder, selection=bundle.Selection(tags=("shared",)),
                         agent=PERSON, **kw)


def _body(record):
    technical = {"id", "schema_version", "revision", "content_hash", "status", "review_state", "created_at",
                 "recorded_at", "changeset", "agent", "activity", "revision_id", "provenance"}
    return {k: v for k, v in record.items() if k not in technical and v is not None}


def _edit(conn, store, docs, rid, text, agent):
    r = check.submit(conn, store, docs, [Proposal("atom", {**_body(lookup.get(conn, "atom", rid)),
                                                           "body": {"ru": text}}, record_id=rid)], agent=agent)
    assert r.state == "approved", r.report


def _base_id(conn) -> str:
    return conn.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()[0]


def _count(conn, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_import_into_empty_base_keeps_ids_and_is_idempotent(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    first = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert first.counts == {"created": 3, "unchanged": 0, "pending": 0, "skipped": 0, "links": 1, "objects": 1}
    assert first.changeset_id is not None and first.complete and first.collisions == []
    got = lookup.get(pg2, "atom", refs["@m"])
    # trust=keep: статус из подборки (запись человека — verified), review_state новой ревизии — none
    assert got["status"] == "verified" and got["review_state"] == "none"
    assert got["provenance"] == {"origin_base": _base_id(pg), "origin_agent": PERSON,
                                 "origin_revision_hash": lookup.get(pg, "atom", refs["@m"])["content_hash"]}
    assert got["about"] == [f"ent:{refs['@s']}"]
    assert lookup.get(pg2, "entity", refs["@s"])["key"] == "sensor_1"
    reason = pg2.execute("SELECT reason FROM changeset WHERE id = %s", (first.changeset_id,)).fetchone()[0]
    assert reason.startswith(f"import {_base_id(pg)} ")
    assert _count(pg2, "import_history") == 0                                   # без with_history истории нет
    [link] = lookup.links(pg2, refs["@n"])
    assert link["rel"] == "see_also" and link["id"] == lookup.links(pg, refs["@n"])[0]["id"]     # id связи тот же
    second = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert second.counts == {"created": 0, "unchanged": 3, "pending": 0, "skipped": 0, "links": 0, "objects": 0}
    assert pg2.execute("SELECT count(*) FROM atom_revision").fetchone()[0] == 2
    assert _count(pg2, "link") == 1


def test_import_divergence_is_pending_not_overwrite(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    rid = refs["@n"]
    _edit(pg2, store2, docs, rid, "Моя правка.", OTHER)
    _edit(pg, store, docs, rid, "Чужая правка.", PERSON)
    _export(pg, store, tmp_path / "c")
    r = bundle.import_(pg2, store2, tmp_path / "c", agent=OTHER)
    assert r.counts["pending"] == 1 and r.counts["unchanged"] == 2 and not r.complete
    assert lookup.get(pg2, "atom", rid)["body"] == {"ru": "Моя правка."}
    [item] = [q for q in r.queued if q["reason"] == "imported"]
    assert str(item["record_id"]) == rid
    # повтор той же подборки — тот же вопрос уже задан: нового пункта и ревизии нет
    again = bundle.import_(pg2, store2, tmp_path / "c", agent=OTHER)
    assert again.counts["pending"] == 0 and again.counts["unchanged"] == 3 and again.queued == []
    # решение человека по пункту imported принимает чужую правку
    review.resolve(pg2, item["id"], "confirmed", agent=OTHER)
    assert lookup.get(pg2, "atom", rid)["body"] == {"ru": "Чужая правка."}


def test_trust_review(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    r = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER, trust="review")
    assert lookup.get(pg2, "atom", refs["@n"])["status"] == "needs_review"
    assert lookup.get(pg2, "entity", refs["@s"])["status"] == "needs_review"
    assert len([q for q in r.queued if q["reason"] == "imported"]) == 3 and not r.complete
    with pytest.raises(bundle.BundleError, match="trust"):
        bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER, trust="all")


def test_trust_keep_draft_gets_semantic_item(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    """Черновик модели приходит черновиком и встаёт на проверку смысла, как после submit."""
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    r = check.submit(pg, store, docs, [Proposal("atom", atom("@a", tags=["shared"]))], agent="model:writer")
    assert r.records[0]["status"] == "draft"
    _export(pg, store, tmp_path / "b")
    got = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert [q["reason"] for q in got.queued] == ["semantic"]
    assert lookup.get(pg2, "atom", r.records[0]["record_id"])["status"] == "draft"


def test_pack_missing_refuses_model_and_person_installs_bundled_packs(pg, pg2, monkeypatch, store, store2, docs,
                                                                     tmp_path):
    """Нет пакета подборки: модели — отказ с подсказкой; человек ставит пакеты из packs/ подборки сам (копия в
    AMEMO_PACKS_HOME, база их знает и после prepare — перезапуска службы)."""
    _prepare(pg, monkeypatch)
    _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b", with_files=False, with_packs=True)
    _prepare(pg2, monkeypatch, env=str(PACKS / "quantities"))        # без ontology
    with pytest.raises(bundle.BundleError, match="ontology 1.0.0") as e:
        bundle.import_(pg2, store2, tmp_path / "b", agent="model:reader", dry_run=True)
    assert e.value.code == "bundle_pack_missing"
    assert "AMEMO_PACKS" in str(e.value) and "подборке b" in str(e.value) and "packs/ontology" in str(e.value)
    assert str(tmp_path) not in str(e.value)                 # полного пути на диске в сообщении нет
    assert _count(pg2, "atom") == 0 and _count(pg2, "object") == 0
    got = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert got.warnings[0] == "поставлены пакеты видов из подборки: ontology 1.0.0"
    assert (packs.installed_root() / "ontology" / "pack.yaml").is_file()
    assert _count(pg2, "atom") == 2
    db.prepare(pg2)
    assert ("ontology", "1.0.0") in pg2.execute("SELECT name, version FROM pack").fetchall()


def test_pack_without_copy_in_bundle_still_refuses(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    """Подборка без packs/ (with_packs выключен): ставить нечего — прежний отказ и человеку."""
    _prepare(pg, monkeypatch)
    _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b", with_files=False, with_packs=False)
    _prepare(pg2, monkeypatch, env=str(PACKS / "quantities"))
    with pytest.raises(bundle.BundleError) as e:
        bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER, dry_run=True)
    assert e.value.code == "bundle_pack_missing"
    assert not (packs.installed_root() / "ontology").exists()


def test_folders_travel_with_new_records(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    """Папка записи едет в подборке (поле folder строки) и ставится новой записи; бывшую запись импорт не двигает."""
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    folders.move(pg, f"atm:{refs['@n']}", "Проекты/Кампус", agent=PERSON)
    _export(pg, store, tmp_path / "b")
    rows = [json.loads(x) for x in (tmp_path / "b" / "atoms.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {r["id"]: r.get("folder") for r in rows}[refs["@n"]] == "Проекты/Кампус"
    bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    folder = lambda: pg2.execute("SELECT folder FROM atom WHERE id = %s", (refs["@n"],)).fetchone()[0]  # noqa: E731
    assert folder() == "Проекты/Кампус"
    folders.move(pg2, f"atm:{refs['@n']}", None, agent=OTHER)
    bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert folder() is None


def test_key_collision_refuses(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    check.submit(pg2, store2, docs, [Proposal("entity", entity("@x", cls="sensor", key="sensor_1"))], agent=OTHER)
    with pytest.raises(bundle.BundleError, match="sensor_1") as e:
        bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert e.value.code == "bundle_key_collision" and len(e.value.details["collisions"]) == 1
    assert _count(pg2, "atom") == 0 and _count(pg2, "object") == 0
    plan = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER, dry_run=True)     # план — с коллизиями
    assert plan.changeset_id is None and len(plan.collisions) == 1 and not plan.complete


def test_dry_run_writes_nothing(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    before = {t: _count(pg2, t) for t in ("atom", "entity", "object", "link", "changeset", "agent")}
    plan = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER, dry_run=True)
    assert plan.counts == {"created": 3, "unchanged": 0, "pending": 0, "skipped": 0, "links": 1, "objects": 1}
    assert plan.changeset_id is None and plan.complete
    assert plan.report["format"] == "amem.check/1" and plan.report["issues"] == []
    assert {t: _count(pg2, t) for t in before} == before
    assert not (tmp_path / "objects2").exists()


def test_history_goes_to_import_history(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    rid = refs["@n"]
    _edit(pg, store, docs, rid, "Вторая.", PERSON)
    _export(pg, store, tmp_path / "b", with_history=True)
    bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert pg2.execute("SELECT count(*) FROM atom_revision WHERE atom_id = %s", (rid,)).fetchone()[0] == 1
    rows = pg2.execute("SELECT n, origin_base::text, content_hash FROM import_history WHERE record_id = %s ORDER BY n",
                       (rid,)).fetchall()
    assert [(n, base) for n, base, _ in rows] == [(1, _base_id(pg)), (2, _base_id(pg))]
    assert rows[1][2] == lookup.get(pg, "atom", rid)["content_hash"]
    bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)                  # повтор — те же строки, без дублей
    assert pg2.execute("SELECT count(*) FROM import_history WHERE record_id = %s", (rid,)).fetchone()[0] == 2


def test_round_trip_to_own_base_is_unchanged(pg, monkeypatch, store, docs, tmp_path):
    _prepare(pg, monkeypatch)
    _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    r = bundle.import_(pg, store, tmp_path / "b", agent=PERSON)
    assert r.counts == {"created": 0, "unchanged": 3, "pending": 0, "skipped": 0, "links": 0, "objects": 0}


def test_return_to_origin_unedited_is_unchanged(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    """A → B → A: тело в B то же, что в A, — только с provenance; в A ничего не меняется."""
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    bundle.export(pg2, store=store2, folder=tmp_path / "back", selection=bundle.Selection(tags=("shared",)),
                  agent=OTHER, with_files=True)
    r = bundle.import_(pg, store, tmp_path / "back", agent=PERSON)
    assert r.counts["unchanged"] == 3 and r.counts["pending"] == 0 and r.counts["links"] == 0


def test_retired_record_is_skipped(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    records.set_status(pg2, "atom", refs["@n"], "deprecated", agent=OTHER)
    _edit(pg, store, docs, refs["@n"], "Чужая правка.", PERSON)
    _export(pg, store, tmp_path / "c")
    r = bundle.import_(pg2, store2, tmp_path / "c", agent=OTHER)
    assert r.counts["skipped"] == 1 and r.counts["pending"] == 0
    assert any(refs["@n"] in w and "deprecated" in w for w in r.warnings)


def test_zip_bundle_imports(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b.zip")
    r = bundle.import_(pg2, store2, tmp_path / "b.zip", agent=OTHER)
    assert r.counts["created"] == 3
    oid = lookup.get(pg2, "atom", refs["@m"])["sources"][0]["object"]
    assert store2.content(oid.split(":", 1)[1], 1).read_text(encoding="utf-8") == (docs / "заметка.md").read_text(
        encoding="utf-8")


def _source_row(conn, rid):
    return conn.execute("SELECT s.verdict, s.page FROM source s JOIN atom_current c ON c.id = s.atom_revision_id "
                        "WHERE c.atom_id = %s", (rid,)).fetchone()


def test_verdicts_copied_with_file_no_file_without(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    verdict = _source_row(pg, refs["@m"])
    assert verdict[0] == "ok"
    _export(pg, store, tmp_path / "with")
    bundle.import_(pg2, store2, tmp_path / "with", agent=OTHER)
    assert _source_row(pg2, refs["@m"]) == verdict


def test_verdict_no_file_without_files(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    _export(pg, store, tmp_path / "bare", with_files=False)
    r = bundle.import_(pg2, store2, tmp_path / "bare", agent=OTHER)
    assert _source_row(pg2, refs["@m"]) == ("no_file", None)
    # место без файла не подтверждено: атом — на проверку, а заметка без источника остаётся verified
    assert lookup.get(pg2, "atom", refs["@m"])["status"] == "needs_review"
    assert lookup.get(pg2, "atom", refs["@n"])["status"] == "verified"
    [item] = [q for q in r.queued if q["reason"] == "imported"]
    assert str(item["record_id"]) == refs["@m"]


def test_object_status_is_carried(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    oid = lookup.get(pg, "atom", refs["@m"])["sources"][0]["object"]
    objects.mark(pg, oid, "parsed", agent=PERSON, note="всё")
    _export(pg, store, tmp_path / "b")
    bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    got = lookup.object_status(pg2, oid)
    # отметку ставит вливающий; кто и когда отметил в базе-источнике — в заметке
    assert got["status"] == "parsed" and got["agent"] == OTHER
    assert got["note"].startswith("всё (из подборки: person:alice, ")


def test_web_object_with_same_url_is_matched(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    """Страница сайта, известная получателю под другим id, сопоставляется с его объектом: ссылка источника — на него."""
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    url = "https://example.org/norm"
    r = check.submit(pg, store, docs, [Proposal("atom", atom("@w", kind="note", basis="author", tags=["shared"],
                                                             sources=[{"path": url}]))], agent=PERSON)
    assert r.state == "approved", r.report
    local = objects.web(pg2, url)
    _export(pg, store, tmp_path / "b")
    got = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert got.counts["created"] == 1 and got.counts["objects"] == 0
    assert any(url in w for w in got.warnings)
    rid = r.records[0]["record_id"]
    assert lookup.get(pg2, "atom", rid)["sources"][0]["object"] == f"obj:{local.object_id}"
    again = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert again.counts["unchanged"] == 1


def test_retired_link_is_retired_on_import(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    [link] = lookup.links(pg, refs["@n"])
    records.retire_link(pg, link["id"], agent=PERSON, reason="не нужна")
    _export(pg, store, tmp_path / "c")
    r = bundle.import_(pg2, store2, tmp_path / "c", agent=OTHER)
    assert lookup.links(pg2, refs["@n"]) == [] and r.counts["links"] == 0


def _rewrite(folder: Path, part: str, change) -> None:
    """Подделать часть подборки и пересчитать её sha256 в манифесте — проверка уже не по целостности файла."""
    rows = [json.loads(line) for line in (folder / part).read_text(encoding="utf-8").splitlines()]
    rows = [change(row) for row in rows]
    (folder / part).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    manifest["parts"][part] = hashlib.sha256((folder / part).read_bytes()).hexdigest()
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def test_level1_violation_refuses_whole_bundle(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")

    def no_unit(row):
        payload = row["revision"]["payload"]
        if payload.get("content"):
            del payload["content"]["values"][0]["unit"]
            row["revision"]["content_hash"] = canon.content_hash(payload)
        return row

    _rewrite(tmp_path / "b", "atoms.jsonl", no_unit)
    plan = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER, dry_run=True)        # план — с отчётом
    assert not plan.complete and any(i["code"] == "unit_required" for i in plan.report["issues"])
    assert all(i["where"].startswith("atm:") for i in plan.report["issues"])
    with pytest.raises(bundle.BundleError, match="уровень 1") as e:
        bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert any(i["code"] == "unit_required" for i in e.value.details["report"]["issues"])
    assert _count(pg2, "atom") == 0 and _count(pg2, "object") == 0


def test_hash_mismatch_refuses(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")

    def edit(row):
        row["revision"]["payload"]["label"] = {"ru": "Подменено"}
        return row

    _rewrite(tmp_path / "b", "atoms.jsonl", edit)
    with pytest.raises(bundle.BundleError, match="content_hash"):
        bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)


def test_damaged_part_refuses(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    with (tmp_path / "b" / "atoms.jsonl").open("a", encoding="utf-8") as f:
        f.write("\n")
    with pytest.raises(bundle.BundleError, match="atoms.jsonl"):
        bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert _count(pg2, "changeset") == 0


def test_model_import_does_not_keep_verified(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    """Проверенное в чужой базе остаётся проверенным, только если вливает человек; модель — needs_review и imported."""
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    r = bundle.import_(pg2, store2, tmp_path / "b", agent="model:importer")
    assert {lookup.get(pg2, "atom", refs[k])["status"] for k in ("@m", "@n")} == {"needs_review"}
    assert lookup.get(pg2, "entity", refs["@s"])["status"] == "needs_review"
    imported = [q for q in r.queued if q["reason"] == "imported"]
    assert len(imported) == 3 and not r.complete
    details = pg2.execute("SELECT details FROM review_item WHERE id = %s", (imported[0]["id"],)).fetchone()[0]
    assert details["origin_status"] == "verified" and details["action"] == "created"


def test_person_import_keeps_verified(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    r = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert lookup.get(pg2, "atom", refs["@n"])["status"] == "verified" and r.queued == [] and r.complete


def test_link_id_with_other_ends_is_collision(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    _export(pg, store, tmp_path / "c")

    def other_end(link):
        return {**link, "dst": f"ent:{refs['@s']}", "retired_at": "2026-01-01T00:00:00+00:00"}

    _rewrite(tmp_path / "c", "links.jsonl", other_end)
    with pytest.raises(bundle.BundleError, match="связь") as e:
        bundle.import_(pg2, store2, tmp_path / "c", agent=OTHER)
    assert e.value.code == "bundle_key_collision"
    assert len(lookup.links(pg2, refs["@n"])) == 1                     # связь не выведена из оборота


def test_only_property_concepts_are_added(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    extra = [{"scheme": "property", "code": "x_reach", "label": {"ru": "Вылет"}},
             {"scheme": "kind", "code": "x_evil", "label": {"ru": "Свой вид"}}]
    (tmp_path / "b" / "concepts.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in extra),
                                                   encoding="utf-8")
    manifest = json.loads((tmp_path / "b" / "manifest.json").read_text(encoding="utf-8"))
    manifest["parts"]["concepts.jsonl"] = hashlib.sha256((tmp_path / "b" / "concepts.jsonl").read_bytes()).hexdigest()
    (tmp_path / "b" / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    r = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    got = dict(pg2.execute("SELECT scheme || '.' || code, origin FROM concept WHERE code LIKE 'x\\_%'").fetchall())
    assert got == {"property.x_reach": "agent"}
    assert any("kind.x_evil" in w for w in r.warnings)


def test_history_hash_mismatch_refuses(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    _edit(pg, store, docs, refs["@n"], "Вторая.", PERSON)
    _export(pg, store, tmp_path / "b", with_history=True)

    def forge(row):
        for h in row.get("history") or []:
            h["payload"]["body"] = {"ru": "Подменено"}
        return row

    _rewrite(tmp_path / "b", "atoms.jsonl", forge)
    with pytest.raises(bundle.BundleError, match="история.*content_hash"):
        bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)


def test_same_file_in_both_bases_is_matched_by_digest(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    """Тот же документ, загруженный в обе базы, — один источник: ссылка — на локальный объект, повтор — unchanged."""
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    local = objects.ingest(pg2, store2, docs, "заметка.md", agent=OTHER)
    _export(pg, store, tmp_path / "b")
    r = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert r.counts["created"] == 3 and r.counts["objects"] == 0
    assert any(f"obj:{local.object_id}" in w and "не переносятся" not in w for w in r.warnings)
    got = lookup.get(pg2, "atom", refs["@m"])
    assert (got["sources"][0]["object"], got["sources"][0]["object_version"]) == (f"obj:{local.object_id}", local.n)
    assert got["provenance"]["origin_revision_hash"] == lookup.get(pg, "atom", refs["@m"])["content_hash"]
    assert _count(pg2, "object") == 1
    assert _source_row(pg2, refs["@m"])[0] == "ok"                    # своя сверка по локальной копии
    again = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert again.counts["unchanged"] == 3 and again.changeset_id is None


def test_partial_file_match_refuses(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    """Получатель знает только первую версию файла, а источник подборки ссылается на вторую — отказ, базы не тронуты."""
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    first = docs.parent / "docs2"
    first.mkdir()
    (first / "заметка.md").write_bytes((docs / "заметка.md").read_bytes())
    _seed(pg, store, docs)
    with (docs / "заметка.md").open("a", encoding="utf-8") as f:
        f.write("\nДобавлено позже.\n")
    r = check.submit(pg, store, docs, [Proposal("atom", atom("@v2", kind="parameter", tags=["shared"],
                                                              sources=[source_md("заметка.md", "Масса 3 кг")],
                                                              content={"values": [value("mass", 3, "kg")]}))],
                     agent=PERSON)
    assert r.state == "approved", r.report
    objects.ingest(pg2, store2, first, "заметка.md", agent=OTHER)
    _export(pg, store, tmp_path / "b")
    before = {t: _count(pg2, t) for t in ("atom", "entity", "object", "object_version", "changeset")}
    with pytest.raises(bundle.BundleError) as e:
        bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert e.value.code == "bundle_object_conflict" and e.value.details["lost"] == [2]
    assert {t: _count(pg2, t) for t in before} == before


def test_quote_not_found_by_own_check_goes_to_review(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    """Своя сверка не нашла цитату в копии файла — атом не остаётся verified: needs_review и пункт imported."""
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")

    def other_quote(row):
        payload = row["revision"]["payload"]
        if payload.get("sources"):
            payload["sources"][0]["quote"] = "Такого текста в заметке нет"
            row["revision"]["content_hash"] = canon.content_hash(payload)
        return row

    _rewrite(tmp_path / "b", "atoms.jsonl", other_quote)
    r = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert _source_row(pg2, refs["@m"])[0] == "not_found"
    assert lookup.get(pg2, "atom", refs["@m"])["status"] == "needs_review"
    assert any(refs["@m"] in w and "not_found" in w for w in r.warnings)
    [item] = [q for q in r.queued if q["reason"] == "imported"]
    details = pg2.execute("SELECT details FROM review_item WHERE id = %s", (item["id"],)).fetchone()[0]
    assert details["origin_status"] == "verified"
    assert [v["verdict"] for v in details["verdicts"]] == ["not_found"]


def test_model_import_of_author_basis_goes_to_review(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    """Модель не обходит политику основания: basis author и автор-человек в provenance — needs_review и imported,
    а не черновик с проверкой смысла."""
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    r = check.submit(pg, store, docs, [Proposal("atom", atom("@a", tags=["shared"]))], agent="model:writer")
    rid = r.records[0]["record_id"]
    _export(pg, store, tmp_path / "b")

    def as_author(row):
        payload = row["revision"]["payload"]
        payload["basis"] = "author"
        payload["provenance"] = {"origin_agent": "person:boss"}
        row["revision"]["content_hash"] = canon.content_hash(payload)
        return row

    _rewrite(tmp_path / "b", "atoms.jsonl", as_author)
    got = bundle.import_(pg2, store2, tmp_path / "b", agent="model:importer")
    assert lookup.get(pg2, "atom", rid)["status"] == "needs_review"
    assert [q["reason"] for q in got.queued] == ["imported"]
    details = pg2.execute("SELECT details FROM review_item WHERE id = %s", (got.queued[0]["id"],)).fetchone()[0]
    assert details["origin_status"] == "draft"
    assert "basis author" in details["why"] and "origin_agent person:boss" in details["why"]


def test_link_matched_only_by_ends_is_not_retired(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    """Подборка с выведенной связью под чужим id не выводит локальную связь с теми же rel и концами."""
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    _export(pg, store, tmp_path / "c")
    from amemo.ids import uuid7

    _rewrite(tmp_path / "c", "links.jsonl",
             lambda l: {**l, "id": str(uuid7()), "retired_at": "2026-01-01T00:00:00+00:00"})
    r = bundle.import_(pg2, store2, tmp_path / "c", agent=OTHER)
    assert len(lookup.links(pg2, refs["@n"])) == 1
    assert any("see_also" in w and "другим id" in w for w in r.warnings)


def test_exchange_back_and_forth_is_unchanged(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    """A → B → A → B без правок: записи обеих баз узнаются на каждом шаге, ничего не записывается."""
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    _seed(pg, store, docs)
    r = check.submit(pg2, store2, docs, [Proposal("atom", atom("@y", kind="note", body={"ru": "Из B."}, basis="author",
                                                               tags=["shared"], sources=None))], agent=OTHER)
    assert r.state == "approved", r.report

    def move(src, src_store, dst, dst_store, name, agent):
        bundle.export(src, store=src_store, folder=tmp_path / name, selection=bundle.Selection(tags=("shared",)),
                      agent=agent, with_files=True)
        return bundle.import_(dst, dst_store, tmp_path / name, agent=agent)

    first = move(pg, store, pg2, store2, "ab", OTHER)
    assert first.counts["created"] == 3
    back = move(pg2, store2, pg, store, "ba", PERSON)
    assert back.counts["created"] == 1 and back.counts["unchanged"] == 3
    for name, (src, ss, dst, ds, who) in {"ab2": (pg, store, pg2, store2, OTHER),
                                          "ba2": (pg2, store2, pg, store, PERSON)}.items():
        again = move(src, ss, dst, ds, name, who)
        assert again.counts["unchanged"] == 4 and again.counts["created"] == again.counts["pending"] == 0
        assert again.changeset_id is None and again.queued == []


def test_repeated_import_does_not_adopt_known_objects(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    """Объект без новых версий и путей не принимается заново: исключительная блокировка объектов не берётся."""
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    calls = []
    adopt = objects.adopt
    monkeypatch.setattr(objects, "adopt", lambda *a, **kw: calls.append(a) or adopt(*a, **kw))
    locks = []
    execute = type(pg2).execute

    def spy(self, query, *args, **kw):
        if "pg_advisory_xact_lock(" in str(query):
            locks.append(query)
        return execute(self, query, *args, **kw)

    monkeypatch.setattr(type(pg2), "execute", spy)
    again = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert again.counts["unchanged"] == 3 and calls == [] and locks == []


def test_invalid_property_concept_is_skipped(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    extra = [{"scheme": "property", "code": "x_bad_unit", "label": {"ru": "Плохая"}, "unit": "кг"},
             {"scheme": "property", "code": "x_no_label"},
             {"scheme": "property", "code": "x_good", "label": {"ru": "Хорошая"}, "unit": "kg"}]
    (tmp_path / "b" / "concepts.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in extra),
                                                   encoding="utf-8")
    manifest = json.loads((tmp_path / "b" / "manifest.json").read_text(encoding="utf-8"))
    manifest["parts"]["concepts.jsonl"] = hashlib.sha256((tmp_path / "b" / "concepts.jsonl").read_bytes()).hexdigest()
    (tmp_path / "b" / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    r = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    got = {c for (c,) in pg2.execute("SELECT code FROM concept WHERE scheme = 'property' AND code LIKE 'x\\_%'")}
    assert got == {"x_good"}
    assert any("x_bad_unit" in w for w in r.warnings) and any("x_no_label" in w for w in r.warnings)


def test_refusal_codes_for_damaged_and_level1(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    _export(pg, store, tmp_path / "c")
    with (tmp_path / "b" / "atoms.jsonl").open("a", encoding="utf-8") as f:
        f.write("\n")
    with pytest.raises(bundle.BundleError) as e:
        bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert e.value.code == bundle.DAMAGED

    def no_unit(row):
        payload = row["revision"]["payload"]
        if payload.get("content"):
            del payload["content"]["values"][0]["unit"]
            row["revision"]["content_hash"] = canon.content_hash(payload)
        return row

    _rewrite(tmp_path / "c", "atoms.jsonl", no_unit)
    with pytest.raises(bundle.BundleError) as e:
        bundle.import_(pg2, store2, tmp_path / "c", agent=OTHER)
    assert e.value.code == bundle.LEVEL1


def _object_locks(watch, pid: int) -> list[str]:
    """Режимы рекомендательной блокировки объектов (OBJECTS_LOCK), которые держит соединение pid: ключ bigint
    в pg_locks — старшая половина в classid, младшая в objid, objsubid = 1."""
    key = objects.OBJECTS_LOCK
    return sorted(mode for (mode,) in watch.execute(
        "SELECT mode FROM pg_locks WHERE locktype = 'advisory' AND pid = %s AND classid::bigint = %s "
        "AND objid::bigint = %s AND objsubid = 1", (pid, key >> 32, key & 0xFFFFFFFF)))


def test_own_check_runs_without_object_lock(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    """Своя сверка (извлечение текста бывает долгим) идёт после приёма объектов и до транзакции записи: блокировки
    объектов у импорта в это время нет, а принятый объект уже виден другим соединениям."""
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    seen = []
    judge = level2.judge_source
    with same_database(pg2, autocommit=True) as watch:
        def spy(*args, **kw):
            seen.append((_object_locks(watch, pg2.info.backend_pid),
                         watch.execute("SELECT count(*) FROM object").fetchone()[0]))
            return judge(*args, **kw)

        monkeypatch.setattr(level2, "judge_source", spy)
        r = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert seen == [([], 1)]
    assert r.counts["created"] == 3 and _source_row(pg2, refs["@m"])[0] == "ok"


def test_write_transaction_holds_shared_object_lock(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    """Транзакция записи — под разделяемой блокировкой объектов, как у submit: пакет другого агента берёт её сразу,
    а исключительная (новая версия объекта, снимок) ждёт фиксации импорта."""
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    got = []
    commit = records.commit
    key = objects.OBJECTS_LOCK
    with same_database(pg2, autocommit=True) as other:
        def spy(*args, **kw):
            got.append((_object_locks(other, pg2.info.backend_pid),
                        other.execute("SELECT pg_try_advisory_xact_lock_shared(%s)", (key,)).fetchone()[0],
                        other.execute("SELECT pg_try_advisory_xact_lock(%s)", (key,)).fetchone()[0]))
            return commit(*args, **kw)

        monkeypatch.setattr(records, "commit", spy)
        r = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
        assert _object_locks(other, pg2.info.backend_pid) == []          # после фиксации — ничего
    assert got == [(["ShareLock"], True, False)]
    assert r.counts["created"] == 3


def test_new_version_between_objects_and_write_gives_source_changed(pg, pg2, monkeypatch, store, store2, docs,
                                                                    tmp_path):
    """Новая версия объекта, принятая параллельным ingest после приёма объектов подборки и до транзакции записи,
    не теряется: ревизия со ссылкой на прежнюю версию получает пункт source_changed."""
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    with (docs / "заметка.md").open("a", encoding="utf-8") as f:
        f.write("\nДобавлено позже.\n")
    adopt, versions = objects.adopt, []
    with same_database(pg2, autocommit=True) as other:
        other.execute("SET lock_timeout = '5s'")      # импорт, держащий блокировку объектов, — отказ, а не зависание

        def then_ingest(*args, **kw):
            out = adopt(*args, **kw)
            versions.append(objects.ingest(other, store2, docs, "заметка.md", agent=OTHER))
            return out

        monkeypatch.setattr(objects, "adopt", then_ingest)
        r = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    [v2] = versions
    assert v2.n == 2 and v2.created
    assert lookup.get(pg2, "atom", refs["@m"])["sources"][0]["object_version"] == 1
    [item] = [q for q in r.queued if q["reason"] == "source_changed"]
    assert str(item["record_id"]) == refs["@m"] and not r.complete
    details = pg2.execute("SELECT details FROM review_item WHERE id = %s", (item["id"],)).fetchone()[0]
    assert [(o["object"], o["from"], o["to"]) for o in details["objects"]] == [(f"obj:{v2.object_id}", [1], 2)]


@pytest.fixture
def pg3(request, pg):
    """Третья чистая схема на том же сервере — база, куда та же подборка вливается без сбоя (для сравнения)."""
    from conftest import _schema

    with _schema(request.node.callspec.params["pg"]) as conn:
        yield conn


def _state(conn, store) -> dict:
    """Что импорт оставил в базе — без своих id ревизий, пакетов и пунктов и без времени: чтобы сравнить две базы."""
    def rows(sql):
        return [tuple(r) for r in conn.execute(sql).fetchall()]

    out = {
        "atoms": rows("SELECT a.id, a.key, a.status, c.content_hash, c.review_state FROM atom a "
                      "JOIN atom_current c ON c.atom_id = a.id ORDER BY a.id"),
        "entities": rows("SELECT e.id, e.key, e.status, c.content_hash FROM entity e "
                         "JOIN entity_current c ON c.entity_id = e.id ORDER BY e.id"),
        "sources": rows("SELECT r.atom_id, s.position, s.object_id, s.object_version, s.verdict, s.page, s.anchor "
                        "FROM source s JOIN atom_revision r ON r.id = s.atom_revision_id ORDER BY 1, 2"),
        "queue": rows("SELECT record_id, reason, state, details FROM review_item ORDER BY record_id, reason"),
        "links": rows("SELECT id, rel, coalesce(src_atom, src_entity), coalesce(dst_atom, dst_entity), retired_at "
                      "FROM link ORDER BY id"),
        "objects": rows("SELECT o.id, o.kind, o.original_name, v.n, v.digest FROM object o "
                        "JOIN object_version v ON v.object_id = o.id ORDER BY o.id, v.n"),
        "paths": rows("SELECT path, object_id FROM object_path ORDER BY path"),
    }
    out["copies"] = [store.head(object_id) for object_id, *_ in out["objects"]]
    return out


def test_write_failure_keeps_objects_and_retry_matches_clean_import(pg, pg2, pg3, monkeypatch, store, store2, docs,
                                                                    tmp_path):
    """Сбой транзакции записи: объекты и копии, принятые до неё своими транзакциями, остаются, записей и пакета нет;
    повтор импорта даёт то же, что импорт без сбоя."""
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch); _prepare(pg3, monkeypatch)
    _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    store3 = ObjectStore(tmp_path / "objects3")
    clean = bundle.import_(pg3, store3, tmp_path / "b", agent="model:importer")
    commit = records.commit

    def broken(*args, **kw):
        raise records.RecordError("сбой записи")

    monkeypatch.setattr(records, "commit", broken)
    with pytest.raises(bundle.BundleError, match="сбой записи"):
        bundle.import_(pg2, store2, tmp_path / "b", agent="model:importer")
    [(object_id,)] = pg2.execute("SELECT id FROM object").fetchall()
    assert store2.head(object_id) == 1
    assert {t: _count(pg2, t) for t in ("atom", "entity", "link", "changeset", "review_item")} == \
        dict.fromkeys(("atom", "entity", "link", "changeset", "review_item"), 0)
    monkeypatch.setattr(records, "commit", commit)
    again = bundle.import_(pg2, store2, tmp_path / "b", agent="model:importer")
    assert again.counts == {**clean.counts, "objects": 0}        # объект принят первой попыткой: он уже не новый
    assert [q["reason"] for q in again.queued] == [q["reason"] for q in clean.queued] and not again.complete
    assert again.warnings == clean.warnings
    assert _state(pg2, store2) == _state(pg3, store3)


def test_object_failure_refuses_and_keeps_adopted(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    """Сбой при приёме объекта (здесь — хранилища) — отказ BundleError до записи: объект, принятый раньше, остаётся
    с копией, записей нет; повтор импорта принимает остальное как есть."""
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    _seed(pg, store, docs)
    r = check.submit(pg, store, docs, [Proposal("atom", atom("@k", tags=["shared"]))], agent=PERSON)
    assert r.state == "approved", r.report
    _export(pg, store, tmp_path / "b")
    add, calls = store2.add_version, []

    def flaky(object_id, *args, **kw):
        calls.append(object_id)
        if len(calls) == 2:
            raise StoreError("нет места на диске")
        return add(object_id, *args, **kw)

    monkeypatch.setattr(store2, "add_version", flaky)
    with pytest.raises(bundle.BundleError, match="нет места на диске"):
        bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    first, second = calls
    assert [oid for (oid,) in pg2.execute("SELECT id FROM object")] == [first]
    assert store2.head(first) == 1 and store2.head(second) == 0
    assert _count(pg2, "atom") == 0 and _count(pg2, "changeset") == 0
    monkeypatch.setattr(store2, "add_version", add)
    again = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert again.counts["created"] == 4 and again.counts["objects"] == 1
    assert _count(pg2, "object") == 2 and store2.head(second) == 1


def test_import_requires_autocommit(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    """Соединение без autocommit — отказ до любого чтения: приём объектов и запись идут своими транзакциями."""
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    with same_database(pg2) as manual:
        with pytest.raises(bundle.BundleError, match="autocommit"):
            bundle.import_(manual, store2, tmp_path / "b", agent=OTHER)
        assert manual.info.transaction_status == TransactionStatus.IDLE      # транзакцию не открыл
    assert _count(pg2, "object") == 0 and not (tmp_path / "objects2").exists()


def test_own_check_failure_is_bundle_error(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    """Сбой своей сверки (копии версии нет в хранилище) — отказ BundleError с местом: записей нет, принятый объект
    остаётся."""
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")

    def broken(*args, **kw):
        raise StoreError("sources[0]: копии файла нет в хранилище")

    monkeypatch.setattr(level2, "judge_source", broken)
    with pytest.raises(bundle.BundleError, match="своя сверка") as e:
        bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert f"atm:{refs['@m']}" in str(e.value) and "копии файла нет" in str(e.value)
    assert _count(pg2, "atom") == 0 and _count(pg2, "changeset") == 0 and _count(pg2, "object") == 1


def test_ingest_during_write_waits_and_marks_written_revision(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    """Новая версия объекта во время транзакции записи: ingest ждёт фиксации импорта (разделяемая блокировка
    объектов), а потом его on_new_version ставит source_changed на только что записанную ревизию."""
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    with (docs / "заметка.md").open("a", encoding="utf-8") as f:
        f.write("\nДобавлено позже.\n")
    app = f"amemo-ingest-{time.monotonic_ns()}"
    versions, errors, started = [], [], []
    commit = records.commit

    def ingest_v2() -> None:
        try:
            with same_database(pg2, autocommit=True, application_name=app) as other:
                versions.append(objects.ingest(other, store2, docs, "заметка.md", agent=OTHER))
        except BaseException as e:                         # noqa: BLE001 — ошибку потока проверяет тест
            errors.append(e)

    def waiting_commit(*args, **kw):
        t = threading.Thread(target=ingest_v2)
        t.start()
        started.append(t)
        deadline = time.monotonic() + 30
        with same_database(pg2, autocommit=True) as watch:
            while watch.execute("SELECT count(*) FROM pg_stat_activity WHERE application_name = %s "
                                "AND wait_event_type = 'Lock' AND wait_event = 'advisory'", (app,)).fetchone()[0] < 1:
                assert not versions and not errors, "ingest не ждал транзакцию записи"
                assert time.monotonic() < deadline, "ingest не встал в ожидание блокировки объектов"
                time.sleep(0.02)
        return commit(*args, **kw)

    monkeypatch.setattr(records, "commit", waiting_commit)
    r = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    started[0].join(timeout=60)
    assert errors == [] and [v.n for v in versions] == [2]
    assert [q for q in r.queued if q["reason"] == "source_changed"] == []        # при записи версии 2 ещё не было
    [revision_id] = pg2.execute("SELECT id FROM atom_current WHERE atom_id = %s", (refs["@m"],)).fetchone()
    [(details, changeset_id)] = pg2.execute(
        "SELECT details, changeset_id FROM review_item WHERE atom_revision_id = %s AND reason = 'source_changed'",
        (revision_id,)).fetchall()
    assert changeset_id is None                                                  # пункт поставила новая версия
    assert [(o["from"], o["to"]) for o in details["objects"]] == [([1], 2)]


# --- свои виды (пакет mine) в подборке: подпроект 4, часть 4d, задача 19 ---

def _kind(**extra) -> dict:
    """Черновик своего вида атома: величина массы и теги."""
    return {"label": {"ru": "Взвешивание"}, "target": "atom", "family": "source",
            "form": [{"key": "mass", "path": "content.values[property=mass]", "label": {"ru": "Масса"},
                      "type": "quantity", "required": True, "property": "mass"},
                     {"key": "tags", "path": "tags", "label": {"ru": "Теги"}, "type": "tags"}],
            "body": "wanted", "widgets": ["sources"], **extra}


def _own_kind_record(conn, store, docs) -> str:
    from amemo import mine

    mine.put(conn, "weighing", _kind(), agent=PERSON)
    r = check.submit(conn, store, docs, [Proposal("atom", atom("@w", kind="weighing", tags=["shared"], basis="author",
                                                                sources=None,
                                                                content={"values": [value("mass", 2, "kg")]}))],
                     agent=PERSON)
    assert r.state == "approved", r.report
    return r.records[0]["record_id"]


def _mine_kinds(conn) -> list[str]:
    return [c for (c,) in conn.execute("SELECT code FROM concept WHERE origin = 'mine' ORDER BY code")]


def test_own_kind_travels_with_packs(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    rid = _own_kind_record(pg, store, docs)
    _export(pg, store, tmp_path / "b", with_packs=True)
    plan = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER, dry_run=True)
    assert plan.kinds == ["weighing"] and plan.counts["kinds"] == 1 and plan.complete, plan.report
    assert _mine_kinds(pg2) == [] and _count(pg2, "atom") == 0                       # dry_run ничего не пишет
    assert pg2.execute("SELECT count(*) FROM pack WHERE name = 'mine'").fetchone()[0] == 0
    got = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert got.kinds == ["weighing"] and got.counts["created"] == 1 and got.complete
    assert _mine_kinds(pg2) == ["weighing"]
    assert lookup.get(pg2, "atom", rid)["kind"] == "weighing"
    # повтор: вид уже есть с тем же содержимым — добавлять нечего
    again = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER, dry_run=True)
    assert again.kinds == [] and again.collisions == []


def test_own_kind_with_other_content_is_pack_conflict(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    from amemo import mine

    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    _own_kind_record(pg, store, docs)
    _export(pg, store, tmp_path / "b", with_packs=True)
    mine.put(pg2, "weighing", _kind(body="none"), agent=OTHER)
    plan = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER, dry_run=True)
    assert plan.kinds == [] and not plan.complete
    assert any(c.startswith("packs/mine") and "weighing" in c for c in plan.collisions), plan.collisions
    with pytest.raises(bundle.BundleError) as e:
        bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert e.value.code == "bundle_pack_conflict" and e.value.details["collisions"]
    assert _count(pg2, "atom") == 0 and _count(pg2, "review_item") == 0             # и в очередь ничего молча


def test_own_kind_without_packs_is_pack_missing(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    _own_kind_record(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    with pytest.raises(bundle.BundleError, match="mine") as e:
        bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER, dry_run=True)
    assert e.value.code == "bundle_pack_missing" and "with_packs" in str(e.value)
    # в свою же базу — без packs/: пакет mine той же версии и digest уже есть
    assert bundle.import_(pg, store, tmp_path / "b", agent=PERSON).counts["unchanged"] == 1


def test_own_kind_from_bundle_is_added_only_by_person(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    from amemo import mine

    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    _own_kind_record(pg, store, docs)
    _export(pg, store, tmp_path / "b", with_packs=True)
    assert bundle.import_(pg2, store2, tmp_path / "b", agent="model:bot", dry_run=True).kinds == ["weighing"]
    with pytest.raises(mine.MineError) as e:
        bundle.import_(pg2, store2, tmp_path / "b", agent="model:bot")
    assert e.value.code == "forbidden" and _mine_kinds(pg2) == [] and _count(pg2, "atom") == 0


def test_own_kind_failing_the_pack_check_is_a_dry_run_collision(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    """Вид подборки, который не проходит проверку пакета в этой базе: у dry_run — коллизия отчёта, а не отказ."""
    from amemo import mine, packs

    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    _own_kind_record(pg, store, docs)
    _export(pg, store, tmp_path / "b", with_packs=True)

    def refuse(*args, **kwargs):
        raise packs.PackError("шаблон weighing: величины нет в словаре")
    monkeypatch.setattr(mine, "_check", refuse)
    plan = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER, dry_run=True)
    assert not plan.complete and any("weighing" in c for c in plan.collisions), plan.collisions
    with pytest.raises(bundle.BundleError) as e:
        bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert e.value.code == "bundle_pack_conflict"
    assert _mine_kinds(pg2) == [] and _count(pg2, "atom") == 0
