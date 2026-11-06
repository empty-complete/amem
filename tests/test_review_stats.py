"""Метрики очереди и проверки: review.stats (разд. 8.7 спецификации подпроекта 3)."""
import itertools
import json
from datetime import datetime, timedelta, timezone

import pytest

from amem import check, db, objects, review
from amem.ids import uuid7
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


_cut = itertools.count()
TOPICS = ("Предел текучести стали", "Модуль упругости алюминия", "Коэффициент трения резины",
          "Плотность стекла", "Теплопроводность пенополистирола", "Прогиб консольной балки",
          "Нагрузка от снега", "Водопоглощение бетона", "Шаг анкерных болтов", "Толщина сварного шва",
          "Класс огнестойкости", "Температура эксплуатации герметика")


def send(conn, store, docs, name, *, quote=None, agent=AUTHOR, **fields) -> check.Submitted:
    # тема, подпись и цитата (обрезка страницы) у каждого атома свои: иначе пакет получит предупреждение о дубликате
    n = next(_cut)
    quote = quote or PAGE2[:len(PAGE2) - n % len(TOPICS)]
    topic = TOPICS[n % len(TOPICS)]
    body = atom(f"@{name}", label={"ru": f"{topic} — величина {n}"}, summary_plain={"ru": f"Про {topic} и ничего больше."},
                sources=[source_pdf(PDF, 2, quote)], **fields)
    return check.submit(conn, store, docs, [Proposal("atom", body, None)], agent=agent)


def item_of(result, reason):
    [q] = [q for q in result.queued if q["reason"] == reason]
    return q["id"]


def created(conn, item_id) -> datetime:
    return conn.execute("SELECT created_at FROM review_item WHERE id = %s", (item_id,)).fetchone()[0]


def put(conn, result, reason, at):
    """Пункт на текущую ревизию записи пакета, поставленный в заданное время."""
    rec = result.records[0]
    return review.insert_item(conn, "atom", rec["record_id"], rec["revision_id"], reason,
                              changeset_id=result.changeset_id, details={}, agent=AUTHOR, at=at)["id"]


def test_empty_base_gives_zeros_and_none(kb):
    out = review.stats(kb, now=datetime(2030, 1, 1, tzinfo=timezone.utc))
    assert all(v == {"queued": 0, "claimed": 0, "expired": 0, "oldest_queued_age_s": None}
               for v in out["queue"].values())
    assert set(out["queue"]) == set(review.REASONS)
    assert all(v == {"count": 0, "median_s": None} for v in out["done"]["by_reason"].values())
    assert out["done"]["obsolete"] == 0
    assert out["changesets"] == {"approved": 0, "rejected": 0, "error_codes": {}}
    assert all(n == 0 for kind in out["records"].values() for n in kind.values())
    assert all(n == 0 for n in out["sources"].values()) and "unchecked" in out["sources"]
    assert out["audit"] == {}
    json.dumps(out)


def test_naive_now_is_rejected(kb):
    with pytest.raises(review.ReviewError, match="часовым поясом"):
        review.stats(kb, now=datetime(2030, 1, 1))


def settle(conn):
    """Закрыть пункты, которые пакеты поставили сами: их время не задано. Закрыты вне окна, в метрики не попадают."""
    conn.execute("UPDATE review_item SET state = 'obsolete', closed_at = '2000-01-01', claimed_by = NULL, "
                 "claimed_until = NULL WHERE state IN ('queued', 'claimed')")


def test_stats_all_sections(kb, store, docs):
    base = datetime.now(timezone.utc) + timedelta(hours=1)        # позже любой записи: решения не сдвигаются
    now = base + timedelta(hours=3)
    mins = lambda m: base + timedelta(minutes=m)
    names = ("a", "b", "c", "d1", "d2", "o", "u1", "u2")
    r = {n: send(kb, store, docs, n) for n in names}
    letter = objects.message(kb, "Письмо о креплении кронштейна")
    ext = check.submit(kb, store, docs, [Proposal("atom", atom("@x", label={"ru": "Крепление по письму"},
                       summary_plain={"ru": "Про письмо."}, sources=[{"object": letter.ref, "object_version": 1}]),
                       None)], agent=AUTHOR)
    ent = check.submit(kb, store, docs, [Proposal("entity", entity("@e"), None)], agent=AUTHOR)
    bad = send(kb, store, docs, "bad", quote="Этой цитаты в документе нет")
    assert (ext.state, ent.state, bad.state) == ("approved", "approved", "rejected")
    # источник без вердикта: ещё не сверялся
    ok = kb.execute("SELECT object_id, object_version FROM source LIMIT 1").fetchone()
    kb.execute("INSERT INTO source (id, entity_revision_id, position, object_id, object_version) "
               "VALUES (%s, %s, 0, %s, %s)", (uuid7(), ent.records[0]["revision_id"], *ok))
    settle(kb)

    # semantic: a — захвачен с живой арендой, b — с истёкшей, c — ждёт с base+20 мин
    for n, m in (("a", 0), ("b", 10), ("c", 20)):
        put(kb, r[n], "semantic", mins(m))
    [live] = review.claim(kb, agent=MODEL, now=mins(170))              # аренда до base+185 мин, now = base+180
    [dead] = review.claim(kb, agent="model:other", now=base)           # аренда до base+15 мин
    assert (live["record_id"], dead["record_id"]) == (r["a"].records[0]["record_id"], r["b"].records[0]["record_id"])
    # warning: решены за 1 и 2 часа; audit: refuted за 1 час и confirmed за 3 часа
    for n, h in (("d1", 1), ("d2", 2)):
        review.resolve(kb, put(kb, r[n], "warning", base), "confirmed", agent=PERSON, now=base + timedelta(hours=h))
    review.resolve(kb, put(kb, r["u1"], "audit", base), "refuted", agent=PERSON, now=mins(60))
    review.resolve(kb, put(kb, r["u2"], "audit", base), "confirmed", agent=PERSON, now=mins(180))
    ob = put(kb, r["o"], "calibration", base)
    kb.execute("UPDATE review_item SET state = 'obsolete', closed_at = %s WHERE id = %s", (mins(10), ob))

    out = review.stats(kb, now=now)
    json.dumps(out)

    assert out["queue"]["semantic"] == {"queued": 1, "claimed": 1, "expired": 1, "oldest_queued_age_s": 9600.0}
    assert all(v == {"queued": 0, "claimed": 0, "expired": 0, "oldest_queued_age_s": None}
               for k, v in out["queue"].items() if k != "semantic")
    assert out["done"]["by_reason"]["warning"] == {"count": 2, "median_s": 5400.0}
    assert out["done"]["by_reason"]["audit"] == {"count": 2, "median_s": 7200.0}
    assert out["done"]["by_reason"]["semantic"] == {"count": 0, "median_s": None}
    assert out["done"]["obsolete"] == 1
    assert out["changesets"] == {"approved": 10, "rejected": 1, "error_codes": {"quote_not_found": 1}}
    assert out["audit"] == {AUTHOR: {"decided": 2, "refuted": 1}}
    # draft: a, b, c, o; needs_review: x (источник-письмо); verified: d1, d2, u2; rejected: u1 (аудит refuted)
    assert out["records"]["atoms"] == {"draft": 4, "needs_review": 1, "auto_verified": 0, "verified": 3,
                                       "rejected": 1, "deprecated": 0, "superseded": 0}
    assert out["records"]["entities"] == {"draft": 0, "needs_review": 0, "auto_verified": 1, "verified": 0,
                                          "rejected": 0, "deprecated": 0, "superseded": 0}
    assert out["sources"] == {"ok": 8, "moved": 0, "fuzzy": 0, "by_locator": 0, "unresolved": 0, "not_found": 0,
                              "no_file": 0, "no_text": 0, "external": 1, "error": 0, "unchecked": 1}


def test_window_limits_done_and_changesets(kb, store, docs):
    base = datetime.now(timezone.utc) + timedelta(hours=1)
    r = send(kb, store, docs, "w")
    review.resolve(kb, put(kb, r, "warning", base), "confirmed", agent=PERSON, now=base + timedelta(hours=1))
    late = base + timedelta(days=10)
    out = review.stats(kb, days=7, now=late)
    assert out["done"]["by_reason"]["warning"]["count"] == 0
    assert out["changesets"]["approved"] == 0
    wide = review.stats(kb, days=30, now=late)
    assert wide["done"]["by_reason"]["warning"]["count"] == 1 and wide["changesets"]["approved"] == 1


def test_window_edges(kb, store, docs):
    """closed_at == now входит в окно, closed_at == now - days — нет."""
    base = datetime.now(timezone.utc) + timedelta(hours=1)
    now = base + timedelta(days=7)
    for name, at in (("lo", base), ("hi", now)):
        r = send(kb, store, docs, name)
        settle(kb)
        review.resolve(kb, put(kb, r, "warning", base), "confirmed", agent=PERSON, now=at)
    out = review.stats(kb, days=7, now=now)
    assert out["done"]["by_reason"]["warning"] == {"count": 1, "median_s": 7 * 86400.0}


def test_median_of_odd_count(kb, store, docs):
    base = datetime.now(timezone.utc) + timedelta(hours=1)
    for name, h in (("m1", 1), ("m2", 2), ("m3", 10)):
        r = send(kb, store, docs, name)
        settle(kb)
        review.resolve(kb, put(kb, r, "warning", base), "confirmed", agent=PERSON, now=base + timedelta(hours=h))
    out = review.stats(kb, now=base + timedelta(days=1))
    assert out["done"]["by_reason"]["warning"] == {"count": 3, "median_s": 7200.0}


def test_audit_two_authors_and_manual_item(kb, store, docs):
    """Автор — агент пакета; у пункта, поставленного вручную (без пакета), — агент пакета ревизии."""
    base = datetime.now(timezone.utc) + timedelta(hours=1)
    a1 = send(kb, store, docs, "p1")
    a2 = send(kb, store, docs, "p2", agent="model:other")
    a3 = send(kb, store, docs, "p3", agent="model:other")
    settle(kb)
    review.resolve(kb, put(kb, a1, "audit", base), "confirmed", agent=PERSON, now=base)
    review.resolve(kb, put(kb, a2, "audit", base), "refuted", agent=PERSON, now=base)
    manual = review.enqueue(kb, f"atm:{a3.records[0]['record_id']}", "audit", agent=PERSON)
    assert kb.execute("SELECT changeset_id FROM review_item WHERE id = %s", (manual,)).fetchone()[0] is None
    review.resolve(kb, manual, "refuted", agent=PERSON, now=base)
    out = review.stats(kb, now=base + timedelta(hours=1))
    assert out["audit"] == {AUTHOR: {"decided": 1, "refuted": 0}, "model:other": {"decided": 2, "refuted": 2}}
