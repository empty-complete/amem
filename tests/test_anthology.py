"""Антология: отбор verified + preferred, подборка amem.bundle/1 и HTML-отчёт (подпроект 5, часть F)."""
import json
import os
from pathlib import Path

import pytest

from amem import anthology, bundle, check, db
from amem.check import Proposal
from check_support import atom, entity, source_md, value

PACKS = Path(__file__).with_name("packs")
PERSON = "person:alice"
MODEL = "model:extractor"


@pytest.fixture
def world(pg, monkeypatch, store, docs):
    """Датчик; два значения массы (preferred и normal), устаревшее, заметка; запись модели — не проверена."""
    monkeypatch.setenv("AMEM_PACKS", os.pathsep.join([str(PACKS / "quantities"), str(PACKS / "ontology")]))
    db.prepare(pg)
    r = check.submit(pg, store, docs, [
        Proposal("entity", entity("@s", cls="sensor")),
        Proposal("atom", atom("@best", kind="parameter", about=["@s"], rank="preferred",
                              sources=[source_md("заметка.md", "Масса 3 кг")], content={"values": [value("mass", 3, "kg")]})),
        Proposal("atom", atom("@alt", kind="parameter", about=["@s"], basis="author", sources=None,
                              content={"values": [value("mass", 3.2, "kg")]})),
        Proposal("atom", atom("@old", kind="note", rank="deprecated", basis="author", sources=None,
                              body={"ru": "Старое."})),
        Proposal("atom", atom("@n", kind="note", about=["@s"], basis="author", sources=None, body={"ru": "Своё."})),
    ], agent=PERSON)
    assert r.state == "approved", r.report
    m = check.submit(pg, store, docs, [
        Proposal("atom", atom("@guess", kind="note", basis="assumed", sources=None, body={"ru": "Догадка модели."})),
    ], agent=MODEL)
    assert m.state == "approved", m.report
    refs = {rec["label"]: f"{'atm' if rec['target'] == 'atom' else 'ent'}:{rec['record_id']}"
            for rec in [*r.records, *m.records]}
    return pg, refs


def test_select_keeps_verified_and_preferred(world):
    pg, refs = world
    got = set(anthology.select(pg))
    assert refs["@best"] in got
    assert refs["@n"] in got
    assert refs["@alt"] not in got          # есть preferred по той же величине того же объекта
    assert refs["@old"] not in got          # deprecated
    status = pg.execute("SELECT status FROM atom WHERE id = %s", (refs["@guess"][4:],)).fetchone()[0]
    assert (refs["@guess"] in got) == (status == "verified")


def test_export_writes_bundle_and_report(world, tmp_path):
    pg, refs = world
    out = tmp_path / "anthology.zip"
    res = anthology.export(pg, store=None, folder=out, agent=PERSON, title="Датчики")
    assert out.exists()
    m = res["manifest"]
    assert m["format"] == "amem.bundle/1"
    assert m["selection"]["statuses"] == ["verified"]
    assert m["counts"]["atoms"] == len(res["refs"]) >= 2
    rep = bundle.inspect(out)
    assert rep["ok"] and rep["counts"]["atoms"] == m["counts"]["atoms"]
    html = res["report"]
    assert html.startswith("<!doctype html>")
    assert "<h1>Датчики</h1>" in html
    assert "3 kg" in html and "3.2 kg" not in html
    assert "«Масса 3 кг»" in html
    assert "Документ s" in html                      # группа по объекту about


def test_empty_anthology_refuses(world, tmp_path):
    pg, _ = world
    with pytest.raises(bundle.BundleError, match="антология пуста"):
        anthology.export(pg, store=None, folder=tmp_path / "x", agent=PERSON, selection=bundle.Selection(tags=("нет",)))


def test_report_escapes_html(world, store, docs):
    pg, _ = world
    r = check.submit(pg, store, docs, [
        Proposal("atom", atom("@x", kind="note", basis="author", sources=None,
                              summary_plain={"ru": "<script>alert(1)</script> & <b>жирно</b>"})),
    ], agent=PERSON)
    ref = f"atm:{r.records[0]['record_id']}"
    page = anthology.report(pg, [ref])
    assert "<script>" not in page and "&lt;script&gt;" in page
