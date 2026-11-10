"""Уровень 1 и статусы (спецификация 3c, разд. 2.1–2.3, 5): skip_if_set, basis, confidence, записи человека."""
import os
from pathlib import Path

import pytest

from amemo import check, db, records, review
from amemo.check import Proposal
from check_support import atom, pack, source_md, value

PACKS = Path(__file__).with_name("packs")
MODEL, PERSON = "model:claude", "person:alice"
NOTE = "заметка.md"


def _packs(*extra) -> str:
    return os.pathsep.join([str(PACKS / "quantities"), str(PACKS / "ontology"), *map(str, extra)])


@pytest.fixture
def ready(pg, monkeypatch):
    monkeypatch.setenv("AMEMO_PACKS", _packs())
    monkeypatch.setenv("AMEMO_BACKEND", "none")          # уровень 4 — только текст, без модели
    db.prepare(pg)
    return pg


def a(ref: str, label: str, kind: str, **fields) -> dict:
    return atom(ref, kind=kind, label={"ru": label}, **fields)


def _submit(conn, store, docs, payload, agent, record_id=None) -> check.Submitted:
    return check.submit(conn, store, docs, [Proposal("atom", payload, record_id)], agent=agent)


def _codes(result) -> set[str]:
    return {i["code"] for i in result.report["issues"]}


def mass(amount=3) -> dict:
    return {"values": [value("mass", amount, "kg")]}


def test_model_without_source_rejected(ready, store, docs):
    r = _submit(ready, store, docs, a("@m", "Масса корпуса 3 кг", "parameter", sources=None, content=mass()), MODEL)
    assert r.state == "rejected" and "template" in _codes(r)


def test_basis_default_skips_source_but_warns_without_rule(ready, store, docs):
    body = a("@t", "Температура воздуха 20 °C", "parameter", sources=None, basis="default",
             content={"values": [value("temperature", 20, "Cel")]})
    r = _submit(ready, store, docs, body, MODEL)
    assert r.state == "approved" and _codes(r) == {"basis_without_rule"}
    [issue] = r.report["issues"]
    assert (issue["level"], issue["severity"], issue["where"]) == (1, "warning", "@t: basis")
    assert r.records[0]["status"] == "needs_review"
    assert [q["reason"] for q in r.queued] == ["warning"]


def test_basis_skips_selectors_rule_too(ready, store, docs):
    # источник без места при basis — без предупреждения has_source о selectors
    def body(**kw):
        return a("@t", "Температура воздуха 20 °C", "parameter", sources=[{"path": NOTE}],
                 content={"values": [value("temperature", 20, "Cel")]}, **kw)
    assert "template" not in _codes(_submit(ready, store, docs, body(basis="assumed"), MODEL))
    assert "template" in _codes(_submit(ready, store, docs, body(), MODEL))


def test_basis_default_with_rule_is_clean(ready, store, docs):
    rule = _submit(ready, store, docs, a("@r", "Температура по умолчанию принимается 20 °C", "method",
                                         body={"ru": "В запас."}, sources=[source_md(NOTE, "Температура 20 °C.")]),
                   PERSON)
    assert rule.state == "approved"
    rule_ref = f"atm:{rule.records[0]['record_id']}"
    r = _submit(ready, store, docs, a("@t", "Температура воздуха 20 °C", "parameter", sources=None, basis="default",
                                      derived_from=[rule_ref], content={"values": [value("temperature", 20, "Cel")]}),
                MODEL)
    assert r.state == "approved" and "basis_without_rule" not in _codes(r)
    assert r.records[0]["status"] == "draft"


def test_basis_author_only_for_person(ready, store, docs):
    body = a("@n", "Проверить крепёж кронштейна", "note", sources=None, body={"ru": "Проверить крепёж."},
             basis="author")
    by_model = _submit(ready, store, docs, body, MODEL)
    assert by_model.state == "rejected" and "basis_author_model" in _codes(by_model)
    ok = _submit(ready, store, docs, body, PERSON)
    assert ok.state == "approved" and ok.records[0]["status"] == "verified"
    assert ok.records[0]["review_state"] == "none"
    assert ok.queued == [] and ok.complete is True and ok.levels["5"] == "not_applicable"
    assert ok.report["records"][0]["planned_status"] == "verified"


def test_person_without_basis_and_source_rejected(ready, store, docs):
    r = _submit(ready, store, docs, a("@n", "Заметка о крепеже", "note", sources=None, body={"ru": "Текст."}), PERSON)
    assert r.state == "rejected" and "template" in _codes(r)


def test_person_batch_still_checked_by_level2(ready, store, docs):
    r = _submit(ready, store, docs, a("@m", "Масса корпуса 3 кг", "parameter", content=mass(),
                                      sources=[source_md(NOTE, "Масса 300 кг.")]), PERSON)
    assert r.state == "rejected"


def test_confidence_person_rejected(ready, store, docs):
    r = _submit(ready, store, docs, a("@n", "Заметка о крепеже", "note", sources=None, body={"ru": "Текст."},
                                      basis="author", confidence=0.9), PERSON)
    assert r.state == "rejected" and "confidence_person" in _codes(r)
    [issue] = [i for i in r.report["issues"] if i["code"] == "confidence_person"]
    assert issue["where"] == "@n: confidence"


def test_low_confidence_needs_review_only_with_rule(ready, store, docs, tmp_path, monkeypatch):
    # без правила в шаблоне низкая уверенность ничего не меняет
    r = _submit(ready, store, docs, a("@m", "Масса корпуса 3 кг", "parameter", confidence=0.5, content=mass(),
                                      sources=[source_md(NOTE, "Масса 3 кг.")]), MODEL)
    assert r.records[0]["status"] == "draft"
    # с правилом high_risk: [low_confidence] — к человеку
    extra = pack(tmp_path / "risk", "risk", {"measurement": {
        "code": "measurement", "version": "1.0.0", "target": "atom", "applies_to": "measurement",
        "extends": ["has_label"], "high_risk": ["low_confidence"]}}, kinds=["measurement"])
    monkeypatch.setenv("AMEMO_PACKS", _packs(extra))
    db.prepare(ready)
    low = _submit(ready, store, docs, a("@m", "Масса корпуса 3 кг", "measurement", confidence=0.5, content=mass(),
                                        sources=[source_md(NOTE, "Масса 3 кг.")]), MODEL)
    assert low.records[0]["status"] == "needs_review"
    assert [q["reason"] for q in low.queued] == ["high_risk"]
    assert low.report["records"][0]["risk"] == ["template:measurement:low_confidence"]
    high = _submit(ready, store, docs, a("@w", "Вес опоры стойки 4 кг", "measurement", confidence=0.95,
                                         content=mass(4), sources=[source_md(NOTE, "Масса 4 кг.")]), MODEL)
    assert high.records[0]["status"] == "draft" and high.report["records"][0]["risk"] == []
    on_edge = _submit(ready, store, docs, a("@e", "Длина кабеля датчика", "measurement",
                                            confidence=check.LOW_CONFIDENCE, sources=[source_md(NOTE)]), MODEL)
    assert on_edge.records[0]["status"] == "draft"        # порог не входит: риск — строго ниже
    # человек риска шаблонов не получает (и confidence не заполняет)
    mine = _submit(ready, store, docs, a("@p", "Ширина полки кронштейна", "measurement",
                                         sources=[source_md(NOTE)]), PERSON)
    assert mine.records[0]["status"] == "verified" and mine.queued == []


def test_person_edit_of_model_atom_keeps_status_and_model_edit_of_person_is_pending(ready, store, docs):
    src = [source_md(NOTE, "Масса 3 кг.")]
    first = _submit(ready, store, docs, a("@m", "Масса корпуса 3 кг", "parameter", sources=src, content=mass()), MODEL)
    rid = first.records[0]["record_id"]
    assert [q["reason"] for q in first.queued] == ["semantic"]
    edited = a("@m", "Масса корпуса 3,0 кг", "parameter", sources=src, content=mass(),
               summary_plain={"ru": "Паспортная масса."})
    by_person = _submit(ready, store, docs, edited, PERSON, record_id=rid)
    # правка человеком записи модели статус не меняет (решение 11.11.2026): вопрос «по смыслу» — к новой ревизии
    assert by_person.records[0]["status"] == "draft" and by_person.records[0]["review_state"] == "none"
    assert [q["reason"] for q in by_person.queued] == ["semantic"]
    again = {**edited, "summary_plain": {"ru": "Масса с упаковкой."}}
    by_model = _submit(ready, store, docs, again, MODEL, record_id=rid)
    assert by_model.records[0]["review_state"] == "pending"
    assert by_model.records[0]["status"] == "draft"


def test_person_edit_of_verified_record_is_not_pending(ready, store, docs):
    src = [source_md(NOTE, "Масса 3 кг.")]
    first = _submit(ready, store, docs, a("@m", "Масса корпуса 3 кг", "parameter", sources=src, content=mass()), MODEL)
    rid = first.records[0]["record_id"]
    records.set_status(ready, "atom", rid, "verified", agent=PERSON)
    edited = a("@m", "Масса корпуса 3,0 кг", "parameter", sources=src, content=mass())
    r = _submit(ready, store, docs, edited, "person:bob", record_id=rid)
    assert (r.records[0]["status"], r.records[0]["review_state"]) == ("verified", "none")


def test_model_edit_of_person_record_is_pending_whatever_status(ready, store, docs):
    """Текущая ревизия записана человеком: правка модели ждёт его, даже если статус уже не verified."""
    body = a("@n", "Проверить крепёж кронштейна", "note", sources=None, body={"ru": "Проверить крепёж."},
             basis="author")
    rid = _submit(ready, store, docs, body, PERSON).records[0]["record_id"]
    records.set_status(ready, "atom", rid, "needs_review", agent=PERSON)
    edit = a("@n", "Проверить крепёж кронштейна", "note", sources=[source_md(NOTE)],
             body={"ru": "Проверить крепёж и анкер."})
    r = _submit(ready, store, docs, edit, MODEL, record_id=rid)
    assert r.state == "approved"
    assert (r.records[0]["status"], r.records[0]["review_state"]) == ("needs_review", "pending")
    assert [q["reason"] for q in r.queued] == ["edit"]
    assert r.report["records"][0]["planned_status"] == "needs_review"


def test_level1_without_agent_skips_agent_rules(ready):
    """level1.check без agent (как в старых вызовах) правил basis author и confidence не применяет."""
    from amemo.check import level1
    from amemo.check.report import Report
    report = Report()
    body = a("@n", "Заметка о крепеже", "note", sources=None, body={"ru": "Текст."}, basis="author", confidence=0.4)
    level1.check(ready, [Proposal("atom", body)], [], report)
    assert report.issues == []


def test_person_entity_is_verified_without_audit(ready, store, docs, monkeypatch):
    """Выборка аудита сущностей: у человека очереди нет даже при выборке 100 %."""
    monkeypatch.setattr(review, "AUDIT_RATE", 1.0)
    r = check.submit(ready, store, docs, [Proposal("entity", {"ref": "@d", "entity_class": "device",
                                                               "label": {"ru": "Насос циркуляционный"}})],
                     agent=PERSON)
    assert r.records[0]["status"] == "verified" and r.queued == []


def _person_note(conn, store, docs, status):
    body = a("@n", "Проверить крепёж кронштейна", "note", sources=None, body={"ru": "Проверить крепёж."},
             basis="author")
    rid = _submit(conn, store, docs, body, PERSON).records[0]["record_id"]
    records.set_status(conn, "atom", rid, status, agent=PERSON)
    edit = a("@n", "Проверить крепёж кронштейна", "note", sources=[source_md(NOTE)],
             body={"ru": "Проверить крепёж и анкер."})
    return rid, _submit(conn, store, docs, edit, MODEL, record_id=rid)


@pytest.mark.parametrize("outcome, state", [("confirmed", "accepted"), ("refuted", "declined")])
def test_model_edit_of_person_record_not_verified_can_be_decided(ready, store, docs, outcome, state):
    """Запись человека в needs_review: правка модели ждёт (pending, пункт edit), и решение по ней принимается —
    по состоянию ревизии, а не по статусу записи; статус записи решение не меняет."""
    rid, r = _person_note(ready, store, docs, "needs_review")
    rev = r.records[0]["revision_id"]
    assert (r.records[0]["status"], r.records[0]["review_state"]) == ("needs_review", "pending")
    [item] = [q for q in r.queued if q["reason"] == "edit"]
    out = review.resolve(ready, item["id"], outcome, agent=PERSON)
    assert out["status"] == "needs_review"
    assert ready.execute("SELECT review_state FROM atom_revision WHERE id = %s", (rev,)).fetchone()[0] == state
    current = ready.execute("SELECT id FROM atom_current WHERE atom_id = %s", (rid,)).fetchone()[0]
    assert (current == rev) is (outcome == "confirmed")


def test_model_edit_of_rejected_person_record_goes_usual_way(ready, store, docs):
    """Отвергнутая запись человека открытых пунктов не держит: правка модели не ждёт, а проверяется как обычно."""
    rid, r = _person_note(ready, store, docs, "rejected")
    assert (r.records[0]["status"], r.records[0]["review_state"]) == ("draft", "none")
    assert [q["reason"] for q in r.queued] == ["semantic"]


def test_person_record_on_old_object_version_gets_source_changed(ready, store, docs):
    """У записи человека из пунктов остаётся только source_changed: это вопрос о файле, а не проверка записи."""
    from amemo import objects
    note = docs / "версии.md"
    note.write_text("# Узел\n\n## Кронштейн\n\nКронштейн КБ-14 крепится анкером.\n", encoding="utf-8")
    v1 = objects.ingest(ready, store, docs, "версии.md", agent=PERSON)
    note.write_text("# Узел\n\n## Кронштейн\n\nКронштейн КБ-16 крепится двумя анкерами.\n", encoding="utf-8")
    objects.ingest(ready, store, docs, "версии.md", agent=PERSON)
    src = {"object": v1.ref, "object_version": 1, "digest": v1.digest,
           "selectors": [{"type": "heading", "value": "Кронштейн"}]}
    r = _submit(ready, store, docs, a("@k", "Кронштейн крепится анкером", "fact", sources=[src]), PERSON)
    assert r.state == "approved" and r.records[0]["status"] == "verified"
    assert [q["reason"] for q in r.queued] == ["source_changed"] and r.complete is False
