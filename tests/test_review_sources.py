"""Пересмотр при новой версии объекта (разд. 8.8 спецификации подпроекта 3): objects.ingest новой версии файла
ставит пункты source_changed текущим и ждущим решения ревизиям со ссылкой на старую версию."""
import threading
import time

import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from amem import check, db, objects, records, review
from amem.check import Proposal, level4
from check_support import CHECK_PACK, atom, entity, source_md

AUTHOR = "model:writer"
PERSON = "person:ann"
NOTE = "Заметки/заметка.md"
V1 = "# Узел\n\n## Кронштейн\n\nКронштейн КБ-14 крепится анкером.\n"
V2 = "# Узел\n\n## Кронштейн\n\nКронштейн КБ-16 крепится двумя анкерами.\n"
V3 = "# Узел\n\n## Кронштейн\n\nКронштейн КБ-18 крепится тремя анкерами.\n"


@pytest.fixture
def kb(pg, monkeypatch):
    monkeypatch.setenv("AMEM_PACKS", str(CHECK_PACK))
    monkeypatch.setenv("AMEM_BACKEND", "none")
    monkeypatch.setattr(review, "AUDIT_RATE", 0.0)
    db.prepare(pg)
    return pg


def write(docs, text: str) -> None:
    (docs / NOTE).write_text(text, encoding="utf-8")


def new_version(kb, store, docs, text: str) -> objects.Version:
    write(docs, text)
    return objects.ingest(kb, store, docs, NOTE, agent=PERSON)


def send(conn, store, docs, body, record_id=None, agent=AUTHOR) -> check.Submitted:
    target = "entity" if "entity_class" in body else "atom"
    result = check.submit(conn, store, docs, [Proposal(target, body, record_id)], agent=agent)
    assert result.state == "approved", result.report["issues"]
    return result


def note_atom(label="@a", **kw) -> dict:
    return atom(label, sources=[source_md(NOTE)], **kw)


def note_entity(label="@e") -> dict:
    return entity(label, sources=[source_md(NOTE)])


def changed(kb, revision_id) -> list[tuple]:
    """Пункты source_changed ревизии: (состояние, details, changeset_id, created_by)."""
    return kb.execute("SELECT state, details, changeset_id, created_by FROM review_item "
                      "WHERE coalesce(atom_revision_id, entity_revision_id) = %s AND reason = 'source_changed' "
                      "ORDER BY created_at, id", (revision_id,)).fetchall()


def test_new_version_queues_current_atom_and_entity(kb, store, docs):
    write(docs, V1)
    a = send(kb, store, docs, note_atom()).records[0]
    e = send(kb, store, docs, note_entity()).records[0]
    v2 = new_version(kb, store, docs, V2)
    assert v2.n == 2
    expected = {"objects": [{"object": v2.ref, "from": [1], "to": 2}]}
    for rec in (a, e):
        assert changed(kb, rec["revision_id"]) == [("queued", expected, None, PERSON)]
    items = review.items(kb, reason="source_changed")
    assert {(i["target"], i["record_id"]) for i in items} == {("atom", a["record_id"]), ("entity", e["record_id"])}


def test_pending_edit_on_old_version_is_queued_too(kb, store, docs):
    write(docs, V1)
    first = send(kb, store, docs, note_atom()).records[0]
    records.set_status(kb, "atom", first["record_id"], "verified", agent=PERSON)
    edit = send(kb, store, docs, note_atom(summary_plain={"ru": "Кронштейн держится на анкере."}),
                first["record_id"]).records[0]
    assert edit["review_state"] == "pending"
    v2 = new_version(kb, store, docs, V2)
    expected = {"objects": [{"object": v2.ref, "from": [1], "to": 2}]}
    assert [d for _, d, _, _ in changed(kb, edit["revision_id"])] == [expected]
    assert [d for _, d, _, _ in changed(kb, first["revision_id"])] == [expected]


@pytest.mark.parametrize("retired", ["rejected", "deprecated", "superseded"])
def test_closed_record_is_skipped(kb, store, docs, retired):
    write(docs, V1)
    rec = send(kb, store, docs, note_atom()).records[0]
    records.set_status(kb, "atom", rec["record_id"], retired, agent=PERSON)
    new_version(kb, store, docs, V2)
    assert changed(kb, rec["revision_id"]) == []


def test_old_revision_is_not_queued(kb, store, docs):
    """Ревизия, которая уже не текущая и не ждёт решения, — не вопрос: пересматривается текущая."""
    write(docs, V1)
    first = send(kb, store, docs, note_atom()).records[0]
    second = send(kb, store, docs, note_atom(summary_plain={"ru": "Кронштейн держится на анкере."}),
                  first["record_id"]).records[0]
    new_version(kb, store, docs, V2)
    assert changed(kb, first["revision_id"]) == []
    assert len(changed(kb, second["revision_id"])) == 1


def test_repeated_ingest_and_third_version_do_not_duplicate(kb, store, docs):
    write(docs, V1)
    rec = send(kb, store, docs, note_atom()).records[0]
    v2 = new_version(kb, store, docs, V2)
    again = objects.ingest(kb, store, docs, NOTE, agent=PERSON)
    assert (again.n, again.created) == (2, False)
    assert len(changed(kb, rec["revision_id"])) == 1
    v3 = new_version(kb, store, docs, V3)
    assert v3.n == 3
    [(st, details, _, _)] = changed(kb, rec["revision_id"])
    assert st == "queued" and details == {"objects": [{"object": v2.ref, "from": [1], "to": 2}]}


def test_third_version_after_decision_queues_again(kb, store, docs):
    """Решённый пункт — уже не открытый: следующая версия ставит новый вопрос."""
    write(docs, V1)
    rec = send(kb, store, docs, note_atom()).records[0]
    new_version(kb, store, docs, V2)
    [(item_id,)] = kb.execute("SELECT id FROM review_item WHERE atom_revision_id = %s AND reason = 'source_changed'",
                              (rec["revision_id"],)).fetchall()
    review.resolve(kb, item_id, "confirmed", agent=PERSON)
    v3 = new_version(kb, store, docs, V3)
    states = [(st, d) for st, d, _, _ in changed(kb, rec["revision_id"])]
    assert states[0][0] == "done"
    assert states[1] == ("queued", {"objects": [{"object": v3.ref, "from": [1], "to": 3}]})


def test_revision_on_new_version_makes_item_obsolete(kb, store, docs):
    write(docs, V1)
    rec = send(kb, store, docs, note_atom()).records[0]
    new_version(kb, store, docs, V2)
    [(item_id,)] = kb.execute("SELECT id FROM review_item WHERE atom_revision_id = %s AND reason = 'source_changed'",
                              (rec["revision_id"],)).fetchall()
    new = send(kb, store, docs, note_atom(summary_plain={"ru": "Кронштейн держится на двух анкерах."}),
               rec["record_id"]).records[0]
    assert kb.execute("SELECT object_version FROM source WHERE atom_revision_id = %s",
                      (new["revision_id"],)).fetchone()[0] == 2
    assert kb.execute("SELECT state FROM review_item WHERE id = %s", (item_id,)).fetchone()[0] == "obsolete"
    assert changed(kb, new["revision_id"]) == []


def test_several_sources_on_old_versions(kb, store, docs):
    """Источники одной ревизии на разные старые версии (на v1 — два): в from — каждая один раз, по возрастанию."""
    write(docs, V1)
    v1 = objects.ingest(kb, store, docs, NOTE, agent=PERSON)
    v2 = new_version(kb, store, docs, V2)
    srcs = [{"object": v.ref, "object_version": v.n, "digest": v.digest,
             "selectors": [{"type": "heading", "value": "Кронштейн"}]} for v in (v2, v1, v1)]
    srcs[2]["quote"] = "Кронштейн КБ-14 крепится анкером."
    rec = send(kb, store, docs, atom("@a", sources=srcs)).records[0]
    v3 = new_version(kb, store, docs, V3)
    details = [d for _, d, _, _ in changed(kb, rec["revision_id"])]
    # submit поставил пункт сам (ссылка на v1 при последней v2) в той же форме; v3 его не дублирует и не меняет
    assert details == [{"objects": [{"object": v1.ref, "from": [1], "to": 2}]}]
    review.resolve(kb, review.items(kb, reason="source_changed")[0]["id"], "confirmed", agent=PERSON)
    write(docs, V1 + "\nДобавлено.\n")
    v4 = objects.ingest(kb, store, docs, NOTE, agent=PERSON)
    [last] = [d for st, d, _, _ in changed(kb, rec["revision_id"]) if st == "queued"]
    assert last == {"objects": [{"object": v3.ref, "from": [1, 2], "to": v4.n}]}


def test_ingest_between_resolve_and_write_gives_one_item(kb, store, docs, monkeypatch):
    """Гонка: пакет разобрал путь в v1 и ещё не начал транзакцию записи, другой процесс принял v2. Ревизии
    ingest не видел — пункт ставит сам пакет (разд. 7.5, шаг 6), ровно один."""
    write(docs, V1)
    original = level4.check

    def racing(conn, batch, report, **kw):
        with db.connect(_dsn(kb)) as other:
            new_version(other, store, docs, V2)
        return original(conn, batch, report, **kw)

    monkeypatch.setattr(level4, "check", racing)
    result = send(kb, store, docs, note_atom())
    rec = result.records[0]
    assert kb.execute("SELECT object_version FROM source WHERE atom_revision_id = %s",
                      (rec["revision_id"],)).fetchone()[0] == 1
    items = changed(kb, rec["revision_id"])
    assert len(items) == 1 and items[0][2] == result.changeset_id
    assert [q["reason"] for q in result.queued].count("source_changed") == 1


def _dsn(conn, **extra) -> str:
    params = conninfo_to_dict(conn.info.dsn)
    params["password"] = conn.info.password
    return make_conninfo(**{**params, **extra})


def test_first_version_and_files_without_references_queue_nothing(kb, store, docs):
    write(docs, V1)
    objects.ingest(kb, store, docs, NOTE, agent=PERSON)
    new_version(kb, store, docs, V2)
    assert kb.execute("SELECT count(*) FROM review_item").fetchone()[0] == 0


def test_ingest_during_write_waits_and_does_not_duplicate(kb, store, docs, monkeypatch):
    """Новая версия во время транзакции записи пакета: ingest ждёт разделяемую блокировку объектов (разд. 7.5,
    шаг 2) и после фиксации пакета видит его ревизию — но пункт уже поставил пакет, второго нет."""
    write(docs, V1)
    app = f"amem-ingest-{time.monotonic_ns()}"
    errors: list[BaseException] = []
    original = check._verdicts
    started: list[threading.Thread] = []

    def ingest_v2() -> None:
        try:
            with db.connect(_dsn(kb, application_name=app)) as other:
                new_version(other, store, docs, V2)
        except BaseException as e:                         # noqa: BLE001 — ошибку потока проверяет тест
            errors.append(e)

    def verdicts(conn, *args, **kw):
        if not started:                                    # ревизия уже записана, транзакция пакета открыта
            t = threading.Thread(target=ingest_v2)
            t.start()
            started.append(t)
            deadline = time.monotonic() + 30
            with db.connect(_dsn(kb)) as watch:            # своё соединение: в транзакции pg_stat_activity — снимок
                while watch.execute("SELECT count(*) FROM pg_stat_activity WHERE application_name = %s "
                                    "AND wait_event_type = 'Lock'", (app,)).fetchone()[0] < 1:
                    assert time.monotonic() < deadline, "ingest не встал в ожидание блокировки объектов"
                    time.sleep(0.02)
        return original(conn, *args, **kw)

    monkeypatch.setattr(check, "_verdicts", verdicts)
    result = send(kb, store, docs, note_atom())
    started[0].join(timeout=60)
    assert errors == []
    rec = result.records[0]
    # пакет записал ссылку на v1, когда v2 ещё не было: пункт — от новой версии, один
    items = changed(kb, rec["revision_id"])
    assert len(items) == 1 and items[0][2] is None
    assert [o["to"] for o in items[0][1]["objects"]] == [2]


def pending_with_source_changed(kb, store, docs):
    """Проверенный атом, ждущая правка на v1, новая версия v2: у правки пункты edit и source_changed."""
    write(docs, V1)
    first = send(kb, store, docs, note_atom()).records[0]
    records.set_status(kb, "atom", first["record_id"], "verified", agent=PERSON)
    result = send(kb, store, docs, note_atom(summary_plain={"ru": "Кронштейн держится на анкере."}),
                  first["record_id"])
    edit = result.records[0]
    new_version(kb, store, docs, V2)
    [sc] = [i for i in review.items(kb, reason="source_changed") if i["revision_id"] == edit["revision_id"]]
    [edit_item] = [q["id"] for q in result.queued if q["reason"] == "edit"]
    return first, edit, sc["id"], edit_item


def item_state(kb, item_id) -> str:
    return kb.execute("SELECT state FROM review_item WHERE id = %s", (item_id,)).fetchone()[0]


def test_confirmed_source_changed_on_pending_edit_is_only_a_verdict(kb, store, docs):
    """О правке решает её пункт edit: подтверждение по другой причине не меняет статус и не закрывает edit."""
    first, edit, sc, edit_item = pending_with_source_changed(kb, store, docs)
    out = review.resolve(kb, sc, "confirmed", agent=PERSON)
    assert out["status"] == "verified" and out["queued"] == []
    assert item_state(kb, sc) == "done" and item_state(kb, edit_item) == "queued"
    assert kb.execute("SELECT review_state FROM atom_revision WHERE id = %s",
                      (edit["revision_id"],)).fetchone()[0] == "pending"
    assert kb.execute("SELECT count(*) FROM status_log WHERE record_id = %s AND reason LIKE 'review:%%'",
                      (first["record_id"],)).fetchone()[0] == 0


def test_refuted_source_changed_on_pending_edit_declines_the_edit(kb, store, docs):
    """Опровержение отклоняет саму правку: статус записи прежний, текущая — прежняя, пункт edit устарел."""
    first, edit, sc, edit_item = pending_with_source_changed(kb, store, docs)
    out = review.resolve(kb, sc, "refuted", agent=PERSON)
    assert out["status"] == "verified"
    assert kb.execute("SELECT review_state FROM atom_revision WHERE id = %s",
                      (edit["revision_id"],)).fetchone()[0] == "declined"
    assert kb.execute("SELECT id FROM atom_current WHERE atom_id = %s",
                      (first["record_id"],)).fetchone()[0] == first["revision_id"]
    assert item_state(kb, sc) == "done" and item_state(kb, edit_item) == "obsolete"
    # пункт source_changed текущей ревизии — отдельный вопрос, он остаётся
    assert [st for st, *_ in changed(kb, first["revision_id"])] == ["queued"]
