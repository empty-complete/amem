"""Уровень 4 автопроверки (разд. 6 спецификации подпроекта 3): дубли текстом и вектором, подсказки связей,
ослабление без вектора. Существующие записи пишутся через records.commit, мимо проверки; вектора — FakeProvider."""
import uuid

import pytest

from amemo import db, embed, records
from amemo.check import Proposal, level1, level4
from amemo.check.report import Report
from check_support import atom, entity
from conftest import FakeProvider

AGENT = "model:tester"
WIND = "Ветровое давление для района II равно 0,30 кПа"
WIND_NEW = "Ветровое давление района II равно 0,30 кПа"


def prop(body: dict, record_id=None) -> Proposal:
    return Proposal("entity" if "entity_class" in body else "atom", body, record_id)


def lab(text: str) -> dict:
    return {"ru": text}


def run(conn, *items, provider=None):
    """Уровни 1 и 4 над пачкой; (замечания уровня 4, degraded)."""
    report = Report()
    batch = level1.check(conn, [i if isinstance(i, Proposal) else prop(i) for i in items], [], report)
    assert not report.violations(), report.issues
    degraded = level4.check(conn, batch, report, provider=provider)
    return [i for i in report.issues if i.level == 4], degraded


def stored(conn, *bodies) -> dict[str, uuid.UUID]:
    bodies = [{k: v for k, v in b.items() if k != "sources"} for b in bodies]
    result = records.commit(conn, [records.Item(prop(b).target, b) for b in bodies], [], agent=AGENT)
    return {n: uuid.UUID(r.split(":", 1)[1]) for n, r in result.refs.items()}


def activate(conn, provider) -> dict:
    model = embed.register_model(conn, provider)
    embed.sync_embeddings(conn, model["id"], provider)
    return embed.activate_model(conn, model["id"])


@pytest.fixture
def kb(pg):
    db.prepare(pg)
    level4._implicit.cache_clear()
    yield pg
    getattr(level4._implicit, "cache_clear", lambda: None)()     # подменённый в тесте — без кэша


def codes(issues):
    return [(i.code, i.severity, i.where) for i in issues]


# --- атомы, текст ---

def test_text_duplicate_with_candidate(kb):
    ids = stored(kb, atom("@old", label=lab(WIND)))
    issues, degraded = run(kb, atom("@a1", label=lab(WIND_NEW)))
    assert codes(issues) == [("duplicate", "warning", "@a1")]
    [cand] = issues[0].details["candidates"]
    assert cand["ref"] == f"atm:{ids['@old']}" and cand["channel"] == "text" and cand["score"] >= level4.DUP_TEXT
    assert degraded == [{"level": 4, "channel": "vector", "reason": "no_active_model"}]


def test_other_kind_is_not_duplicate(kb):
    stored(kb, atom("@old", kind="term", label=lab(WIND)))
    issues, _ = run(kb, atom("@a1", label=lab(WIND_NEW)))
    assert issues == []


def test_rejected_is_not_duplicate(kb):
    ids = stored(kb, atom("@old", label=lab(WIND)))
    kb.execute("UPDATE atom SET status = 'rejected' WHERE id = %s", (ids["@old"],))
    issues, _ = run(kb, atom("@a1", label=lab(WIND_NEW)))
    assert issues == []


def test_edit_does_not_find_itself(kb):
    ids = stored(kb, atom("@old", label=lab(WIND)))
    issues, _ = run(kb, prop(atom("@a1", label=lab(WIND_NEW)), ids["@old"]))
    assert issues == []


def test_related_below_threshold_at_most_five(kb):
    stored(kb, *[atom(f"@r{n}", label=lab(f"Ветровое давление района II на высоте {n * 10} м увеличивают"))
                 for n in range(1, 8)])
    issues, _ = run(kb, atom("@a1", label=lab(WIND_NEW)))
    assert codes(issues) == [("related", "info", "@a1")]
    cands = issues[0].details["candidates"]
    assert len(cands) == level4.RELATED == 5
    assert all(level4.REL_TEXT <= c["score"] < level4.DUP_TEXT for c in cands)


def test_stop_words_only_label_has_no_text_candidates(kb):
    stored(kb, atom("@old", label=lab("и в на")))
    issues, _ = run(kb, atom("@a1", label=lab("и в на")))
    assert issues == []


# --- атомы, вектор ---

def test_vector_duplicate(kb):
    fake = FakeProvider()
    ids = stored(kb, atom("@old", label=lab("Кронштейн крепится к закладной анкером")))
    activate(kb, fake)
    old_doc = kb.execute("SELECT document FROM search_document WHERE record_id = %s", (ids["@old"],)).fetchone()[0]
    new = atom("@a1", label=lab("Совсем иная подпись про стекло"), summary_plain=lab("Другие слова."))

    class Twin(FakeProvider):
        def _embed(self, texts):
            return [FakeProvider.vector(old_doc if "стекло" in t else t) for t in texts]

    issues, degraded = run(kb, new, provider=Twin())
    assert degraded == []
    assert codes(issues) == [("duplicate", "warning", "@a1")]
    cand = issues[0].details["candidates"][0]
    assert cand["ref"] == f"atm:{ids['@old']}" and cand["channel"] == "vector"
    assert cand["score"] == pytest.approx(1.0)


def test_vector_edit_does_not_find_itself(kb):
    fake = FakeProvider()
    ids = stored(kb, atom("@old", label=lab("Кронштейн крепится к закладной анкером")))
    activate(kb, fake)
    body = {k: v for k, v in atom("@old", label=lab("Кронштейн крепится к закладной анкером")).items()}
    issues, degraded = run(kb, prop(body, ids["@old"]), provider=fake)
    assert degraded == [] and issues == []


# --- ослабление ---

def test_backend_disabled(kb, monkeypatch):
    activate(kb, FakeProvider())
    stored(kb, atom("@old", label=lab(WIND)))
    monkeypatch.setenv("AMEMO_BACKEND", "none")
    issues, degraded = run(kb, atom("@a1", label=lab(WIND_NEW)), provider=FakeProvider())
    assert degraded == [{"level": 4, "channel": "vector", "reason": "backend_disabled"}]
    assert codes(issues) == [("duplicate", "warning", "@a1")]


def test_no_active_model(kb):
    issues, degraded = run(kb, atom("@a1", label=lab(WIND_NEW)), provider=FakeProvider())
    assert degraded == [{"level": 4, "channel": "vector", "reason": "no_active_model"}]
    assert issues == []


class Broken(FakeProvider):
    def _embed(self, texts):
        raise embed.EmbeddingError("провайдер недоступен")


def test_implicit_provider_error_degrades(kb, monkeypatch):
    activate(kb, FakeProvider())
    stored(kb, atom("@old", label=lab(WIND)))
    monkeypatch.setattr(level4, "_implicit", lambda: Broken())
    issues, degraded = run(kb, atom("@a1", label=lab(WIND_NEW)))
    assert degraded == [{"level": 4, "channel": "vector", "reason": "provider_error"}]
    assert codes(issues) == [("duplicate", "warning", "@a1")]


def test_implicit_provider_is_cached(kb, monkeypatch):
    made = []
    monkeypatch.setattr(embed, "get_provider", lambda explicit=None: made.append(1) or Broken())
    level4._provider(None)
    level4._provider(None)
    assert len(made) == 1


def test_explicit_provider_error_raises(kb):
    activate(kb, FakeProvider())
    with pytest.raises(embed.EmbeddingError):
        run(kb, atom("@a1", label=lab(WIND_NEW)), provider=Broken())


# --- сущности ---

def test_entity_alias_duplicate_suggests_same_as(kb):
    ids = stored(kb, entity("@e0", cls="organization", label=lab("Пример"), aliases=["Пример и партнёры"]))
    issues, _ = run(kb, entity("@e1", cls="organization", label=lab("Пример и партнеры")))
    assert codes(issues) == [("duplicate", "warning", "@e1")]
    assert [c["suggest"] for c in issues[0].details["candidates"]] == ["same_as"]
    assert issues[0].details["candidates"][0]["ref"] == f"ent:{ids['@e0']}"


def test_entity_other_class_is_not_duplicate(kb):
    stored(kb, entity("@e0", cls="person", label=lab("Пример"), aliases=["Пример и партнёры"]))
    issues, _ = run(kb, entity("@e1", cls="organization", label=lab("Пример и партнеры")))
    assert issues == []


# --- внутри пачки ---

def test_duplicate_inside_batch(kb):
    issues, _ = run(kb, atom("@a1", label=lab(WIND)), atom("@a2", label=lab(WIND_NEW)))
    assert codes(issues) == [("duplicate", "warning", "@a2")]
    assert issues[0].details["candidates"][0]["ref"] == "@a1"


def test_inside_batch_other_kind_is_not_duplicate(kb):
    issues, _ = run(kb, atom("@a1", label=lab(WIND)), atom("@a2", kind="term", label=lab(WIND_NEW)))
    assert issues == []


# --- журнал ---

def test_retrieval_log_untouched(kb):
    fake = FakeProvider()
    stored(kb, atom("@old", label=lab(WIND)))
    activate(kb, fake)
    before = kb.execute("SELECT count(*) FROM retrieval").fetchone()[0]
    issues, degraded = run(kb, atom("@a1", label=lab(WIND_NEW)), provider=fake)
    assert degraded == [] and codes(issues) == [("duplicate", "warning", "@a1")]
    assert kb.execute("SELECT count(*) FROM retrieval").fetchone()[0] == before
