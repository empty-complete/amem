"""Идентификаторы UUIDv7 (RFC 9562, разд. 5.7): 48 бит времени Unix в мс, версия 7, 12-битный счётчик, вариант RFC, 62 случайных бита.

Счётчик — метод 1 из разд. 6.2: внутри одной миллисекунды идентификаторы растут, поэтому сортировка по id
совпадает с порядком создания. В Python 3.12 своей uuid7 нет, в PostgreSQL 16 — тоже (uuidv7() появилась в 18).
"""
from __future__ import annotations

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = 0
_seq = 0


def uuid7() -> uuid.UUID:
    global _last_ms, _seq
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms > _last_ms:
            _last_ms = ms
            _seq = int.from_bytes(os.urandom(2), "big") & 0x3FF   # старт в нижней четверти: запас на рост
        else:
            _seq += 1
            if _seq > 0xFFF:            # счётчик кончился — занимаем следующую миллисекунду
                _last_ms += 1
                _seq = 0
        ms, seq = _last_ms, _seq
    rand = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    return uuid.UUID(int=(ms << 80) | (0x7 << 76) | (seq << 64) | (0b10 << 62) | rand)


def seed(last: uuid.UUID) -> None:
    """Продолжить счётчик после уже выданного id — при старте сервера это самый поздний id в базе.

    Принимает только UUIDv7, какие выдаёт uuid7(): чужой id со временем из далёкого будущего навсегда сдвинул бы
    счётчик, а предельный сделал бы новые id невозможными. Более ранний id счётчик не двигает.
    Без seed после перезапуска с часами, ушедшими назад (WSL2 после сна), новые id оказались бы меньше
    уже записанных."""
    if last.version != 7 or last.variant != uuid.RFC_4122:
        raise ValueError(f"seed: не UUIDv7: {last}")
    global _last_ms, _seq
    ms, seq = last.int >> 80, (last.int >> 64) & 0xFFF
    with _lock:
        if (ms, seq) > (_last_ms, _seq):
            _last_ms, _seq = ms, seq
