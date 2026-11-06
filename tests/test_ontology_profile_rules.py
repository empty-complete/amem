"""Профили: проверка раздела parameters при загрузке пакетов и сведение по extends."""
import os
from pathlib import Path

import pytest
import yaml

from amem import db, packs
from amem.check import templates

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
    monkeypatch.setenv("AMEM_PACKS", os.pathsep.join([str(QUANTITIES), str(ONTOLOGY)]))
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
