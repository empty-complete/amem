"""Автопроверка записей перед записью в базу: уровни 1–4 (схема и шаблон, привязка к источнику, здравый смысл,
дубли), отчёт, действующие шаблоны, числа и единицы.

Устройство и правила — docs/superpowers/specs/2026-11-05-amem-subproject-3-autocheck-design.md.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal


@dataclass
class Proposal:
    """Предложенная ревизия: новая запись, если record_id нет, иначе новая ревизия существующей.
    Статус агент не предлагает: его ставит автопроверка."""
    target: Literal["atom", "entity"]
    payload: dict
    record_id: uuid.UUID | str | None = None
