"""Текст xlsx, docx и pptx по страницам: лист книги, страница Word или слайд — одна «страница».

Модуль не знает о базе. None — текста нет: файл битый, зашифрован, пуст или превышает пределы
(подрезанный текст дал бы ложное «цитата не найдена»)."""
from __future__ import annotations

import posixpath
import re
import zipfile
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from xml.etree import ElementTree

MAX_XML_BYTES = 64 * 2**20           # распакованный word/document.xml: ElementTree строит всё дерево в памяти
MAX_TEXT_CHARS = 50_000_000
MAX_CELLS = 5_000_000                # обойдённых ячеек xlsx, пустые тоже
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"

_SKIP = {W + t for t in ("del", "moveFrom", "delText", "instrText", "pPr", "rPr", "tblPr", "trPr", "tcPr", "sectPr")} | {_MC_FALLBACK}
_NUMBER = re.compile(r"[#0?,]*0(?:\.([0#]+))?")
_FORMAT_NOISE = re.compile(r'"[^"]*"|\[[^\]]*\]|\\.|_.|\*.')

_BAD_FILE = (zipfile.BadZipFile, KeyError, ElementTree.ParseError, ValueError, NotImplementedError, RuntimeError,
             RecursionError, MemoryError)


class _NoDoctype(ElementTree.TreeBuilder):
    """Любое объявление DOCTYPE (а с ним и сущностей) отвергается при разборе, в любой кодировке и после комментариев."""

    def doctype(self, name, pubid, system):
        raise ValueError("DOCTYPE в XML")


def _round(x: float, decimals: int) -> Decimal:
    """Округление, как в Excel: половина — от нуля, по десятичной записи числа, а не по двоичной."""
    return Decimal(repr(x)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


def _cell_text(value, number_format: str) -> str:
    """Значение ячейки так, как его показывает Excel (разд. 9.1 спецификации)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time() else value.isoformat(sep=" ")
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, (int, float)):
        return _number_text(value, number_format or "")
    return re.sub(r"\s*[\r\n]+\s*", " ", str(value)).replace("\t", " ")


def _number_text(x: int | float, number_format: str) -> str:
    # Разделитель тысяч (#,##0.00) намеренно не ставится: в документах он разный (пробел, запятая, неразрывный пробел).
    section = _FORMAT_NOISE.sub("", number_format.split(";")[0])
    m = _NUMBER.search(section)
    if m and "E" not in section.upper().replace("\\", "") and x == x and abs(x) != float("inf"):
        frac = m.group(1) or ""
        percent = "%" in section
        d = _round(x, 15) if isinstance(x, int) else Decimal(repr(x))
        if percent:
            d *= 100
        q = d.quantize(Decimal(1).scaleb(-len(frac)), rounding=ROUND_HALF_UP)
        text = f"{q:f}"
        if "." in text:                                 # «#» после запятой — необязательные знаки
            keep = frac.count("0")
            whole, _, digits = text.partition(".")
            while len(digits) > keep and digits.endswith("0"):
                digits = digits[:-1]
            text = f"{whole}.{digits}" if digits else whole
        return text + ("%" if percent else "")
    if isinstance(x, int):
        return str(x)
    if x == x and abs(x) < 1e15 and x == int(x):
        return str(int(x))
    return format(x, ".15g")


def xlsx_pages(file: Path) -> list[str] | None:
    """Каждый лист (и скрытый) — страница: имя листа, затем строки с ячейками через табуляцию."""
    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException

    try:
        wb = load_workbook(file, read_only=True, data_only=True)
    except (InvalidFileException, *_BAD_FILE):
        return None
    pages: list[str] = []
    total = 0
    has_text = False
    cell_count = 0
    try:
        for ws in wb.worksheets:
            ws.reset_dimensions()                       # заявленный размер листа в файле бывает неверным
            lines = [ws.title]
            for row in ws.iter_rows():
                cell_count += len(row) or 1
                if cell_count > MAX_CELLS:
                    return None
                cells = [_cell_text(c.value, getattr(c, "number_format", "")) for c in row]
                line = "\t".join(cells).rstrip("\t")
                if line.strip():
                    lines.append(line)
                    total += len(line) + 1
                    has_text = True
                if total > MAX_TEXT_CHARS:
                    return None
            pages.append("\n".join(lines))
    except (InvalidFileException, *_BAD_FILE):
        return None
    finally:
        wb.close()
    return pages if has_text else None


def _read_limited(zf: zipfile.ZipFile, name: str) -> bytes | None:
    """Распакованное содержимое; больше предела — None. Размер из ZipInfo не годится: его задаёт сам файл."""
    chunks: list[bytes] = []
    size = 0
    with zf.open(name) as f:
        while block := f.read(1 << 20):
            size += len(block)
            if size > MAX_XML_BYTES:
                return None
            chunks.append(block)
    return b"".join(chunks)


class _Pages:
    """Сборка страниц из потока событий обхода: текст, конец абзаца, ячейки, строки, разрывы."""

    def __init__(self) -> None:
        self.pages: list[list[str]] = [[]]
        self.line: list[str] = []
        self.in_cell = 0
        self.chars = 0

    def _page_has_text(self) -> bool:
        return any(s.strip() for s in self.line) or any(l.strip() for l in self.pages[-1])

    def text(self, s: str) -> None:
        self.line.append(s)
        self.chars += len(s)

    def end_line(self) -> None:
        line = "".join(self.line).rstrip(" \t")
        self.line = []
        if line.strip():
            self.pages[-1].append(line)

    def end_paragraph(self) -> None:
        if not self.in_cell:
            self.end_line()
        elif self.line and not "".join(self.line).endswith(("\t", " ")):
            self.text(" ")                              # абзацы ячейки — через пробел

    def page_break(self) -> None:
        if self._page_has_text():                       # разрыв на ещё пустой странице новой не начинает
            self.end_line()
            self.pages.append([])

    def result(self) -> list[str] | None:
        self.end_line()
        pages = ["\n".join(p) for p in self.pages if p]
        return pages or None


def _walk(el: ElementTree.Element, out: _Pages) -> None:
    for child in el:
        tag = child.tag
        if tag in _SKIP:
            continue
        if tag == W + "t":
            out.text(child.text or "")
        elif tag == W + "tab":
            out.text("\t")
        elif tag == W + "noBreakHyphen":
            out.text("-")
        elif tag == W + "cr":
            out.end_paragraph()
        elif tag == W + "br":
            kind = child.get(W + "type")
            if kind == "page":
                out.page_break()
            elif kind != "column":
                out.end_paragraph()
        elif tag == W + "lastRenderedPageBreak":
            out.page_break()
        elif tag == W + "p":
            _walk(child, out)
            out.end_paragraph()
        elif tag == W + "tc":
            out.in_cell += 1
            _walk(child, out)
            out.in_cell -= 1
            out.line = ["".join(out.line).rstrip(" "), "\t"]
        elif tag == W + "tr":
            _walk(child, out)
            if not out.in_cell:                         # строка вложенной таблицы остаётся в строке внешней
                out.end_line()
        else:
            _walk(child, out)
        if out.chars > MAX_TEXT_CHARS:
            raise ValueError("текст больше предела")


def docx_pages(file: Path) -> list[str] | None:
    """Страница Word — страница: новая начинается на ручном разрыве и на метке Word lastRenderedPageBreak."""
    try:
        with zipfile.ZipFile(file) as zf:
            data = _read_limited(zf, "word/document.xml")
        if data is None:
            return None
        parser = ElementTree.XMLParser(target=_NoDoctype())
        parser.feed(data)
        root = parser.close()
        out = _Pages()
        _walk(root, out)
        return out.result()
    except _BAD_FILE:
        return None


def _xml(zf: zipfile.ZipFile, name: str) -> ElementTree.Element:
    """Часть пакета Office деревом: без DOCTYPE и не больше MAX_XML_BYTES (иначе ValueError)."""
    data = _read_limited(zf, name)
    if data is None:
        raise ValueError(f"{name}: больше предела")
    parser = ElementTree.XMLParser(target=_NoDoctype())
    parser.feed(data)
    return parser.close()


def _slide_order(zf: zipfile.ZipFile) -> list[str]:
    """Части слайдов в порядке показа: список sldIdLst в presentation.xml и его связи, а не имена slideN.xml."""
    pres = _xml(zf, "ppt/presentation.xml")
    rels = _xml(zf, "ppt/_rels/presentation.xml.rels")
    target = {r.get("Id"): r.get("Target", "") for r in rels.iter(REL + "Relationship")}
    order = []
    for sid in pres.iter(P + "sldId"):
        t = target.get(sid.get(R + "id"), "")
        if t:
            order.append(posixpath.normpath(t.lstrip("/") if t.startswith("/") else posixpath.join("ppt", t)))
    return order


def _paragraph(p: ElementTree.Element) -> str:
    """Абзац DrawingML: текст прогонов и полей, разрыв строки — перевод строки."""
    parts = []
    for el in p.iter():
        if el.tag == A + "t":
            parts.append(el.text or "")
        elif el.tag == A + "br":
            parts.append("\n")
    return "".join(parts).strip()


def pptx_pages(file: Path) -> list[str] | None:
    """Слайд — страница, в порядке показа (скрытые тоже: номер слайда их считает): текст фигур, групп и таблиц
    по абзацам; заметки докладчика не входят. Нет слайдов или текста — None."""
    try:
        with zipfile.ZipFile(file) as zf:
            pages, chars = [], 0
            for name in _slide_order(zf):
                text = "\n".join(line for line in (_paragraph(p) for p in _xml(zf, name).iter(A + "p")) if line)
                chars += len(text)
                if chars > MAX_TEXT_CHARS:
                    raise ValueError("текст больше предела")
                pages.append(text)
        return pages if any(pages) else None
    except _BAD_FILE:
        return None
