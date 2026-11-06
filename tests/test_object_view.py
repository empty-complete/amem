"""Карточка объекта (lookup.object_view) и окно листа xlsx (objects.sheet) — разд. 1.2 спецификации подпроекта 4."""
import datetime

import pytest

from amem import db, lookup, objects
from amem.objects import ObjectError
from amem.ocfl_store import ObjectStore
from amem.records import Item, commit
from samples import make_xlsx

AGENT = "model:tester"
PDF = "НД/СП 99.pdf"
XLSX = "Таблицы/нагрузки.xlsx"


@pytest.fixture
def kb(pg):
    db.prepare(pg)
    return pg


@pytest.fixture
def store(tmp_path):
    return ObjectStore(tmp_path / "objects")


@pytest.fixture
def book(docs, kb, store):
    make_xlsx(docs / XLSX, {"Сводка": [["Итог"]],
                            "Нагрузки": [["Район", "w0, кПа", "Дата"], ["II", 0.3, datetime.date(2024, 5, 1)],
                                         ["III", 0.38, None]]},
              formats={("Нагрузки", "B2"): "0.00"})
    return objects.ingest(kb, store, docs, XLSX, agent=AGENT)


def fact(docs, kb, store, path, **source):
    body = {"ref": "@f", "kind": "fact", "label": {"ru": "Давление ветра для района II"},
            "sources": [{"path": path, **source}]}
    body = objects.resolve_sources(kb, store, docs, body, agent=AGENT)
    return commit(kb, [Item("atom", body)], agent=AGENT).revisions[0].record_id


def test_view_unknown_object(kb):
    assert lookup.object_view(kb, "obj:00000000-0000-7000-8000-000000000000") is None


def test_view_cited_by_current_revisions(kb, docs, store):
    v = objects.ingest(kb, store, docs, PDF, agent=AGENT)
    sel = [{"type": "page", "value": "2"}]
    rid = fact(docs, kb, store, PDF, selectors=sel, quote="Таблица 1")
    body = {"kind": "fact", "label": {"ru": "Давление ветра для района II, ред. 2"},
            "sources": [{"path": PDF, "quote": "Таблица 1"}]}
    commit(kb, [Item("atom", objects.resolve_sources(kb, store, docs, body, agent=AGENT), record_id=rid)], agent=AGENT)
    view = lookup.object_view(kb, v.ref)
    assert view["id"] == str(v.object_id) and view["kind"] == "file"
    # первая ревизия уже не текущая: цитата только из второй
    assert view["cited_by"] == [{"record": f"atm:{rid}", "version": 1, "quote": "Таблица 1"}]
    assert objects.mark(kb, v.object_id, "parsed", agent=AGENT) is None
    assert lookup.object_view(kb, v.object_id)["status"] == "parsed"


def test_view_citation_fields(kb, docs, store):
    v = objects.ingest(kb, store, docs, PDF, agent=AGENT)
    sel = [{"type": "page", "value": "2"}]
    rid = fact(docs, kb, store, PDF, selectors=sel, quote="Таблица 1")
    kb.execute("UPDATE source SET verdict = 'ok', checked_at = now()")
    [c] = lookup.object_view(kb, v.object_id)["cited_by"]
    assert c == {"record": f"atm:{rid}", "version": 1, "selectors": sel, "quote": "Таблица 1", "verdict": "ok"}


def test_view_without_status_and_citations(kb, docs, store):
    v = objects.ingest(kb, store, docs, PDF, agent=AGENT)
    view = lookup.object_view(kb, v.object_id)
    assert (view["status"], view["cited_by"], view["pages"], view["sheets"]) == (None, [], None, None)


def test_view_pages_from_cache_only(kb, docs, store):
    v = objects.ingest(kb, store, docs, PDF, agent=AGENT)
    assert lookup.object_view(kb, v.object_id)["pages"] is None        # чтение карточки текст не извлекает
    assert kb.execute("SELECT count(*) FROM object_text").fetchone()[0] == 0
    pages = objects.text(kb, store, v.object_id, 1)
    view = lookup.object_view(kb, v.object_id)
    assert view["pages"] == len(pages) and view["sheets"] is None


def test_view_no_text_is_none(kb, docs, store):
    v = objects.ingest(kb, store, docs, "НД/скан.docx", agent=AGENT)
    assert objects.text(kb, store, v.object_id, 1) is None
    assert lookup.object_view(kb, v.object_id)["pages"] is None


def test_view_sheets_of_xlsx(kb, store, book):
    assert lookup.object_view(kb, book.object_id)["sheets"] is None    # текст ещё не извлекали
    objects.text(kb, store, book.object_id, 1)
    view = lookup.object_view(kb, book.object_id)
    assert (view["pages"], view["sheets"]) == (2, ["Сводка", "Нагрузки"])


def test_sheet_range(kb, store, book):
    got = objects.sheet(kb, store, book.object_id, 1, "Нагрузки", "B2:C3")
    assert got == {"name": "Нагрузки", "range": "B2:C3", "rows": [["0.30", "2024-05-01"], ["0.38", ""]]}


def test_sheet_values_match_extracted_text(kb, store, book):
    line = objects.text(kb, store, book.object_id, 1)[1].split("\n")[2]
    rows = objects.sheet(kb, store, book.object_id, 1, "Нагрузки", "A2:C2")["rows"]
    assert "\t".join(rows[0]) == line


def test_sheet_name_and_whole_sheet(kb, store, book):
    got = objects.sheet(kb, store, book.object_id, 1, "нагрузки")
    assert got["name"] == "Нагрузки" and got["range"] == "A1:C3" and got["rows"][0] == ["Район", "w0, кПа", "Дата"]


def test_sheet_window_beyond_data_is_padded(kb, store, book):
    got = objects.sheet(kb, store, book.object_id, 1, "Сводка", "a1:b3")
    assert got == {"name": "Сводка", "range": "A1:B3", "rows": [["Итог", ""], ["", ""], ["", ""]]}


def test_sheet_not_found(kb, store, book):
    with pytest.raises(ObjectError) as e:
        objects.sheet(kb, store, book.object_id, 1, "Снег", "A1:B2")
    assert e.value.code == "not_found"
    with pytest.raises(ObjectError) as e:
        objects.sheet(kb, store, book.object_id, 7, "Нагрузки", "A1:B2")
    assert e.value.code == "not_found"


def test_sheet_too_large(kb, store, book):
    with pytest.raises(ObjectError) as e:
        objects.sheet(kb, store, book.object_id, 1, "Нагрузки", "A1:CV101")      # 100 x 101 = 10 100
    assert e.value.code == "too_large"
    ok = objects.sheet(kb, store, book.object_id, 1, "Нагрузки", "A1:CV100")      # ровно 10 000
    assert len(ok["rows"]) == 100 and len(ok["rows"][0]) == 100


@pytest.mark.parametrize("bad", ["", "B2:", "2B", "D4:B2", "A0:B2", "A1:XFE2", "B2:C", "A1;B2"])
def test_sheet_invalid_range(kb, store, book, bad):
    with pytest.raises(ObjectError) as e:
        objects.sheet(kb, store, book.object_id, 1, "Нагрузки", bad or "  ")
    assert e.value.code == "invalid"


def test_sheet_not_a_workbook(kb, docs, store):
    v = objects.ingest(kb, store, docs, PDF, agent=AGENT)
    with pytest.raises(ObjectError) as e:
        objects.sheet(kb, store, v.object_id, 1, "Лист1", "A1:B2")
    assert e.value.code == "invalid"


def test_object_error_code_defaults_to_none():
    assert ObjectError("x").code is None
