"""Профили: проверка раздела parameters при загрузке пакетов и сведение по extends."""
import os
from pathlib import Path

import pytest
import yaml

from amemo import db, packs
from amemo.check import templates

PACKS = Path(__file__).with_name("packs")
ONTOLOGY, QUANTITIES = PACKS / "ontology", PACKS / "quantities"


def _with_template(tmp_path, body, requires=True):
    root = tmp_path / "p"
    (root / "templates").mkdir(parents=True)
    manifest = {"name": "p", "version": "1.0.0"}
    if requires:
        manifest["requires"] = {"quantities": ">=1.0.0"}
    (root / "pack.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (root / "templates" / "t.yaml").write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
    return root


def _entity_template(**extra):
    return {"code": "t", "version": "1.0.0", "target": "entity", **extra}


def test_ontology_pack_loads():
    loaded = packs.load_packs([packs.CORE_PACK, QUANTITIES, ONTOLOGY])
    assert [p.name for p in loaded] == ["core", "quantities", "ontology"]


@pytest.mark.parametrize("parameters, message", [
    ([{"property": "nope"}], "property nope — нет в словаре property"),
    ([{"property": "mass", "origin": "rumor"}], "origin rumor — нет в словаре parameter_origin"),
    ([{"property": "mass", "default": {"amount": 1, "unit": "kilos"}}], "default.unit kilos — не код UCUM"),
    ([{"property": "mass", "default": {"amount": 1, "unit": "m"}}], "default.unit m не переводится в kg"),
    ([{"property": "mass"}, {"property": "mass"}], "property mass повторяется"),
])
def test_bad_parameters_name_file(tmp_path, parameters, message):
    root = _with_template(tmp_path, _entity_template(parameters=parameters))
    with pytest.raises(packs.PackError, match=message) as e:
        packs.load_packs([packs.CORE_PACK, QUANTITIES, root])
    assert "t.yaml" in str(e.value)


def test_parameters_only_for_entities(tmp_path):
    body = {"code": "t", "version": "1.0.0", "target": "atom", "parameters": [{"property": "mass"}]}
    root = _with_template(tmp_path, body)
    with pytest.raises(packs.PackError, match="parameters — только у шаблонов target entity"):
        packs.load_packs([packs.CORE_PACK, QUANTITIES, root])


def test_parameters_merge_by_property(pg, monkeypatch):
    monkeypatch.setenv("AMEMO_PACKS", os.pathsep.join([str(QUANTITIES), str(ONTOLOGY)]))
    db.prepare(pg)
    active = templates.active(pg)
    rules = templates.rules_for(active, "entity", "sensor")
    assert [r["property"] for r in rules.parameters] == ["mass", "temperature", "length"]
    temperature = rules.parameters[1]
    assert temperature["required"] is True and temperature["origin"] == "measured"
    assert "default" not in temperature                      # правило потомка заменяет правило предка целиком
    assert rules.parameter_origins["temperature"] == "sensor@1.0.0"
    assert rules.parameter_origins["mass"] == "device@1.0.0"
    assert templates.rules_for(active, "entity", "document").parameters == ()


def _with_properties(tmp_path, parameters):
    """Пакет со своими величинами: abs_temperature в K и ratio без единицы."""
    root = _with_template(tmp_path, _entity_template(parameters=parameters))
    (root / "vocab").mkdir()
    (root / "vocab" / "property.yaml").write_text(yaml.safe_dump({"scheme": "property", "concepts": [
        {"code": "abs_temperature", "label": {"ru": "абсолютная температура", "en": "absolute temperature"},
         "definition": {"ru": "Температура по шкале Кельвина."}, "unit": "K"},
        {"code": "ratio", "label": {"ru": "доля", "en": "ratio"}, "definition": {"ru": "Доля без единицы в словаре."}},
    ]}, allow_unicode=True), encoding="utf-8")
    return root


def test_default_in_cel_for_kelvin_property_is_accepted(tmp_path):
    root = _with_properties(tmp_path, [{"property": "abs_temperature", "default": {"amount": 20, "unit": "Cel"}}])
    loaded = packs.load_packs([packs.CORE_PACK, QUANTITIES, root])
    [t] = loaded[-1].templates
    assert t.parameters[0].default.unit == "Cel"


def test_default_of_property_without_unit_is_checked_only_for_ucum(tmp_path):
    ok = _with_properties(tmp_path / "ok", [{"property": "ratio", "default": {"amount": 0.5, "unit": "1"}}])
    assert packs.load_packs([packs.CORE_PACK, QUANTITIES, ok])[-1].templates[0].parameters[0].default.amount == 0.5
    bad = _with_properties(tmp_path / "bad", [{"property": "ratio", "default": {"amount": 1, "unit": "kilos"}}])
    with pytest.raises(packs.PackError, match="default.unit kilos — не код UCUM"):
        packs.load_packs([packs.CORE_PACK, QUANTITIES, bad])
