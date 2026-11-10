"""Числа атома и текста (amemo.check.numbers), без базы."""
from decimal import Decimal as D

import pytest

from amemo.check.numbers import atom_numbers, missing, text_numbers


def test_atom_numbers_paths_and_condition_flag():
    payload = {
        "content": {
            "values": [
                {
                    "amount": 1.5,
                    "lower_bound": 1,
                    "qualifiers": [
                        {"amount": 7},
                        {"upper_bound": 0.3},
                    ],
                }
            ],
            "table": {"rows": [["a", 1], [2, 3], [4, 0.5, True]]},
        },
        "qualifiers": [{"amount": 20}],
    }
    got = atom_numbers(payload)
    assert ("content.values[0].amount", D("1.5"), False) in got
    assert ("content.values[0].lower_bound", D("1"), False) in got
    assert ("content.values[0].qualifiers[0].amount", D("7"), True) in got
    assert ("content.values[0].qualifiers[1].upper_bound", D("0.3"), True) in got
    assert ("qualifiers[0].amount", D("20"), True) in got
    assert ("content.table.rows[1][0]", D("2"), False) in got
    assert ("content.table.rows[2][1]", D("0.5"), False) in got
    assert not any(p == "content.table.rows[2][2]" for p, _, _ in got)  # True — не число


def test_atom_numbers_skips_strings_formulas_and_bad_shapes():
    payload = {"content": {"table": {"rows": [["0,5", {"formula": "=A1+1"}, "=B2", None, 4]]}}}
    assert atom_numbers(payload) == [("content.table.rows[0][4]", D("4"), False)]
    assert atom_numbers({}) == []
    assert atom_numbers({"content": {"values": "x", "table": []}, "qualifiers": 5}) == []


@pytest.mark.parametrize("text", ["0,17", "0.17", "k 0,17 m"])
def test_decimal_separators(text):
    assert D("0.17") in text_numbers(text)


@pytest.mark.parametrize("text", ["1 200", "1 200", "1 200", "1 200"])
def test_digit_groups(text):
    assert D("1200") in text_numbers(text)


@pytest.mark.parametrize("text", ["−5", "-5", "–5", "t = -5", "(−5)", "x (–5 °C)"])
def test_negative_flush_after_non_digit(text):
    got = text_numbers(text)
    assert D("-5") in got and D("5") not in got


@pytest.mark.parametrize("text", ["5–10", "5 – 10", "5-10"])
def test_range_dash_gives_both(text):
    got = text_numbers(text)
    assert {D("5"), D("10"), D("-10")} <= got


def test_spaced_dash_gives_both():
    got = text_numbers("– 10")
    assert D("10") in got and D("-10") in got


def test_ambiguous_separator_and_spaces():
    assert {D("1.2"), D("1200")} <= text_numbers("1,200")
    assert {D("1.2"), D("1200")} <= text_numbers("1.200")
    assert {D("10200"), D("10"), D("200")} <= text_numbers("10 200")
    assert D("1.25") in text_numbers("1,25") and D("125") not in text_numbers("1,25")


def test_exponent_and_percent():
    assert D("0.0015") in text_numbers("1,5e-3")
    assert D("0.0015") in text_numbers("1,5E−3")
    assert D("12") in text_numbers("12%")


def test_missing():
    nums = [("a", D("0.3"), False), ("b", D("42"), True), ("c", D("7"), False)]
    assert missing(nums[:1], ["значение 0,30 Вт"]) == []
    assert missing(nums, ["0,30", "x 42"]) == [nums[2]]
    assert missing(nums, []) == nums
    assert missing([("a", D(str(0.3)), False)], ["0,30"]) == []


@pytest.mark.parametrize("text", ["5\n–10", "5\t–10", "5 –\n10", "5\n– 10"])
def test_range_dash_across_any_whitespace(text):
    assert {D("5"), D("10"), D("-10")} <= text_numbers(text)


def test_spaced_dash_after_newline_gives_both():
    got = text_numbers("слово\n–\n10")
    assert D("10") in got and D("-10") in got


def test_digit_groups_only_with_plain_spaces():
    assert D("1200") not in text_numbers("1\n200")
    assert {D("1"), D("200")} <= text_numbers("1\n200")


def test_no_thousands_reading_with_exponent():
    got = text_numbers("1,200e2")
    assert D("120") in got and D("1200") not in got and D("120000") not in got


def test_date_and_letter_prefixed_number_do_not_fail():
    assert D("31.01") in text_numbers("31.01.2026")
    assert D("2026") in text_numbers("31.01.2026")
    assert D("10") in text_numbers("болт м10")


def test_groups_with_fraction_and_two_groups():
    assert D("1200300") in text_numbers("1 200 300")
    assert D("10200.5") in text_numbers("10 200,5")


def test_minus_zero():
    assert D("0") in text_numbers("−0")
