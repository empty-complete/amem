"""Очередь проверки: захват с арендой, права, решение с вердиктом и последствиями, аудит, ручная постановка
(разд. 7.3–7.5, 8.2–8.6 спецификации подпроекта 3). Пункты ставит check.submit — как в работе."""
import threading
import time
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from amem import check, db, objects, records, review
from amem.check import Proposal
from check_support import CHECK_PACK, PDF, atom, entity, source_pdf

AUTHOR = "model:writer"
MODEL = "model:verifier"
PERSON = "person:ann"
PAGE2 = "Ветровой район II: w0 = 0,30 кПа"


@pytest.fixture
def kb(pg, monkeypatch):
    monkeypatch.setenv("AMEM_PACKS", str(CHECK_PACK))
    monkeypatch.setenv("AMEM_BACKEND", "none")
    monkeypatch.setattr(review, "AUDIT_RATE", 0.0)
    db.prepare(pg)
    return pg


def lab(text: str) -> dict:
    return {"ru": text}


def wind(**kw) -> dict:
    return atom("@a", **{"label": lab("Нормативное ветровое давление района II"),
                         "sources": [source_pdf(PDF, 2, PAGE2)], **kw})


def send(conn, store, docs, body, record_id=None, agent=AUTHOR) -> check.Submitted:
    target = "entity" if "entity_class" in body else "atom"
    result = check.submit(conn, store, docs, [Proposal(target, body, record_id)], agent=agent)
    assert result.state == "approved", result.report["issues"]
    return result


def queued(result: check.Submitted, reason: str):
    [item] = [q for q in result.queued if q["reason"] == reason]
    return item["id"]


def state(conn, item_id) -> str:
    return conn.execute("SELECT state FROM review_item WHERE id = %s", (item_id,)).fetchone()[0]


def status(conn, record_id, target="atom") -> str:
    return conn.execute(f"SELECT status FROM {target} WHERE id = %s", (record_id,)).fetchone()[0]


def open_items(conn, record_id) -> list[tuple]:
    return conn.execute("SELECT reason, coalesce(atom_revision_id, entity_revision_id) FROM review_item "
                        "WHERE record_id = %s AND state IN ('queued', 'claimed') ORDER BY created_at, id",
                        (record_id,)).fetchall()


def verification(conn, item_id) -> tuple:
    return conn.execute("SELECT method, outcome, confidence, agent, note FROM verification WHERE review_item_id = %s",
                        (item_id,)).fetchone()


def dsn_of(conn) -> str:
    params = conninfo_to_dict(conn.info.dsn)
    params["password"] = conn.info.password
    return make_conninfo(**params)


def warned(conn, store, docs, text="Письмо о креплении кронштейна") -> check.Submitted:
    """Атом с источником-письмом: предупреждение, пункт warning."""
    v = objects.message(conn, text)
    return send(conn, store, docs, atom("@w", sources=[{"object": v.ref, "object_version": 1}]))


# --- захват ---

def test_claim_returns_oldest_semantic_with_body_sources_and_author(kb, store, docs):
    first = send(kb, store, docs, wind())
    send(kb, store, docs, atom("@b", label=lab("Закладная деталь из стали С245")))
    [got] = review.claim(kb, agent=MODEL)
    rec = first.records[0]
    assert got["id"] == queued(first, "semantic") and got["reason"] == "semantic"
    assert got["state"] == "claimed" and got["claimed_by"] == MODEL
    assert got["claimed_until"] > datetime.now(timezone.utc) + timedelta(minutes=14)
    assert got["record_id"] == rec["record_id"] and got["revision_id"] == rec["revision_id"]
    assert got["ref"] == f"atm:{rec['record_id']}" and got["target"] == "atom"
    assert got["payload"]["label"] == lab("Нормативное ветровое давление района II")
    assert got["author"] == AUTHOR and got["changeset_id"] == first.changeset_id
    [src] = got["sources"]
    assert src["verdict"] == "ok" and src["page"] == 2 and src["quote"] == PAGE2
    assert state(kb, got["id"]) == "claimed"


def test_model_gets_only_semantic_and_not_its_own(kb, store, docs):
    w = warned(kb, store, docs)
    assert review.claim(kb, agent=MODEL) == []
    own = send(kb, store, docs, wind(), agent=MODEL)
    assert review.claim(kb, agent=MODEL) == []                 # свой semantic автору не достаётся
    [got] = review.claim(kb, agent="model:other")
    assert got["id"] == queued(own, "semantic")
    assert state(kb, queued(w, "warning")) == "queued"


def test_person_author_gets_own_semantic(kb, store, docs):
    own = send(kb, store, docs, wind(), agent=PERSON)
    assert own.queued == []                           # запись человека в очередь не ставится (спецификация 3c, разд. 5)
    rec = own.records[0]
    with kb.transaction():                              # пункт на ревизию человека — как поставил бы его submit до 3c
        item = review.insert_item(kb, "atom", rec["record_id"], rec["revision_id"], "semantic",
                                  changeset_id=own.changeset_id, details={}, agent=PERSON,
                                  at=datetime.now(timezone.utc))
    [got] = review.claim(kb, agent=PERSON)              # исключение автора — только для модели (разд. 8.2)
    assert got["id"] == item["id"] and got["author"] == PERSON


def test_claim_rejects_unknown_reasons(kb, store, docs):
    send(kb, store, docs, wind())
    with pytest.raises(review.ReviewError, match="неизвестные причины"):
        review.claim(kb, agent=PERSON, reasons=["semantic", "nonsense"])
    with pytest.raises(review.ReviewError, match="не строка"):
        review.claim(kb, agent=MODEL, reasons="semantic")
    assert review.claim(kb, agent=MODEL, reasons=["warning"]) == []        # известная, но недоступная — фильтр
    assert kb.execute("SELECT count(*) FROM review_item WHERE state = 'claimed'").fetchone()[0] == 0


def test_person_gets_everything(kb, store, docs):
    w = warned(kb, store, docs)
    s = send(kb, store, docs, wind())
    got = review.claim(kb, agent=PERSON, limit=10)
    assert [g["id"] for g in got] == [queued(w, "warning"), queued(s, "semantic")]
    assert review.claim(kb, agent=PERSON, limit=10) == []


def test_claim_filters_by_reasons(kb, store, docs):
    w = warned(kb, store, docs)
    send(kb, store, docs, wind())
    [got] = review.claim(kb, agent=PERSON, reasons=["warning"], limit=10)
    assert got["id"] == queued(w, "warning")
    assert review.claim(kb, agent=MODEL, reasons=["warning"]) == []


def test_parallel_claims_get_different_items(kb, store, docs):
    for i in range(4):
        warned(kb, store, docs, f"Письмо {i} о креплении кронштейна")
    dsn = dsn_of(kb)
    barrier = threading.Barrier(2)
    got: list[list[dict]] = [[], []]
    errors: list[BaseException] = []

    def worker(k: int) -> None:
        try:
            with db.connect(dsn) as conn:
                barrier.wait(timeout=30)
                got[k] = review.claim(conn, agent=f"person:p{k}", limit=2)
        except BaseException as e:                         # noqa: BLE001 — ошибку потока проверяет тест
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert errors == []
    ids = [g["id"] for g in got[0] + got[1]]
    assert len(ids) == len(set(ids)) and len(ids) == 4


def test_expired_lease_goes_to_another(kb, store, docs):
    s = send(kb, store, docs, wind())
    [mine] = review.claim(kb, agent=MODEL)
    assert review.claim(kb, agent="model:other") == []
    later = datetime.now(timezone.utc) + timedelta(minutes=20)
    [theirs] = review.claim(kb, agent="model:other", now=later)
    assert theirs["id"] == mine["id"] == queued(s, "semantic") and theirs["claimed_by"] == "model:other"


def test_release(kb, store, docs):
    s = send(kb, store, docs, wind())
    [got] = review.claim(kb, agent=MODEL)
    with pytest.raises(review.ReviewError, match="держит"):
        review.release(kb, got["id"], agent="model:other")
    review.release(kb, got["id"], agent=MODEL)
    row = kb.execute("SELECT state, claimed_by, claimed_until FROM review_item WHERE id = %s",
                     (queued(s, "semantic"),)).fetchone()
    assert row == ("queued", None, None)
    with pytest.raises(review.ReviewError):
        review.release(kb, got["id"], agent=MODEL)                 # уже не захвачен


# --- решение по semantic ---

def test_model_confirms_semantic_with_high_confidence(kb, store, docs):
    s = send(kb, store, docs, wind())
    rec = s.records[0]
    out = review.resolve(kb, queued(s, "semantic"), "confirmed", confidence=0.9, agent=MODEL, note="совпадает")
    assert out["status"] == "auto_verified" and out["queued"] == []
    assert status(kb, rec["record_id"]) == "auto_verified"
    assert verification(kb, queued(s, "semantic")) == ("llm_judge", "confirmed", 0.9, MODEL, "совпадает")
    assert out["verification_id"] == kb.execute("SELECT id FROM verification WHERE review_item_id = %s",
                                                (queued(s, "semantic"),)).fetchone()[0]
    assert state(kb, queued(s, "semantic")) == "done"
    log = kb.execute("SELECT status, agent, reason FROM status_log WHERE record_id = %s ORDER BY changed_at DESC, id "
                     "DESC LIMIT 1", (rec["record_id"],)).fetchone()
    assert log == ("auto_verified", MODEL, "review:semantic")


@pytest.mark.parametrize("outcome,confidence", [("confirmed", 0.5), ("partial", 0.9), ("refuted", 0.9),
                                                ("uncertain", 0.9)])
def test_model_doubt_goes_to_person(kb, store, docs, outcome, confidence):
    s = send(kb, store, docs, wind())
    rec = s.records[0]
    out = review.resolve(kb, queued(s, "semantic"), outcome, confidence=confidence, agent=MODEL)
    assert out["status"] == "needs_review" and status(kb, rec["record_id"]) == "needs_review"
    [doubt] = out["queued"]
    assert doubt["reason"] == "semantic_doubt" and doubt["record_id"] == rec["record_id"]
    assert open_items(kb, rec["record_id"]) == [("semantic_doubt", rec["revision_id"])]
    details = kb.execute("SELECT details FROM review_item WHERE id = %s", (doubt["id"],)).fetchone()[0]
    assert details["outcome"] == outcome and details["confidence"] == confidence


@pytest.mark.parametrize("confidence,expected", [(0.8, "auto_verified"), (0.79, "needs_review")])
def test_semantic_threshold_is_inclusive(kb, store, docs, confidence, expected):
    """Порог SEMANTIC_MIN_CONFIDENCE = 0,8 включается: ровно 0,8 — подтверждение, чуть меньше — сомнение."""
    s = send(kb, store, docs, wind())
    out = review.resolve(kb, queued(s, "semantic"), "confirmed", confidence=confidence, agent=MODEL)
    assert out["status"] == expected


def test_model_without_confidence_is_error(kb, store, docs):
    s = send(kb, store, docs, wind())
    with pytest.raises(review.ReviewError, match="confidence"):
        review.resolve(kb, queued(s, "semantic"), "confirmed", agent=MODEL)
    with pytest.raises(review.ReviewError, match="confidence"):
        review.resolve(kb, queued(s, "semantic"), "confirmed", confidence=1.5, agent=MODEL)
    assert state(kb, queued(s, "semantic")) == "queued"
    assert kb.execute("SELECT count(*) FROM verification").fetchone()[0] == 0


def test_author_model_cannot_resolve_its_semantic(kb, store, docs):
    s = send(kb, store, docs, wind())
    with pytest.raises(review.ReviewError, match="автор"):
        review.resolve(kb, queued(s, "semantic"), "confirmed", confidence=0.9, agent=AUTHOR)


def test_person_on_semantic(kb, store, docs):
    s = send(kb, store, docs, wind())
    rec = s.records[0]
    with pytest.raises(review.ReviewError, match="uncertain"):
        review.resolve(kb, queued(s, "semantic"), "uncertain", agent=PERSON)
    out = review.resolve(kb, queued(s, "semantic"), "confirmed", agent=PERSON)
    assert out["status"] == "verified" and status(kb, rec["record_id"]) == "verified"
    assert verification(kb, queued(s, "semantic"))[:2] == ("human", "confirmed")


def test_claimed_by_other_cannot_be_resolved(kb, store, docs):
    s = send(kb, store, docs, wind())
    review.claim(kb, agent="model:other")
    with pytest.raises(review.ReviewError, match="захвачен"):
        review.resolve(kb, queued(s, "semantic"), "confirmed", confidence=0.9, agent=MODEL)
    later = datetime.now(timezone.utc) + timedelta(minutes=20)
    out = review.resolve(kb, queued(s, "semantic"), "confirmed", confidence=0.9, agent=MODEL, now=later)
    assert out["status"] == "auto_verified"


def test_resolved_item_cannot_be_resolved_again(kb, store, docs):
    s = send(kb, store, docs, wind())
    review.resolve(kb, queued(s, "semantic"), "confirmed", agent=PERSON)
    with pytest.raises(review.ReviewError, match="закрыт"):
        review.resolve(kb, queued(s, "semantic"), "refuted", agent=PERSON)


# --- права и прочие причины ---

def test_warning_rights_and_refute(kb, store, docs):
    w = warned(kb, store, docs)
    rec = w.records[0]
    with pytest.raises(review.ReviewError, match="только человек"):
        review.resolve(kb, queued(w, "warning"), "confirmed", confidence=0.9, agent=MODEL)
    with pytest.raises(review.ReviewError, match="partial"):
        review.resolve(kb, queued(w, "warning"), "partial", agent=PERSON)
    out = review.resolve(kb, queued(w, "warning"), "refuted", agent=PERSON, note="письмо не про это")
    assert out["status"] == "rejected" and status(kb, rec["record_id"]) == "rejected"
    assert verification(kb, queued(w, "warning")) == ("human", "refuted", None, PERSON, "письмо не про это")


def test_unknown_agent_kind_is_error(kb, store, docs):
    s = send(kb, store, docs, wind())
    with pytest.raises(review.ReviewError, match="person:"):
        review.resolve(kb, queued(s, "semantic"), "confirmed", agent="robot:x")


def edited(kb, store, docs, text="Давление ветра для района II.", agent=AUTHOR):
    first = send(kb, store, docs, wind())
    rec = first.records[0]
    records.set_status(kb, "atom", rec["record_id"], "verified", agent=PERSON)
    result = send(kb, store, docs, wind(summary_plain=lab(text)), rec["record_id"], agent=agent)
    return rec, result


def test_edit_confirmed_becomes_current(kb, store, docs):
    rec, result = edited(kb, store, docs)
    new = result.records[0]
    out = review.resolve(kb, queued(result, "edit"), "confirmed", agent=PERSON)
    assert out["status"] == "verified" and status(kb, rec["record_id"]) == "verified"
    current = kb.execute("SELECT id, review_state FROM atom_current WHERE atom_id = %s",
                         (rec["record_id"],)).fetchone()
    assert current == (new["revision_id"], "accepted")
    assert open_items(kb, rec["record_id"]) == []


def test_edit_refuted_is_declined(kb, store, docs):
    rec, result = edited(kb, store, docs)
    new = result.records[0]
    out = review.resolve(kb, queued(result, "edit"), "refuted", agent=PERSON)
    assert out["status"] == "verified"
    assert kb.execute("SELECT review_state FROM atom_revision WHERE id = %s",
                      (new["revision_id"],)).fetchone()[0] == "declined"
    assert kb.execute("SELECT id FROM atom_current WHERE atom_id = %s",
                      (rec["record_id"],)).fetchone()[0] == rec["revision_id"]


def test_person_edit_of_verified_needs_no_confirmation(kb, store, docs):
    """Правка человеком проверенной записи (спецификация 3c, разд. 5): сразу текущая, пункта edit нет."""
    rec, result = edited(kb, store, docs, agent=PERSON)
    assert result.queued == [] and result.records[0]["review_state"] == "none"
    assert status(kb, rec["record_id"]) == "verified"
    assert kb.execute("SELECT id FROM atom_current WHERE atom_id = %s",
                      (rec["record_id"],)).fetchone()[0] == result.records[0]["revision_id"]


def test_edit_verdict_without_decision_when_status_moved(kb, store, docs):
    """Ожидаемый статус edit — verified: если запись успела уйти в needs_review, вердикт пишется, а правка
    остаётся ждать решения — records.decide не вызывается."""
    rec, result = edited(kb, store, docs)
    records.set_status(kb, "atom", rec["record_id"], "needs_review", agent=PERSON)
    item_id = queued(result, "edit")
    out = review.resolve(kb, item_id, "confirmed", agent=PERSON)
    assert out["status"] == "needs_review"
    assert kb.execute("SELECT review_state FROM atom_revision WHERE id = %s",
                      (result.records[0]["revision_id"],)).fetchone()[0] == "pending"
    assert verification(kb, item_id)[:2] == ("human", "confirmed") and state(kb, item_id) == "done"


def test_edit_by_model_is_error(kb, store, docs):
    _, result = edited(kb, store, docs)
    with pytest.raises(review.ReviewError, match="только человек"):
        review.resolve(kb, queued(result, "edit"), "confirmed", confidence=0.9, agent=MODEL)


# --- несколько пунктов у ревизии ---

def old_version_atom(kb, store, docs) -> check.Submitted:
    """Атом со ссылкой на первую версию заметки, у которой уже есть вторая: пункты semantic и source_changed."""
    note = docs / "Заметки" / "версии.md"
    note.write_text("# Узел\n\n## Кронштейн\n\nКронштейн КБ-14 крепится анкером.\n", encoding="utf-8")
    v1 = objects.ingest(kb, store, docs, "Заметки/версии.md", agent=AUTHOR)
    note.write_text("# Узел\n\n## Кронштейн\n\nКронштейн КБ-16 крепится двумя анкерами.\n", encoding="utf-8")
    objects.ingest(kb, store, docs, "Заметки/версии.md", agent=AUTHOR)
    src = {"object": v1.ref, "object_version": 1, "digest": v1.digest,
           "selectors": [{"type": "heading", "value": "Кронштейн"}]}
    return send(kb, store, docs, atom("@a", sources=[src]))


def test_person_decision_closes_other_items_of_revision(kb, store, docs):
    result = old_version_atom(kb, store, docs)
    rec = result.records[0]
    out = review.resolve(kb, queued(result, "source_changed"), "confirmed", agent=PERSON)
    assert out["status"] == "verified"
    assert state(kb, queued(result, "semantic")) == "obsolete"
    assert open_items(kb, rec["record_id"]) == []


def test_person_decision_keeps_source_changed_open(kb, store, docs):
    """Решавший semantic не видел новой версии файла: source_changed остаётся отдельным вопросом (разд. 7.3)."""
    result = old_version_atom(kb, store, docs)
    rec = result.records[0]
    out = review.resolve(kb, queued(result, "semantic"), "confirmed", agent=PERSON)
    assert out["status"] == "verified"
    assert state(kb, queued(result, "source_changed")) == "queued"
    assert open_items(kb, rec["record_id"]) == [("source_changed", rec["revision_id"])]


def test_model_verdict_without_status_change_when_status_moved(kb, store, docs):
    s = send(kb, store, docs, wind())
    rec = s.records[0]
    records.set_status(kb, "atom", rec["record_id"], "verified", agent=PERSON)
    out = review.resolve(kb, queued(s, "semantic"), "refuted", confidence=0.9, agent=MODEL)
    assert out["status"] == "verified" and out["queued"] == []
    assert status(kb, rec["record_id"]) == "verified"
    assert verification(kb, queued(s, "semantic"))[:2] == ("llm_judge", "refuted")
    assert state(kb, queued(s, "semantic")) == "done"


def test_two_pending_edits_newer_accepted_closes_older_on_claim(kb, store, docs):
    rec, older = edited(kb, store, docs, text="Давление ветра для района II, вариант один.")
    newer = send(kb, store, docs, wind(summary_plain=lab("Давление ветра для района II, вариант два.")),
                 rec["record_id"])
    assert state(kb, queued(older, "edit")) == "queued"
    records.decide(kb, "atom", newer.records[0]["revision_id"], True, agent=PERSON)      # мимо очереди
    got = review.claim(kb, agent=PERSON, reasons=["edit"], limit=10)
    assert [g["id"] for g in got] == [queued(newer, "edit")]
    assert state(kb, queued(older, "edit")) == "obsolete"


def test_accepting_newer_edit_through_queue_closes_older(kb, store, docs):
    rec, older = edited(kb, store, docs, text="Давление ветра для района II, вариант один.")
    newer = send(kb, store, docs, wind(summary_plain=lab("Давление ветра для района II, вариант два.")),
                 rec["record_id"])
    review.resolve(kb, queued(newer, "edit"), "confirmed", agent=PERSON)
    assert state(kb, queued(older, "edit")) == "obsolete"


# --- устаревание мимо очереди ---

def bypass(kb, rec) -> None:
    """Новая ревизия записи через records.commit, минуя submit и его закрытие пунктов."""
    records.commit(kb, [records.Item("atom", atom(None, label=lab("Нормативное ветровое давление, новая редакция"),
                                                  sources=None), rec["record_id"])], agent=PERSON)


def test_stale_item_is_closed_on_claim(kb, store, docs):
    s = send(kb, store, docs, wind())
    bypass(kb, s.records[0])
    assert state(kb, queued(s, "semantic")) == "queued"
    assert review.claim(kb, agent=MODEL) == []
    assert state(kb, queued(s, "semantic")) == "obsolete"


def test_stale_item_is_closed_on_resolve(kb, store, docs):
    s = send(kb, store, docs, wind())
    bypass(kb, s.records[0])
    with pytest.raises(review.ReviewError, match="устарел"):
        review.resolve(kb, queued(s, "semantic"), "confirmed", confidence=0.9, agent=MODEL)
    assert state(kb, queued(s, "semantic")) == "obsolete"
    assert kb.execute("SELECT count(*) FROM verification").fetchone()[0] == 0


def test_stale_check_comes_before_lease_and_rights(kb, store, docs):
    """Устаревший пункт закрывается, даже если он захвачен другим или решающий не вправе его решать."""
    s = send(kb, store, docs, wind())
    review.claim(kb, agent="model:other")
    bypass(kb, s.records[0])
    with pytest.raises(review.ReviewError, match="устарел"):
        review.resolve(kb, queued(s, "semantic"), "confirmed", confidence=0.9, agent=MODEL)
    assert state(kb, queued(s, "semantic")) == "obsolete"
    w = warned(kb, store, docs)
    records.commit(kb, [records.Item("atom", atom(None, label=lab("Кронштейн, новая редакция"), sources=None),
                                     w.records[0]["record_id"])], agent=PERSON)
    with pytest.raises(review.ReviewError, match="устарел"):
        review.resolve(kb, queued(w, "warning"), "confirmed", confidence=0.9, agent=MODEL)
    assert state(kb, queued(w, "warning")) == "obsolete"
    with pytest.raises(review.ReviewError, match="закрыт"):
        review.resolve(kb, queued(w, "warning"), "confirmed", agent=PERSON)


def test_record_error_in_resolve_is_review_error(kb, store, docs, monkeypatch):
    _, result = edited(kb, store, docs)

    def broken(*args, **kwargs):
        raise records.RecordError("сбой проекции записи")

    monkeypatch.setattr(records, "decide", broken)
    with pytest.raises(review.ReviewError, match="сбой проекции записи"):
        review.resolve(kb, queued(result, "edit"), "confirmed", agent=PERSON)
    assert state(kb, queued(result, "edit")) == "queued"                   # всё откатилось
    assert kb.execute("SELECT count(*) FROM verification").fetchone()[0] == 0


def test_retired_record_item_is_closed_on_claim(kb, store, docs):
    w = warned(kb, store, docs)
    records.set_status(kb, "atom", w.records[0]["record_id"], "deprecated", agent=PERSON)
    assert review.claim(kb, agent=PERSON) == []
    assert state(kb, queued(w, "warning")) == "obsolete"


# --- аудит ---

def test_auto_verified_atom_may_go_to_audit(kb, store, docs, monkeypatch):
    s = send(kb, store, docs, wind())
    monkeypatch.setattr(review, "AUDIT_RATE", 1.0)
    out = review.resolve(kb, queued(s, "semantic"), "confirmed", confidence=0.95, agent=MODEL)
    assert out["status"] == "auto_verified"
    [audit] = out["queued"]
    assert audit["reason"] == "audit"
    assert open_items(kb, s.records[0]["record_id"]) == [("audit", s.records[0]["revision_id"])]
    out = review.resolve(kb, audit["id"], "confirmed", agent=PERSON)
    assert out["status"] == "verified"


# --- ручная постановка ---

def test_enqueue_calibration(kb, store, docs):
    e = send(kb, store, docs, entity("@e"))
    rec = e.records[0]
    ref = f"ent:{rec['record_id']}"
    item_id = review.enqueue(kb, ref, "calibration", agent=PERSON, note="для настройки порога")
    assert review.enqueue(kb, ref, "calibration", agent=PERSON) == item_id
    row = kb.execute("SELECT reason, state, entity_revision_id, changeset_id, created_by, details FROM review_item "
                     "WHERE id = %s", (item_id,)).fetchone()
    assert row[:5] == ("calibration", "queued", rec["revision_id"], None, PERSON)
    assert row[5]["note"] == "для настройки порога"
    assert review.enqueue(kb, ref, "audit", agent=PERSON) != item_id
    with pytest.raises(review.ReviewError, match="person:"):
        review.enqueue(kb, ref, "calibration", agent=MODEL)
    with pytest.raises(review.ReviewError, match="calibration"):
        review.enqueue(kb, ref, "semantic", agent=PERSON)
    with pytest.raises(review.ReviewError, match="записи нет"):
        review.enqueue(kb, "ent:01900000-0000-7000-8000-000000000001", "audit", agent=PERSON)


# --- список ---

def test_items_filters(kb, store, docs):
    w = warned(kb, store, docs)
    s = send(kb, store, docs, wind())
    assert [i["id"] for i in review.items(kb, state="queued", reason="semantic")] == [queued(s, "semantic")]
    assert [i["id"] for i in review.items(kb, state="queued")] == [queued(w, "warning"), queued(s, "semantic")]
    ref = f"atm:{w.records[0]['record_id']}"
    assert [i["id"] for i in review.items(kb, record=ref)] == [queued(w, "warning")]
    assert review.items(kb, state="done") == []
    assert len(review.items(kb, limit=1)) == 1


def test_items_record_by_key_uuid_and_bad_arguments(kb, store, docs):
    s = send(kb, store, docs, wind(key="wind.ii"))
    rec = s.records[0]["record_id"]
    expected = [queued(s, "semantic")]
    assert [i["id"] for i in review.items(kb, record="atm:wind.ii")] == expected
    assert [i["id"] for i in review.items(kb, record=rec)] == expected
    assert [i["id"] for i in review.items(kb, record=str(rec))] == expected
    with pytest.raises(review.ReviewError, match="atm:wind.ii"):
        review.items(kb, record="wind.ii")                       # ключ без приставки — подсказка
    with pytest.raises(review.ReviewError, match="нет записи с ключом"):
        review.items(kb, record="atm:nope")
    with pytest.raises(review.ReviewError, match="состояние"):
        review.items(kb, state="open")
    with pytest.raises(review.ReviewError, match="причина"):
        review.items(kb, reason="nonsense")
    for limit in (0, -1, "5", True):
        with pytest.raises(review.ReviewError, match="limit"):
            review.items(kb, limit=limit)


# --- тупики ---

def wait_locked(conn, app: str, n: int) -> None:
    """Дождаться, пока n соединений с этим application_name встанут в ожидание блокировки."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        waiting = conn.execute("SELECT count(*) FROM pg_stat_activity WHERE application_name = %s "
                               "AND wait_event_type = 'Lock'", (app,)).fetchone()[0]
        if waiting >= n:
            return
        time.sleep(0.02)
    raise AssertionError(f"{app}: за 30 с в ожидание блокировки встали не все {n} соединения")


def crossing(kb, hold, workers) -> list[BaseException]:
    """Третье соединение держит блокировку (hold — запросы в открытой транзакции); оба потока стартуют и встают
    в ожидание; затем блокировка отпускается. Ошибки потоков — в ответе."""
    app = f"amem-cross-{time.monotonic_ns()}"
    params = conninfo_to_dict(dsn_of(kb))
    dsn = make_conninfo(**{**params, "application_name": app})
    errors: list[BaseException] = []

    def run(fn) -> None:
        try:
            with db.connect(dsn) as conn:
                fn(conn)
        except BaseException as e:                         # noqa: BLE001 — ошибку потока проверяет тест
            errors.append(e)

    with db.connect(dsn_of(kb)) as holder, db.connect(dsn_of(kb)) as watch:
        with holder.transaction():
            for sql, args in hold:
                holder.execute(sql, args)
            threads = [threading.Thread(target=run, args=(fn,)) for fn in workers]
            for t in threads:
                t.start()
            wait_locked(watch, app, len(workers))
        for t in threads:
            t.join(timeout=120)
        assert not any(t.is_alive() for t in threads)
    return errors


def test_resolve_and_submit_on_one_record_do_not_deadlock(kb, store, docs):
    """Решение по пункту и новая ревизия той же записи сходятся на заблокированной записи, 10 раз. Оба идут
    агент → запись → пункты: решение либо проходит, либо видит, что пункт устарел (ReviewError), но не тупик."""
    rec = send(kb, store, docs, wind()).records[0]
    for round_ in range(10):
        [item_id] = [i["id"] for i in review.items(kb, state="queued", record=f"atm:{rec['record_id']}")]
        outcomes: list[str] = []

        def submit(conn, round_=round_) -> None:
            body = wind(summary_plain=lab(f"Пояснение {round_}: давление ветра района II."))
            result = check.submit(conn, store, docs, [Proposal("atom", body, rec["record_id"])],
                                  agent=f"model:writer-{round_}")
            assert result.state == "approved", result.report["issues"]
            outcomes.append("submit")

        def resolve(conn, round_=round_, item_id=item_id) -> None:
            try:
                review.resolve(conn, item_id, "confirmed", confidence=0.9, agent=f"model:verifier-{round_}")
                outcomes.append("resolved")
            except review.ReviewError:
                outcomes.append("stale")                    # пункт успел устареть — так и должно быть

        errors = crossing(kb, [("SELECT 1 FROM atom WHERE id = %s FOR NO KEY UPDATE", (rec["record_id"],))],
                          [submit, resolve])
        assert not any(isinstance(e, psycopg.errors.DeadlockDetected) for e in errors), errors
        assert errors == [] and sorted(outcomes) in (["resolved", "submit"], ["stale", "submit"]), (round_, errors)
        assert len(open_items(kb, rec["record_id"])) == 1


def test_claim_and_resolve_do_not_deadlock(kb, store, docs):
    """Захват и решение одного пункта одним новым агентом сходятся на вставке агента (третье соединение вставило
    его и держит запись), 10 раз: claim записи не ждёт, resolve ждёт запись, затем пункт — без тупика."""
    rec = send(kb, store, docs, wind()).records[0]
    for round_ in range(10):
        if round_:
            send(kb, store, docs, wind(summary_plain=lab(f"Пояснение {round_}: давление ветра района II.")),
                 rec["record_id"])
        [item_id] = [i["id"] for i in review.items(kb, state="queued", record=f"atm:{rec['record_id']}")]
        agent = f"model:judge-{round_}"
        got: list = []

        def claim(conn) -> None:
            got.extend(review.claim(conn, agent=agent, reasons=["semantic"], limit=50))

        def resolve(conn) -> None:
            review.resolve(conn, item_id, "confirmed", confidence=0.9, agent=agent)

        errors = crossing(kb, [("INSERT INTO agent (id) VALUES (%s)", (agent,)),
                               ("SELECT 1 FROM atom WHERE id = %s FOR NO KEY UPDATE", (rec["record_id"],))],
                          [claim, resolve])
        assert not any(isinstance(e, psycopg.errors.DeadlockDetected) for e in errors), errors
        assert errors == [], (round_, errors)
        assert state(kb, item_id) == "done"
        assert status(kb, rec["record_id"]) == "auto_verified"
