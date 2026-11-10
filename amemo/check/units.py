"""Единицы UCUM: проверка кода и перевод величины (спецификация подпроекта 3, разд. 3.5).

Код проверяет грамматика UCUM из ucumvert, с учётом регистра: kPa — код, KPA и кПа — нет. Перевод идёт через
pint и нужен только уровню 3. Верный код переводится не всегда: у W/(m2.Cel) смещённая шкала внутри
произведения — convert даёт None, а код при этом верный.

Парсер и реестр pint создаются один раз на процесс, при первом обращении: каждый — доли секунды.
"""
from __future__ import annotations

import functools

from lark.exceptions import LarkError
from pint.errors import PintError
from ucumvert import PintUcumRegistry, get_ucum_parser


@functools.cache
def _parser():
    return get_ucum_parser()


@functools.cache
def _registry() -> PintUcumRegistry:
    return PintUcumRegistry()


def is_ucum(code) -> bool:
    """Строка — код UCUM по грамматике; перевод в pint здесь не проверяется."""
    if not isinstance(code, str):
        return False
    try:
        _parser().parse(code)
    except LarkError:
        return False
    return True


def convert(amount: float, unit: str, to: str) -> float | None:
    """amount в единицах unit → в единицах to; None — не код UCUM, другая размерность или смещённая шкала."""
    ureg = _registry()
    try:
        return float(ureg.Quantity(amount, ureg.from_ucum(unit)).to(ureg.from_ucum(to)).magnitude)
    except (LarkError, PintError):
        return None
