"""Единицы UCUM: проверка кода с учётом регистра и перевод величины (разд. 3.5 спецификации подпроекта 3).
База не нужна."""
import pytest

from amem.check import units


@pytest.mark.parametrize("code", ["kPa", "W/(m2.K)", "W/(m2.Cel)", "Cel", "1", "%", "mm", "kg/m3", "Pa.s", "[degF]"])
def test_ucum_codes_accepted(code):
    assert units.is_ucum(code) is True


@pytest.mark.parametrize("code", ["кПа", "KPA", "m/s/", "", " kPa", None, 5])
def test_not_ucum_rejected(code):
    assert units.is_ucum(code) is False


def test_convert_scales_and_offsets():
    assert units.convert(0.38, "kPa", "Pa") == pytest.approx(380, abs=1e-9)
    assert units.convert(20, "Cel", "K") == pytest.approx(293.15, abs=1e-9)
    assert units.convert(5, "%", "1") == pytest.approx(0.05, abs=1e-12)
    assert isinstance(units.convert(1, "m", "mm"), float)


@pytest.mark.parametrize("unit, to", [
    ("m", "kg"),                       # разные размерности
    ("W/(m2.Cel)", "W/(m2.K)"),        # смещённая шкала внутри произведения: код верный, перевода нет
    ("кПа", "Pa"),                     # не код UCUM
    ("kPa", "KPA"),
])
def test_convert_impossible_gives_none(unit, to):
    assert units.convert(1, unit, to) is None


def test_parser_and_registry_created_once():
    units.is_ucum("kPa")
    units.convert(1, "m", "mm")
    assert units._parser() is units._parser() and units._registry() is units._registry()
