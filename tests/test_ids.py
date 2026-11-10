import types
import uuid

import pytest

import amemo.ids as ids_mod
from amemo.ids import uuid7


def _freeze(monkeypatch, now_ns: int) -> list[int]:
    """Остановить часы модуля ids и сбросить его счётчик; вернуть [now_ns] — чтобы переводить часы в тесте."""
    now = [now_ns]
    monkeypatch.setattr(ids_mod, "time", types.SimpleNamespace(time_ns=lambda: now[0]))
    monkeypatch.setattr(ids_mod, "_last_ms", 0)
    monkeypatch.setattr(ids_mod, "_seq", 0)
    return now


def test_uuid7_version_variant_and_time(monkeypatch):
    # не по настоящим часам: счётчик общий на процесс, и если часы ушли назад, пока шли предыдущие тесты
    # (на WSL2 — несколько раз в час), генератор их обгоняет — время id больше часов (см. докстринг uuid7)
    t = 1_800_000_000_000
    _freeze(monkeypatch, t * 1_000_000 + 999_999)       # счётчик сброшен — генератор не впереди часов
    u = uuid7()
    assert u.version == 7 and u.variant == uuid.RFC_4122
    assert u.int >> 80 == t                              # время — мс часов в момент вызова


def test_uuid7_sorted_in_creation_order_and_unique():
    ids = [uuid7() for _ in range(5000)]       # тысячи id за несколько миллисекунд
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_uuid7_monotonic_when_clock_steps_back(monkeypatch):
    now = _freeze(monkeypatch, 1_800_000_000_000 * 1_000_000)
    a = uuid7()
    now[0] -= 10_000 * 1_000_000               # NTP или WSL перевели часы на 10 с назад
    b = uuid7()
    assert b > a and b.int >> 80 == a.int >> 80
    now[0] += 10_001 * 1_000_000               # часы догнали генератор — время id снова по часам
    c = uuid7()
    assert c > b and c.int >> 80 == 1_800_000_000_001


def test_uuid7_counter_overflow_borrows_next_ms(monkeypatch):
    t = 1_800_000_000_000
    _freeze(monkeypatch, t * 1_000_000)        # часы стоят
    ids = [uuid7() for _ in range(5000)]       # больше 4096 за одну мс — счётчик точно переполнится
    assert ids == sorted(ids) and len(set(ids)) == 5000
    assert all(u.version == 7 for u in ids)
    assert {u.int >> 80 for u in ids} == {t, t + 1}


def test_seed_continues_after_given_id(monkeypatch):
    t = 1_800_000_000_000
    _freeze(monkeypatch, t * 1_000_000)
    later = uuid.UUID(int=((t + 5_000) << 80) | (0x7 << 76) | (7 << 64) | (0b10 << 62) | 1)   # +5 с, счётчик 7
    ids_mod.seed(later)
    nxt = uuid7()
    assert nxt > later and nxt.int >> 80 == t + 5_000 and (nxt.int >> 64) & 0xFFF == 8 and nxt.version == 7
    ids_mod.seed(uuid.UUID(int=t << 80 | 0x7 << 76 | 0b10 << 62))           # более ранний id счётчик не сдвигает
    assert uuid7() > nxt


def test_seed_at_counter_limit_moves_to_next_ms(monkeypatch):
    t = 1_800_000_000_000
    _freeze(monkeypatch, t * 1_000_000)
    ids_mod.seed(uuid.UUID(int=((t + 5_000) << 80) | (0x7 << 76) | (0xFFF << 64) | (0b10 << 62)))
    nxt = uuid7()
    assert nxt.int >> 80 == t + 5_001 and (nxt.int >> 64) & 0xFFF == 0 and nxt.version == 7


def test_seed_rejects_non_v7():
    with pytest.raises(ValueError, match="не UUIDv7"):
        ids_mod.seed(uuid.uuid4())
