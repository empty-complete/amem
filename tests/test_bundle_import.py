"""Импорт подборки: id сохраняются, повтор идемпотентен, расхождение — pending, trust, пакеты, коллизии, dry_run,
история, объекты и итоги сверки, связи (спецификация 3c, разд. 4.3)."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from amem import bundle, canon, check, db, lookup, objects, records, review
from amem.check import Proposal
from check_support import atom, entity, source_md, value

PACKS = Path(__file__).with_name("packs")
PERSON, OTHER = "person:alice", "person:bob"
ENV = os.pathsep.join([str(PACKS / "quantities"), str(PACKS / "ontology")])


def _prepare(conn, monkeypatch, env=ENV):
    monkeypatch.setenv("AMEM_PACKS", env)
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


def test_pack_missing_refuses_with_hint(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch)
    _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b", with_files=False, with_packs=True)
    _prepare(pg2, monkeypatch, env=str(PACKS / "quantities"))        # без ontology
    with pytest.raises(bundle.BundleError, match="ontology 1.0.0") as e:
        bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert e.value.code == "bundle_pack_missing"
    assert "AMEM_PACKS" in str(e.value) and str(tmp_path / "b" / "packs" / "ontology") in str(e.value)
    assert _count(pg2, "atom") == 0 and _count(pg2, "object") == 0


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
    from amem.ids import uuid7

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
