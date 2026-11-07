"""Метка <private> (спецификация подпроекта 4, разд. 6.4): скрытое вырезается до поиска, журнала и записи.

strip(text) убирает всё между <private> и </private> вместе с метками. Незакрытая метка скрывает текст до конца:
лучше потерять хвост, чем записать то, что человек просил не сохранять. Метки — без учёта регистра, с пробелами
и переводами строк внутри угловых скобок («< private >», «</ private >»): набранная небрежно метка тоже скрывает.
Вложенная <private> не закрывается первой же </private>, поэтому скрытое внутри неё тоже не выходит наружу.
Одиночная </private> без открывающей — обычный текст.
"""
from __future__ import annotations

import re

# захватывающие квантификаторы (*+, Python 3.11+): пробелы после «<» не перебираются заново, и «<» с длинным
# хвостом пробелов или переводов строк разбирается за линейное время, а не за квадратичное
_TAG = re.compile(r"<\s*+(/?)\s*+private\s*+>", re.IGNORECASE)


def strip(text: str) -> str:
    """Текст без частей в <private>…</private>; остальное — как было, пробелы вокруг не сжимаются."""
    if not isinstance(text, str):
        raise TypeError(f"private.strip: нужна строка, получено {type(text).__name__}")
    kept, depth, start = [], 0, 0
    for tag in _TAG.finditer(text):
        closing = tag.group(1) == "/"
        if depth == 0:
            if closing:
                continue                      # закрывающая без открывающей — часть текста
            kept.append(text[start:tag.start()])
            depth = 1
        elif closing:
            depth -= 1
            if depth == 0:
                start = tag.end()
        else:
            depth += 1
    if depth == 0:
        kept.append(text[start:])
    return "".join(kept)
