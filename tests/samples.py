"""Тестовые документы: условный норматив (PDF) и заметка (.md)."""
from pathlib import Path

import pymupdf

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

NOTE_MD = "# Узел крепления\n\n## Кронштейн\n\nКронштейн КБ-14 крепится к закладной анкером М10.\n"


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


def make_docs(root: Path) -> Path:
    """Папка документов: норматив PDF, заметка .md, «документ» .docx без извлекаемого текста."""
    make_pdf(root / "НД" / "СП 99.pdf", SP_PAGES)
    (root / "Заметки").mkdir(parents=True, exist_ok=True)
    (root / "Заметки" / "узел.md").write_text(NOTE_MD, encoding="utf-8")
    (root / "НД" / "скан.docx").write_bytes(b"PK\x03\x04 not a real docx")
    return root
