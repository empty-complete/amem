"""Схема автопроверки: коды, перечни очереди, отчёт и шаблон decision в ядре (с 1.2.0)."""
import json

import pytest
from packaging.version import Version
from pydantic import ValidationError

from amemo import model_v1, packs

CHECK_CODES = {
    "schema", "unknown_code", "ref_unknown", "template", "ucum", "unit_required", "bounds_order",
    "link_not_allowed", "link_required", "link_pair", "retired_record", "record_error",
    "source_unresolved", "version_missing", "digest_mismatch", "pdf_page_required", "pdf_quote_required",
    "quote_not_found", "quote_fuzzy", "quote_ocr", "number_not_found", "page_moved", "place_unresolved", "no_text",
    "external_source", "source_error", "numbers_unchecked", "label_long", "edition_filled",
    "unknown_property", "out_of_range", "unit_mismatch", "conflict",
    "duplicate", "related",
    "basis_author_model", "basis_without_rule", "confidence_person", "bundle_pack_missing", "bundle_key_collision",
    "bundle_object_conflict", "bundle_pack_conflict",
}

REPORT = {
    "format": "amem.check/1",
    "levels": {"1": "done", "2": "done", "3": "done", "4": "done"},
    "issues": [{"level": 2, "severity": "info", "code": "page_moved", "where": "@a1: sources[0]",
                "message": "Цитата найдена на странице 12, а не 11", "details": {"page": 12}}],
    "degraded": [{"level": 4, "channel": "vector", "reason": "backend_disabled"}],
    "templates": ["has_label@1.0.0", "has_source@1.0.0", "has_value@1.0.0"],
    "records": [{"label": "@a1", "target": "atom", "planned_status": "draft", "risk": []}],
}


def _values(enum):
    return {m.value for m in enum}


def test_check_code_matches_spec_table():
    assert _values(model_v1.CheckCode) == CHECK_CODES


@pytest.mark.parametrize("enum, expected", [
    ("ReviewReason", {"semantic", "warning", "high_risk", "semantic_doubt", "edit", "source_changed",
                      "audit", "calibration", "imported"}),
    ("ReviewItemState", {"queued", "claimed", "done", "obsolete"}),
    ("VerificationMethod", {"llm_judge", "human"}),
    ("VerificationOutcome", {"confirmed", "partial", "refuted", "uncertain"}),
    ("HighRiskRule", {"always", "numeric", "low_confidence"}),
])
def test_queue_enums(enum, expected):
    assert _values(getattr(model_v1, enum)) == expected


def test_template_high_risk_values():
    base = {"code": "decision", "version": "1.0.0", "target": "atom"}
    t = model_v1.Template.model_validate_json(json.dumps({**base, "high_risk": ["always"]}), strict=True)
    assert t.high_risk == [model_v1.HighRiskRule.always]
    with pytest.raises(ValidationError):
        model_v1.Template.model_validate_json(json.dumps({**base, "high_risk": ["sometimes"]}), strict=True)


def test_report_example_passes_strict():
    report = model_v1.CheckReport.model_validate_json(json.dumps(REPORT), strict=True)
    assert report.format == "amem.check/1"
    assert report.issues[0].code == model_v1.CheckCode.page_moved
    assert report.records[0]["label"] == "@a1"


def test_report_format_is_fixed():
    with pytest.raises(ValidationError):
        model_v1.CheckReport.model_validate_json(json.dumps({**REPORT, "format": "amem.check/2"}), strict=True)


def test_issue_rejects_unknown_code_and_level():
    issue = REPORT["issues"][0]
    for bad in ({**issue, "code": "no_such_code"}, {**issue, "level": 5}, {**issue, "level": 0}):
        with pytest.raises(ValidationError):
            model_v1.CheckIssue.model_validate_json(json.dumps(bad), strict=True)


def test_core_pack_has_decision_template():
    pack = packs.load_pack(packs.CORE_PACK)
    assert Version(pack.version) >= Version("1.2.0")             # шаблон decision — с ядра 1.2.0
    decision = {t.code: t for t in pack.templates}["decision"]
    assert decision.applies_to == "decision"
    assert decision.high_risk == [model_v1.HighRiskRule.always]
