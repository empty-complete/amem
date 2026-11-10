"""Библиотека для службы (спецификация подпроекта 4, разд. 1.2): фильтры поиска списком, выдача без журнала,
what_changed с limit и who, задача сессии, коды ReviewError, семья вида, имя базы, сведения о бэкапах."""
import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import ValidationError

from amem import backup, db, embed, folders, ids, model_v1, packs, recipes, records, review, usefulness, vocab
from amem.records import Item, RecordError
from conftest import FakeProvider

AGENT = "model:test"
HUMAN = "person:ann"
EXAMPLE = Path(__file__).with_name("packs") / "example"


@pytest.fixture
def kb(pg):
    db.prepare(pg)
    return pg


def atom(key, label, *, kind="fact", codes=None):
    return Item("atom", {"ref": f"@{key}", "kind": kind, "key": key, "label": {"ru": label},
                         "summary_plain": {"ru": label}, "codes": codes or []})


def entity(key, label, *, cls="document", codes=None):
    return Item("entity", {"ref": f"@{key}", "entity_class": cls, "key": key, "label": {"ru": label},
                           "codes": codes or []})


def write(kb, *items, agent=AGENT):
    return records.commit(kb, list(items), agent=agent)


def refs(result) -> set[str]:
    return {item["ref"] for item in result["items"]}


def dsn_of(conn) -> str:
    params = conninfo_to_dict(conn.info.dsn)
    params["password"] = conn.info.password
    return make_conninfo(**params)


def count(kb, table: str) -> int:
    return kb.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


# --- фильтры поиска списком ---

def mixed(kb) -> dict:
    """Атомы трёх видов и сущности трёх классов с одной маркой и одним словом в подписи."""
    written = write(kb,
                    atom("f", "Кронштейн факт", kind="fact", codes=["SVC-1"]),
                    atom("t", "Кронштейн термин", kind="term", codes=["SVC-1"]),
                    atom("m", "Кронштейн методика", kind="method", codes=["SVC-1"]),
                    entity("p", "Кронштейн проект", cls="project", codes=["SVC-1"]),
                    entity("d", "Кронштейн документ", cls="document", codes=["SVC-1"]),
                    entity("s", "Кронштейн программа", cls="software", codes=["SVC-1"]))
    return {name.removeprefix("@"): ref for name, ref in written.refs.items()}


def one_axis(text: str) -> list[float]:
    out = [0.0] * 384
    out[0] = 1.0
    return out


@pytest.mark.parametrize("recipe,query", [("exact_fact", "SVC-1"), ("similar", "кронштейн")])
def test_kind_and_entity_class_accept_several_values(kb, recipe, query):
    r = mixed(kb)
    run = getattr(recipes, recipe)

    assert refs(run(kb, query, agent=AGENT, kind=["fact", "term"])) == {r["f"], r["t"]}
    assert refs(run(kb, query, agent=AGENT, kind=("fact", "term", "fact"))) == {r["f"], r["t"]}
    assert refs(run(kb, query, agent=AGENT, entity_class=["project", "document"])) == {r["p"], r["d"]}
    assert refs(run(kb, query, agent=AGENT, kind="fact")) == {r["f"]}                # одно значение — строкой
    assert refs(run(kb, query, agent=AGENT, entity_class="software")) == {r["s"]}
    # оба фильтра: атомы этих видов и сущности этих классов
    assert refs(run(kb, query, agent=AGENT, kind=["method"], entity_class=["software"])) == {r["m"], r["s"]}
    assert refs(run(kb, query, agent=AGENT, kind=["fact"], target="atom", entity_class=["software"])) == {r["f"]}
    assert refs(run(kb, query, agent=AGENT, kind=[])) == set(r.values())             # пустой набор — без фильтра
    for bad in ([1], [""], 5, ["fact", None]):
        with pytest.raises(ValueError, match="kind"):
            run(kb, query, agent=AGENT, kind=bad)
    with pytest.raises(ValueError, match="entity_class"):
        run(kb, query, agent=AGENT, entity_class=[""])


def test_vector_channel_takes_several_kinds(kb):
    r = mixed(kb)
    provider = FakeProvider()
    provider.vector = one_axis
    model = embed.register_model(kb, provider)
    embed.sync_embeddings(kb, model["id"], provider)
    embed.activate_model(kb, model["id"])

    result = recipes.exact_fact(kb, "нет такого слова", agent=AGENT, provider=provider,
                                kind=["fact", "method"], entity_class=["project"])

    assert result["semantic"] == "used" and refs(result) == {r["f"], r["m"], r["p"]}
    assert all(m["channel"] == "vector" for item in result["items"] for m in item["matches"])


# --- выдача без журнала ---

@pytest.mark.parametrize("recipe,query", [("exact_fact", "SVC-1"), ("similar", "кронштейн")])
def test_log_false_skips_the_search_log(kb, recipe, query):
    mixed(kb)
    before = (count(kb, "retrieval"), count(kb, "retrieval_item"))

    quiet = getattr(recipes, recipe)(kb, query, agent=AGENT, log=False)

    assert quiet["retrieval_id"] is None and quiet["items"]
    assert (count(kb, "retrieval"), count(kb, "retrieval_item")) == before
    logged = getattr(recipes, recipe)(kb, query, agent=AGENT)
    assert logged["retrieval_id"] is not None and count(kb, "retrieval") == before[0] + 1
    assert [item["ref"] for item in logged["items"]] == [item["ref"] for item in quiet["items"]]


# --- what_changed: агент, limit, who ---

def history(kb):
    """Ревизии модели и человека, связь модели, выведенная человеком, решение человека о правке."""
    first = write(kb, atom("a", "Первый"), entity("e", "Документ"))
    a_id = uuid.UUID(first.refs["@a"].split(":", 1)[1])
    link = records.commit(kb, [], [{"rel": "depends_on", "src": first.refs["@a"], "dst": first.refs["@e"]}],
                          agent=AGENT).links[0]
    records.set_status(kb, "atom", a_id, "verified", agent=HUMAN, reason="проверено")
    records.retire_link(kb, link, agent=HUMAN, reason="устарела")
    pending = Item("atom", {"kind": "fact", "key": "a", "label": {"ru": "Первый, правка"},
                            "summary_plain": {"ru": "Первый"}, "codes": []}, record_id=a_id, review_state="pending")
    second = records.commit(kb, [pending], agent=AGENT).revisions[0]
    records.decide(kb, "atom", second.revision_id, accept=True, agent=HUMAN)
    write(kb, atom("b", "Второй", kind="term"), agent=HUMAN)
    return first.refs["@a"], link


def test_what_changed_events_carry_agent(kb):
    ref, link = history(kb)
    events = recipes.what_changed(kb)["events"]

    by_type = {}
    for event in events:
        by_type.setdefault(event["type"], []).append(event)
    assert {e["agent"] for e in by_type["revision"]} == {AGENT, HUMAN}
    assert [e["agent"] for e in by_type["revision"] if e["ref"] == ref] == [AGENT, AGENT]
    [created] = by_type["link_created"]
    [retired] = by_type["link_retired"]
    assert created["id"] == retired["id"] == str(link)
    assert created["agent"] == AGENT and retired["agent"] == HUMAN       # вывел связь другой агент
    [reviewed] = by_type["review"]
    assert reviewed["agent"] == reviewed["reviewed_by"] == HUMAN
    assert all(isinstance(event["agent"], str) for event in events)


def test_what_changed_who_and_limit(kb):
    ref, _ = history(kb)
    full = recipes.what_changed(kb)["events"]
    people = [e for e in full if e["agent"].startswith("person:")]
    models = [e for e in full if e["agent"].startswith("model:")]
    assert people and models and len(people) + len(models) == len(full)

    assert recipes.what_changed(kb, who="person")["events"] == people
    assert recipes.what_changed(kb, who="model")["events"] == models
    assert recipes.what_changed(kb, who="all")["events"] == full
    for n in range(1, len(full) + 2):                    # limit оставляет самые новые, порядок прежний
        assert recipes.what_changed(kb, limit=n)["events"] == full[-n:]
    for n in (1, 2, len(people)):
        assert recipes.what_changed(kb, who="person", limit=n)["events"] == people[-n:]
    of_ref = recipes.what_changed(kb, ref=ref)["events"]
    assert recipes.what_changed(kb, ref=ref, limit=3)["events"] == of_ref[-3:]
    since = datetime.fromisoformat(full[2]["at"])
    window = recipes.what_changed(kb, since=since)["events"]
    assert recipes.what_changed(kb, since=since, limit=2, who="model")["events"] == [
        e for e in window if e["agent"].startswith("model:")][-2:]

    for bad in (0, -1, True, "3", 1.5):
        with pytest.raises(RecordError, match="limit"):
            recipes.what_changed(kb, limit=bad)
    for bad in ("people", "", None, "PERSON"):
        with pytest.raises(RecordError, match="who"):
            recipes.what_changed(kb, who=bad)


def test_what_changed_folder_events_follow_who_and_limit(kb):
    ref = write(kb, atom("x", "Запись")).refs["@x"]
    folders.move(kb, ref, "Проекты/Альфа", agent=HUMAN)
    folders.move(kb, ref, None, agent=AGENT)
    full = recipes.what_changed(kb)["events"]
    moves = [e for e in full if e["type"] == "folder"]
    assert [(e["agent"], e["to"]) for e in moves] == [(HUMAN, "Проекты/Альфа"), (AGENT, None)]
    assert recipes.what_changed(kb, limit=1)["events"] == [moves[-1]]
    assert [e["type"] for e in recipes.what_changed(kb, who="person")["events"]] == ["folder"]


# --- задача сессии ---

def test_session_activity_is_one_task_per_label(kb):
    first = usefulness.session_activity(kb, "mcp:x")
    again = usefulness.session_activity(kb, "mcp:x")
    other = usefulness.session_activity(kb, "mcp:y")

    assert isinstance(first, uuid.UUID) and first == again and other != first
    rows = kb.execute("SELECT id, kind, label FROM activity ORDER BY id").fetchall()
    assert rows == [(first, "session", "mcp:x"), (other, "session", "mcp:y")]
    assert first.version == 7
    for bad in ("", "   ", None, 5):
        with pytest.raises(ValueError, match="метка"):
            usefulness.session_activity(kb, bad)


def test_session_activity_ignores_other_kinds_with_same_label(kb):
    task = ids.uuid7()
    kb.execute("INSERT INTO activity (id, kind, label, started_at) VALUES (%s, 'task', 'mcp:x', now())", (task,))
    session = usefulness.session_activity(kb, "mcp:x")
    assert session != task
    assert kb.execute("SELECT kind FROM activity WHERE id = %s", (session,)).fetchone()[0] == "session"


def test_session_activity_search_and_helpful(kb):
    ref = write(kb, atom("w", "Ветровое давление", codes=["WND-1"])).refs["@w"]
    session = usefulness.session_activity(kb, "mcp:x")
    foreign = usefulness.session_activity(kb, "mcp:y")

    found = recipes.exact_fact(kb, "WND-1", agent=AGENT, activity=session)
    assert kb.execute("SELECT activity FROM retrieval WHERE id = %s", (found["retrieval_id"],)).fetchone()[0] == session
    usefulness.mark_helpful(kb, found["retrieval_id"], [ref], agent=AGENT, activity=session)
    assert kb.execute("SELECT count(*) FROM atom_use WHERE activity = %s", (session,)).fetchone()[0] == 1

    other = recipes.exact_fact(kb, "WND-1", agent=AGENT, activity=foreign)
    with pytest.raises(ValueError, match="activity"):
        usefulness.mark_helpful(kb, other["retrieval_id"], [ref], agent=AGENT, activity=session)
    quiet = recipes.exact_fact(kb, "WND-1", agent=AGENT, activity=session, log=False)
    assert quiet["retrieval_id"] is None


def test_session_activity_in_parallel_is_one_task(kb):
    dsn = dsn_of(kb)
    barrier = threading.Barrier(4)
    got, errors = [None] * 4, []

    def worker(k: int) -> None:
        try:
            with db.connect(dsn) as conn:
                barrier.wait(timeout=30)
                got[k] = usefulness.session_activity(conn, "mcp:parallel")
        except BaseException as e:                         # noqa: BLE001 — ошибку потока проверяет тест
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert errors == [] and len(set(got)) == 1
    assert kb.execute("SELECT count(*) FROM activity WHERE label = 'mcp:parallel'").fetchone()[0] == 1


# --- коды ReviewError ---

def queue(kb, reason="semantic", agent=AGENT, key="r"):
    """Запись модели и пункт очереди на её ревизию — как его поставил бы check.submit."""
    written = write(kb, atom(key, f"Запись {key}"), agent=agent)
    rev = written.revisions[0]
    with kb.transaction():
        item = review.insert_item(kb, "atom", rev.record_id, rev.revision_id, reason,
                                  changeset_id=written.changeset_id, details={}, agent=agent,
                                  at=datetime.now(timezone.utc))
    return item["id"], rev


def error_of(call, *args, **kwargs) -> review.ReviewError:
    with pytest.raises(review.ReviewError) as caught:
        call(*args, **kwargs)
    return caught.value


def test_review_error_closed_says_who_and_when(kb):
    item, _ = queue(kb)
    review.resolve(kb, item, "confirmed", agent=HUMAN)
    closed_at = kb.execute("SELECT closed_at FROM review_item WHERE id = %s", (item,)).fetchone()[0]

    e = error_of(review.resolve, kb, item, "refuted", agent=HUMAN)
    assert e.code == "closed" and e.by == HUMAN and e.at == closed_at
    assert "уже закрыт" in str(e)                                        # сообщение прежнее
    e = error_of(review.release, kb, item, agent=HUMAN)
    assert e.code == "closed" and e.by == HUMAN and e.at == closed_at


def test_review_error_closed_obsolete_has_no_author(kb):
    item, rev = queue(kb)
    records.commit(kb, [Item("atom", {"kind": "fact", "key": "r", "label": {"ru": "Новая редакция"},
                                      "summary_plain": {"ru": "Новая"}, "codes": []}, rev.record_id)], agent=HUMAN)
    e = error_of(review.resolve, kb, item, "confirmed", confidence=0.9, agent="model:judge")
    assert e.code == "stale" and "устарел" in str(e)
    closed_at = kb.execute("SELECT closed_at FROM review_item WHERE id = %s", (item,)).fetchone()[0]
    e = error_of(review.resolve, kb, item, "confirmed", agent=HUMAN)
    assert e.code == "closed" and e.by is None and e.at == closed_at


def test_review_error_forbidden_bad_outcome_claimed(kb):
    warning, _ = queue(kb, "warning", key="w")
    semantic, _ = queue(kb, "semantic", key="s")

    assert error_of(review.resolve, kb, warning, "confirmed", confidence=0.9, agent="model:judge").code == "forbidden"
    assert error_of(review.resolve, kb, semantic, "confirmed", confidence=0.9, agent=AGENT).code == "forbidden"
    assert error_of(review.enqueue, kb, "atm:w", "audit", agent="model:judge").code == "forbidden"
    e = error_of(review.resolve, kb, semantic, "uncertain", agent=HUMAN)
    assert e.code == "bad_outcome" and e.by is None and e.at is None
    assert error_of(review.resolve, kb, semantic, "confirmed", agent="model:judge").code == "bad_outcome"
    assert error_of(review.resolve, kb, semantic, "confirmed", confidence=1.5,
                    agent="model:judge").code == "bad_outcome"

    review.claim(kb, agent="model:other")
    e = error_of(review.resolve, kb, semantic, "confirmed", confidence=0.9, agent="model:judge")
    assert e.code == "claimed" and "захвачен" in str(e)
    assert error_of(review.release, kb, semantic, agent="model:judge").code == "claimed"


def test_review_error_not_found_and_invalid(kb):
    missing = uuid.UUID("01900000-0000-7000-8000-000000000001")
    assert error_of(review.resolve, kb, missing, "confirmed", agent=HUMAN).code == "not_found"
    assert error_of(review.release, kb, missing, agent=HUMAN).code == "not_found"
    assert error_of(review.enqueue, kb, f"atm:{missing}", "audit", agent=HUMAN).code == "not_found"
    assert error_of(review.enqueue, kb, "atm:no.such", "audit", agent=HUMAN).code == "not_found"
    assert error_of(review.claim, kb, agent=HUMAN, reasons="semantic").code == "invalid"
    assert error_of(review.claim, kb, agent="robot:x").code == "invalid"
    assert error_of(review.items, kb, state="lost").code == "invalid"
    assert error_of(review.resolve, kb, "не uuid", "confirmed", agent=HUMAN).code == "invalid"
    item, _ = queue(kb)
    assert error_of(review.release, kb, item, agent=HUMAN).code == "invalid"           # пункт никто не держит
    assert set(review.ReviewError.CODES) == {"closed", "forbidden", "bad_outcome", "stale", "claimed",
                                             "not_found", "invalid"}


# --- семья вида ---

def test_concept_family_in_schema():
    assert "family" in model_v1.Concept.model_fields
    body = {"scheme": "kind", "code": "norm", "label": {"ru": "норма"}}
    assert model_v1.Concept.model_validate_json(json.dumps({**body, "family": "source"}), strict=True).family == "source"
    assert model_v1.Concept.model_validate_json(json.dumps(body), strict=True).family is None
    with pytest.raises(ValidationError):
        model_v1.Concept.model_validate_json(json.dumps({**body, "family": "other"}), strict=True)


def test_core_marks_its_kinds():
    core = packs.load_pack(packs.CORE_PACK)
    assert core.version == "1.4.0"
    assert {c.code: c.family for c in core.concepts if c.scheme == "kind"} == {
        "fact": "source", "parameter": "source", "term": "source", "requirement": "source",
        "decision": "work", "lesson": "work", "method": "work", "question": "work", "note": "work"}
    assert all(c.family is None for c in core.concepts if c.scheme != "kind")


def test_family_only_for_kinds(tmp_path):
    pack = tmp_path / "bad"
    (pack / "vocab").mkdir(parents=True)
    (pack / "pack.yaml").write_text("name: bad\nversion: 1.0.0\n", encoding="utf-8")
    (pack / "vocab" / "entity_class.yaml").write_text(
        "scheme: entity_class\nconcepts:\n- code: device\n  label: {ru: прибор}\n  family: source\n", encoding="utf-8")
    with pytest.raises(packs.PackError, match="family"):
        packs.load_pack(pack)
    (pack / "vocab" / "entity_class.yaml").write_text(
        "scheme: kind\nconcepts:\n- code: norm\n  label: {ru: норма}\n  family: law\n", encoding="utf-8")
    with pytest.raises(packs.PackError, match="norm"):
        packs.load_pack(pack)
    (pack / "vocab" / "entity_class.yaml").write_text(
        "scheme: kind\nconcepts:\n- code: norm\n  label: {ru: норма}\n  family: source\n", encoding="utf-8")
    assert [c.family for c in packs.load_pack(pack).concepts] == ["source"]


def test_vocab_family_and_entries(kb, monkeypatch):
    monkeypatch.setattr(packs, "discover", lambda: [packs.CORE_PACK, EXAMPLE])
    db.load_vocab(kb)

    assert vocab.family(kb, "fact") == "source" and vocab.family(kb, "note") == "work"
    assert vocab.family(kb, "idea") == "work"                          # вид пакета без family — work
    with pytest.raises(vocab.VocabError, match="no_such"):
        vocab.family(kb, "no_such")
    families = vocab.families(kb)
    assert families["requirement"] == "source" and families["idea"] == "work" and families["question"] == "work"

    kinds = vocab.entries(kb, "kind")
    assert [e["code"] for e in kinds] == sorted(e["code"] for e in kinds)
    fact = next(e for e in kinds if e["code"] == "fact")
    assert fact == {"code": "fact", "label": {"ru": "факт", "en": "fact"},
                    "definition": {"ru": "Утверждение о мире или наблюдение из документа, не являющееся нормой "
                                         "или решением."},
                    "pack": "core", "broader": None, "family": "source"}
    idea = next(e for e in kinds if e["code"] == "idea")
    assert idea["pack"] == "example" and idea["family"] == "work"
    classes = vocab.entries(kb, "entity_class")
    assert all("family" not in e for e in classes) and {"project", "document"} <= {e["code"] for e in classes}
    statuses = {e["code"]: e for e in vocab.entries(kb, "status")}
    assert statuses["draft"]["pack"] == "schema" and statuses["draft"]["label"]["ru"] == "не проверен"
    assert vocab.entries(kb, "no_such_scheme") == []
    json.dumps(kinds)


# --- имя базы ---

def test_base_name(kb):
    assert db.base_name(kb) is None
    assert db.set_base_name(kb, "  Рабочая база  ") == "Рабочая база"
    assert db.base_name(kb) == "Рабочая база"
    db.set_base_name(kb, "Ёще одна")                          # NFC: Ё одним знаком
    assert db.base_name(kb) == "Ёще одна"
    assert kb.execute("SELECT value FROM meta WHERE key = 'base_name'").fetchone()[0] == "Ёще одна"
    assert kb.execute("SELECT count(*) FROM meta WHERE key = 'base_name'").fetchone()[0] == 1
    for bad in ("", "   ", None, 5, "a\nb", "a‎b", "x" * 201):
        with pytest.raises(db.BaseNameError):
            db.set_base_name(kb, bad)
    assert db.base_name(kb) == "Ёще одна"
    db.prepare(kb)                                                   # повторная подготовка имя не трогает
    assert db.base_name(kb) == "Ёще одна"


# --- бэкапы ---

def test_backups_report_created_at_and_size(tmp_path):
    def pair(name, size, **extra):
        (tmp_path / f"{name}.dump").write_bytes(b"x" * size)
        (tmp_path / f"{name}.json").write_text(json.dumps(
            {"kind": "amem.pg_dump", "format": 1, "file": f"{name}.dump", "size": size, **extra}), encoding="utf-8")

    pair("2026-11-05T08-00-00Z", 7, created_at="2026-11-05T08:00:00.250000+00:00")
    pair("2026-11-05T09-00-00Z", 3)                                  # манифест без created_at — время из имени

    got = backup.backups(tmp_path)

    assert [(b["name"], b["created_at"], b["size"]) for b in got] == [
        ("2026-11-05T08-00-00Z", "2026-11-05T08:00:00.250000+00:00", 7),
        ("2026-11-05T09-00-00Z", "2026-11-05T09:00:00+00:00", 3)]
    assert got[0]["dump"] == str(tmp_path / "2026-11-05T08-00-00Z.dump")
    assert datetime.fromisoformat(got[1]["created_at"]) == datetime(2026, 11, 5, 9, tzinfo=timezone.utc)
    json.dumps(got)


def test_created_backup_lists_manifest_time_and_size(pgdb, tmp_path):
    dsn = pgdb()
    with db.connect(dsn) as conn:
        db.prepare(conn)
    now = datetime(2026, 11, 5, 8, 0, tzinfo=timezone.utc) + timedelta(seconds=1)
    made = backup.create(dsn, tmp_path / "bk", now=now)
    [listed] = backup.backups(tmp_path / "bk")
    assert listed["created_at"] == made["created_at"] == now.isoformat()
    assert listed["size"] == made["size"] == Path(made["dump"]).stat().st_size
