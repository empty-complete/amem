"""Метрики очереди и проверки: review.stats (разд. 8.7 спецификации подпроекта 3)."""
import itertools
import json
from datetime import datetime, timedelta, timezone

import pytest

from amem import check, db, review
from amem.check import Proposal
from check_support import CHECK_PACK, PDF, atom, source_pdf

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


def test_stats_all_sections(kb, store, docs):
    base = datetime.now(timezone.utc) + timedelta(hours=1)        # позже любой записи: решения не сдвигаются
    now = base + timedelta(hours=3)
    # три пункта semantic: захвачен с живой арендой, захвачен с истёкшей, ждёт
    s = [send(kb, store, docs, n) for n in ("a", "b", "c")]
    ids = [item_of(r, "semantic") for r in s]
    [live] = review.claim(kb, agent=MODEL, now=base + timedelta(minutes=170))     # аренда до now+5 мин
    [dead] = review.claim(kb, agent="model:other", now=base)                      # аренда до base+15 мин
    assert (live["id"], dead["id"]) == (ids[0], ids[1])
    # два решённых пункта с известными интервалами
    d1, d2 = send(kb, store, docs, "d1"), send(kb, store, docs, "d2")
    w1, w2 = put(kb, d1, "warning", base), put(kb, d2, "warning", base)
    review.resolve(kb, w1, "confirmed", agent=PERSON, now=base + timedelta(hours=1))
    review.resolve(kb, w2, "confirmed", agent=PERSON, now=base + timedelta(hours=2))
    # устаревший пункт
    o = send(kb, store, docs, "o")
    ob = put(kb, o, "calibration", base)
    kb.execute("UPDATE review_item SET state = 'obsolete', closed_at = %s WHERE id = %s",
               (base + timedelta(minutes=10), ob))
    # отклонённый пакет: цитаты нет на странице
    bad = send(kb, store, docs, "bad", quote="Этой цитаты в документе нет")
    assert bad.state == "rejected"
    # аудит: один refuted, один confirmed, оба от AUTHOR
    u1, u2 = send(kb, store, docs, "u1"), send(kb, store, docs, "u2")
    review.resolve(kb, put(kb, u1, "audit", base), "refuted", agent=PERSON, now=base + timedelta(hours=1))
    review.resolve(kb, put(kb, u2, "audit", base), "confirmed", agent=PERSON, now=base + timedelta(hours=1))

    out = review.stats(kb, now=now)
    json.dumps(out)

    sem = out["queue"]["semantic"]
    # у записей d1, d2, o, u1, u2 тоже свои semantic: проверяем то, что известно точно
    own = {i: kb.execute("SELECT state, claimed_until < %s FROM review_item WHERE id = %s", (now, i)).fetchone()
           for i in ids}
    assert own[ids[0]] == ("claimed", False) and own[ids[1]] == ("claimed", True)
    open_sem = [r[0] for r in kb.execute("SELECT state FROM review_item WHERE reason = 'semantic' "
                                         "AND state IN ('queued', 'claimed')").fetchall()]
    assert sem["queued"] == open_sem.count("queued")
    assert sem["claimed"] == 1 and sem["expired"] == 1
    oldest = min(created(kb, r[0]) for r in kb.execute(
        "SELECT id FROM review_item WHERE reason = 'semantic' AND state = 'queued'").fetchall())
    assert sem["oldest_queued_age_s"] == pytest.approx((now - oldest).total_seconds(), abs=1e-3)

    assert out["done"]["by_reason"]["warning"] == {"count": 2, "median_s": 5400.0}
    assert out["done"]["by_reason"]["audit"] == {"count": 2, "median_s": 3600.0}
    # устаревший вручную и четыре semantic, закрытые итоговым решением человека по тем же ревизиям
    assert out["done"]["obsolete"] == 5
    assert out["changesets"]["rejected"] == 1
    assert out["changesets"]["approved"] == len(s) + 2 + 1 + 2
    assert out["changesets"]["error_codes"] == {"quote_not_found": 1}
    assert out["audit"] == {AUTHOR: {"decided": 2, "refuted": 1}}
    assert sum(out["records"]["atoms"].values()) == 8
    assert out["sources"]["ok"] == 8 and out["sources"]["unchecked"] == 0


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
