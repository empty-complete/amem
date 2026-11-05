"""Текст xlsx и docx: страницы, числа как в ячейке, защита от DOCTYPE и больших файлов (без базы)."""
import datetime
import zipfile

import pytest

from amem import db, extract, objects, sources
from amem.ocfl_store import ObjectStore
from amem.sources import extract_pages
from samples import make_docs, make_docx, make_xlsx

AGENT = "model:claude"


@pytest.fixture
def kb(pg):
    db.prepare(pg)
    return pg


@pytest.fixture
def docs(tmp_path):
    return make_docs(tmp_path / "docs")


@pytest.fixture
def store(tmp_path):
    return ObjectStore(tmp_path / "objects")


def xlsx(tmp_path, rows, fmt=None, name="книга.xlsx"):
    return extract.xlsx_pages(make_xlsx(tmp_path / name, {"Лист": rows}, {("Лист", ref): f for ref, f in (fmt or {}).items()}))


def cells(tmp_path, value, fmt=None):
    [page] = xlsx(tmp_path, [[value]], {"A1": fmt} if fmt else None)
    return page.split("\n", 1)[1]


def test_xlsx_sheets_are_pages(tmp_path):
    pages = extract.xlsx_pages(make_xlsx(tmp_path / "a.xlsx", {"Нагрузки": [["район", "w0"], ["II", 0.3]],
                                                               "Узлы": [["КБ-14", "М10"]]}))
    assert pages == ["Нагрузки\nрайон\tw0\nII\t0.3", "Узлы\nКБ-14\tМ10"]


def test_xlsx_numbers_as_shown(tmp_path):
    assert cells(tmp_path, 0.187, "0.00") == "0.19"
    assert cells(tmp_path, 0.187) == "0.187"
    assert cells(tmp_path, 0.18700000000000003) == "0.187"
    assert cells(tmp_path, 12.0) == "12"
    assert cells(tmp_path, 12) == "12"
    assert cells(tmp_path, 0.05, "0%") == "5%"
    assert cells(tmp_path, 0.1234, "0.00%") == "12.34%"
    assert cells(tmp_path, 1234.5, "#,##0.00") == "1234.50"
    assert cells(tmp_path, 0.185, "0.00") == "0.19"
    assert cells(tmp_path, 2.6, "0") == "3"


def test_xlsx_other_values(tmp_path):
    [page] = xlsx(tmp_path, [[datetime.date(2026, 1, 31), True, "а\nб", None, "в"], [None, None], ["", "  "], ["x"]])
    assert page == "Лист\n2026-01-31\tTRUE\tа б\t\tв\nx"


def test_xlsx_formula_without_cached_value_and_hidden_sheet(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.title = "Первый"
    wb.active["A1"] = "=1+2"
    wb.active["B1"] = "текст"
    hidden = wb.create_sheet("Скрытый")
    hidden["A1"] = "тайна"
    hidden.sheet_state = "hidden"
    wb.save(tmp_path / "f.xlsx")
    assert extract.xlsx_pages(tmp_path / "f.xlsx") == ["Первый\n\tтекст", "Скрытый\nтайна"]


def test_xlsx_broken(tmp_path):
    (tmp_path / "битая.xlsx").write_bytes(b"PK\x03\x04 not a workbook")
    assert extract.xlsx_pages(tmp_path / "битая.xlsx") is None
    (tmp_path / "текст.xlsx").write_text("просто текст")
    assert extract.xlsx_pages(tmp_path / "текст.xlsx") is None
    assert extract.xlsx_pages(make_xlsx(tmp_path / "пустая.xlsx", {"Лист": []})) is None


def docx(tmp_path, blocks):
    return extract.docx_pages(make_docx(tmp_path / "д.docx", blocks))


def test_docx_body_in_order(tmp_path):
    pages = docx(tmp_path, ["Заголовок", ("table", [["Район", "w0"], ["II", "0,30"]]), "Итог\tчерез табуляцию"])
    assert pages == ["Заголовок\nРайон\tw0\nII\t0,30\nИтог\tчерез табуляцию"]


def test_docx_tracked_changes(tmp_path):
    assert docx(tmp_path, ["Один", ("del", "удалено"), ("ins", "вставлено")]) == ["Один\nвставлено"]


def test_docx_pages(tmp_path):
    assert docx(tmp_path, ["А", ("page",), "Б"]) == ["А", "Б"]
    assert docx(tmp_path, ["А", ("rendered",), "Б"]) == ["А", "Б"]
    assert docx(tmp_path, ["А", ("page",), ("rendered",), "Б"]) == ["А", "Б"]         # одна новая страница, не две
    assert docx(tmp_path, [("page",), "А"]) == ["А"]                                  # разрыв на пустой странице
    assert docx(tmp_path, ["А", "Б"]) == ["А\nБ"]


def test_docx_nothing_to_read(tmp_path):
    assert docx(tmp_path, []) is None
    assert docx(tmp_path, [("doctype",), "А"]) is None
    (tmp_path / "скан.docx").write_bytes(b"PK\x03\x04 not a real docx")
    assert extract.docx_pages(tmp_path / "скан.docx") is None
    with zipfile.ZipFile(tmp_path / "пустой.docx", "w") as zf:
        zf.writestr("readme.txt", "нет document.xml")
    assert extract.docx_pages(tmp_path / "пустой.docx") is None
    with zipfile.ZipFile(tmp_path / "кривой.docx", "w") as zf:
        zf.writestr("word/document.xml", "<w:document")
    assert extract.docx_pages(tmp_path / "кривой.docx") is None


def test_docx_limits(tmp_path, monkeypatch):
    path = make_docx(tmp_path / "д.docx", ["Небольшой текст"])
    assert extract.docx_pages(path) is not None
    monkeypatch.setattr(extract, "MAX_XML_BYTES", 100)
    assert extract.docx_pages(path) is None
    monkeypatch.undo()
    monkeypatch.setattr(extract, "MAX_TEXT_CHARS", 5)
    assert extract.docx_pages(path) is None


def test_extract_pages_dispatch(tmp_path):
    x = make_xlsx(tmp_path / "к.xlsx", {"Лист": [["a"]]})
    assert extract_pages(x) == ["Лист\na"]
    assert extract_pages(x.rename(tmp_path / "к.xlsm")) == ["Лист\na"]
    assert extract_pages(make_docx(tmp_path / "д.docx", ["Текст"])) == ["Текст"]
    for name in ("старый.doc", "слайды.pptx"):
        (tmp_path / name).write_bytes(b"PK\x03\x04")
        assert extract_pages(tmp_path / name) is None


def test_objects_text_docx_cached_by_digest(kb, docs, store, monkeypatch):
    make_docx(docs / "НД" / "д.docx", ["Первая", ("page",), "Вторая"])
    version = objects.ingest(kb, store, docs, "НД/д.docx", agent=AGENT)
    assert objects.text(kb, store, version.object_id, 1) == ["Первая", "Вторая"]
    assert kb.execute("SELECT page FROM object_text WHERE digest = %s ORDER BY page", (version.digest,)).fetchall() == [(1,), (2,)]

    def no_more(path):
        raise AssertionError("текст уже в кэше")

    monkeypatch.setattr(sources, "extract_pages", no_more)
    assert objects.text(kb, store, version.object_id, 1) == ["Первая", "Вторая"]
