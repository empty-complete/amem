"""Блок ui шаблона и форма вида (подпроект 4, часть 4d, задача 17; спецификация разд. 6a.2).

Пакет tests/packs/forms: вид reading (ui с величинами, body none), memo (ui перекрывает тип и подпись),
plain (без своего шаблона — форма из интерфейсов ядра). Проверка пакета — без базы; форма — на настоящей базе."""
import os
from pathlib import Path

import pytest
import yaml

from amem import db, forms, packs, records
from amem.records import Item

PACKS = Path(__file__).with_name("packs")
FORMS = PACKS / "forms"
PERSON = "person:ann"


def _pack(root: Path, template: dict, properties=()) -> Path:
    """Пакет с видом idea и одним шаблоном; properties — коды величин словаря пакета."""
    (root / "vocab").mkdir(parents=True)
    (root / "templates").mkdir()
    (root / "pack.yaml").write_text("name: uitest\nversion: 1.0.0\n", encoding="utf-8")
    vocab = {"kind": [{"code": "idea", "label": {"ru": "идея", "en": "idea"}}]}
    if properties:
        vocab["property"] = [{"code": p, "label": {"ru": p, "en": p}, "unit": "m"} for p in properties]
    for scheme, concepts in vocab.items():
        (root / "vocab" / f"{scheme}.yaml").write_text(
            yaml.safe_dump({"scheme": scheme, "concepts": concepts}, allow_unicode=True), encoding="utf-8")
    body = {"code": "idea", "version": "1.0.0", "target": "atom", "applies_to": "idea", **template}
    (root / "templates" / "idea.yaml").write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
    return root


def _load(root: Path):
    return packs.load_packs([packs.CORE_PACK, root])


# --- проверка блока ui в пакете ---

def test_ui_path_without_rule_is_pack_error(tmp_path):
    root = _pack(tmp_path / "p", {"fields": [{"path": "valid_from"}],
                                  "ui": {"fields": [{"path": "valid_to", "label": {"ru": "до"}}]}})
    with pytest.raises(packs.PackError) as e:
        _load(root)
    text = str(e.value)
    assert "idea.yaml" in text and "шаблон idea" in text and "ui.fields: valid_to" in text


def test_ui_paths_of_rules_ancestors_interfaces_and_base_are_accepted(tmp_path):
    """Свой путь, путь интерфейса ядра (has_label: summary_plain), поле формы about и величина словаря — можно."""
    root = _pack(tmp_path / "p", {"fields": [{"path": "valid_from"}], "ui": {"fields": [
        {"path": "valid_from", "type": "date"}, {"path": "summary_plain", "label": {"ru": "Коротко"}},
        {"path": "about", "label": {"ru": "Прибор"}}, {"path": "content.values[property=depth]"}]}},
        properties=["depth"])
    [idea] = [t for p in _load(root) if p.name == "uitest" for t in p.templates]
    assert [f.path for f in idea.ui.fields] == ["valid_from", "summary_plain", "about", "content.values[property=depth]"]


@pytest.mark.parametrize("ui, words", [
    ({"fields": [{"path": "content.values[property=depth]"}]}, "property depth нет в словаре"),
    ({"fields": [{"path": "about"}, {"path": "about"}]}, "путь повторяется"),
])
def test_ui_bad_fields(tmp_path, ui, words):
    with pytest.raises(packs.PackError, match=words):
        _load(_pack(tmp_path / "p", {"ui": ui}))


def test_ui_only_for_atom_and_entity(tmp_path):
    root = _pack(tmp_path / "p", {})
    (root / "templates" / "idea.yaml").write_text(yaml.safe_dump({
        "code": "seealso", "version": "1.0.0", "target": "link", "applies_to": "see_also",
        "ui": {"body": "none"}}), encoding="utf-8")
    with pytest.raises(packs.PackError, match="ui — только у шаблонов atom и entity"):
        _load(root)


def test_ui_values_are_closed(tmp_path):
    with pytest.raises(packs.PackError, match="body"):
        _load(_pack(tmp_path / "p", {"ui": {"body": "maybe"}}))


# --- форма вида ---

@pytest.fixture
def kb(pg, monkeypatch):
    monkeypatch.setenv("AMEM_PACKS", os.pathsep.join(
        [str(FORMS), str(PACKS / "quantities"), str(PACKS / "ontology")]))
    db.prepare(pg)
    return pg


def _view(conn, code, target="atom") -> dict:
    [view] = forms.views(conn, target=target, code=code)
    return view


def test_form_types_from_paths(kb):
    """about → object, величины ui → quantity (property, unit словаря), valid_from и valid_to → period,
    rank (перечень со словарём) → choice, derived_from (rel через поле) → record, tags → tags."""
    form = _view(kb, "reading")["form"]
    assert [(f["key"], f["path"], f["type"]) for f in form] == [
        ("about", "about", "object"),
        ("humidity", "content.values[property=humidity]", "quantity"),
        ("pressure", "content.values[property=pressure]", "quantity"),
        ("valid", "valid_from", "period"),
        ("rank", "rank", "choice"),
        ("derived_from", "derived_from", "record"),
        ("tags", "tags", "tags"),
    ]
    by = {f["key"]: f for f in form}
    assert by["about"]["accepts"] == {"entity_classes": ["artifact"], "kinds": []} and by["about"]["required"]
    assert (by["humidity"]["property"], by["humidity"]["unit"]) == ("humidity", "%")
    assert (by["pressure"]["property"], by["pressure"]["unit"]) == ("pressure", "kPa")
    # правило content.values просит одно значение из двух величин — ни одна по отдельности не обязательна
    assert not by["humidity"]["required"] and not by["pressure"]["required"]
    assert by["rank"]["scheme"] == "rank"
    assert by["derived_from"]["accepts"] == {"entity_classes": [], "kinds": [], "rel": "derived_from"}
    assert by["tags"]["accepts"] is None and not by["tags"]["required"]


def test_labels_from_ui_then_vocabulary(kb):
    by = {f["key"]: f for f in _view(kb, "reading")["form"]}
    assert by["humidity"]["label"] == {"ru": "Влажность воздуха", "en": "Air humidity"}       # из ui
    assert by["pressure"]["label"] == {"ru": "давление", "en": "pressure"}                     # из словаря property
    assert by["pressure"]["hint"] == {"ru": "Давление воздуха."}
    assert by["about"]["label"] == forms.LABELS["about"]


def test_ui_type_and_label_override(kb):
    by = {f["key"]: f for f in _view(kb, "memo")["form"]}
    assert (by["tags"]["type"], by["tags"]["label"], by["tags"]["hint"]) == ("text", {"ru": "Метки"},
                                                                             {"ru": "Через запятую."})
    assert (by["valid_from"]["type"], by["valid_from"]["required"]) == ("text", True)


def test_body_and_widgets(kb):
    reading, memo, plain = (_view(kb, c) for c in ("reading", "memo", "plain"))
    assert (reading["body"], reading["widgets"]) == ("none", ["sources", "values_table"])
    assert (memo["body"], memo["widgets"]) == ("wanted", ["sources", "links"])
    assert (plain["body"], plain["widgets"]) == ("wanted", ["sources", "links"])


def test_interface_rules_are_checks_not_fields(kb):
    """Вид без своего шаблона — форма из интерфейсов: правила подписи, источников и единиц полями не становятся."""
    for code in ("plain", "note", "fact"):
        assert [f["path"] for f in _view(kb, code)["form"]] == ["about", "tags"], code


def test_entity_profile_is_not_a_form_field(kb):
    """Профиль сущности (parameters) — значения атомов parameter, их показывает карточка: у тела сущности нет content."""
    device = _view(kb, "device", "entity")
    assert [f["path"] for f in device["form"]] == ["codes"]
    assert device["family"] == "object" and device["pack"] == "ontology"


def test_views_of_every_kind_and_class(kb):
    done = records.commit(kb, [Item("atom", {"kind": "plain", "label": {"ru": "Проба"}, "sources": []})],
                          agent=PERSON)
    assert done.revisions
    atoms = {v["code"]: v for v in forms.views(kb, target="atom")}
    kinds = {code for (code,) in kb.execute("SELECT code FROM concept WHERE scheme = 'kind'").fetchall()}
    assert set(atoms) == kinds and {"note", "decision", "fact", "reading"} <= kinds
    assert all(v["target"] == "atom" and v["applies_to"] == v["code"] and not v["editable"] for v in atoms.values())
    assert (atoms["reading"]["family"], atoms["plain"]["family"], atoms["note"]["family"]) == ("source", "work", "work")
    assert (atoms["reading"]["pack"], atoms["note"]["pack"]) == ("forms", "core")
    assert atoms["reading"]["description"] == {"ru": "Показание: о каком приборе, значения, когда действует."}
    assert atoms["plain"]["description"] == {"ru": "Вид без своего шаблона."}                   # определение вида
    assert (atoms["plain"]["records"], atoms["reading"]["records"]) == (1, 0)
    everything = forms.views(kb)
    assert {v["target"] for v in everything} == {"atom", "entity"}
    assert len(everything) == len(atoms) + len(forms.views(kb, target="entity"))
