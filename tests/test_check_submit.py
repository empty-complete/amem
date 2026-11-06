"""check.submit — статусы по замечаниям и риску, итоги сверки, пункты очереди, ответ (разд. 1.1, 2.3, 7, 8.1–8.2
спецификации подпроекта 3). Существующие записи создаются тем же submit, статус человека — records.set_status."""
import os
import threading
import uuid

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from amem import check, db, embed, model_v1, objects, records, review
from amem.check import Proposal, level4
from amem.ocfl_store import StoreError
from check_support import CHECK_PACK, PDF, atom, entity, pack, source_md, source_pdf, value
from conftest import FakeProvider

AGENT = "model:tester"
PERSON = "person:reviewer"
PAGE2 = "Ветровой район II: w0 = 0,30 кПа"


@pytest.fixture
def kb(pg, monkeypatch):
    monkeypatch.setenv("AMEM_PACKS", str(CHECK_PACK))
    monkeypatch.setenv("AMEM_BACKEND", "none")          # уровень 4 — только текст, без модели
    monkeypatch.setattr(review, "AUDIT_RATE", 0.0)      # выборка аудита — только там, где тест её включает
    db.prepare(pg)
    return pg


def lab(text: str) -> dict:
    return {"ru": text}


def prop(body: dict, record_id=None) -> Proposal:
    return Proposal("entity" if "entity_class" in body else "atom", body, record_id)


def send(conn, store, docs, *bodies, links=(), agent=AGENT, **kw) -> check.Submitted:
    return check.submit(conn, store, docs, [b if isinstance(b, Proposal) else prop(b) for b in bodies], links,
                        agent=agent, **kw)


def codes(result: check.Submitted) -> list[tuple[str, str, str]]:
    return [(i["code"], i["severity"], i["where"]) for i in result.report["issues"]]


def items(conn, record_id) -> list[tuple]:
    """Пункты очереди записи: (причина, состояние, ревизия) по времени постановки."""
    return conn.execute("SELECT reason, state, coalesce(atom_revision_id, entity_revision_id) FROM review_item "
                        "WHERE record_id = %s ORDER BY created_at, id", (record_id,)).fetchall()


def status(conn, target, record_id) -> str:
    return conn.execute(f"SELECT status FROM {target} WHERE id = %s", (record_id,)).fetchone()[0]


def current(conn, record_id) -> uuid.UUID:
    return conn.execute("SELECT id FROM atom_current WHERE atom_id = %s", (record_id,)).fetchone()[0]


def wind(label="@a", **kw) -> dict:
    return atom(label, **{"label": lab("Нормативное ветровое давление района II"),
                          "sources": [source_pdf(PDF, 2, PAGE2)], **kw})


# --- отклонение ---

def test_rejected_batch_writes_nothing_and_is_complete(kb, store, docs):
    result = send(kb, store, docs, atom("@a"), atom("@b", label=lab("Анкер ставят в бетон"), sources=None))
    assert result.state == "rejected"
    assert ("template", "violation", "@b: sources") in codes(result)
    assert kb.execute("SELECT count(*) FROM atom").fetchone()[0] == 0
    stored = kb.execute("SELECT state, check_report FROM changeset WHERE id = %s", (result.changeset_id,)).fetchone()
    assert stored[0] == "rejected" and stored[1] == result.report
    model_v1.CheckReport.model_validate(result.report)
    assert "records" not in result.report
    assert result.levels == {"1": "done", "2": "done", "3": "skipped", "4": "skipped", "5": "skipped"}
    assert result.report["levels"] == {"1": "done", "2": "done", "3": "skipped", "4": "skipped"}
    assert result.queued == [] and result.records == [] and result.complete is True


# --- новый атом ---

def test_clean_pdf_atom_is_draft_and_queued_for_level5(kb, store, docs):
    result = send(kb, store, docs, wind())
    assert result.state == "approved"
    [rec] = result.records
    assert rec["status"] == "draft" and rec["created"] is True and rec["review_state"] == "none"
    assert status(kb, "atom", rec["record_id"]) == "draft"
    assert [q["reason"] for q in result.queued] == ["semantic"]
    assert result.queued[0]["label"] == "@a" and result.queued[0]["record_id"] == rec["record_id"]
    assert result.levels["5"] == "queued" and result.complete is False
    assert result.report["records"] == [{"label": "@a", "target": "atom", "planned_status": "draft", "risk": []}]
    assert "review" not in result.report and "queued" not in result.report
    model_v1.CheckReport.model_validate(result.report)
    verdict, page, anchor, checked_at = kb.execute(
        "SELECT verdict, page, anchor, checked_at FROM source WHERE atom_revision_id = %s AND position = 0",
        (rec["revision_id"],)).fetchone()
    created_at = kb.execute("SELECT created_at FROM changeset WHERE id = %s", (result.changeset_id,)).fetchone()[0]
    assert (verdict, page, checked_at) == ("ok", 2, created_at) and anchor
    row = kb.execute("SELECT state, changeset_id, created_by, details FROM review_item WHERE id = %s",
                     (result.queued[0]["id"],)).fetchone()
    assert row[:3] == ("queued", result.changeset_id, AGENT)
    assert row[3]["risk"] == [] and "issues" in row[3]


def test_message_source_goes_to_person(kb, store, docs):
    v = objects.message(kb, "Письмо о креплении кронштейна")
    result = send(kb, store, docs, atom("@a", sources=[{"object": v.ref, "object_version": 1}]))
    [rec] = result.records
    assert rec["status"] == "needs_review"
    assert [q["reason"] for q in result.queued] == ["warning"]
    assert result.levels["5"] == "not_applicable" and result.complete is False
    details = kb.execute("SELECT details FROM review_item WHERE id = %s", (result.queued[0]["id"],)).fetchone()[0]
    assert "external_source" in details["issues"]


def test_decision_is_high_risk(kb, store, docs):
    result = send(kb, store, docs, atom("@d", kind="decision", label=lab("Кронштейны крепим анкерами М10")))
    assert codes(result) == [] or all(c[1] == "info" for c in codes(result))
    [rec] = result.records
    assert rec["status"] == "needs_review"
    assert result.report["records"][0]["risk"] == ["template:decision:always"]
    assert [q["reason"] for q in result.queued] == ["high_risk"]
    assert result.levels["5"] == "not_applicable"


def test_rule_with_number_is_numeric_risk(kb, store, docs):
    body = atom("@r", kind="rule", label=lab("Ветровое давление района II принимают 0,30 кПа"),
                content={"values": [value("pressure", 0.3, "kPa")]}, sources=[source_pdf(PDF, 2, PAGE2)])
    result = send(kb, store, docs, body)
    assert result.state == "approved"
    assert result.report["records"][0]["risk"] == ["template:rule:numeric"]
    assert result.records[0]["status"] == "needs_review"
    assert [q["reason"] for q in result.queued] == ["high_risk"]


# --- сущности ---

def test_clean_entity_is_auto_verified_and_complete(kb, store, docs):
    result = send(kb, store, docs, entity("@e"))
    [rec] = result.records
    assert rec["status"] == "auto_verified" and result.queued == []
    assert result.complete is True and result.levels["5"] == "not_applicable"
    assert result.report["records"] == [{"label": "@e", "target": "entity", "planned_status": "auto_verified",
                                         "risk": []}]


def test_entity_audit_sample(kb, store, docs, monkeypatch):
    monkeypatch.setattr(review, "AUDIT_RATE", 1.0)
    result = send(kb, store, docs, entity("@e"))
    assert result.records[0]["status"] == "auto_verified"
    assert [q["reason"] for q in result.queued] == ["audit"]
    assert result.complete is False and result.levels["5"] == "not_applicable"


def test_in_audit_is_deterministic():
    rid = uuid.UUID("01900000-0000-7000-8000-000000000001")
    assert review.in_audit(rid, 1.0) is True and review.in_audit(rid, 0.0) is False
    assert review.in_audit(rid, 0.5) == review.in_audit(rid, 0.5)
    share = sum(review.in_audit(uuid.UUID(int=(0x0190 << 112) | (7 << 76) | (2 << 62) | i), review.AUDIT_RATE)
                for i in range(20000)) / 20000
    assert 0.01 < share < 0.03


def test_entity_with_risk_goes_to_person(pg, store, docs, monkeypatch, tmp_path):
    risky = pack(tmp_path / "risky", "risky", {"any_entity": {
        "code": "any_entity", "version": "1.0.0", "target": "entity",
        "description": {"ru": "Все сущности — к человеку."}, "high_risk": ["always"]}})
    monkeypatch.setenv("AMEM_PACKS", os.pathsep.join([str(CHECK_PACK), str(risky)]))
    monkeypatch.setenv("AMEM_BACKEND", "none")
    db.prepare(pg)
    result = send(pg, store, docs, entity("@e"))
    assert result.records[0]["status"] == "needs_review"
    assert result.report["records"][0]["risk"] == ["template:document:always"]
    assert [q["reason"] for q in result.queued] == ["high_risk"]


# --- правки ---

def first(conn, store, docs, body) -> dict:
    result = send(conn, store, docs, body)
    assert result.state == "approved", result.report["issues"]
    return result.records[0]


def test_edit_of_verified_waits_for_person(kb, store, docs):
    rec = first(kb, store, docs, wind())
    records.set_status(kb, "atom", rec["record_id"], "verified", agent=PERSON)
    result = send(kb, store, docs, Proposal("atom", wind(summary_plain=lab("Давление ветра для района II.")),
                                            rec["record_id"]))
    assert result.state == "approved"
    [new] = result.records
    assert new["created"] is True and new["review_state"] == "pending" and new["status"] == "verified"
    assert current(kb, rec["record_id"]) == rec["revision_id"]
    assert status(kb, "atom", rec["record_id"]) == "verified"
    assert [q["reason"] for q in result.queued] == ["edit"]
    assert result.report["records"][0]["planned_status"] == "verified"


def test_edit_of_draft_replaces_semantic_item(kb, store, docs):
    rec = first(kb, store, docs, wind())
    result = send(kb, store, docs, Proposal("atom", wind(summary_plain=lab("Давление ветра для района II.")),
                                            rec["record_id"]))
    [new] = result.records
    assert new["created"] is True and current(kb, rec["record_id"]) == new["revision_id"]
    assert new["status"] == "draft"
    assert items(kb, rec["record_id"]) == [("semantic", "obsolete", rec["revision_id"]),
                                           ("semantic", "queued", new["revision_id"])]
    closed = kb.execute("SELECT closed_at FROM review_item WHERE atom_revision_id = %s",
                        (rec["revision_id"],)).fetchone()[0]
    assert closed == kb.execute("SELECT created_at FROM changeset WHERE id = %s", (result.changeset_id,)).fetchone()[0]


def test_edit_with_warning_moves_status_to_needs_review(kb, store, docs):
    rec = first(kb, store, docs, wind())
    v = objects.message(kb, "Письмо о ветровом давлении")
    result = send(kb, store, docs, Proposal("atom", wind(sources=[{"object": v.ref, "object_version": 1}]),
                                            rec["record_id"]))
    assert result.records[0]["status"] == "needs_review"
    assert status(kb, "atom", rec["record_id"]) == "needs_review"
    log = kb.execute("SELECT status, agent, reason FROM status_log WHERE record_id = %s ORDER BY changed_at, id",
                     (rec["record_id"],)).fetchall()
    assert log[-1] == ("needs_review", AGENT, "autocheck")
    assert [r[:2] for r in items(kb, rec["record_id"])] == [("semantic", "obsolete"), ("warning", "queued")]


def test_edit_of_deprecated_is_rejected(kb, store, docs):
    rec = first(kb, store, docs, wind())
    records.set_status(kb, "atom", rec["record_id"], "deprecated", agent=PERSON)
    result = send(kb, store, docs, Proposal("atom", wind(summary_plain=lab("Новое пояснение.")), rec["record_id"]))
    assert result.state == "rejected"
    assert ("retired_record", "violation", "@a") in codes(result)
    assert result.levels["5"] == "skipped"


def test_same_body_keeps_status_and_refreshes_verdicts(kb, store, docs):
    rec = first(kb, store, docs, wind())
    records.set_status(kb, "atom", rec["record_id"], "rejected", agent=PERSON)
    result = send(kb, store, docs, Proposal("atom", wind(), rec["record_id"]))
    assert result.state == "approved"
    [same] = result.records
    assert same["created"] is False and same["revision_id"] == rec["revision_id"] and same["status"] == "rejected"
    assert status(kb, "atom", rec["record_id"]) == "rejected"
    assert result.queued == [] and result.complete is True
    checked = kb.execute("SELECT checked_at FROM source WHERE atom_revision_id = %s", (rec["revision_id"],)).fetchone()
    created_at = kb.execute("SELECT created_at FROM changeset WHERE id = %s", (result.changeset_id,)).fetchone()[0]
    assert checked[0] == created_at


# --- поздние отказы и гонки ---

def test_late_record_error_rejects_whole_batch(kb, store, docs):
    first(kb, store, docs, wind(key="wind_ii"))
    result = send(kb, store, docs, atom("@b", key="wind_ii", label=lab("Анкер М10 ставят в бетон класса B25")),
                  atom("@c", label=lab("Закладная деталь из стали С245")))
    assert result.state == "rejected"
    [issue] = [i for i in result.report["issues"] if i["code"] == "record_error"]
    assert issue["severity"] == "violation" and issue["level"] == 1 and issue["where"] == "@b"
    assert result.levels["3"] == "done" and result.levels["4"] == "done" and result.levels["5"] == "skipped"
    assert result.report["levels"]["3"] == "done"
    assert kb.execute("SELECT count(*) FROM atom").fetchone()[0] == 1
    assert kb.execute("SELECT state FROM changeset WHERE id = %s", (result.changeset_id,)).fetchone()[0] == "rejected"
    assert kb.execute("SELECT count(*) FROM review_item").fetchone()[0] == 1       # только semantic первого пакета
    model_v1.CheckReport.model_validate(result.report)


def test_status_race_rejects_with_retired_record(kb, store, docs, monkeypatch):
    rec = first(kb, store, docs, wind())
    original = level4.check

    def racing(conn, batch, report, **kw):
        records.set_status(conn, "atom", rec["record_id"], "deprecated", agent=PERSON)
        return original(conn, batch, report, **kw)

    monkeypatch.setattr(level4, "check", racing)
    result = send(kb, store, docs, Proposal("atom", wind(summary_plain=lab("Новое пояснение.")), rec["record_id"]))
    assert result.state == "rejected"
    assert ("retired_record", "violation", "@a") in codes(result)
    assert kb.execute("SELECT count(*) FROM atom_revision WHERE atom_id = %s", (rec["record_id"],)).fetchone()[0] == 1
    assert status(kb, "atom", rec["record_id"]) == "deprecated"


def test_source_on_old_object_version_is_queued(kb, store, docs):
    note = docs / "Заметки" / "версии.md"
    note.write_text("# Узел\n\n## Кронштейн\n\nКронштейн КБ-14 крепится анкером.\n", encoding="utf-8")
    v1 = objects.ingest(kb, store, docs, "Заметки/версии.md", agent=AGENT)
    note.write_text("# Узел\n\n## Кронштейн\n\nКронштейн КБ-16 крепится двумя анкерами.\n", encoding="utf-8")
    v2 = objects.ingest(kb, store, docs, "Заметки/версии.md", agent=AGENT)
    assert (v1.n, v2.n) == (1, 2)
    src = {"object": v1.ref, "object_version": 1, "digest": v1.digest,
           "selectors": [{"type": "heading", "value": "Кронштейн"}]}
    result = send(kb, store, docs, atom("@a", sources=[src]))
    assert result.state == "approved", result.report["issues"]
    reasons = {q["reason"]: q for q in result.queued}
    assert set(reasons) == {"semantic", "source_changed"}
    details = kb.execute("SELECT details FROM review_item WHERE id = %s",
                         (reasons["source_changed"]["id"],)).fetchone()[0]
    assert details == {"objects": [{"object": v1.ref, "from": [1], "to": 2}]}         # без замечаний пакета


def test_store_error_is_raised_and_nothing_is_written(kb, store, docs, monkeypatch):
    def broken(*args, **kwargs):
        raise StoreError("корня хранилища нет")

    monkeypatch.setattr(objects, "resolve_sources", broken)
    with pytest.raises(StoreError, match="корня"):
        send(kb, store, docs, wind())
    assert kb.execute("SELECT count(*) FROM changeset").fetchone()[0] == 0
    assert kb.execute("SELECT count(*) FROM atom").fetchone()[0] == 0


def test_links_are_written(kb, store, docs):
    result = send(kb, store, docs, wind(), atom("@b", label=lab("Закладная деталь из стали С245")),
                  links=[{"rel": "see_also", "src": "@a", "dst": "@b"}])
    assert result.state == "approved", result.report["issues"]
    assert kb.execute("SELECT count(*) FROM link WHERE changeset_id = %s", (result.changeset_id,)).fetchone()[0] >= 1


# --- тупики ---

@pytest.mark.parametrize("mode", ["two_agents", "one_new_agent", "submit_and_status"])
def test_new_agents_editing_one_record_do_not_deadlock(kb, store, docs, mode):
    """Два писателя одной записи одновременно, 20 раз. one_new_agent — два пакета одного ещё не записанного агента;
    submit_and_status — пакет и смена статуса (records.set_status) от одного нового агента: set_status вставляет
    агента до блокировки записи, и если бы submit вставлял его после своей блокировки, они встали бы в тупик."""
    rec = first(kb, store, docs, wind())
    params = conninfo_to_dict(kb.info.dsn)
    params["password"] = kb.info.password
    dsn = make_conninfo(**params)
    for round_ in range(20):
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []
        states: list[str] = []

        def writer(k: int) -> None:
            try:
                with db.connect(dsn) as conn:
                    body = wind(summary_plain=lab(f"Пояснение {round_}-{k}: давление ветра района II."))
                    agent = f"model:writer-{round_}" if mode != "two_agents" else f"model:writer-{round_}-{k}"
                    barrier.wait(timeout=30)
                    if mode == "submit_and_status" and k == 1:
                        records.set_status(conn, "atom", rec["record_id"], "needs_review", agent=agent)
                        states.append("approved")
                        return
                    result = check.submit(conn, store, docs, [Proposal("atom", body, rec["record_id"])],
                                          agent=agent)
                    states.append(result.state)
            except BaseException as e:                     # noqa: BLE001 — ошибку потока проверяет тест
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(k,)) for k in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)
        assert not any(isinstance(e, psycopg.errors.DeadlockDetected) for e in errors), errors
        assert errors == [] and states == ["approved", "approved"], (round_, errors, states)
    open_items = kb.execute("SELECT count(*) FROM review_item WHERE record_id = %s AND state = 'queued'",
                            (rec["record_id"],)).fetchone()[0]
    assert open_items == 1                                 # открыт только пункт текущей ревизии


def test_report_has_violations_and_summary():
    from amem.check.report import Report

    report = Report()
    assert report.has_violations() is False and report.summary() == "Замечаний нет"
    report.add(2, "info", "page_moved", "@a: sources[0]", "Цитата найдена на странице 3, а не 2", page=3)
    report.add(1, "violation", "template", "@b: sources", "У атома нет источника.")
    assert report.has_violations() is True
    assert report.summary() == ("Ошибок: 1, предупреждений: 0, сведений: 1\n"
                                "- violation template — @b: sources: У атома нет источника.")


def test_new_agent_is_inserted_before_record_lock(kb, store, docs, monkeypatch):
    """Порядок шага 1 разд. 7.5 — детерминированно. Пакет нового агента держит запись (после блокировки ждёт),
    тем временем тот же агент меняет статус записи: set_status вставляет агента, затем ждёт запись. Если бы submit
    вставлял агента после блокировки записи, он ждал бы незафиксированного агента, а тот — запись: тупик.
    При правильном порядке вставка агента в set_status ждёт фиксации пакета, и оба доходят до конца."""
    rec = first(kb, store, docs, wind())
    params = conninfo_to_dict(kb.info.dsn)
    params["password"] = kb.info.password
    dsn = make_conninfo(**params)
    agent = "model:writer-new"
    locked, inserted = threading.Event(), threading.Event()
    errors: list[BaseException] = []
    decide, ensure = check._decide, records._ensure_agent

    def decide_and_wait(plan, status):
        decide(plan, status)
        if threading.current_thread().name == "submit":
            locked.set()
            inserted.wait(timeout=2)        # при правильном порядке не дождётся: вставка агента ждёт этот пакет

    def ensure_and_signal(conn, who):
        ensure(conn, who)
        if threading.current_thread().name == "status":
            inserted.set()

    monkeypatch.setattr(check, "_decide", decide_and_wait)
    monkeypatch.setattr(records, "_ensure_agent", ensure_and_signal)

    def run(name: str) -> None:
        try:
            with db.connect(dsn) as conn:
                if name == "submit":
                    body = wind(summary_plain=lab("Пояснение: давление ветра района II."))
                    result = check.submit(conn, store, docs, [Proposal("atom", body, rec["record_id"])], agent=agent)
                    assert result.state == "approved", result.report["issues"]
                else:
                    assert locked.wait(timeout=60)
                    records.set_status(conn, "atom", rec["record_id"], "needs_review", agent=agent)
        except BaseException as e:                         # noqa: BLE001 — ошибку потока проверяет тест
            errors.append(e)

    threads = [threading.Thread(target=run, args=(n,), name=n) for n in ("submit", "status")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert not any(isinstance(e, psycopg.errors.DeadlockDetected) for e in errors), errors
    assert errors == []
    assert status(kb, "atom", rec["record_id"]) == "needs_review"


# --- неверный вызов ---

def test_empty_batch_is_check_error(kb, store, docs):
    with pytest.raises(check.CheckError, match="пустая пачка"):
        check.submit(kb, store, docs, [], [], agent=AGENT)
    assert kb.execute("SELECT count(*) FROM changeset").fetchone()[0] == 0
    assert kb.execute("SELECT count(*) FROM agent WHERE id = %s", (AGENT,)).fetchone()[0] == 0


def test_connection_without_autocommit_is_check_error(kb, store, docs):
    params = conninfo_to_dict(kb.info.dsn)
    params["password"] = kb.info.password
    with psycopg.connect(make_conninfo(**params)) as conn:          # autocommit=False
        with pytest.raises(check.CheckError, match="autocommit"):
            check.submit(conn, store, docs, [prop(wind())], agent=AGENT)
    assert kb.execute("SELECT count(*) FROM changeset").fetchone()[0] == 0


def test_unknown_activity_is_check_error(kb, store, docs):
    with pytest.raises(check.CheckError, match="activity"):
        send(kb, store, docs, wind(), activity=uuid.UUID("01900000-0000-7000-8000-000000000001"))
    assert kb.execute("SELECT count(*) FROM changeset").fetchone()[0] == 0


def test_unknown_target_is_schema_issue(kb, store, docs):
    result = check.submit(kb, store, docs, [Proposal("link", {"ref": "@x"})], agent=AGENT)
    assert result.state == "rejected"
    assert [c[0] for c in codes(result)] == ["schema"]


# --- сквозные: уровни 2–4 в записи ---

def test_conflict_is_risk_and_goes_to_person(kb, store, docs):
    stored = records.commit(kb, [records.Item("entity", entity("@e")), records.Item("atom", atom(
        "@a0", label=lab("Давление ветра района II по старым данным"), sources=None,
        content={"values": [value("pressure", 0.38, "kPa")]}, about=["@e"]))], agent=AGENT)
    ent, rival = stored.refs["@e"], stored.refs["@a0"]
    result = send(kb, store, docs, wind(content={"values": [value("pressure", 0.3, "kPa")]}, about=[ent]))
    assert result.state == "approved", result.report["issues"]
    assert result.report["records"][0]["risk"] == ["conflict"]
    assert result.records[0]["status"] == "needs_review"
    [queued] = result.queued
    assert queued["reason"] == "high_risk"
    details = kb.execute("SELECT details FROM review_item WHERE id = %s", (queued["id"],)).fetchone()[0]
    assert details["risk"] == ["conflict"]
    assert {"code": "conflict", "ref": rival, "suggest": "contradicts"} in details["candidates"]


def test_moved_quote_fixes_page_in_source(kb, store, docs):
    result = send(kb, store, docs, wind(sources=[source_pdf(PDF, 3, PAGE2)]))
    assert ("page_moved", "info", "@a: sources[0]") in codes(result)
    assert result.records[0]["status"] == "draft"                  # info на статус не влияет
    row = kb.execute("SELECT verdict, page, selectors FROM source WHERE atom_revision_id = %s",
                     (result.records[0]["revision_id"],)).fetchone()
    assert row[:2] == ("moved", 2) and row[2] == [{"type": "page", "value": "3"}]


def test_similar_entity_goes_to_person_with_same_as(kb, store, docs):
    old = first(kb, store, docs, entity("@e0", cls="organization", label=lab("Пример"),
                                        aliases=["Пример и партнёры"]))
    result = send(kb, store, docs, entity("@e1", cls="organization", label=lab("Пример и партнеры")))
    assert result.records[0]["status"] == "needs_review"
    [queued] = result.queued
    assert queued["reason"] == "warning"
    details = kb.execute("SELECT details FROM review_item WHERE id = %s", (queued["id"],)).fetchone()[0]
    [cand] = [c for c in details["candidates"] if c["code"] == "duplicate"]
    assert cand["ref"] == f"ent:{old['record_id']}" and cand["suggest"] == "same_as"


def test_active_model_and_provider_give_no_degraded(kb, store, docs, monkeypatch):
    monkeypatch.delenv("AMEM_BACKEND")
    fake = FakeProvider()
    model = embed.register_model(kb, fake)
    embed.sync_embeddings(kb, model["id"], fake)
    embed.activate_model(kb, model["id"])
    result = send(kb, store, docs, wind(), provider=fake)
    assert result.state == "approved"
    assert result.report["degraded"] == []
    assert fake.calls                                              # вектор действительно считался
