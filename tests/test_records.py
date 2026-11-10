"""Запись и чтение схемы v1 на PostgreSQL 18 и 16: пакеты изменений, ревизии, проверка, «на момент», редакции, связи."""
import json
import threading
import time
import unicodedata
from datetime import date, datetime, timezone

import psycopg
import pytest

from amemo import canon, db, lookup, model_v1, records
from amemo.ids import uuid7
from amemo.records import Item, RecordError, commit, decide, reject, retire_link, set_status
from v1_support import same_database

AGENT = "model:claude"
HUMAN = "person:filipp"
OBJ_ID = uuid7()
OBJ = f"obj:{OBJ_ID}"           # объект источника — строки базы без копии файла: хранилище проверяет test_objects.py
DIGEST = "sha256:" + "ab" * 32


@pytest.fixture
def kb(pg):
    db.prepare(pg)
    pg.execute("INSERT INTO object (id, kind, original_name, created_at) "
               "VALUES (%s, 'file', 'СП 20.13330.2016.pdf', now())", (OBJ_ID,))
    pg.execute("INSERT INTO object_version (object_id, kind, n, digest, size, recorded_at) "
               "VALUES (%s, 'file', 1, %s, 0, now())", (OBJ_ID, DIGEST))
    return pg


def sp20(**extra) -> dict:
    return {"ref": "@sp20", "entity_class": "document", "key": "sp20_13330",
            "label": {"ru": "СП 20.13330 Нагрузки и воздействия"}, **extra}


def edition(ref="@sp20_2016", key="sp20_13330_2016", start="2017-06-04", end=None, of="@sp20") -> dict:
    return {"ref": ref, "entity_class": "edition", "key": key, "label": {"ru": f"СП 20.13330 ред. {key[-4:]}"},
            "edition_of": of, "valid_from": start, **({"valid_to": end} if end else {})}


def fact(**extra) -> dict:
    return {"ref": "@w0", "kind": "fact", "key": "sp20.t11_1",
            "label": {"ru": "Нормативное ветровое давление w0 по ветровым районам (СП 20, табл. 11.1)"},
            "summary_plain": {"ru": "Ветровое давление на высоте 10 м: от 0,17 кПа (Iа) до 0,85 кПа (VII)."},
            "codes": ["w0", "11.1"], "about": ["@sp20"],
            "sources": [{"object": OBJ, "object_version": 1, "digest": DIGEST, "quote": "Таблица 11.1",
                         "selectors": [{"type": "table", "value": "11.1"}], "edition": "@sp20_2016"}], **extra}


def by_key(norm_payload: dict) -> dict:
    """То же тело атома, но со ссылками по ключам — так его пришлют в следующей пачке."""
    return {**{k: v for k, v in norm_payload.items() if k != "ref"}, "about": ["ent:sp20_13330"],
            "sources": [{**norm_payload["sources"][0], "edition": "ent:sp20_13330_2016"}]}


def base(kb):
    return commit(kb, [Item("entity", sp20()), Item("entity", edition()), Item("atom", fact())],
                  agent=AGENT, reason="СП 20, табл. 11.1")


def atom_id(result) -> str:
    return result.refs["@w0"].split(":", 1)[1]


def test_commit_resolves_refs_and_returns_valid_records(kb):
    result = base(kb)
    assert set(result.refs) == {"@sp20", "@sp20_2016", "@w0"}
    record = lookup.get(kb, "atom", atom_id(result))
    model_v1.Atom.model_validate_json(json.dumps(record), strict=True)
    assert record["about"] == [result.refs["@sp20"]]
    assert record["sources"][0]["edition"] == result.refs["@sp20_2016"]
    assert record["revision"] == 1 and record["status"] == "draft" and record["agent"] == AGENT
    assert record["content_hash"].startswith("sha256-c1:") and "ref" not in record
    entity = lookup.get(kb, "entity", result.refs["@sp20"].split(":", 1)[1])
    model_v1.Entity.model_validate_json(json.dumps(entity), strict=True)
    assert lookup.by_key(kb, "entity", "sp20_13330") == result.refs["@sp20"]
    about = kb.execute("SELECT entity_id FROM atom_about").fetchall()
    assert [str(r[0]) for r in about] == [result.refs["@sp20"].split(":", 1)[1]]


@pytest.mark.parametrize("table", ["atom_revision", "entity_revision"])
def test_hash_recomputes_from_stored_payload(kb, table):
    base(kb)
    rows = kb.execute(f"SELECT payload, content_hash FROM {table}").fetchall()
    assert rows and all(canon.content_hash(payload) == content_hash for payload, content_hash in rows)


def test_same_body_gives_no_new_revision(kb):
    result = base(kb)
    again = commit(kb, [Item("atom", by_key(fact()), record_id=result.revisions[2].record_id)], agent=AGENT)
    assert not again.revisions[0].created
    assert again.revisions[0].revision_id == result.revisions[2].revision_id
    assert len(lookup.history(kb, "atom", atom_id(result))) == 1


def test_changed_body_gives_next_revision_and_keeps_old(kb):
    result = base(kb)
    first = kb.execute("SELECT payload FROM atom_revision").fetchone()[0]
    changed = by_key(fact(label={"ru": "w0 по ветровым районам (СП 20, табл. 11.1)"}))
    commit(kb, [Item("atom", changed, record_id=result.revisions[2].record_id)], agent=AGENT)
    history = lookup.history(kb, "atom", atom_id(result))
    assert [h["n"] for h in history] == [1, 2]
    assert lookup.get(kb, "atom", atom_id(result))["label"]["ru"].startswith("w0 по")
    assert kb.execute("SELECT payload FROM atom_revision WHERE n = 1").fetchone()[0] == first


@pytest.mark.parametrize("sql", [
    "UPDATE atom_revision SET payload = '{}'",
    "DELETE FROM atom_revision",
    "UPDATE atom_revision SET review_state = 'accepted'",          # решение — только для pending, с автором
    "UPDATE changeset SET reason = 'задним числом'",
    "DELETE FROM status_log",
    "DELETE FROM atom_about",
], ids=["правка ревизии", "удаление ревизии", "решение без pending", "правка пакета", "удаление журнала",
        "удаление about"])
def test_history_cannot_be_rewritten(kb, sql):
    base(kb)
    with pytest.raises(psycopg.errors.RaiseException, match="amemo:"):
        with kb.transaction():
            kb.execute(sql)


def test_pending_revision_waits_for_decision(kb):
    result = base(kb)
    record_id = result.revisions[2].record_id
    pending = commit(kb, [Item("atom", by_key(fact(key="sp20.t11_1_v2")), record_id=record_id,
                               review_state="pending")], agent=AGENT)
    current = lookup.get(kb, "atom", record_id)
    assert current["revision"] == 1 and current["key"] == "sp20.t11_1"       # правка ещё не подменила атом
    decide(kb, "atom", pending.revisions[0].revision_id, accept=True, agent=HUMAN)
    current = lookup.get(kb, "atom", record_id)
    assert current["revision"] == 2 and current["review_state"] == "accepted"
    assert lookup.by_key(kb, "atom", "sp20.t11_1_v2") == f"atm:{record_id}"   # проекция ключа обновилась


def test_declined_revision_never_becomes_current(kb):
    result = base(kb)
    record_id = result.revisions[2].record_id
    pending = commit(kb, [Item("atom", by_key(fact(codes=["w0"])), record_id=record_id, review_state="pending")],
                     agent=AGENT)
    decide(kb, "atom", pending.revisions[0].revision_id, accept=False, agent=HUMAN)
    assert lookup.get(kb, "atom", record_id)["revision"] == 1
    with pytest.raises(RecordError, match="решение по ней уже принято"):
        decide(kb, "atom", pending.revisions[0].revision_id, accept=True, agent=HUMAN)


def test_new_atom_on_review_is_current(kb):
    result = commit(kb, [Item("entity", sp20()), Item("entity", edition()),
                         Item("atom", fact(), status="needs_review", review_state="pending")], agent=AGENT)
    record = lookup.get(kb, "atom", atom_id(result))
    assert record["review_state"] == "pending" and record["status"] == "needs_review"


def test_as_of_shows_what_was_known_then(kb):
    before = datetime.now(timezone.utc)
    result = base(kb)
    record_id = result.revisions[2].record_id
    t1 = datetime.now(timezone.utc)
    pending = commit(kb, [Item("atom", by_key(fact(codes=["w0"])), record_id=record_id, review_state="pending")],
                     agent=AGENT)
    t2 = datetime.now(timezone.utc)
    decide(kb, "atom", pending.revisions[0].revision_id, accept=True, agent=HUMAN)
    set_status(kb, "atom", record_id, "verified", agent=HUMAN)
    assert lookup.get(kb, "atom", record_id, at=before) is None                  # тогда атома ещё не было
    then = lookup.get(kb, "atom", record_id, at=t1)
    assert then["revision"] == 1 and then["status"] == "draft"
    then = lookup.get(kb, "atom", record_id, at=t2)
    assert then["revision"] == 1                                                  # правка ждала решения
    now = lookup.get(kb, "atom", record_id)
    assert now["revision"] == 2 and now["status"] == "verified"


def test_editions_in_force_on_date(kb):
    base(kb)
    commit(kb, [Item("entity", edition("@sp20_2011", "sp20_13330_2011", "2011-05-20", "2017-06-03",
                                       of="ent:sp20_13330"))], agent=AGENT)
    keys = {r[0]: r[1] for r in kb.execute("SELECT id, key FROM entity")}
    sp20_id = lookup.by_key(kb, "entity", "sp20_13330").split(":", 1)[1]
    assert [keys[i] for i in lookup.editions_in_force(kb, sp20_id, date(2015, 1, 1))] == ["sp20_13330_2011"]
    assert [keys[i] for i in lookup.editions_in_force(kb, sp20_id, date(2026, 10, 19))] == ["sp20_13330_2016"]
    assert lookup.editions_in_force(kb, sp20_id, date(2010, 1, 1)) == []


def test_overlapping_edition_rejected_whole_bundle(kb):
    base(kb)
    count = kb.execute("SELECT count(*) FROM changeset").fetchone()[0]
    with pytest.raises(RecordError, match="пересекается"):
        commit(kb, [Item("entity", edition("@sp20_x", "sp20_13330_x", "2017-01-01", of="ent:sp20_13330"))],
               agent=AGENT)
    assert kb.execute("SELECT count(*) FROM changeset").fetchone()[0] == count      # пачка не записана


@pytest.mark.parametrize("items, message", [
    (lambda: [Item("entity", sp20()), Item("entity", sp20(ref="@other"))], "ключ 'sp20_13330' уже занят"),
    (lambda: [Item("atom", fact(about=["ent:no_such_key"], sources=[]))], "нет записи с ключом no_such_key"),
    (lambda: [Item("atom", fact(about=["@nobody"], sources=[]))], "@nobody: в пачке нет записи"),
    (lambda: [Item("entity", sp20()), Item("entity", sp20(key="other"))], "@sp20: два раза в одной пачке"),
    (lambda: [Item("atom", {**fact(ref="@a", sources=[]), "about": ["@b"]}),
              Item("atom", fact(ref="@b", key="b", sources=[], about=[]))], "нужна ent:"),
    (lambda: [], "пустая пачка"),
], ids=["ключ занят", "нет ключа", "нет @имени", "@имя дважды", "about на атом из пачки", "пустая пачка"])
def test_bad_bundles_rejected(kb, items, message):
    with pytest.raises(RecordError, match=message):
        commit(kb, items(), agent=AGENT)
    assert kb.execute("SELECT count(*) FROM changeset").fetchone()[0] == 0


def test_links_written_once_checked_and_retired(kb):
    result = base(kb)
    w0, sp20_ref = result.refs["@w0"], result.refs["@sp20"]
    link = {"rel": "depends_on", "src": w0, "dst": "ent:sp20_13330", "note": {"ru": "табл. 11.1"}}
    first = commit(kb, [], [link], agent=AGENT).links[0]
    assert commit(kb, [], [link], agent=AGENT).links[0] == first                  # та же связь — не дубль
    other = commit(kb, [Item("atom", fact(ref="@w0b", key="w0b", sources=[], about=["ent:sp20_13330"]))],
                   agent=AGENT).refs["@w0b"]
    a = commit(kb, [], [{"rel": "contradicts", "src": w0, "dst": other}], agent=AGENT).links[0]
    assert commit(kb, [], [{"rel": "contradicts", "src": other, "dst": w0}], agent=AGENT).links[0] == a   # симметрична
    with pytest.raises(RecordError, match="refines: atom → entity не допускается"):
        commit(kb, [], [{"rel": "refines", "src": w0, "dst": sp20_ref}], agent=AGENT)
    before = datetime.now(timezone.utc)
    retire_link(kb, first, agent=HUMAN, reason="дубль связи about")
    assert [l["rel"] for l in lookup.links(kb, w0.split(":", 1)[1])] == ["contradicts"]
    assert {l["rel"] for l in lookup.links(kb, w0.split(":", 1)[1], at=before)} == {"depends_on", "contradicts"}
    with pytest.raises(RecordError, match="уже выведена"):
        retire_link(kb, first, agent=HUMAN, reason="повторно")


def test_rejected_changeset_kept_without_records(kb):
    db.load_vocab(kb)
    cs = reject(kb, agent=AGENT, check_report={"level": 2, "errors": ["цитата не найдена"]}, reason="СП 20")
    state, report = kb.execute("SELECT state, check_report FROM changeset WHERE id = %s", (cs,)).fetchone()
    assert state == "rejected" and report["level"] == 2
    assert kb.execute("SELECT count(*) FROM atom").fetchone()[0] == 0


def test_status_changes_are_logged(kb):
    result = base(kb)
    record_id = result.revisions[2].record_id
    set_status(kb, "atom", record_id, "verified", agent=HUMAN, reason="сверено с СП 20, стр. 27")
    log = kb.execute("SELECT status, agent, reason FROM status_log WHERE record_id = %s ORDER BY changed_at",
                     (record_id,)).fetchall()
    assert log == [("draft", AGENT, None), ("verified", HUMAN, "сверено с СП 20, стр. 27")]
    with pytest.raises(RecordError, match="такой записи нет"):
        set_status(kb, "atom", uuid7(), "verified", agent=HUMAN)


def test_jsonb_round_trip_keeps_hash_and_body(kb):
    """Тело с большими числами и текстом в NFD после jsonb даёт тот же хэш и ту же каноническую форму."""
    nfd = unicodedata.normalize("NFD", "Ёлочный узел й")
    table = {"columns": [{"code": "c", "label": {"ru": nfd}}], "rows": [[nfd, 1e23]]}
    payload = fact(label={"ru": nfd}, content={"values": [{"property": "mass", "amount": 1e16, "unit": "kg"}],
                                               "table": table})
    commit(kb, [Item("entity", sp20()), Item("entity", edition()), Item("atom", payload)], agent=AGENT)
    stored, content_hash = kb.execute("SELECT payload, content_hash FROM atom_revision").fetchone()
    assert canon.content_hash(stored) == content_hash
    # повторная канонизация сохранённого тела ничего не меняет: большие числа jsonb возвращает целыми,
    # канонизация снова делает их числами с плавающей точкой — хэш тот же
    assert canon.content_hash(canon.canonical(stored, "atom")) == content_hash
    assert stored["label"]["ru"] == unicodedata.normalize("NFC", nfd)


def _in_parallel(*jobs):
    """Запустить функции одновременно, каждую со своим соединением; вернуть результаты и ошибки."""
    barrier, results, errors = threading.Barrier(len(jobs)), [None] * len(jobs), []

    def run(i, job):
        try:
            barrier.wait()
            results[i] = job()
        except Exception as e:                                  # noqa: BLE001 — ошибку потока проверяет тест
            errors.append(e)

    threads = [threading.Thread(target=run, args=(i, job)) for i, job in enumerate(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, errors


def test_concurrent_revisions_of_one_record_go_in_turn(kb):
    result = base(kb)
    record_id = result.revisions[2].record_id

    def write(codes):
        def job():
            with same_database(kb, autocommit=True) as conn:
                return commit(conn, [Item("atom", by_key(fact(codes=codes)), record_id=record_id)], agent=AGENT)
        return job

    _, errors = _in_parallel(write(["w0", "a"]), write(["w0", "b"]))
    assert errors == []
    assert [h["n"] for h in lookup.history(kb, "atom", record_id)] == [1, 2, 3]


def test_concurrent_same_symmetric_link_written_once(kb):
    result = base(kb)
    w0 = result.refs["@w0"]
    other = commit(kb, [Item("atom", fact(ref="@w0b", key="w0b", sources=[], about=["ent:sp20_13330"]))],
                   agent=AGENT).refs["@w0b"]

    def link(src, dst):
        def job():
            with same_database(kb, autocommit=True) as conn:
                return commit(conn, [], [{"rel": "contradicts", "src": src, "dst": dst}], agent=AGENT).links[0]
        return job

    ids, errors = _in_parallel(link(w0, other), link(other, w0))
    assert errors == [] and ids[0] == ids[1]
    assert kb.execute("SELECT count(*) FROM link WHERE retired_at IS NULL").fetchone()[0] == 1


def test_link_to_itself_rejected(kb):
    w0 = base(kb).refs["@w0"]
    with pytest.raises(RecordError, match="не может ссылаться на себя"):
        commit(kb, [], [{"rel": "same_as", "src": w0, "dst": w0}], agent=AGENT)


def test_write_functions_need_autocommit(kb):
    with same_database(kb) as plain:                            # psycopg по умолчанию — без autocommit
        with pytest.raises(RecordError, match="autocommit"):
            commit(plain, [Item("entity", sp20())], agent=AGENT)


def test_refs_work_in_any_order(kb):
    """@имя ссылается и на запись, которая в пачке дальше: атом раньше норматива, редакция раньше документа."""
    first = fact(derived_from=["@w0b"])
    second = fact(ref="@w0b", key="w0b", sources=[])
    result = commit(kb, [Item("atom", first), Item("atom", second), Item("entity", edition()), Item("entity", sp20())],
                    agent=AGENT)
    record = lookup.get(kb, "atom", atom_id(result))
    assert record["about"] == [result.refs["@sp20"]] and record["derived_from"] == [result.refs["@w0b"]]


def test_declined_new_record_frees_key_and_edition(kb):
    """Отклонённая новая запись ничего за собой не оставляет: ни ключа, ни срока редакции."""
    base(kb)
    sp20_id = lookup.by_key(kb, "entity", "sp20_13330").split(":", 1)[1]
    old = edition("@x", "sp20_13330_2010", "2010-01-01", "2010-12-31", of="ent:sp20_13330")
    pending = commit(kb, [Item("entity", old, review_state="pending")], agent=AGENT)
    assert len(lookup.editions_in_force(kb, sp20_id, date(2010, 6, 1))) == 1          # до решения — видна
    decide(kb, "entity", pending.revisions[0].revision_id, accept=False, agent=HUMAN)
    assert lookup.get(kb, "entity", pending.revisions[0].record_id) is None
    assert lookup.by_key(kb, "entity", "sp20_13330_2010") is None
    assert lookup.editions_in_force(kb, sp20_id, date(2010, 6, 1)) == []
    commit(kb, [Item("entity", {**old, "ref": "@y"})], agent=AGENT)                  # ключ и срок снова свободны


def test_as_of_decisions_taken_after_moment_are_pending(kb):
    result = commit(kb, [Item("entity", sp20()), Item("entity", edition()),
                         Item("atom", fact(), status="needs_review", review_state="pending")], agent=AGENT)
    record_id = result.revisions[2].record_id
    before_decision = datetime.now(timezone.utc)
    decide(kb, "atom", result.revisions[2].revision_id, accept=True, agent=HUMAN)
    assert lookup.get(kb, "atom", record_id, at=before_decision)["review_state"] == "pending"
    assert lookup.get(kb, "atom", record_id)["review_state"] == "accepted"
    edit = commit(kb, [Item("atom", by_key(fact(codes=["w0"])), record_id=record_id, review_state="pending")],
                  agent=AGENT)
    decide(kb, "atom", edit.revisions[0].revision_id, accept=False, agent=HUMAN)
    assert lookup.get(kb, "atom", record_id, at=datetime.now(timezone.utc))["revision"] == 1   # отклонённая не видна


def test_edition_period_follows_accepted_revision(kb):
    base(kb)
    sp20_id = lookup.by_key(kb, "entity", "sp20_13330").split(":", 1)[1]
    edition_id = lookup.by_key(kb, "entity", "sp20_13330_2016").split(":", 1)[1]
    pending = commit(kb, [Item("entity", {**edition(start="2017-07-01"), "edition_of": "ent:sp20_13330"},
                               record_id=edition_id, review_state="pending")], agent=AGENT)
    assert len(lookup.editions_in_force(kb, sp20_id, date(2017, 6, 10))) == 1        # до решения — прежний срок
    decide(kb, "entity", pending.revisions[0].revision_id, accept=True, agent=HUMAN)
    assert lookup.editions_in_force(kb, sp20_id, date(2017, 6, 10)) == []


def test_unknown_record_id_rejected(kb):
    base(kb)
    with pytest.raises(RecordError, match="такой записи нет"):
        commit(kb, [Item("atom", by_key(fact()), record_id=uuid7())], agent=AGENT)


def test_concurrent_identical_bodies_give_one_revision(kb):
    result = base(kb)
    record_id = result.revisions[2].record_id
    body = by_key(fact(codes=["w0", "одинаково"]))

    def write():
        with same_database(kb, autocommit=True) as conn:
            return commit(conn, [Item("atom", body, record_id=record_id)], agent=AGENT).revisions[0].created

    created, errors = _in_parallel(write, write)
    assert errors == [] and sorted(created) == [False, True]
    assert [h["n"] for h in lookup.history(kb, "atom", record_id)] == [1, 2]


def test_bundles_in_opposite_order_do_not_deadlock(kb):
    result = base(kb)
    a = result.revisions[2].record_id
    b = commit(kb, [Item("atom", fact(ref="@b", key="b", sources=[], about=["ent:sp20_13330"]))],
               agent=AGENT).revisions[0].record_id
    body_a, body_b = by_key(fact(codes=["a2"])), fact(key="b", sources=[], about=["ent:sp20_13330"], codes=["b2"])
    body_b.pop("ref")

    def write(order):
        def job():
            with same_database(kb, autocommit=True) as conn:
                items = {"a": Item("atom", body_a, record_id=a), "b": Item("atom", body_b, record_id=b)}
                return commit(conn, [items[k] for k in order], agent=AGENT)
        return job

    _, errors = _in_parallel(write("ab"), write("ba"))
    assert errors == []


def test_naive_moment_rejected(kb):
    record_id = base(kb).revisions[2].record_id
    with pytest.raises(RecordError, match="часовым поясом"):
        lookup.get(kb, "atom", record_id, at=datetime.now())


@pytest.mark.parametrize("call", [
    lambda kb: lookup.get(kb, "atom WHERE false --", uuid7()),
    lambda kb: lookup.by_key(kb, "entity; DROP TABLE atom", "x"),
    lambda kb: set_status(kb, "link", uuid7(), "verified", agent=HUMAN),
    lambda kb: commit(kb, [Item("object", {"kind": "fact"})], agent=AGENT),
], ids=["get", "by_key", "set_status", "commit"])
def test_unknown_target_rejected(kb, call):
    with pytest.raises(RecordError, match="неизвестный вид записи"):
        call(kb)


def test_item_status_applies_to_existing_record_in_same_commit(kb):
    result = base(kb)
    record_id = result.revisions[2].record_id
    set_status(kb, "atom", record_id, "verified", agent=HUMAN)
    commit(kb, [Item("atom", by_key(fact(codes=["w0"])), record_id=record_id)], agent=AGENT)
    assert lookup.get(kb, "atom", record_id)["status"] == "verified"                  # статус не задан — прежний
    commit(kb, [Item("atom", by_key(fact(codes=["w0", "x"])), record_id=record_id, status="needs_review")],
           agent=AGENT, reason="вышла новая редакция")
    assert lookup.get(kb, "atom", record_id)["status"] == "needs_review"
    log = kb.execute("SELECT status, reason FROM status_log WHERE record_id = %s ORDER BY changed_at, id",
                     (record_id,)).fetchall()
    assert log == [("draft", None), ("verified", None), ("needs_review", "вышла новая редакция")]   # причина — пакета


def test_duplicate_about_refs_written_once(kb):
    sp20_ref = commit(kb, [Item("entity", sp20()), Item("entity", edition())], agent=AGENT).refs["@sp20"]
    result = commit(kb, [Item("atom", {**by_key(fact()), "ref": "@w0", "about": ["ent:sp20_13330", sp20_ref]})],
                    agent=AGENT)
    assert kb.execute("SELECT count(*) FROM atom_about").fetchone()[0] == 1
    assert lookup.get(kb, "atom", atom_id(result))["about"] == [sp20_ref] * 2              # тело — как прислано


def test_resubmitted_pending_body_gives_no_new_revision(kb):
    record_id = base(kb).revisions[2].record_id
    body = by_key(fact(codes=["w0", "на проверке"]))
    first = commit(kb, [Item("atom", body, record_id=record_id, review_state="pending")], agent=AGENT)
    again = commit(kb, [Item("atom", body, record_id=record_id, review_state="pending")], agent=AGENT)
    assert first.revisions[0].created and not again.revisions[0].created
    assert again.revisions[0].revision_id == first.revisions[0].revision_id


@pytest.mark.parametrize("bundle, message", [
    (lambda: ([Item("atom", fact(about=["ent:nope"], sources=[]))], []), r"@w0: about\[0\]: ent:nope"),
    (lambda: ([Item("entity", edition(start="2020-01-01", end="2019-01-01", of="ent:sp20_13330"))], []),
     "valid_from 2020-01-01 позже valid_to 2019-01-01"),
    (lambda: ([Item("entity", {"entity_class": "document", "key": "sp22", "label": {"ru": "СП 22"}}),
               Item("atom", {k: v for k, v in fact(key="z", about=["ent:nope"], sources=[]).items() if k != "ref"})],
              []), r"items\[1\]: about\[0\]: ent:nope"),
    (lambda: ([], [{"rel": "supersedes", "src": "ent:sp20_13330_2016", "dst": "ent:sp20_13330"},
                   {"rel": "attached_by", "src": "ent:sp20_13330", "dst": "ent:sp20_13330_2016"}]),
     r"links\[1\]: неизвестный вид связи 'attached_by'"),
    (lambda: ([], [{"rel": "about", "src": "ent:sp20_13330", "dst": "ent:sp20_13330_2016"}]),
     r"links\[0\]: связь about задаётся полем about"),
], ids=["путь ссылки", "срок задом наперёд", "запись без ref", "неизвестная связь", "about связью"])
def test_errors_name_the_place(kb, bundle, message):
    base(kb)
    items, links = bundle()
    with pytest.raises(RecordError, match=message):
        commit(kb, items, links, agent=AGENT)


def test_unknown_activity_rejected(kb):
    db.load_vocab(kb)
    with pytest.raises(RecordError, match="задачи"):
        commit(kb, [Item("entity", sp20())], agent=AGENT, activity=uuid7())


def test_links_report_provenance(kb):
    result = base(kb)
    w0 = result.refs["@w0"]
    cs = commit(kb, [], [{"rel": "depends_on", "src": w0, "dst": "ent:sp20_13330",
                          "qualifiers": [{"property": "applies_to_range", "value_text": "Iа…VII"}]}],
                agent=AGENT).changeset_id
    [link] = lookup.links(kb, w0.split(":", 1)[1])
    assert link["changeset"] == str(cs) and link["agent"] == AGENT and link["qualifiers"][0]["value_text"] == "Iа…VII"
    assert isinstance(link["id"], str) and datetime.fromisoformat(link["created_at"]).tzinfo is not None


@pytest.mark.parametrize("entity_first", [True, False], ids=["сущность раньше", "сущность позже"])
def test_keys_resolve_against_state_before_bundle(kb, entity_first):
    """Ключ ищется по базе до пачки, в любом порядке пачки: на запись этой же пачки ссылаются @именем."""
    base(kb)
    items = [Item("entity", {"entity_class": "document", "key": "sp22", "label": {"ru": "СП 22"}}),
             Item("atom", fact(ref="@x", key="x", sources=[], about=["ent:sp22"]))]
    with pytest.raises(RecordError, match="нет записи с ключом sp22"):
        commit(kb, items if entity_first else items[::-1], agent=AGENT)


def test_renamed_key_still_resolves_in_same_bundle(kb):
    result = base(kb)
    sp20_id = result.revisions[0].record_id
    renamed = {**{k: v for k, v in sp20().items() if k != "ref"}, "key": "sp20_13330_new"}
    done = commit(kb, [Item("entity", renamed, record_id=sp20_id),
                       Item("atom", fact(ref="@x", key="x", sources=[], about=["ent:sp20_13330"]))], agent=AGENT)
    assert lookup.get(kb, "atom", done.refs["@x"].split(":", 1)[1])["about"] == [result.refs["@sp20"]]
    assert lookup.by_key(kb, "entity", "sp20_13330_new") == result.refs["@sp20"]


def test_old_pending_body_does_not_swallow_new_write(kb):
    """Ревизия, ждущая проверки, старше текущей — не повод пропустить запись её тела: оно становится текущим."""
    record_id = base(kb).revisions[2].record_id
    b, c = by_key(fact(codes=["B"])), by_key(fact(codes=["C"]))
    commit(kb, [Item("atom", b, record_id=record_id, review_state="pending")], agent=AGENT)        # n=2 ждёт
    commit(kb, [Item("atom", c, record_id=record_id)], agent=AGENT)                                 # n=3 текущая
    again = commit(kb, [Item("atom", b, record_id=record_id)], agent=AGENT)
    assert again.revisions[0].created and again.revisions[0].n == 4
    assert lookup.get(kb, "atom", record_id)["codes"] == ["B"]


@pytest.mark.parametrize("existing", [True, False], ids=["правка записи", "новая запись"])
def test_body_accepted_without_review_replaces_pending_one(kb, existing):
    """То же тело, но уже без проверки (none), — новая ревизия, и она текущая: ждущая не поглощает принятую."""
    if existing:
        record_id = base(kb).revisions[2].record_id
        body = by_key(fact(codes=["B"]))
    else:
        commit(kb, [Item("entity", sp20()), Item("entity", edition())], agent=AGENT)
        body = by_key(fact())
        record_id = commit(kb, [Item("atom", body, review_state="pending")], agent=AGENT).revisions[0].record_id
    pending = commit(kb, [Item("atom", body, record_id=record_id, review_state="pending")], agent=AGENT)
    accepted = commit(kb, [Item("atom", body, record_id=record_id)], agent=AGENT)
    assert accepted.revisions[0].created and accepted.revisions[0].n == pending.revisions[0].n + 1
    record = lookup.get(kb, "atom", record_id)
    assert record["revision"] == accepted.revisions[0].n and record["review_state"] == "none"


@pytest.mark.parametrize("call", [
    lambda kb: commit(kb, [Item("atom", by_key(fact()), record_id="w0")], agent=AGENT),
    lambda kb: set_status(kb, "atom", "w0", "verified", agent=HUMAN),
    lambda kb: decide(kb, "atom", "w0", accept=True, agent=HUMAN),
    lambda kb: retire_link(kb, "w0", agent=HUMAN, reason="проверка"),
], ids=["commit", "set_status", "decide", "retire_link"])
def test_non_uuid_ids_rejected(kb, call):
    base(kb)
    with pytest.raises(RecordError, match="'w0': это не UUID"):
        call(kb)


def test_record_ids_as_text_or_uuid_in_one_bundle(kb):
    result = base(kb)
    sp20_id, w0_id = result.revisions[0].record_id, result.revisions[2].record_id
    relabelled = {**{k: v for k, v in sp20().items() if k != "ref"}, "label": {"ru": "СП 20.13330 «Нагрузки»"}}
    done = commit(kb, [Item("atom", by_key(fact(codes=["s"])), record_id=str(w0_id)),
                       Item("entity", relabelled, record_id=sp20_id)], agent=AGENT)
    assert [r.created for r in done.revisions] == [True, True]
    assert [r.record_id for r in done.revisions] == [w0_id, sp20_id]


def test_link_to_record_held_by_writer_does_not_wait(kb):
    """Запись держит другой писатель (блокировка, как в commit), — связь на неё не ждёт: FOR NO KEY UPDATE не мешает
    проверке внешнего ключа. С FOR UPDATE два пакета, правящие A со связью на B и B со связью на A, встали бы в тупик."""
    w0 = base(kb).refs["@w0"]
    with same_database(kb, autocommit=True) as writer, writer.transaction():
        records._lock(writer, "atom", w0.split(":", 1)[1])
        kb.execute("SET lock_timeout = '2s'")
        try:
            commit(kb, [], [{"rel": "depends_on", "src": w0, "dst": "ent:sp20_13330"}], agent=AGENT)
        finally:
            kb.execute("RESET lock_timeout")


def test_clock_going_back_keeps_order(kb, monkeypatch):
    """Часы ушли назад: пакет, статус и решение — не раньше последнего изменения записи, порядок истории цел."""
    record_id = base(kb).revisions[2].record_id
    monkeypatch.setattr(records, "_now", lambda: datetime(2000, 1, 1, tzinfo=timezone.utc))
    edit = commit(kb, [Item("atom", by_key(fact(codes=["назад"])), record_id=record_id, review_state="pending")],
                  agent=AGENT)
    set_status(kb, "atom", record_id, "verified", agent=HUMAN)
    decide(kb, "atom", edit.revisions[0].revision_id, accept=True, agent=HUMAN)
    (first, _), (second, reviewed) = kb.execute(
        "SELECT recorded_at, reviewed_at FROM atom_revision WHERE atom_id = %s ORDER BY n", (record_id,)).fetchall()
    assert first <= second <= reviewed
    changed = [r[0] for r in kb.execute("SELECT changed_at FROM status_log WHERE record_id = %s ORDER BY id",
                                        (record_id,))]
    assert changed == sorted(changed) and changed[-1] >= second
    assert lookup.get(kb, "atom", record_id)["revision"] == 2


def _wait_until_blocked(conn, timeout=10.0):
    """Ждать, пока другое соединение не встанет в ожидание блокировки."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if conn.execute("SELECT count(*) FROM pg_stat_activity WHERE pid <> pg_backend_pid() "
                        "AND datname = current_database() AND wait_event_type = 'Lock'").fetchone()[0]:
            return
        time.sleep(0.02)
    raise AssertionError("соседнее соединение так и не встало в ожидание")


def test_new_agent_bundle_and_decision_do_not_deadlock(kb, monkeypatch):
    """Новый автор: решение уже завело автора и ещё не взяло запись; пакет того же автора по той же записи ждёт
    автора, ещё не держа запись, — тупика нет. Возьми пакет запись раньше автора, он встал бы в тупик с решением."""
    record_id = base(kb).revisions[2].record_id
    pending = commit(kb, [Item("atom", by_key(fact(codes=["p"])), record_id=record_id, review_state="pending")],
                     agent=AGENT)
    newbie = "person:newbie"
    paused, go = threading.Event(), threading.Event()
    ensure = records._ensure_agent

    def ensure_then_pause(conn, agent):
        ensure(conn, agent)
        if threading.current_thread().name == "decide":
            paused.set()
            go.wait(10)

    monkeypatch.setattr(records, "_ensure_agent", ensure_then_pause)
    errors = []

    def thread(name, job):
        def run():
            try:
                with same_database(kb, autocommit=True) as conn:
                    job(conn)
            except Exception as e:          # noqa: BLE001 — ошибку проверяет тест
                errors.append((name, e))
        return threading.Thread(target=run, name=name)

    deciding = thread("decide", lambda c: decide(c, "atom", pending.revisions[0].revision_id, accept=True,
                                                 agent=newbie))
    writing = thread("commit", lambda c: commit(c, [Item("atom", by_key(fact(codes=["w"])), record_id=record_id)],
                                                agent=newbie))
    deciding.start()
    assert paused.wait(10)
    writing.start()
    _wait_until_blocked(kb)
    go.set()
    deciding.join(20)
    writing.join(20)
    assert errors == []


def test_every_ref_field_resolved_through_commit(kb):
    """Поля-ссылки тела разрешаются при записи все — и scope.project, и term символа формулы."""
    result = base(kb)
    project = {"ref": "@kampus", "entity_class": "project", "key": "kampus", "label": {"ru": "Кампус"}}
    calc = fact(ref="@calc", key="calc", sources=[], about=["ent:sp20_13330"], scope={"project": "@kampus"},
                content={"formula": {"latex": "w = w_0 k", "symbols": [{"symbol": "w_0", "term": "atm:sp20.t11_1"}]}})
    done = commit(kb, [Item("atom", calc), Item("entity", project)], agent=AGENT)
    record = lookup.get(kb, "atom", done.refs["@calc"].split(":", 1)[1])
    assert record["scope"]["project"] == done.refs["@kampus"]
    assert record["content"]["formula"]["symbols"][0]["term"] == result.refs["@w0"]
    # новое поле-ссылка в схеме — сюда же, в тело calc
    assert set(canon.REF_FIELDS["atom"]) == {"about[]", "derived_from[]", "scope.project", "sources[].object",
                                             "sources[].edition", "content.formula.symbols[].term"}


@pytest.mark.parametrize("existing", [True, False], ids=["правка записи", "новая запись"])
def test_atom_derived_from_itself_rejected(kb, existing):
    result = base(kb)
    if existing:
        w0 = result.refs["@w0"]
        item = Item("atom", by_key(fact(derived_from=[w0])), record_id=w0.split(":", 1)[1])
    else:
        item = Item("atom", fact(ref="@self", key="self", sources=[], about=["ent:sp20_13330"],
                                 derived_from=["@self"]))
    with pytest.raises(RecordError, match="выведен из самого себя"):
        commit(kb, [item], agent=AGENT)


def test_bundles_with_same_links_in_opposite_order_do_not_deadlock(kb, monkeypatch):
    """Связи пишутся в одном порядке для всех пакетов: два пакета с теми же связями в разном порядке не встают
    в тупик на уникальном индексе — второй ждёт первого и получает уже записанные связи."""
    w0 = base(kb).refs["@w0"]
    one = {"rel": "depends_on", "src": w0, "dst": "ent:sp20_13330"}
    two = {"rel": "depends_on", "src": w0, "dst": "ent:sp20_13330_2016"}
    paused, go = threading.Event(), threading.Event()
    write_link = records._write_link

    def write_then_pause(*args):
        link_id = write_link(*args)
        if threading.current_thread().name == "x" and not paused.is_set():
            paused.set()
            go.wait(10)
        return link_id

    monkeypatch.setattr(records, "_write_link", write_then_pause)
    results, errors = {}, []

    def thread(name, links):
        def run():
            try:
                with same_database(kb, autocommit=True) as conn:
                    results[name] = commit(conn, [], links, agent=AGENT).links
            except Exception as e:          # noqa: BLE001 — ошибку проверяет тест
                errors.append((name, e))
        return threading.Thread(target=run, name=name)

    x, y = thread("x", [one, two]), thread("y", [two, one])
    x.start()
    assert paused.wait(10)
    y.start()
    _wait_until_blocked(kb)
    go.set()
    x.join(20)
    y.join(20)
    assert errors == []
    assert results["x"] == results["y"][::-1]            # те же связи; id — в порядке своей пачки


def test_source_rows_follow_revision_body(kb):
    """Источники ревизии раскладываются в source по порядку тела; та же ревизия второй раз строк не добавляет."""
    result = base(kb)
    record_id = result.revisions[2].record_id
    [revision] = lookup.history(kb, "atom", record_id)
    [source] = lookup.revision_sources(kb, "atom", revision["id"])
    assert (source["object"], source["object_version"], source["position"]) == (OBJ, 1, 0)
    assert source["selectors"] == [{"type": "table", "value": "11.1"}] and source["quote"] == "Таблица 11.1"
    assert source["edition"] == result.refs["@sp20_2016"] and "verdict" not in source
    commit(kb, [Item("atom", by_key(fact()), record_id=record_id)], agent=AGENT)
    assert kb.execute("SELECT count(*) FROM source").fetchone()[0] == 1


def test_entity_revision_has_sources_too(kb):
    """Файл, которым представлена редакция, — источник ревизии сущности."""
    scan = {"object": OBJ, "object_version": 1, "digest": DIGEST, "role": "primary"}
    result = commit(kb, [Item("entity", sp20()), Item("entity", {**edition(), "sources": [scan]})], agent=AGENT)
    [revision] = lookup.history(kb, "entity", result.revisions[1].record_id)
    assert [(s["object"], s["role"]) for s in lookup.revision_sources(kb, "entity", revision["id"])] == \
        [(OBJ, "primary")]


def _without_file(kb, kind: str, value: str) -> str:
    """Страница сайта или переписка строками базы, без копии: одна версия без digest."""
    object_id = uuid7()
    column = "url, retrieved_at" if kind == "web" else "original_name"
    values = "%s, current_date" if kind == "web" else "%s"
    kb.execute(f"INSERT INTO object (id, kind, {column}, created_at) VALUES (%s, %s, {values}, now())",
               (object_id, kind, value))
    kb.execute("INSERT INTO object_version (object_id, kind, n, recorded_at) VALUES (%s, %s, 1, now())",
               (object_id, kind))
    return f"obj:{object_id}"


def test_sources_without_file_and_order_of_rows(kb):
    """Источники-сайт и переписка — без digest; строки source идут в порядке тела: sources[i] ↔ position i."""
    site = _without_file(kb, "web", "https://example.org/norms")
    letter = _without_file(kb, "message", "Письмо от 12.03.2024")
    body = fact(sources=[{"object": site, "object_version": 1}, {"object": letter, "object_version": 1},
                         {"object": OBJ, "object_version": 1, "digest": DIGEST}])
    result = commit(kb, [Item("entity", sp20()), Item("entity", edition()), Item("atom", body)], agent=AGENT)
    [revision] = lookup.history(kb, "atom", result.revisions[2].record_id)
    rows = lookup.revision_sources(kb, "atom", revision["id"])
    assert [(s["position"], s["object"]) for s in rows] == [(0, site), (1, letter), (2, OBJ)]
    with pytest.raises(RecordError, match="без файла — digest не нужен"):
        commit(kb, [Item("atom", fact(ref="@x", key="x", about=["ent:sp20_13330"],
                                      sources=[{"object": site, "object_version": 1, "digest": DIGEST}]))],
               agent=AGENT)


@pytest.mark.parametrize("source, message", [
    (lambda: {"object": f"obj:{uuid7()}", "object_version": 1, "digest": DIGEST}, "такого объекта нет"),
    (lambda: {"object": "obj:not-a-uuid", "object_version": 1, "digest": DIGEST}, "такого объекта нет"),
    (lambda: {"object": OBJ, "object_version": 2, "digest": DIGEST}, "нет версии 2"),
    (lambda: {"object": OBJ, "object_version": 1, "digest": "sha256:" + "cd" * 32}, "не совпадает с версией 1"),
    (lambda: {"object": OBJ, "object_version": 1}, "digest не указан"),
], ids=["нет объекта", "не UUID", "нет версии", "чужой digest", "без digest"])
def test_source_must_match_object_version(kb, source, message):
    with pytest.raises(RecordError, match=message):
        commit(kb, [Item("entity", sp20()), Item("entity", edition()), Item("atom", fact(sources=[source()]))],
               agent=AGENT)


def test_source_row_changes_only_by_check(kb):
    """Строку источника меняет только итог сверки с файлом (уровень 2); удалить её нельзя."""
    base(kb)
    kb.execute("UPDATE source SET verdict = 'ok', page = 27, anchor = 'Таблица 11.1', checked_at = now()")
    with pytest.raises(psycopg.errors.RaiseException, match="только итог сверки"):
        kb.execute("UPDATE source SET quote = 'другая цитата'")
    with pytest.raises(psycopg.errors.RaiseException, match="нельзя удалить"):
        kb.execute("DELETE FROM source")
