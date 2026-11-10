"""Тестовые документы: условный норматив (PDF), «скан» протокола (PDF из картинок) и заметка (.md)."""
import os
from pathlib import Path

import pymupdf
import pytest

from amemo import sources

# Страницы норматива: оглавление; пункт, таблица вразрядку с переносом, формула; приложение.
SP_PAGES = [
    "<p>СП 99.13330 Нагрузки и воздействия. Содержание</p>"
    "<p>Таблица 1.1 ........ 2</p><p>Приложение А ........ 3</p>"
    "<p>Значения принимают по таблице 1.1 с учётом района.</p>",
    "<p>1.2.3 Нормативное значение ветрового давления принимают</p>"
    "<p>Т а б л и ц а 1 .1 – Расчётное значение ветро-<br>вого давления</p>"
    "<p>Ветровой район II: w0 = 0,30 кПа</p>"
    "<p>w = w0 k c (1.1)</p>",
    "<p>ПРИЛОЖЕНИЕ А</p>"
    "<p>Самара относится ко II ветровому району по карте.</p>"
    "<p>1.4 соответственно для промежуточных значений.</p>",
]

# Страницы «скана» протокола испытаний: крупный шрифт, чтобы OCR читал уверенно.
SCAN_PAGES = [
    "<p style='font-size:18pt'>ПРОТОКОЛ ИСПЫТАНИЙ № 12</p>"
    "<p style='font-size:18pt'>Образец: стеклопакет двухкамерный, формула 4-16-4-16-4.</p>",
    "<p style='font-size:18pt'>Результаты испытаний</p>"
    "<p style='font-size:18pt'>Сопротивление теплопередаче образца составило 0,72 единицы.</p>"
    "<p style='font-size:18pt'>Температура наружного воздуха минус 20 градусов.</p>",
]
SCAN_QUOTE = "Сопротивление теплопередаче образца составило 0,72"
# OCR в тестах: без языковых данных tesseract (rus, eng) тесты пропускаются — но не в CI, где они должны быть
needs_ocr = pytest.mark.skipif(sources.ocr_languages() is None and not os.environ.get("CI"),
                               reason="нет языковых данных tesseract (rus, eng)")

NOTE_MD = "# Узел крепления\n\n## Кронштейн\n\nКронштейн КБ-14 крепится к закладной анкером М10.\n"
# Заметка с величинами для тестов basis и confidence: по фразе на строку, раздел — тот же «Кронштейн».
VALUES_MD = "# Величины\n\n## Кронштейн\n\nМасса 3 кг.\n\nМасса 4 кг.\n\nТемпература 20 °C.\n"


def make_pdf(path: Path, pages: list[str]) -> Path:
    """PDF с кириллицей: каждый элемент — HTML одной страницы; пустая строка — пустая страница."""
    doc = pymupdf.open()
    for html in pages:
        page = doc.new_page()
        if html:
            page.insert_htmlbox(pymupdf.Rect(40, 40, 560, 800), html)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


def make_scanned_pdf(path: Path, pages: list[str], *, text_pages: tuple[int, ...] = (), dpi: int = 200) -> Path:
    """«Скан»: каждая страница — картинка с отрисованным HTML, без текстового слоя; страницы с номерами (с 0)
    из text_pages — обычные, с текстовым слоем; пустая строка — пустая страница без картинки."""
    doc, draft = pymupdf.open(), pymupdf.open()
    for i, html in enumerate(pages):
        page = doc.new_page()
        if html and i in text_pages:
            page.insert_htmlbox(pymupdf.Rect(40, 40, 560, 800), html)
        elif html:
            render = draft.new_page()
            render.insert_htmlbox(pymupdf.Rect(40, 40, 560, 800), html)
            page.insert_image(page.rect, pixmap=render.get_pixmap(dpi=dpi))
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


def make_docs(root: Path) -> Path:
    """Папка документов: норматив PDF, заметки .md, «документ» .docx без извлекаемого текста."""
    make_pdf(root / "НД" / "СП 99.pdf", SP_PAGES)
    (root / "Заметки").mkdir(parents=True, exist_ok=True)
    (root / "Заметки" / "узел.md").write_text(NOTE_MD, encoding="utf-8")
    (root / "заметка.md").write_text(VALUES_MD, encoding="utf-8")
    (root / "НД" / "скан.docx").write_bytes(b"PK\x03\x04 not a real docx")
    return root


def make_xlsx(path: Path, sheets: dict[str, list[list]], formats: dict | None = None) -> Path:
    """Книга xlsx: имя листа → строки значений; formats — number_format ячеек, {(лист, "B2"): "0.00"}."""
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    for (sheet, ref), fmt in (formats or {}).items():
        wb[sheet][ref].number_format = fmt
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _runs(text: str) -> str:
    """Текст с \\t как w:tab: «а\\tб» → два w:t и w:tab между ними."""
    return "<w:tab/>".join(f"<w:t xml:space=\"preserve\">{_esc(part)}</w:t>" for part in text.split("\t"))


def _docx_body(blocks: list) -> str:
    out: list[str] = []
    rendered = False                                 # ("rendered",) — метка в начале следующего абзаца
    for block in blocks:
        if isinstance(block, str):
            mark = "<w:r><w:lastRenderedPageBreak/></w:r>" if rendered else ""
            rendered = False
            out.append(f"<w:p>{mark}<w:r>{_runs(block)}</w:r></w:p>")
            continue
        kind = block[0]
        if kind == "table":
            rows = "".join("<w:tr>" + "".join(f"<w:tc><w:p><w:r>{_runs(c)}</w:r></w:p></w:tc>" for c in row) + "</w:tr>"
                           for row in block[1])
            out.append(f"<w:tbl><w:tblPr/>{rows}</w:tbl>")
        elif kind == "page":
            out.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        elif kind == "rendered":
            rendered = True
        elif kind == "del":
            out.append(f"<w:p><w:del><w:r><w:delText>{_esc(block[1])}</w:delText></w:r></w:del></w:p>")
        elif kind == "ins":
            out.append(f"<w:p><w:ins><w:r>{_runs(block[1])}</w:r></w:ins></w:p>")
        elif kind == "doctype":
            pass                                     # обрабатывается в make_docx
        else:
            raise ValueError(f"неизвестный блок {kind!r}")
    return "".join(out)


def make_docx(path: Path, blocks: list) -> Path:
    """Минимальный docx: абзацы, таблицы, разрывы страниц, правки; ("doctype",) — DOCTYPE в начале XML."""
    import zipfile

    doctype = '<!DOCTYPE w:document [<!ENTITY e "x">]>' if ("doctype",) in blocks else ""
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>{doctype}'
                f'<w:document xmlns:w="{_W}"><w:body>{_docx_body(blocks)}</w:body></w:document>')
    content_types = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
                     'content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
                     'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/'
                     'document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.'
                     'main+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
            'relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document)
    return path
