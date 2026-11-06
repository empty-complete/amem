"""Уровень 2 автопроверки — привязка к источнику (разд. 4 спецификации подпроекта 3).

Пачка проходит уровень 1, потом уровень 2; сверяются только замечания уровня 2. Документы — из фикстуры docs
(норматив PDF со страницами SP_PAGES, заметка .md, «скан» .docx без текста) и созданные в тесте xlsx и docx."""
import pytest

from amem import db, model_v1, objects, records, sources
from amem.check import Proposal, level1, level2
from amem.check.report import Report
from amem.ocfl_store import StoreError
from check_support import CHECK_PACK, MD, PDF, atom, entity, source_md, source_pdf, value
from samples import make_docx, make_xlsx

AGENT = "model:tester"
PAGE2 = "Ветровой район II: w0 = 0,30 кПа"
PAGE3 = "Самара относится ко II ветровому району по карте."
XLSX = "Таблицы/нагрузки.xlsx"
DOCX1 = "Письма/записка.docx"
DOCX2 = "Письма/отчёт.docx"
VERDICTS = {v.value for v in model_v1.SourceVerdict}


@pytest.fixture
def kb(pg, monkeypatch):
    monkeypatch.setenv("AMEM_PACKS", str(CHECK_PACK))
    db.prepare(pg)
    return pg


@pytest.fixture
def more(docs):
    """Книга с листом «Нагрузки» и два docx: в одну и в две страницы."""
    make_xlsx(docs / XLSX, {"Сводка": [["Итог"]], "Нагрузки": [["Ветровой район II", "кПа"], ["Давление", "0,30"]]})
    make_docx(docs / DOCX1, ["Записка о креплении кронштейна к закладной."])
    make_docx(docs / DOCX2, ["Первая страница отчёта.", ("page",), "Вторая страница: кронштейн КБ-14."])
    return docs


def proposal(body: dict) -> Proposal:
    return Proposal("entity" if "entity_class" in body else "atom", body)


def run(conn, store, docs, *bodies):
    """Уровни 1 и 2 над пачкой; замечания уровня 2 — тройками (код, важность, место)."""
    report = Report()
    batch = level1.check(conn, [proposal(b) for b in bodies], [], report)
    results = level2.check(conn, store, docs, batch, report, agent=AGENT)
    issues = [(i.code, i.severity, i.where) for i in report.issues if i.level == 2]
    return batch, results, issues, report


def one(conn, store, docs, body):
    """Один атом или сущность @a: (итог первого источника, замечания уровня 2, тело после уровня 2, отчёт)."""
    batch, results, issues, report = run(conn, store, docs, body)
    return results["@a"][0], issues, batch.items[0].payload, report


def pdf_atom(page, quote, **kw):
    return atom("@a", sources=[source_pdf(PDF, page, quote, **kw)])


def l2(report, code):
    return [i for i in report.issues if i.level == 2 and i.code == code]


# --- place: селекторы → ожидаемое место ---

def test_place_reads_selectors_and_refined_by():
    p = level2.place([{"type": "page", "value": "12", "refined_by": {"type": "table", "value": "11.1"}}], None)
    assert (p.page, p.pages, p.locator, p.quote, p.sheet) == (12, [], "табл. 11.1", "", None)
    p = level2.place([{"type": "page", "value": "24–25"}, {"type": "clause", "value": "5.2"}], "цитата")
    assert (p.page, p.pages, p.locator, p.quote) == (None, [24, 25], "п. 5.2", "цитата")
    p = level2.place([{"type": "figure", "value": "3", "label": "рисунок 3"}, {"type": "formula", "value": "7"}], None)
    assert p.locator == "рисунок 3; формула (7)"
    p = level2.place([{"type": "sheet", "value": "Нагрузки", "refined_by": {"type": "range", "value": "A1:B2"}},
                      {"type": "text_quote", "value": "из селектора"}], "")
    assert (p.sheet, p.quote, p.locator) == ("Нагрузки", "из селектора", "")
    assert level2.place([{"type": "heading", "value": "Кронштейн"}], None).locator == "Кронштейн"
    assert level2.place([{"type": "page", "value": "24-25"}], None).pages == [24, 25]


def test_verdicts_are_from_schema():
    assert level2.VERDICTS <= VERDICTS


# --- разбор ---

def test_unresolved_path(kb, store, docs):
    check, issues, _, report = one(kb, store, docs, atom("@a", sources=[source_md("НД/нет.pdf")]))
    assert issues == [("source_unresolved", "violation", "@a: sources[0]")]
    assert check.verdict is None
    assert "файла нет" in l2(report, "source_unresolved")[0].message


def test_two_bad_sources_two_issues(kb, store, docs):
    _, _, issues, _ = run(kb, store, docs, atom("@a", sources=[source_md("НД/нет.pdf"), source_md("НД/нет2.md")]))
    assert issues == [("source_unresolved", "violation", "@a: sources[0]"),
                      ("source_unresolved", "violation", "@a: sources[1]")]


def test_object_version_and_digest(kb, store, docs):
    v = objects.ingest(kb, store, docs, PDF, agent=AGENT)
    sel = [{"type": "page", "value": "2"}]
    bad = [{"object": v.ref, "object_version": 5, "digest": v.digest, "selectors": sel, "quote": PAGE2},
           {"object": v.ref, "object_version": 1, "digest": "sha256:" + "0" * 64, "selectors": sel, "quote": PAGE2},
           {"object": v.ref, "object_version": 1, "digest": v.digest, "selectors": sel, "quote": PAGE2}]
    batch, results, issues, _ = run(kb, store, docs, atom("@a", sources=bad))
    assert issues == [("version_missing", "violation", "@a: sources[0]"),
                      ("digest_mismatch", "violation", "@a: sources[1]")]
    assert [c.verdict for c in results["@a"]] == [None, None, "ok"]


def test_payload_gets_resolved_sources(kb, store, docs):
    check, issues, body, _ = one(kb, store, docs, pdf_atom(2, PAGE2))
    assert issues == []
    src = body["sources"][0]
    assert src["object"].startswith("obj:") and src["object_version"] == 1 and src["digest"].startswith("sha256:")
    assert "path" in src                                 # путь остаётся: records его не пишет, а метка понятна
    assert kb.execute("SELECT count(*) FROM source").fetchone()[0] == 0         # итоги пишет submit


# --- PDF ---

def test_pdf_page_required(kb, store, docs):
    _, issues, _, _ = one(kb, store, docs, atom("@a", sources=[{"path": PDF, "quote": PAGE2}]))
    assert issues == [("pdf_page_required", "violation", "@a: sources[0]")]


@pytest.mark.parametrize("quote", [None, "0,30 кПа"])
def test_pdf_quote_required(kb, store, docs, quote):
    assert len("0,30 кПа") < sources.MIN_QUOTE
    _, issues, _, _ = one(kb, store, docs, pdf_atom(2, quote))
    assert issues == [("pdf_quote_required", "violation", "@a: sources[0]")]


# --- цитата ---

def test_quote_on_page_ok(kb, store, docs):
    check, issues, _, _ = one(kb, store, docs, pdf_atom(2, PAGE2))
    assert (check.position, check.verdict, check.page, check.anchor) == (0, "ok", 2, PAGE2)
    assert issues == []
    assert len(check.fragments) == 1 and PAGE2 in check.fragments[0]


def test_quote_moved(kb, store, docs):
    check, issues, _, report = one(kb, store, docs, pdf_atom(3, PAGE2))
    assert (check.verdict, check.page) == ("moved", 2)
    assert issues == [("page_moved", "info", "@a: sources[0]")]
    assert l2(report, "page_moved")[0].details["page"] == 2


def test_quote_fuzzy(kb, store, docs):
    check, issues, _, report = one(kb, store, docs, pdf_atom(2, "Нормативное значение ветрвого давления принимают"))
    assert check.verdict == "fuzzy"
    assert issues == [("quote_fuzzy", "violation", "@a: sources[0].quote")]
    details = l2(report, "quote_fuzzy")[0].details
    assert details["anchor"] == "Нормативное значение ветрового давления принимают"
    assert details["page"] == 2 and details["score"] >= sources.FUZZY_SCORE


def test_quote_not_found(kb, store, docs):
    check, issues, _, _ = one(kb, store, docs, pdf_atom(2, "Этой фразы в нормативе нет совсем"))
    assert check.verdict == "not_found" and check.fragments == []
    assert issues == [("quote_not_found", "violation", "@a: sources[0].quote")]


# --- без цитаты ---

def test_md_heading_without_quote(kb, store, docs):
    check, issues, _, _ = one(kb, store, docs, atom("@a", sources=[source_md(MD)]))
    assert check.verdict in ("by_locator", "ok") and check.page == 1
    assert issues == []
    assert "Кронштейн" in check.fragments[0]


def test_one_page_docx_without_place_unresolved(kb, store, more):
    check, issues, _, _ = one(kb, store, more, atom("@a", sources=[{"path": DOCX1}]))
    assert check.verdict == "unresolved" and check.page is None and check.fragments == []
    assert issues == [("place_unresolved", "warning", "@a: sources[0]")]


def test_docx_quote_on_second_page(kb, store, more):
    check, issues, _, _ = one(kb, store, more, atom("@a", sources=[{"path": DOCX2, "quote": "кронштейн КБ-14"}]))
    assert (check.verdict, check.page, issues) == ("ok", 2, [])


# --- xlsx ---

def test_xlsx_sheet_by_locator(kb, store, more):
    src = {"path": XLSX, "selectors": [{"type": "sheet", "value": "нагрузки"}]}       # регистр не важен
    check, issues, _, _ = one(kb, store, more, atom("@a", sources=[src]))
    assert (check.verdict, check.page, issues) == ("by_locator", 2, [])
    assert check.fragments[0].startswith("Нагрузки")


def test_xlsx_sheet_quote_ok(kb, store, more):
    src = {"path": XLSX, "selectors": [{"type": "sheet", "value": "Нагрузки"}], "quote": "Ветровой район II"}
    check, issues, _, _ = one(kb, store, more, atom("@a", sources=[src]))
    assert (check.verdict, check.page, issues) == ("ok", 2, [])


def test_xlsx_unknown_sheet_unresolved(kb, store, more):
    src = {"path": XLSX, "selectors": [{"type": "sheet", "value": "Снег"}]}
    check, issues, _, _ = one(kb, store, more, atom("@a", sources=[src]))
    assert check.verdict == "unresolved"
    assert issues == [("place_unresolved", "warning", "@a: sources[0]")]


# --- числа ---

def numbered(page, quote, **kw):
    return atom("@a", content={"values": [value("pressure", 0.3, "kPa")]}, sources=[source_pdf(PDF, page, quote, **kw)])


def test_number_found_on_page(kb, store, docs):
    _, issues, _, _ = one(kb, store, docs, numbered(2, PAGE2))
    assert issues == []


def test_number_not_found_violation(kb, store, docs):
    _, issues, _, report = one(kb, store, docs, numbered(3, PAGE3))
    assert issues == [("number_not_found", "violation", "@a")]
    assert l2(report, "number_not_found")[0].details["numbers"] == [{"path": "content.values[0].amount",
                                                                     "value": "0.3"}]


def test_number_not_found_derived_warning(kb, store, docs):
    _, issues, _, _ = one(kb, store, docs, numbered(3, PAGE3, role="derived"))
    assert issues == [("number_not_found", "warning", "@a")]


def test_number_only_in_qualifiers_warning(kb, store, docs):
    body = atom("@a", qualifiers=[value("temperature", 7, "Cel")], sources=[source_pdf(PDF, 3, PAGE3)])
    _, issues, _, report = one(kb, store, docs, body)
    assert issues == [("number_not_found", "warning", "@a")]
    assert l2(report, "number_not_found")[0].details["numbers"] == [{"path": "qualifiers[0].amount", "value": "7"}]


def test_number_on_page_of_range(kb, store, docs):
    src = {"path": PDF, "selectors": [{"type": "page", "value": "2–3"}], "quote": PAGE3}
    body = atom("@a", content={"values": [value("pressure", 0.3, "kPa")]}, sources=[src])
    check, issues, _, _ = one(kb, store, docs, body)
    assert (check.verdict, check.page, len(check.fragments)) == ("ok", 3, 2)
    assert issues == []


# --- без текста ---

def test_web_external(kb, store, docs):
    v = objects.web(kb, "https://example.org/norms")
    check, issues, _, _ = one(kb, store, docs, atom("@a", sources=[{"object": v.ref, "object_version": 1}]))
    assert check.verdict == "external"
    assert issues == [("external_source", "warning", "@a: sources[0]")]


def test_no_text_and_numbers_unchecked(kb, store, docs):
    body = atom("@a", content={"values": [value("pressure", 0.3, "kPa")]}, sources=[{"path": "НД/скан.docx"}])
    check, issues, _, _ = one(kb, store, docs, body)
    assert check.verdict == "no_text"
    assert issues == [("no_text", "warning", "@a: sources[0]"), ("numbers_unchecked", "info", "@a")]


# --- сбои ---

def test_extract_error(kb, store, docs, monkeypatch):
    def broken(file):
        raise RuntimeError("сбой разбора")

    monkeypatch.setattr(sources, "extract_pages", broken)
    check, issues, _, report = one(kb, store, docs, pdf_atom(2, PAGE2))
    assert check.verdict == "error"
    assert issues == [("source_error", "warning", "@a: sources[0]")]
    assert "сбой разбора" in l2(report, "source_error")[0].message


def test_missing_copy_raises_store_error(kb, store, docs):
    v = objects.ingest(kb, store, docs, PDF, agent=AGENT)
    store.content(v.object_id, v.n).unlink()              # копия версии пропала из хранилища
    with pytest.raises(StoreError, match="sources\\[0\\]"):
        run(kb, store, docs, pdf_atom(2, PAGE2))


# --- редакция ---

def edition(conn, store, docs, name):
    body = objects.resolve_sources(conn, store, docs, entity(name, cls="edition", sources=[{"path": PDF}]),
                                   agent=AGENT)
    result = records.commit(conn, [records.Item("entity", body)], agent=AGENT)
    return result.refs[name]


def test_edition_filled(kb, store, docs):
    ref = edition(kb, store, docs, "@ed")
    _, issues, body, _ = one(kb, store, docs, pdf_atom(2, PAGE2))
    assert body["sources"][0]["edition"] == ref
    assert issues == [("edition_filled", "info", "@a: sources[0].edition")]


def test_edition_ambiguous_not_filled(kb, store, docs):
    edition(kb, store, docs, "@ed1")
    edition(kb, store, docs, "@ed2")
    _, issues, body, _ = one(kb, store, docs, pdf_atom(2, PAGE2))
    assert "edition" not in body["sources"][0]
    assert issues == []


def test_edition_given_kept(kb, store, docs):
    ref = edition(kb, store, docs, "@ed")
    other = edition(kb, store, docs, "@ed2")
    _, issues, body, _ = one(kb, store, docs, pdf_atom(2, PAGE2, edition=other))
    assert body["sources"][0]["edition"] == other != ref
    assert issues == []


# --- сущность ---

def test_entity_quote_not_found_warning(kb, store, docs):
    check, issues, _, _ = one(kb, store, docs, entity("@a", sources=[{"path": PDF, "quote": "Этой фразы нет нигде"}]))
    assert check.verdict == "not_found"
    assert issues == [("quote_not_found", "warning", "@a: sources[0].quote")]


def test_entity_fuzzy_warning_and_kept(kb, store, docs):
    src = {"path": PDF, "quote": "Нормативное значение ветрвого давления принимают"}
    check, issues, _, _ = one(kb, store, docs, entity("@a", sources=[src]))
    assert check.verdict == "fuzzy" and check.anchor == "Нормативное значение ветрового давления принимают"
    assert issues == [("quote_fuzzy", "warning", "@a: sources[0].quote")]


def test_entity_pdf_without_page_no_issue(kb, store, docs):
    check, issues, body, _ = one(kb, store, docs, entity("@a", sources=[{"path": PDF}]))
    assert issues == []
    assert check.verdict is None
    assert body["sources"][0]["object"].startswith("obj:")


def test_entity_unresolved_path_violation(kb, store, docs):
    _, issues, _, _ = one(kb, store, docs, entity("@a", sources=[{"path": "НД/нет.pdf"}]))
    assert issues == [("source_unresolved", "violation", "@a: sources[0]")]


# --- итоги — из перечня схемы ---

def test_all_returned_verdicts_in_schema(kb, store, more, monkeypatch):
    v = objects.web(kb, "https://example.org/norms")
    bodies = [pdf_atom(2, PAGE2), atom("@b", sources=[source_pdf(PDF, 3, PAGE2)]),
              atom("@c", sources=[source_pdf(PDF, 2, "Нормативное значение ветрвого давления принимают")]),
              atom("@d", sources=[source_pdf(PDF, 2, "Этой фразы в нормативе нет совсем")]),
              atom("@e", sources=[{"path": XLSX, "selectors": [{"type": "sheet", "value": "Нагрузки"}]}]),
              atom("@f", sources=[{"path": DOCX1}]), atom("@g", sources=[{"path": "НД/скан.docx"}]),
              atom("@h", sources=[{"object": v.ref, "object_version": 1}])]
    _, results, _, _ = run(kb, store, more, *bodies)
    seen = {c.verdict for checks in results.values() for c in checks}
    assert seen == {"ok", "moved", "fuzzy", "not_found", "by_locator", "unresolved", "no_text", "external"}
    assert seen <= VERDICTS
    monkeypatch.setattr(sources, "extract_pages", lambda file: (_ for _ in ()).throw(RuntimeError("x")))
    _, results, _, _ = run(kb, store, more, atom("@a", sources=[{"path": DOCX2, "quote": "кронштейн КБ-14"}]))
    assert results["@a"][0].verdict == "error" and "error" in VERDICTS


def test_unparsed_item_skipped(kb, store, docs):
    batch, results, issues, _ = run(kb, store, docs, atom("@a", label=None, kind=5))
    assert not batch.items[0].ok
    assert results == {} and issues == []


# --- по ревью ---

def test_resolve_store_error_raises(kb, store, docs, monkeypatch):
    def broken(*a, **kw):
        raise StoreError("том хранилища не подключён")

    monkeypatch.setattr(objects, "ingest", broken)
    with pytest.raises(StoreError, match=r"^@a: sources\[0\]: том хранилища"):
        run(kb, store, docs, pdf_atom(2, PAGE2))


def test_judge_bug_raises(kb, store, docs, monkeypatch):
    def broken(*a, **kw):
        raise TypeError("ошибка кода сверки")

    monkeypatch.setattr(sources, "judge", broken)
    with pytest.raises(TypeError, match="ошибка кода сверки"):
        run(kb, store, docs, pdf_atom(2, PAGE2))


def test_txt_one_page_ok(kb, store, docs):
    (docs / "Заметки" / "узел.txt").write_text("Кронштейн КБ-14 крепится анкером М10.", encoding="utf-8")
    check, issues, _, _ = one(kb, store, docs, atom("@a", sources=[{"path": "Заметки/узел.txt"}]))
    assert (check.verdict, check.page, issues) == ("ok", 1, [])
    assert "М10" in check.fragments[0]


def test_text_quote_selector(kb, store, docs):
    src = {"path": PDF, "selectors": [{"type": "page", "value": "2", "refined_by": {"type": "text_quote",
                                                                                    "value": PAGE2}}]}
    check, issues, _, _ = one(kb, store, docs, atom("@a", sources=[src]))
    assert (check.verdict, check.page, check.anchor, issues) == ("ok", 2, PAGE2, [])


def test_md_heading_exact(kb, store, docs):
    """Значение heading — локатор как есть: правил локатора для него нет, итог — одностраничное ok заметки."""
    check, issues, _, _ = one(kb, store, docs, atom("@a", sources=[source_md(MD)]))
    assert (check.verdict, check.page, check.anchor, issues) == ("ok", 1, None, [])


def test_xlsx_quote_on_other_sheet_moved(kb, store, more):
    src = {"path": XLSX, "selectors": [{"type": "sheet", "value": "Сводка"}], "quote": "Ветровой район II"}
    check, issues, _, report = one(kb, store, more, atom("@a", sources=[src]))
    assert (check.verdict, check.page) == ("moved", 2)
    assert issues == [("page_moved", "info", "@a: sources[0]")]
    assert l2(report, "page_moved")[0].details == {"page": 2, "expected": 1}


def test_entity_page_only_no_issue(kb, store, docs):
    check, issues, _, _ = one(kb, store, docs, entity("@a", sources=[source_pdf(PDF, 2, None)]))
    assert (check.verdict, issues) == (None, [])


def test_entity_numbers_not_checked(kb, store, docs, monkeypatch):
    def forbidden(payload):
        raise AssertionError("у сущности числа не сверяются")

    monkeypatch.setattr(level2.numbers, "atom_numbers", forbidden)
    check, issues, _, _ = one(kb, store, docs, entity("@a", sources=[source_pdf(PDF, 3, PAGE3)]))
    assert (check.verdict, issues) == ("ok", [])


def test_external_edition_not_looked_up(kb, store, docs):
    v = objects.web(kb, "https://example.org/norms")
    body = objects.resolve_sources(kb, store, docs, entity("@ed", cls="edition", sources=[
        {"object": v.ref, "object_version": 1}]), agent=AGENT)
    records.commit(kb, [records.Item("entity", body)], agent=AGENT)
    _, issues, body, _ = one(kb, store, docs, atom("@a", sources=[{"object": v.ref, "object_version": 1}]))
    assert "edition" not in body["sources"][0]
    assert issues == [("external_source", "warning", "@a: sources[0]")]


# --- кэш путей на пакет ---

def test_path_is_resolved_once_per_batch(kb, store, docs, monkeypatch):
    calls = []
    ingest = objects.ingest

    def counted(*args, **kwargs):
        calls.append(args[3] if len(args) > 3 else kwargs.get("path"))
        return ingest(*args, **kwargs)

    monkeypatch.setattr(objects, "ingest", counted)
    bodies = [atom(f"@a{i}", sources=[source_pdf(PDF, 2, PAGE2)]) for i in range(20)]
    batch, results, issues, _ = run(kb, store, docs, *bodies)
    assert calls == [PDF]
    assert {results[f"@a{i}"][0].verdict for i in range(20)} == {"ok"}
    assert len({it.payload["sources"][0]["object"] for it in batch.items}) == 1
    assert batch.items[5].payload["sources"][0]["quote"] == PAGE2


def test_unresolved_path_is_reported_for_each_source(kb, store, docs, monkeypatch):
    calls = []
    resolve = objects.resolve_sources

    def counted(*args, **kwargs):
        calls.append(1)
        return resolve(*args, **kwargs)

    monkeypatch.setattr(objects, "resolve_sources", counted)
    bodies = [atom(f"@a{i}", sources=[source_md("Заметки/нет такого.md")]) for i in range(3)]
    _, _, issues, report = run(kb, store, docs, *bodies)
    assert len(calls) == 1
    assert issues == [("source_unresolved", "violation", f"@a{i}: sources[0]") for i in range(3)]
    assert len({i.message for i in l2(report, "source_unresolved")}) == 1
