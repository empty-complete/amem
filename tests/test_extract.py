"""Текст xlsx, docx и pptx: страницы, числа как в ячейке, защита от DOCTYPE и больших файлов (без базы)."""
import datetime
import zipfile

import pytest

from amemo import db, extract, objects, sources
from amemo.sources import extract_pages
from samples import make_docs, make_docx, make_xlsx

AGENT = "model:claude"


@pytest.fixture
def kb(pg):
    db.prepare(pg)
    return pg


@pytest.fixture
def docs(tmp_path):
    return make_docs(tmp_path / "docs")


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


def _docx_with_xml(path, xml: bytes):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", xml)
    return path


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def test_docx_doctype_cannot_be_hidden(tmp_path):
    body = f'<w:document xmlns:w="{W_NS}"><w:body><w:p><w:r><w:t>&e;</w:t></w:r></w:p></w:body></w:document>'
    dtd = '<!DOCTYPE w:document [<!ENTITY e "x">]>'
    late = "<!--" + "а" * 5000 + "-->" + dtd + body                                  # после комментария больше 4 КиБ
    assert extract.docx_pages(_docx_with_xml(tmp_path / "1.docx", ("<?xml version='1.0'?>" + late).encode())) is None
    utf16 = ("<?xml version='1.0' encoding='UTF-16'?>" + dtd + body).encode("utf-16")
    assert extract.docx_pages(_docx_with_xml(tmp_path / "2.docx", utf16)) is None


def test_docx_extra_elements(tmp_path):
    xml = (f'<w:document xmlns:w="{W_NS}" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"><w:body>'
           '<w:p><w:r><w:t>а</w:t><w:cr/><w:t>б</w:t><w:noBreakHyphen/><w:t>в</w:t></w:r></w:p>'
           '<w:p><w:moveFrom><w:r><w:t>старое место</w:t></w:r></w:moveFrom><w:moveTo><w:r><w:t>новое</w:t></w:r></w:moveTo></w:p>'
           '<w:p><mc:AlternateContent><mc:Choice><w:r><w:t>выбор</w:t></w:r></mc:Choice>'
           '<mc:Fallback><w:r><w:t>запасной</w:t></w:r></mc:Fallback></mc:AlternateContent></w:p>'
           '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>внешняя</w:t></w:r></w:p>'
           '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>вложенная</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>2</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
           '</w:tc><w:tc><w:p><w:r><w:t>соседка</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
           '</w:body></w:document>')
    pages = extract.docx_pages(_docx_with_xml(tmp_path / "x.docx", xml.encode()))
    assert pages == ["а\nб-в\nновое\nвыбор\nвнешняя вложенная\t2\t\tсоседка"]


def test_xlsx_cell_and_text_limits(tmp_path, monkeypatch):
    path = make_xlsx(tmp_path / "к.xlsx", {"Лист": [["a", "b"], [], ["c", "d"]]})
    assert extract.xlsx_pages(path) is not None
    monkeypatch.setattr(extract, "MAX_CELLS", 3)
    assert extract.xlsx_pages(path) is None
    monkeypatch.undo()
    monkeypatch.setattr(extract, "MAX_TEXT_CHARS", 3)
    assert extract.xlsx_pages(path) is None


def make_pptx(path, slides, order=None):
    """Минимальный pptx: slides — список слайдов, слайд — список абзацев (строка или список прогонов, «\\n» — a:br);
    order — порядок показа по номерам частей slideN.xml (по умолчанию как есть)."""
    ns = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
          'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')

    def para(x):
        runs = x if isinstance(x, list) else [x]
        return "<a:p>" + "".join("<a:br/>" if r == "\n" else f"<a:r><a:t>{r}</a:t></a:r>" for r in runs) + "</a:p>"

    order = order or list(range(1, len(slides) + 1))
    with zipfile.ZipFile(path, "w") as zf:
        ids = "".join(f'<p:sldId id="{255 + i}" r:id="rId{n}"/>' for i, n in enumerate(order, 1))
        zf.writestr("ppt/presentation.xml", f"<p:presentation {ns}><p:sldIdLst>{ids}</p:sldIdLst></p:presentation>")
        rels = "".join(f'<Relationship Id="rId{n}" Target="slides/slide{n}.xml"/>' for n in order)
        zf.writestr("ppt/_rels/presentation.xml.rels",
                    f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}'
                    "</Relationships>")
        for n, paras in enumerate(slides, 1):
            body = "".join(para(x) for x in paras)
            zf.writestr(f"ppt/slides/slide{n}.xml",
                        f"<p:sld {ns}><p:cSld><p:spTree><p:sp><p:txBody>{body}</p:txBody></p:sp>"
                        "</p:spTree></p:cSld></p:sld>")
    return path


def test_pptx_slides_in_show_order(tmp_path):
    f = make_pptx(tmp_path / "п.pptx", [["Первый", ["Нагрузка ", "0,3 кПа"]], ["Второй", ["строка", "\n", "ниже"]]],
                  order=[2, 1])
    assert extract.pptx_pages(f) == ["Второй\nстрока\nниже", "Первый\nНагрузка 0,3 кПа"]
    assert extract_pages(f) == extract.pptx_pages(f)


def test_pptx_nothing_to_read(tmp_path):
    assert extract.pptx_pages(make_pptx(tmp_path / "пусто.pptx", [[], []])) is None
    (tmp_path / "битая.pptx").write_bytes(b"PK\x03\x04 not a deck")
    assert extract.pptx_pages(tmp_path / "битая.pptx") is None
    with zipfile.ZipFile(tmp_path / "без.pptx", "w") as zf:
        zf.writestr("ppt/presentation.xml", "<!DOCTYPE p [<!ENTITY e 'x'>]><p/>")
    assert extract.pptx_pages(tmp_path / "без.pptx") is None
