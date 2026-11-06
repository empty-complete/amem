"""Схема подпроекта 3c: основание и уверенность атома, правило skip_if_set, профиль шаблона, происхождение."""
import json

import pytest

from amem import model_v1
from v1_support import example, pydantic_errors, json_errors

ATOM = "atom_fact.yaml"          # нейтральный пример атома из tests/v1_examples


def _atom(**extra):
    return {**example(ATOM), **extra}


def test_basis_enum():
    assert [m.value for m in model_v1.Basis] == ["default", "assumed", "author"]


@pytest.mark.parametrize("basis", ["default", "assumed", "author"])
def test_atom_accepts_basis(basis):
    assert pydantic_errors("AtomPayload", _atom(basis=basis)) == []
    assert json_errors("AtomPayload", _atom(basis=basis)) == []


def test_atom_rejects_unknown_basis():
    assert pydantic_errors("AtomPayload", _atom(basis="guess"))


@pytest.mark.parametrize("value, ok", [(0.0, True), (0.8, True), (1.0, True), (1.5, False), (-0.1, False), ("0.8", False)])
def test_atom_confidence_bounds(value, ok):
    assert (pydantic_errors("AtomPayload", _atom(confidence=value)) == []) is ok


def test_field_rule_skip_if_set():
    rule = model_v1.FieldRule.model_validate({"path": "sources", "required": True, "skip_if_set": "basis"}, strict=True)
    assert rule.skip_if_set == "basis"


def test_template_parameters():
    body = {"code": "device", "version": "1.0.0", "target": "entity", "applies_to": "device",
            "parameters": [{"property": "mass", "required": True, "group": "body",
                            "default": {"amount": 1.0, "unit": "kg"},
                            "ask": {"ru": "изготовитель"}, "hint": {"ru": "паспорт"}, "when": {"ru": "всегда"}}]}
    t = model_v1.Template.model_validate_json(json.dumps(body), strict=True)
    assert t.parameters[0].property == "mass" and t.parameters[0].required is True
    bad = {**body, "parameters": [{"required": True}]}
    with pytest.raises(ValueError):
        model_v1.Template.model_validate_json(json.dumps(bad), strict=True)


def test_provenance_fields():
    p = model_v1.Provenance.model_validate({
        "origin_base": "01932f5e-7a3b-7c4d-8e9f-0123456789ab",
        "origin_revision_hash": "sha256-c1:" + "0" * 64, "origin_agent": "person:alice"}, strict=True)
    assert p.origin_agent == "person:alice"
    with pytest.raises(ValueError):
        model_v1.Provenance.model_validate({"origin_revision_hash": "sha256:" + "0" * 64}, strict=True)


def test_new_enum_values():
    assert "imported" in {m.value for m in model_v1.ReviewReason}
    assert "low_confidence" in {m.value for m in model_v1.HighRiskRule}
    for code in ["basis_author_model", "basis_without_rule", "confidence_person",
                 "bundle_pack_missing", "bundle_key_collision"]:
        assert code in {m.value for m in model_v1.CheckCode}
