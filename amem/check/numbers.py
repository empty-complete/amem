"""Числа атома и числа текста для сверки с фрагментом источника (спецификация подпроекта 3, разд. 4.5).

Сравнение точное, через Decimal: число из JSON переводится как Decimal(str(x)), так что float 0.3 равен «0,30».
Запись текста может читаться по-разному («1,200» — 1.2 или 1200, «10 200» — 10200 или 10 и 200): берутся все
прочтения, чтобы не терять верные числа. Лишние прочтения безвредны: они только расширяют множество.
"""
from __future__ import annotations

import math
import re
import unicodedata
from decimal import Decimal, InvalidOperation

_FIELDS = ("amount", "lower_bound", "upper_bound")
_SIGNS = "-−–‒"  # дефис-минус, минус, короткое и цифровое тире
_EXP = r"(?:[eE][-+−]?\d+)?"
_FRAC = r"(?:[.,]\d+)?"
# с группами разрядов: «1 200», «10 200,5»
_GROUPED = re.compile(rf"(?<!\d)(\d{{1,3}}(?: \d{{3}})+)(?!\d)({_FRAC})({_EXP})")
# без групп: каждое число по отдельности
_PLAIN = re.compile(rf"(?<!\d)(\d+)({_FRAC})({_EXP})")


def _num(x) -> Decimal | None:
    """Число JSON (не bool, не NaN/inf) как Decimal; иначе None."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return Decimal(str(x))


def _bounds(obj, path: str, cond: bool):
    if not isinstance(obj, dict):
        return
    for f in _FIELDS:
        d = _num(obj.get(f))
        if d is not None:
            yield (f"{path}.{f}", d, cond)


def atom_numbers(payload) -> list[tuple[str, Decimal, bool]]:
    """Тройки (путь, число, из_условия) тела атома: значения, уточнения, числовые ячейки таблицы."""
    out: list[tuple[str, Decimal, bool]] = []
    if not isinstance(payload, dict):
        return out
    content = payload.get("content")
    if isinstance(content, dict):
        values = content.get("values")
        for i, v in enumerate(values if isinstance(values, list) else []):
            out.extend(_bounds(v, f"content.values[{i}]", False))
            quals = v.get("qualifiers") if isinstance(v, dict) else None
            for j, q in enumerate(quals if isinstance(quals, list) else []):
                out.extend(_bounds(q, f"content.values[{i}].qualifiers[{j}]", True))
        table = content.get("table")
        rows = table.get("rows") if isinstance(table, dict) else None
        for r, row in enumerate(rows if isinstance(rows, list) else []):
            for c, cell in enumerate(row if isinstance(row, list) else []):
                d = _num(cell)
                if d is not None:
                    out.append((f"content.table.rows[{r}][{c}]", d, False))
    quals = payload.get("qualifiers")
    for k, q in enumerate(quals if isinstance(quals, list) else []):
        out.extend(_bounds(q, f"qualifiers[{k}]", True))
    return out


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    return text.replace(" ", " ").replace(" ", " ").replace(" ", " ")


def _sign_variants(text: str, start: int) -> tuple[int, ...]:
    """Знаки, с которыми читается число, начинающееся в позиции start: (1,), (-1,) или (1, -1)."""
    i = start - 1
    spaced = False
    while i >= 0 and text[i] == " ":
        i -= 1
        spaced = True
    if i < 0 or text[i] not in _SIGNS:
        return (1,)
    # знак найден; смотрим, что стоит перед ним (пробелы пропускаем)
    j = i - 1
    while j >= 0 and text[j] == " ":
        j -= 1
    after_digit = j >= 0 and text[j].isdigit()
    if spaced or after_digit:
        return (1, -1)
    return (-1,)


def _values(m: re.Match) -> list[Decimal]:
    """Прочтения одной записи: основное и, при ровно трёх цифрах после запятой или точки, «тысячи»."""
    whole = m.group(1).replace(" ", "")
    frac = m.group(2)
    exp = m.group(3).replace("−", "-")
    reads = [whole + ("." + frac[1:] if frac else "")]
    if frac and len(frac) == 4 and not exp:
        reads.append(whole + frac[1:])
    out = []
    for r in reads:
        try:
            out.append(Decimal(r + exp))
        except InvalidOperation:
            pass
    return out


def text_numbers(text: str) -> set[Decimal]:
    """Все числа текста, во всех допустимых прочтениях (разделители, пробелы-разряды, знак, экспонента)."""
    text = _normalize(text)
    found: set[Decimal] = set()
    for rx in (_GROUPED, _PLAIN):
        for m in rx.finditer(text):
            signs = _sign_variants(text, m.start())
            for v in _values(m):
                for s in signs:
                    found.add(v if s > 0 else -v)
    return found


def missing(numbers, fragments) -> list[tuple[str, Decimal, bool]]:
    """Тройки, числа которых не найдены ни в одном фрагменте; пусто, если нашлись все."""
    pool: set[Decimal] = set()
    for f in fragments:
        pool |= text_numbers(f)
    return [t for t in numbers if t[1] not in pool]
