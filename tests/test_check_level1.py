"""Уровень 1 автопроверки (разд. 1.1, шаги 1–3, и разд. 3 спецификации подпроекта 3) и отчёт amem.check/1 (разд. 2).

Уровень 1: разбор тела, коды словаря, ссылки, шаблоны, жёсткие правила величин, концы и правила связей, политика
статуса. База — с тестовым пакетом tests/packs/check (виды rule и idea); записи, на которые ссылается пачка, пишутся
мимо проверки через records.commit. Каждый случай даёт ровно одно замечание с точным местом."""
import copy
import json
import os
import uuid
from datetime import date

import pytest

from amem import db, model_v1, records
from amem.check import Proposal, level1, templates
from amem.check.report import Issue, Report
from amem.ids import uuid7
from check_support import CHECK_PACK, MD, PDF, atom, entity, pack, source_md, source_pdf, value

AGENT = "model:tester"
HUMAN = "person:reviewer"
INTERFACES = ("has_label@1.0.0", "has_source@1.1.0", "has_value@1.0.0")
DOC = entity("@doc")


def rule(**fields) -> dict:
    """Атом вида rule, проходящий свой шаблон: есть значение и about на документ @doc."""
    return atom("@r", kind="rule", **{"content": {"values": [value("pressure", 0.38, "kPa")]}, "about": ["@doc"],
                                      **fields})


def proposal(body: dict, record_id=None) -> Proposal:
    return Proposal("entity" if "entity_class" in body else "atom", body, record_id)


def run(conn, *items, links=()):
    """Уровень 1 над пачкой; замечания — тройками (код, важность, место)."""
    report = Report()
    batch = level1.check(conn, [i if isinstance(i, Proposal) else proposal(i) for i in items], list(links), report)
    return batch, [(i.code, i.severity, i.where) for i in report.issues], report


def existing(conn, *bodies, links=()) -> dict[str, uuid.UUID]:
    """Записать тела мимо проверки (без источников: записи нужны только как цели ссылок); @имя → id."""
    result = records.commit(conn, [records.Item(proposal(b).target, b) for b in bodies], links, agent=AGENT)
    return {name: uuid.UUID(ref.split(":", 1)[1]) for name, ref in result.refs.items()}


@pytest.fixture
def kb(pg, monkeypatch):
    monkeypatch.setenv("AMEM_PACKS", str(CHECK_PACK))
    db.prepare(pg)
    return pg


# --- отчёт (без базы) ---

def test_report_collects_issues_and_selects_by_label():
    report = Report()
    a = report.add(1, "violation", "schema", "@a: label", "Нет подписи", loc=["label"], msg="Field required")
    b = report.add(2, "warning", "no_text", "@a1: sources[0]", "У файла нет текста")
    c = report.add(1, "warning", "link_required", "@a", "Нет связи about")
    assert a == Issue(1, "violation", "schema", "@a: label", "Нет подписи", {"loc": ["label"], "msg": "Field required"})
    assert report.issues == [a, b, c]
    assert report.violations() == [a]
    assert report.for_label("@a") == [a, c]                       # @a1 — другая запись
    assert report.for_label("@a1") == [b]


@pytest.mark.parametrize("level, severity, code", [(1, "violation", "nope"), (1, "error", "schema"),
                                                   (5, "violation", "schema"), (0, "info", "page_moved")])
def test_report_rejects_codes_outside_schema(level, severity, code):
    report = Report()
    with pytest.raises(AssertionError):
        report.add(level, severity, code, "@a", "сообщение")
    assert report.issues == []


def test_report_json_passes_check_report_schema():
    report = Report()
    report.add(2, "info", "page_moved", "@a1: sources[0]", "Цитата найдена на странице 12, а не 11", page=12)
    report.add(1, "violation", "template", "@a1: content.values", "Нет значений", template="rule@1.0.0",
               path="content.values", rule="required")
    out = report.as_json(levels={"1": "done", "2": "done", "3": "done", "4": "done"},
                         records=[{"label": "@a1", "target": "atom", "planned_status": "draft", "risk": []}],
                         templates=[*INTERFACES],
                         degraded=[{"level": 4, "channel": "vector", "reason": "backend_disabled"}])
    model_v1.CheckReport.model_validate_json(json.dumps(out, ensure_ascii=False), strict=True)
    assert out["format"] == "amem.check/1"
    assert out["issues"][0] == {"level": 2, "severity": "info", "code": "page_moved", "where": "@a1: sources[0]",
                                "message": "Цитата найдена на странице 12, а не 11", "details": {"page": 12}}
    assert out["templates"] == list(INTERFACES) and out["records"][0]["planned_status"] == "draft"


def test_empty_report_json_is_valid():
    out = Report().as_json(levels={"1": "done", "2": "skipped", "3": "skipped", "4": "skipped"}, records=[],
                           templates=[], degraded=[])
    assert model_v1.CheckReport.model_validate_json(json.dumps(out), strict=True).issues == []


# --- уровень 1: чистая пачка ---

def test_clean_batch_describes_records_refs_and_templates(kb):
    link = {"rel": "see_also", "src": "@r", "dst": "@i", "note": {"ru": "то же правило"}}
    batch, issues, _ = run(kb, rule(), DOC, atom("@i", kind="idea", body={"ru": "Пояснение."}), links=[link])
    assert issues == []
    r, doc, i = batch.items
    assert (r.label, r.target, r.code, r.record_id, r.status, r.ok) == ("@r", "atom", "rule", None, None, True)
    assert r.payload == rule()
    assert r.rules.templates == (*INTERFACES, "rule@1.0.0") and r.rules.high_risk == frozenset({"numeric"})
    assert (doc.target, doc.code) == ("entity", "document")
    assert doc.rules == templates.Rules(templates=(), fields={}, allowed=None, required_links=(), high_risk=frozenset())
    assert i.rules.templates == (*INTERFACES, "idea@1.0.0")
    assert batch.refs == {"@r": ("atom", "rule"), "@doc": ("entity", "document"), "@i": ("atom", "idea")}
    assert batch.templates == (*INTERFACES, "rule@1.0.0", "idea@1.0.0")
    assert batch.links == [link]


def test_level1_writes_nothing_and_keeps_payloads(kb):
    tables = [row[0] for row in kb.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() "
        "AND table_type = 'BASE TABLE' ORDER BY 1")]

    def counts():
        return {t: kb.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}

    bodies = [rule(), DOC, atom("@a", about=["ent:missing_key"]), atom("@b", label=None)]
    before, kept = counts(), copy.deepcopy(bodies)
    run(kb, *bodies, links=[{"rel": "see_also", "src": "@a", "dst": "@r"}, {"rel": "nope", "src": "@a", "dst": "@b"}])
    assert counts() == before
    assert bodies == kept


# --- уровень 1: одно замечание на случай ---

def _no_place(source: dict) -> dict:
    return {k: v for k, v in source.items() if k != "selectors"}


ONE = {
    # схема
    "no_label": ([atom("@a", label=None)], [], ("schema", "violation", "@a: label")),
    "wrong_type_deep": ([atom("@a", content={"values": [value("pressure", 0.38, 5)]})], [],
                        ("schema", "violation", "@a: content.values[0].unit")),
    "no_ref_gives_items_label": ([atom(None, label=None)], [], ("schema", "violation", "items[0]: label")),
    "ref_twice": ([atom("@a"), atom("@a")], [], ("schema", "violation", "items[1]: ref")),
    "not_json": ([atom("@a", valid_from=date(2026, 1, 1))], [], ("schema", "violation", "@a")),
    # коды словаря
    "unknown_kind": ([atom("@a", kind="nope")], [], ("unknown_code", "violation", "@a: kind")),
    "unknown_class": ([entity("@e", cls="nope")], [], ("unknown_code", "violation", "@e: entity_class")),
    "unknown_selector": ([atom("@a", sources=[source_md(MD, selectors=[{"type": "pagee", "value": "2"}])])], [],
                         ("unknown_code", "violation", "@a: sources[0].selectors[0].type")),
    "unknown_selector_in_refined_by": (
        [atom("@a", sources=[source_md(MD, selectors=[
            {"type": "table", "value": "1.1", "refined_by": {"type": "pagee", "value": "2"}}])])], [],
        ("unknown_code", "violation", "@a: sources[0].selectors[0].refined_by.type")),
    # ссылки
    "unknown_key": ([atom("@a", about=["ent:missing_key"])], [], ("ref_unknown", "violation", "@a: about[0]")),
    "unknown_uuid": ([atom("@a", about=[f"ent:{uuid7()}"])], [], ("ref_unknown", "violation", "@a: about[0]")),
    "unknown_name": ([atom("@a", derived_from=["@nope"])], [], ("ref_unknown", "violation", "@a: derived_from[0]")),
    "name_of_atom_where_entity": ([atom("@a", about=["@b"]), atom("@b")], [],
                                  ("ref_unknown", "violation", "@a: about[0]")),
    "unknown_edition": ([atom("@a", sources=[source_md(MD, edition="ent:missing_edition")])], [],
                        ("ref_unknown", "violation", "@a: sources[0].edition")),
    "unknown_edition_of": ([entity("@e", cls="edition", edition_of="@nope")], [],
                           ("ref_unknown", "violation", "@e: edition_of")),
    # шаблоны ядра и пакета
    "rule_without_values": ([rule(content=None), DOC], [], ("template", "violation", "@r: content.values")),
    "rule_with_empty_values": ([rule(content={"values": []}), DOC], [],
                               ("template", "violation", "@r: content.values")),
    "idea_without_body": ([atom("@i", kind="idea")], [], ("template", "warning", "@i: body")),
    "idea_with_blank_body": ([atom("@i", kind="idea", body={"ru": "  "})], [], ("template", "warning", "@i: body")),
    "summary_without_ru": ([atom("@a", summary_plain={"ru": "", "en": "Bracket on one anchor."})], [],
                           ("template", "violation", "@a: summary_plain")),
    "no_sources": ([atom("@a", sources=None)], [], ("template", "violation", "@a: sources")),
    "second_source_without_place": ([atom("@a", sources=[source_md(MD), _no_place(source_md(MD))])], [],
                                    ("template", "warning", "@a: sources[1].selectors")),
    # единицы и жёсткие правила величин
    "not_ucum": ([atom("@a", content={"values": [value("pressure", 0.38, "кПа")]})], [],
                 ("ucum", "violation", "@a: content.values[0].unit")),
    "not_ucum_in_qualifier": (
        [atom("@a", content={"values": [
            value("pressure", 0.38, "kPa", qualifiers=[value("temperature", 20, "KPA")])]})], [],
        ("ucum", "violation", "@a: content.values[0].qualifiers[0].unit")),
    "not_ucum_in_column": (
        [atom("@a", content={"table": {"columns": [{"code": "w0", "label": {"ru": "Давление"}, "unit": "кПа"}]}})],
        [], ("ucum", "violation", "@a: content.table.columns[0].unit")),
    "empty_unit": ([atom("@a", content={"values": [value("pressure", 0.38, "")]})], [],
                   ("ucum", "violation", "@a: content.values[0].unit")),
    "amount_without_unit": ([atom("@a", content={"values": [value("pressure", 0.38, None)]})], [],
                            ("unit_required", "violation", "@a: content.values[0].unit")),
    "bound_without_unit": ([atom("@a", qualifiers=[value("temperature", None, None, lower_bound=-20)])], [],
                           ("unit_required", "violation", "@a: qualifiers[0].unit")),
    "bounds_reversed": ([atom("@a", content={"values": [value("length", None, "m", lower_bound=5, upper_bound=1)]})],
                        [], ("bounds_order", "violation", "@a: content.values[0]")),
    "amount_below_bound": (
        [atom("@a", content={"values": [value("length", 0.5, "m", lower_bound=1, upper_bound=5)]})], [],
        ("bounds_order", "violation", "@a: content.values[0]")),
    "amount_above_bound": ([atom("@a", content={"values": [value("length", 7, "m", upper_bound=5)]})], [],
                           ("bounds_order", "violation", "@a: content.values[0]")),
    # связи
    "link_not_allowed": ([rule(), DOC], [{"rel": "depends_on", "src": "@r", "dst": "@doc"}],
                         ("link_not_allowed", "violation", "links[0]")),
    "symmetric_link_not_allowed_at_dst": ([rule(), DOC, atom("@a")], [{"rel": "contradicts", "src": "@a", "dst": "@r"}],
                                          ("link_not_allowed", "violation", "links[0]")),
    "field_link_not_allowed": ([rule(derived_from=["@a"]), DOC, atom("@a")], [],
                               ("link_not_allowed", "violation", "@r: derived_from")),
    "rule_without_about": ([rule(about=None)], [], ("link_required", "warning", "@r")),
    "rule_about_project": ([rule(about=["@p"]), entity("@p", cls="project")], [],
                           ("link_required", "warning", "@r")),
    "link_pair": ([atom("@a"), DOC], [{"rel": "refines", "src": "@a", "dst": "@doc"}],
                  ("link_pair", "violation", "links[0]")),
    "link_to_itself": ([atom("@a")], [{"rel": "see_also", "src": "@a", "dst": "@a"}],
                       ("link_pair", "violation", "links[0]")),
    "link_by_field_rel": ([atom("@a"), DOC], [{"rel": "about", "src": "@a", "dst": "@doc"}],
                          ("link_not_allowed", "violation", "links[0]: rel")),
    "unknown_rel": ([atom("@a"), atom("@b")], [{"rel": "nope", "src": "@a", "dst": "@b"}],
                    ("unknown_code", "violation", "links[0]: rel")),
    "link_end_unknown": ([atom("@a")], [{"rel": "see_also", "src": "@a", "dst": "ent:missing_key"}],
                         ("ref_unknown", "violation", "links[0]: dst")),
    "link_schema": ([atom("@a")], [{"rel": "see_also", "src": "@a"}], ("schema", "violation", "links[0]: dst")),
    "link_qualifier_bounds": (
        [atom("@a"), atom("@b")],
        [{"rel": "depends_on", "src": "@a", "dst": "@b",
          "qualifiers": [value("temperature", 20, "Cel", lower_bound=30)]}],
        ("bounds_order", "violation", "links[0]: qualifiers[0]")),
}


@pytest.mark.parametrize("case", ONE)
def test_one_issue(kb, case):
    items, links, expected = ONE[case]
    _, issues, _ = run(kb, *items, links=links)
    assert issues == [expected]


def test_found_batch_name_gives_no_issue(kb):
    assert run(kb, atom("@a", about=["@b"]), entity("@b"))[1] == []
    assert run(kb, entity("@b"), atom("@a", about=["@b"], derived_from=["@c"]), atom("@c"))[1] == []    # любой порядок


def test_each_schema_error_is_an_issue_with_loc_and_msg(kb):
    batch, issues, report = run(kb, atom("@a", label=None, kind=5))
    assert sorted(issues) == [("schema", "violation", "@a: kind"), ("schema", "violation", "@a: label")]
    missing = next(i for i in report.issues if i.where == "@a: label")
    assert missing.details == {"loc": ["label"], "msg": "Field required"}
    item = batch.items[0]
    assert (item.ok, item.rules, item.code) == (False, None, None)
    assert batch.refs == {"@a": ("atom", None)}


def test_unknown_target_is_schema_issue(kb):
    batch, issues, _ = run(kb, Proposal("link", {"rel": "see_also", "src": "@a", "dst": "@b"}))
    assert issues == [("schema", "violation", "items[0]: target")]
    assert batch.items[0].ok is False


def test_template_issue_names_template_path_and_rule(kb):
    _, _, report = run(kb, rule(content=None), DOC)
    [issue] = report.issues
    assert (issue.level, issue.details) == (1, {"template": "rule@1.0.0", "path": "content.values", "rule": "required"})
    _, _, report = run(kb, atom("@a", sources=None))
    [issue] = report.issues
    assert issue.message == "У атома нет источника и не задано основание basis."                        # текст правила has_source
    _, _, report = run(kb, atom("@a", content={"values": [value("pressure", 0.38, "кПа")]}))
    [issue] = report.issues
    assert issue.details == {"template": "has_value@1.0.0", "path": "content.values[].unit", "rule": "ucum",
                             "unit": "кПа"}
    _, _, report = run(kb, rule(about=None))
    [issue] = report.issues
    assert issue.details == {"template": "rule@1.0.0", "rel": "about", "to_classes": ["document"]}


@pytest.mark.parametrize("items, links, details", [
    ([atom("@a", kind="nope")], [], {"scheme": "kind", "value": "nope"}),
    ([entity("@e", cls="nope")], [], {"scheme": "entity_class", "value": "nope"}),
    ([atom("@a", sources=[source_md(MD, selectors=[{"type": "table", "value": "1", "refined_by":
                                                    {"type": "pagee", "value": "2"}}])])], [],
     {"scheme": "selector_type", "value": "pagee"}),
    ([atom("@a"), atom("@b")], [{"rel": "nope", "src": "@a", "dst": "@b"}], {"scheme": "rel", "value": "nope"}),
])
def test_unknown_code_names_scheme_and_value(kb, items, links, details):
    _, _, report = run(kb, *items, links=links)
    [issue] = report.issues
    assert (issue.code, issue.details) == ("unknown_code", details)


def test_report_of_level1_passes_check_report_schema(kb):
    _, issues, report = run(kb, rule(content=None, about=["ent:missing_key"]), atom("@a", label=None),
                            links=[{"rel": "refines", "src": "@r", "dst": "@doc"}])
    assert len(issues) >= 3
    out = report.as_json(levels={"1": "done", "2": "done", "3": "skipped", "4": "skipped"}, records=[],
                         templates=[], degraded=[])
    model_v1.CheckReport.model_validate_json(json.dumps(out, ensure_ascii=False), strict=True)


# --- уровень 1: записи в базе ---

def test_refs_to_existing_records_by_key_and_uuid(kb):
    ids = existing(kb, entity("@sp", key="sp99_13330"), atom("@base", sources=None, key="w0_base"))
    _, issues, _ = run(kb, rule(about=["ent:sp99_13330"]),
                       atom("@a", about=[f"ent:{ids['@sp']}"], derived_from=["atm:w0_base", f"atm:{ids['@base']}"]))
    assert issues == []                    # и about по ключу на документ закрывает обязательную связь rule


def test_unknown_record_id(kb):
    ids = existing(kb, atom("@a", sources=None))
    assert run(kb, Proposal("atom", atom("@a"), uuid7()))[1] == [("ref_unknown", "violation", "@a: record_id")]
    assert run(kb, Proposal("entity", entity("@e"), ids["@a"]))[1] == [("ref_unknown", "violation", "@e: record_id")]
    assert run(kb, Proposal("atom", atom("@a"), "not-a-uuid"))[1] == [("schema", "violation", "@a: record_id")]


def test_two_edits_of_one_record_in_batch(kb):
    ids = existing(kb, atom("@a", sources=None))
    _, issues, report = run(kb, Proposal("atom", atom("@a"), ids["@a"]), Proposal("atom", atom("@b"), str(ids["@a"])))
    assert issues == [("schema", "violation", "@b: record_id")]
    assert report.issues[0].message.endswith("запись уже правится в этой пачке: @a")


@pytest.mark.parametrize("status", ["deprecated", "superseded"])
@pytest.mark.parametrize("stored, edit", [(atom("@a", sources=None), atom("@a")), (entity("@a"), entity("@a"))],
                         ids=["atom", "entity"])
def test_edit_of_retired_record(kb, status, stored, edit):
    target = proposal(stored).target
    ids = existing(kb, stored)
    records.set_status(kb, target, ids["@a"], status, agent=HUMAN)
    batch, issues, report = run(kb, Proposal(target, edit, ids["@a"]))
    assert issues == [("retired_record", "violation", "@a")]
    assert report.issues[0].details == {"status": status}
    assert (batch.items[0].record_id, batch.items[0].status) == (ids["@a"], status)


def test_edit_reads_status_of_existing_record(kb):
    ids = existing(kb, atom("@a", sources=None))
    records.set_status(kb, "atom", ids["@a"], "verified", agent=HUMAN)
    batch, issues, _ = run(kb, Proposal("atom", atom(None), str(ids["@a"])))          # id строкой, без ref
    assert issues == []
    item = batch.items[0]
    assert (item.label, item.record_id, item.status, item.code, item.ok) == ("items[0]", ids["@a"], "verified",
                                                                             "fact", True)


def test_link_from_existing_record_follows_its_template(kb):
    existing(kb, DOC, atom("@r", kind="rule", sources=None, about=["@doc"], key="r1"))
    _, issues, _ = run(kb, atom("@a"), links=[{"rel": "depends_on", "src": "atm:r1", "dst": "@a"}])
    assert issues == [("link_not_allowed", "violation", "links[0]")]


def test_stored_link_does_not_break_allowed_on_edit(kb):
    """Уже записанные связи на allowed не перепроверяются: пакет отвечает за то, что предлагает."""
    ids = existing(kb, DOC, atom("@r", kind="rule", sources=None, about=["@doc"]), atom("@a", sources=None),
                   links=[{"rel": "depends_on", "src": "@r", "dst": "@a"}])
    assert run(kb, Proposal("atom", rule(about=[f"ent:{ids['@doc']}"]), ids["@r"]))[1] == []


def test_link_to_itself_by_name_and_id(kb):
    ids = existing(kb, atom("@a", sources=None))
    _, issues, _ = run(kb, Proposal("atom", atom("@a"), ids["@a"]),
                       links=[{"rel": "see_also", "src": "@a", "dst": f"atm:{ids['@a']}"}])
    assert issues == [("link_pair", "violation", "links[0]")]


# --- уровень 1: правила полей и связей временного пакета ---

@pytest.fixture
def memo_kb(pg, monkeypatch, tmp_path):
    """Вид memo — правила selector_types, entity_classes, min_count; вид remark — обязательная связь see_also;
    у связи see_also — шаблон с обязательной заметкой."""
    memo = pack(tmp_path / "memo", "memo", {
        "memo": {"code": "memo", "version": "1.0.0", "target": "atom", "applies_to": "memo", "fields": [
            {"path": "sources[].selectors", "selector_types": ["page"]},
            {"path": "about", "entity_classes": ["document", "edition"]},
            {"path": "codes", "min_count": 2, "severity": "warning", "message": {"ru": "Нужны два обозначения."}}]},
        "remark": {"code": "remark", "version": "1.0.0", "target": "atom", "applies_to": "remark",
                 "links": {"allowed": ["see_also", "about"], "required": [{"rel": "see_also"}]}},
        "see_also_note": {"code": "see_also_note", "version": "1.0.0", "target": "link", "applies_to": "see_also",
                          "fields": [{"path": "note", "required": True, "severity": "warning"}]},
    }, kinds=["memo", "remark"])
    monkeypatch.setenv("AMEM_PACKS", os.pathsep.join([str(CHECK_PACK), str(memo)]))
    db.prepare(pg)
    return pg


def memo(**fields) -> dict:
    return atom("@m", kind="memo", **{"sources": [source_pdf(PDF, 2, "Нормативное значение ветрового давления")],
                                      "about": ["@doc"], "codes": ["w0", "1.1"], **fields})


def note(**fields) -> dict:
    return atom("@n", kind="remark", **fields)


SEE = {"rel": "see_also", "src": "@n", "dst": "@a", "note": {"ru": "то же место"}}
REFINED_PAGE = [{"type": "table", "value": "1.1", "refined_by": {"type": "page", "value": "2"}}]

MEMO = {
    "page_in_refined_by": ([memo(sources=[source_md(MD, selectors=REFINED_PAGE)]), DOC], [], None),
    "no_page": ([memo(sources=[source_pdf(PDF, 2, "Нормативное значение"), source_md(MD)]), DOC], [],
                ("template", "violation", "@m: sources[1].selectors")),
    "about_project": ([memo(about=["@doc", "@p"]), DOC, entity("@p", cls="project")], [],
                      ("template", "violation", "@m: about[1]")),
    # правило memo с тем же путём заменило has_source: required-предупреждения нет, есть selector_types
    "no_selectors": ([memo(sources=[{"path": PDF, "quote": "Нормативное значение"}]), DOC], [],
                     ("template", "violation", "@m: sources[0].selectors")),
    # один дефект — одно замечание: ref_unknown, а entity_classes по этой ссылке молчит
    "about_atom": ([memo(about=["@doc", "@a"]), DOC, atom("@a")], [], ("ref_unknown", "violation", "@m: about[1]")),
    "one_code": ([memo(codes=["w0"]), DOC], [], ("template", "warning", "@m: codes")),
    "no_codes": ([memo(codes=None), DOC], [], ("template", "warning", "@m: codes")),
    "note_linked": ([note(), atom("@a")], [SEE], None),
    "note_linked_symmetric": ([note(), atom("@a")], [{**SEE, "src": "@a", "dst": "@n"}], None),
    "note_without_link": ([note()], [], ("link_required", "violation", "@n")),
    "note_with_other_link": ([note(), atom("@a")], [SEE, {"rel": "depends_on", "src": "@n", "dst": "@a"}],
                             ("link_not_allowed", "violation", "links[1]")),
    "link_without_note": ([note(), atom("@a")], [{k: v for k, v in SEE.items() if k != "note"}],
                          ("template", "warning", "links[0]: note")),
}


@pytest.mark.parametrize("case", MEMO)
def test_pack_rule(memo_kb, case):
    items, links, expected = MEMO[case]
    _, issues, _ = run(memo_kb, *items, links=links)
    assert issues == ([expected] if expected else [])


def test_inactive_template_rule_does_not_fire(pg, monkeypatch, tmp_path):
    """Пакет убран из AMEM_PACKS и load_vocab повторён: правило его шаблона больше не срабатывает (разд. 13)."""
    extra = pack(tmp_path / "extra", "extra", {"fact_codes": {
        "code": "fact_codes", "version": "1.0.0", "target": "atom", "applies_to": "fact",
        "fields": [{"path": "codes", "required": True, "severity": "warning"}]}})
    monkeypatch.setenv("AMEM_PACKS", os.pathsep.join([str(CHECK_PACK), str(extra)]))
    db.prepare(pg)
    assert run(pg, atom("@a"))[1] == [("template", "warning", "@a: codes")]
    monkeypatch.setenv("AMEM_PACKS", str(CHECK_PACK))
    db.load_vocab(pg)
    assert run(pg, atom("@a"))[1] == []


def test_rule_message_and_link_template(memo_kb):
    batch, _, report = run(memo_kb, memo(codes=["w0"]), DOC, note(), atom("@a"), links=[SEE])
    [issue] = report.issues
    assert issue.message == "Нужны два обозначения."
    assert issue.details == {"template": "memo@1.0.0", "path": "codes", "rule": "min_count"}
    assert "see_also_note@1.0.0" in batch.templates


def test_existing_entity_class_breaks_template_rule(memo_kb):
    existing(memo_kb, entity("@p", cls="project", key="tower"), entity("@d", key="doc1"))
    assert run(memo_kb, memo(about=["ent:doc1", "ent:tower"]))[1] == [("template", "violation", "@m: about[1]")]


@pytest.mark.parametrize("direction", ["from_record", "to_record"])
def test_existing_links_count_for_required_link(memo_kb, direction):
    ends = ("@n", "@a") if direction == "from_record" else ("@a", "@n")       # see_also симметрична
    ids = existing(memo_kb, atom("@n", kind="remark", sources=None), atom("@a", sources=None),
                   links=[{"rel": "see_also", "src": ends[0], "dst": ends[1], "note": {"ru": "то же"}}])
    assert run(memo_kb, Proposal("atom", note(), ids["@n"]))[1] == []
    link_id = memo_kb.execute("SELECT id FROM link").fetchone()[0]
    records.retire_link(memo_kb, link_id, agent=HUMAN, reason="лишняя связь")
    assert run(memo_kb, Proposal("atom", note(), ids["@n"]))[1] == [("link_required", "violation", "@n")]
