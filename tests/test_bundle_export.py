"""Экспорт подборки amem.bundle/1: отбор, замыкание, части, файлы, пакеты, zip, inspect (спецификация 3c, разд. 4.1–4.2)."""
import hashlib
import json
import os
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from amem import bundle, check, db, model_v1, records
from amem.check import Proposal
from amem.records import Item
from check_support import atom, entity, source_md, value

PACKS = Path(__file__).with_name("packs")
PERSON = "person:alice"
PARTS = {"atoms.jsonl", "entities.jsonl", "links.jsonl", "objects.jsonl", "sources.jsonl", "concepts.jsonl"}


@pytest.fixture
def world(pg, monkeypatch, store, docs):
    """Проект, стойка с датчиком (part_of), параметр датчика с источником, заметки с тегом shared и без."""
    monkeypatch.setenv("AMEM_PACKS", os.pathsep.join([str(PACKS / "quantities"), str(PACKS / "ontology")]))
    db.prepare(pg)
    r = check.submit(pg, store, docs, [
        Proposal("entity", entity("@p", cls="project")),
        Proposal("entity", entity("@rack", cls="device")),
        Proposal("entity", entity("@s", cls="sensor")),
        Proposal("atom", atom("@m", kind="parameter", about=["@s"], tags=["shared"], scope={"project": "@p"},
                              sources=[source_md("заметка.md", "Масса 3 кг")],
                              content={"values": [value("mass", 3, "kg")]})),
        Proposal("atom", atom("@n", kind="note", body={"ru": "Общая."}, basis="author", tags=["shared"],
                              sources=None)),
        Proposal("atom", atom("@priv", kind="note", body={"ru": "Моё."}, basis="author", tags=["shared"],
                              scope={"visibility": "private"}, sources=None)),
        Proposal("atom", atom("@other", kind="note", body={"ru": "Не в теге."}, basis="author", sources=None)),
    ], links=[{"rel": "part_of", "src": "@s", "dst": "@rack"},
              {"rel": "see_also", "src": "@n", "dst": "@m", "note": {"ru": "связаны"}}], agent=PERSON)
    assert r.state == "approved", r.report
    refs = {rec["label"]: f"{'atm' if rec['target'] == 'atom' else 'ent'}:{rec['record_id']}" for rec in r.records}
    return pg, refs


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _ids(path: Path) -> set[str]:
    return {row["id"] for row in _rows(path)}


def _id(ref: str) -> str:
    return ref.split(":", 1)[1]


def test_export_by_tag_closes_over_about_and_links(world, tmp_path):
    pg, refs = world
    out = tmp_path / "b"
    m = bundle.export(pg, store=None, folder=out, selection=bundle.Selection(tags=("shared",)), agent=PERSON)
    assert _ids(out / "atoms.jsonl") == {_id(refs["@m"]), _id(refs["@n"])}       # private исключён, @other не в теге
    assert _ids(out / "entities.jsonl") == {_id(refs["@s"]), _id(refs["@p"])}    # about и scope.project; @rack — нет
    links = _rows(out / "links.jsonl")
    assert [(l["rel"], l["src"], l["dst"]) for l in links] == [("see_also", refs["@n"], refs["@m"])]
    assert links[0]["note"] == {"ru": "связаны"} and links[0]["agent"] == PERSON and links[0]["retired_at"] is None
    assert m["format"] == "amem.bundle/1" and {p["name"] for p in m["packs"]} == {"core", "quantities", "ontology"}
    assert m["counts"] == {"atoms": 2, "entities": 2, "links": 1, "objects": 1, "sources": 1, "concepts": 0}
    assert set(m["parts"]) == PARTS and m["base_id"] == pg.execute(
        "SELECT value FROM meta WHERE key = 'base_id'").fetchone()[0]
    assert m["agent"] == PERSON and m["selection"]["tags"] == ["shared"] and m["with_files"] is False
    model_v1.BundleManifest.model_validate(m)
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8")) == m


def test_record_rows_carry_current_revision_as_is(world, tmp_path):
    pg, refs = world
    out = tmp_path / "b"
    bundle.export(pg, store=None, folder=out, selection=bundle.Selection(refs=(refs["@m"],)), agent=PERSON)
    [row] = _rows(out / "atoms.jsonl")
    current = pg.execute("SELECT id, n, content_hash, payload FROM atom_current WHERE atom_id = %s",
                         (_id(refs["@m"]),)).fetchone()
    rev = row["revision"]
    assert (rev["id"], rev["n"], rev["content_hash"], rev["payload"]) == (str(current[0]), *current[1:])
    assert row["kind"] == "parameter" and row["status"] == "verified" and rev["agent"] == PERSON
    assert rev["review_state"] == "none" and "history" not in row
    [src] = _rows(out / "sources.jsonl")
    assert src["revision_id"] == rev["id"] and src["position"] == 0 and src["verdict"] == "ok"
    [obj] = _rows(out / "objects.jsonl")
    assert obj["kind"] == "file" and obj["logical_paths"] == ["заметка.md"] and obj["status"] is None
    assert f"obj:{obj['id']}" == rev["payload"]["sources"][0]["object"]
    model_v1.ObjectRecord.model_validate({k: v for k, v in obj.items() if k != "status"})


def test_export_by_project_includes_part_of_chain(world, tmp_path):
    pg, refs = world
    out = tmp_path / "b"
    bundle.export(pg, store=None, folder=out, selection=bundle.Selection(project=refs["@p"]), agent=PERSON)
    assert _ids(out / "atoms.jsonl") == {_id(refs["@m"])}
    assert _ids(out / "entities.jsonl") == {_id(refs["@s"]), _id(refs["@p"]), _id(refs["@rack"])}
    assert {l["rel"] for l in _rows(out / "links.jsonl")} == {"part_of"}


def test_export_by_project_takes_parts_of_project_and_their_atoms(world, tmp_path, store, docs):
    pg, refs = world
    done = records.commit(pg, [Item("entity", entity("@unit", cls="device")),
                               Item("atom", atom("@u", kind="note", about=["@unit"], basis="author", sources=None))],
                          [{"rel": "part_of", "src": "@unit", "dst": refs["@p"]}], agent=PERSON)
    unit, u = (f"{p}:{rev.record_id}" for p, rev in zip(("ent", "atm"), done.revisions))
    out = tmp_path / "b"
    bundle.export(pg, store=None, folder=out, selection=bundle.Selection(project=refs["@p"]), agent=PERSON)
    assert _ids(out / "atoms.jsonl") == {_id(refs["@m"]), _id(u)}           # атом о части проекта — тоже его
    assert _id(unit) in _ids(out / "entities.jsonl")


def test_export_private_explicit(world, tmp_path):
    pg, refs = world
    out = tmp_path / "b"
    bundle.export(pg, store=None, folder=out, selection=bundle.Selection(tags=("shared",), include_private=True),
                  agent=PERSON)
    assert _id(refs["@priv"]) in _ids(out / "atoms.jsonl")


def test_selection_by_kind_class_status_since_and_everything(world, tmp_path):
    pg, refs = world
    def atoms(sel, name):
        bundle.export(pg, store=None, folder=tmp_path / name, selection=sel, agent=PERSON)
        return _ids(tmp_path / name / "atoms.jsonl"), _ids(tmp_path / name / "entities.jsonl")
    got, ents = atoms(bundle.Selection(kinds=("note",)), "kinds")
    assert got == {_id(refs["@n"]), _id(refs["@other"])} and ents == set()
    got, ents = atoms(bundle.Selection(entity_classes=("device",)), "classes")
    assert got == set() and ents == {_id(refs["@rack"])}                      # класс не наследуется: sensor — нет
    got, _ = atoms(bundle.Selection(tags=("shared",), statuses=("draft",)), "status")
    assert got == set()                                                        # у человека всё verified
    got, _ = atoms(bundle.Selection(tags=("shared",), since=datetime.now(timezone.utc) + timedelta(hours=1)), "since")
    assert got == set()
    got, ents = atoms(bundle.Selection(), "all")                                # без условий — вся база без private
    assert got == {_id(refs[r]) for r in ("@m", "@n", "@other")} and len(ents) == 3


def test_selection_refs_by_key_and_unknown(world, tmp_path):
    pg, refs = world
    done = records.commit(pg, [Item("atom", atom("@k", kind="note", key="note.k", basis="author", sources=None))],
                          agent=PERSON)
    out = tmp_path / "b"
    bundle.export(pg, store=None, folder=out, selection=bundle.Selection(refs=("atm:note.k", refs["@s"])), agent=PERSON)
    assert _ids(out / "atoms.jsonl") == {str(done.revisions[0].record_id)}
    assert _ids(out / "entities.jsonl") == {_id(refs["@s"])}
    with pytest.raises(bundle.BundleError, match="atm:nope: записи нет"):
        bundle.export(pg, store=None, folder=tmp_path / "c", selection=bundle.Selection(refs=("atm:nope",)),
                      agent=PERSON)
    assert not (tmp_path / "c").exists()


def test_retired_link_is_exported_with_retired_at(world, tmp_path):
    pg, refs = world
    pg.execute("UPDATE link SET retired_at = created_at, retired_by = changeset_id WHERE rel = 'see_also'")
    out = tmp_path / "b"
    bundle.export(pg, store=None, folder=out, selection=bundle.Selection(tags=("shared",)), agent=PERSON)
    [link] = _rows(out / "links.jsonl")
    assert link["retired_at"] is not None


def test_with_history_keeps_older_revisions(world, tmp_path):
    pg, refs = world
    body = {k: v for k, v in atom(None, kind="note", body={"ru": "Общая, правка."}, basis="author",
                                     tags=["shared"], sources=None).items()}
    records.commit(pg, [Item("atom", body, record_id=_id(refs["@n"]))], agent=PERSON)
    out = tmp_path / "b"
    m = bundle.export(pg, store=None, folder=out, selection=bundle.Selection(refs=(refs["@n"],)), agent=PERSON,
                      with_history=True)
    [row] = _rows(out / "atoms.jsonl")
    assert row["revision"]["n"] == 2 and [h["n"] for h in row["history"]] == [1]
    assert row["history"][0]["payload"]["body"] == {"ru": "Общая."} and row["history"][0]["agent"] == PERSON
    assert m["with_history"] is True


def test_export_with_files_and_inspect(world, tmp_path, store):
    pg, refs = world
    out = tmp_path / "b"
    bundle.export(pg, store=store, folder=out, selection=bundle.Selection(refs=(refs["@m"],)), agent=PERSON,
                  with_files=True)
    [file] = list((out / "objects" / "sha256").iterdir())
    assert hashlib.sha256(file.read_bytes()).hexdigest() == file.name
    [obj] = _rows(out / "objects.jsonl")
    assert obj["versions"][0]["digest"] == f"sha256:{file.name}"
    info = bundle.inspect(out)
    assert info["ok"] is True and info["damaged"] == [] and info["counts"]["atoms"] == 1
    assert f"objects/sha256/{file.name}" in info["parts"]
    (out / "atoms.jsonl").write_text("{}\n", encoding="utf-8")
    file.write_bytes(b"other")
    info = bundle.inspect(out)
    assert info["ok"] is False and set(info["damaged"]) == {"atoms.jsonl", f"objects/sha256/{file.name}"}
    (out / "links.jsonl").unlink()
    assert "links.jsonl" in bundle.inspect(out)["damaged"]


def test_with_files_needs_store(world, tmp_path):
    pg, refs = world
    with pytest.raises(bundle.BundleError, match="хранилище"):
        bundle.export(pg, store=None, folder=tmp_path / "b", selection=bundle.Selection(refs=(refs["@m"],)),
                      agent=PERSON, with_files=True)
    assert not (tmp_path / "b").exists()


def test_export_refuses_existing_folder(world, tmp_path):
    pg, _ = world
    (tmp_path / "b").mkdir()
    with pytest.raises(bundle.BundleError, match="уже есть"):
        bundle.export(pg, store=None, folder=tmp_path / "b", selection=bundle.Selection(), agent=PERSON)


def test_export_with_packs_checks_digest(world, tmp_path):
    pg, refs = world
    out = tmp_path / "b"
    m = bundle.export(pg, store=None, folder=out, selection=bundle.Selection(tags=("shared",)), agent=PERSON,
                      with_packs=True)
    assert (out / "packs" / "ontology" / "pack.yaml").exists() and (out / "packs" / "core" / "vocab").is_dir()
    assert "packs/ontology/pack.yaml" in m["parts"] and bundle.inspect(out)["ok"] is True
    pg.execute("UPDATE pack SET digest = 'deadbeef' WHERE name = 'ontology'")
    with pytest.raises(bundle.BundleError, match="digest пакета ontology"):
        bundle.export(pg, store=None, folder=tmp_path / "c", selection=bundle.Selection(tags=("shared",)),
                      agent=PERSON, with_packs=True)
    assert not (tmp_path / "c").exists()


def test_agent_concepts_go_to_concepts_jsonl(world, tmp_path):
    pg, refs = world
    data = {"scheme": "property", "code": "glow", "label": {"ru": "свечение", "en": "glow"}}
    pg.execute("INSERT INTO concept (scheme, code, data, origin, updated_at) VALUES ('property', 'glow', %s, "
               "'agent', now())", (json.dumps(data),))
    records.commit(pg, [Item("atom", atom("@g", kind="parameter", about=[refs["@s"]], tags=["glow"], basis="author",
                                          sources=None, content={"values": [value("glow", 1, "1")]}))],
                   agent=PERSON)
    out = tmp_path / "b"
    m = bundle.export(pg, store=None, folder=out, selection=bundle.Selection(tags=("glow",)), agent=PERSON)
    assert _rows(out / "concepts.jsonl") == [data] and m["counts"]["concepts"] == 1


def test_export_zip(world, tmp_path, store):
    pg, refs = world
    out = tmp_path / "b.zip"
    m = bundle.export(pg, store=store, folder=out, selection=bundle.Selection(tags=("shared",)), agent=PERSON,
                      with_files=True)
    with zipfile.ZipFile(out) as z:
        names = {i.filename: i for i in z.infolist()}
    assert "manifest.json" in names and set(m["parts"]) <= set(names)
    assert all(i.compress_type == zipfile.ZIP_STORED for n, i in names.items() if n.startswith("objects/"))
    info = bundle.inspect(out)
    assert info["ok"] is True and info["counts"]["atoms"] == 2
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith((".b", "b"))] == ["b.zip"]   # без временных


def test_inspect_rejects_other_format(tmp_path):
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "manifest.json").write_text(json.dumps({"format": "amem.bundle/2"}), encoding="utf-8")
    with pytest.raises(bundle.BundleError, match="amem.bundle/2"):
        bundle.inspect(tmp_path / "b")
    with pytest.raises(bundle.BundleError, match="manifest.json"):
        bundle.inspect(tmp_path / "nothing")


def _note(ref, **fields):
    return atom(ref, kind="note", basis="author", sources=None, **fields)


def test_closure_takes_atom_refs_and_their_refs(world, tmp_path):
    pg, refs = world
    done = records.commit(pg, [
        Item("atom", _note("@base", about=[refs["@rack"]])),
        Item("atom", _note("@t", body={"ru": "Обозначение массы."})),
        Item("atom", _note("@d", tags=["dx"], derived_from=["@base"])),
        Item("atom", atom("@f", kind="fact", basis="author", sources=None, tags=["dx"],
                          content={"formula": {"latex": "m = \\rho V", "symbols": [{"symbol": "m", "term": "@t"}]}})),
    ], agent=PERSON)
    base, term, derived, formula = (str(r.record_id) for r in done.revisions)
    out = tmp_path / "b"
    bundle.export(pg, store=None, folder=out, selection=bundle.Selection(tags=("dx",)), agent=PERSON)
    assert _ids(out / "atoms.jsonl") == {base, term, derived, formula}    # derived_from и term вне отбора
    assert _ids(out / "entities.jsonl") == {_id(refs["@rack"])}            # about атома из замыкания


def test_closure_refuses_rejected_and_private_targets(world, tmp_path):
    pg, refs = world
    done = records.commit(pg, [Item("atom", _note("@base")),
                               Item("atom", _note("@d", tags=["dx"], derived_from=["@base", refs["@priv"]]))],
                          agent=PERSON)
    base = done.revisions[0].record_id
    records.set_status(pg, "atom", base, "rejected", agent=PERSON)
    with pytest.raises(bundle.BundleError) as e:
        bundle.export(pg, store=None, folder=tmp_path / "b", selection=bundle.Selection(tags=("dx",)), agent=PERSON)
    assert f"atm:{base} (rejected)" in str(e.value) and f"{refs['@priv']} (private)" in str(e.value)
    assert not (tmp_path / "b").exists()
    records.set_status(pg, "atom", base, "draft", agent=PERSON)
    bundle.export(pg, store=None, folder=tmp_path / "c", selection=bundle.Selection(tags=("dx",), include_private=True),
                  agent=PERSON)
    assert {str(base), _id(refs["@priv"])} <= _ids(tmp_path / "c" / "atoms.jsonl")


def test_selection_rejects_string_instead_of_tuple():
    with pytest.raises(bundle.BundleError, match="Selection.tags"):
        bundle.Selection(tags="shared")
    with pytest.raises(bundle.BundleError, match="Selection.refs"):
        bundle.Selection(refs=[1])


def _counts(pg) -> dict:
    tables = [r[0] for r in pg.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = "
                                       "current_schema() AND table_type = 'BASE TABLE' ORDER BY 1")]
    return {t: pg.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}


def test_export_changes_nothing_and_is_repeatable(world, tmp_path, store):
    pg, refs = world
    before = _counts(pg)
    sel = bundle.Selection(tags=("shared",))
    a = bundle.export(pg, store=store, folder=tmp_path / "a", selection=sel, agent=PERSON, with_files=True,
                      with_history=True, with_packs=True)
    b = bundle.export(pg, store=store, folder=tmp_path / "b.zip", selection=sel, agent=PERSON, with_files=True,
                      with_history=True, with_packs=True)
    assert _counts(pg) == before
    assert {k: v for k, v in a.items() if k != "created_at"} == {k: v for k, v in b.items() if k != "created_at"}


def test_with_files_store_error_is_bundle_error(world, tmp_path):
    from amem.ocfl_store import ObjectStore
    pg, refs = world
    with pytest.raises(bundle.BundleError, match="не скопирован из хранилища"):
        bundle.export(pg, store=ObjectStore(tmp_path / "empty"), folder=tmp_path / "b",
                      selection=bundle.Selection(refs=(refs["@m"],)), agent=PERSON, with_files=True)
    assert not (tmp_path / "b").exists()


def test_inspect_requires_every_part(world, tmp_path):
    pg, _ = world
    out = tmp_path / "b"
    bundle.export(pg, store=None, folder=out, selection=bundle.Selection(tags=("shared",)), agent=PERSON)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    del manifest["parts"]["links.jsonl"]
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    info = bundle.inspect(out)
    assert info["ok"] is False and info["damaged"] == ["links.jsonl"] and info["unexpected"] == ["links.jsonl"]


def _zip(path: Path, members: dict[str, bytes], symlink: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.json", json.dumps({"format": "amem.bundle/1"}))
        for name, raw in members.items():
            z.writestr(zipfile.ZipInfo(name), raw, compress_type=zipfile.ZIP_DEFLATED)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (0o120777 << 16)
            z.writestr(info, "/etc/passwd")
    return path


@pytest.mark.parametrize("name", ["../evil.txt", "/abs.txt", "a\\..\\b.txt", "C:/win.txt"])
def test_zip_with_bad_names_is_refused_before_unpacking(tmp_path, name):
    with pytest.raises(bundle.BundleError, match="недопустимое имя"):
        bundle.inspect(_zip(tmp_path / "b.zip", {name: b"x"}))
    assert not (tmp_path / "evil.txt").exists()


def test_zip_with_symlink_is_refused(tmp_path):
    with pytest.raises(bundle.BundleError, match="символическая ссылка"):
        bundle.inspect(_zip(tmp_path / "b.zip", {}, symlink="atoms.jsonl"))


def test_zip_bomb_limits(tmp_path, monkeypatch):
    path = _zip(tmp_path / "b.zip", {"atoms.jsonl": b"\0" * (2 << 20)})          # 2 МиБ нулей: сжатие ~1000:1
    with pytest.raises(bundle.BundleError, match="zip-бомбу"):
        bundle.inspect(path)
    monkeypatch.setattr(bundle, "MAX_RATIO", 10 ** 6)
    monkeypatch.setattr(bundle, "MAX_UNPACKED", 1 << 20)
    with pytest.raises(bundle.BundleError, match="больше предела"):
        bundle.inspect(path)
    monkeypatch.setattr(bundle, "MAX_UNPACKED", 1 << 30)
    monkeypatch.setattr(bundle, "MAX_MEMBERS", 1)
    with pytest.raises(bundle.BundleError, match="записей в архиве"):
        bundle.inspect(path)
