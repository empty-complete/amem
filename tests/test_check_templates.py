"""Шаблоны автопроверки: проверка при загрузке пакетов (разд. 3.6 спецификации подпроекта 3) и сведение
шаблонов записи по наследованию (разд. 3.2).

Загрузка проверяется без базы — на временных пакетах; сведение — на базе с тестовым пакетом tests/packs/check,
так что действующие шаблоны читаются из template_active."""
import os
from pathlib import Path

import pytest
import yaml

from amem import db, packs
from amem.check import templates

CHECK = Path(__file__).with_name("packs") / "check"
INTERFACES = ("has_label@1.0.0", "has_source@1.0.0", "has_value@1.0.0")


def _t(code, **extra):
    """Тело шаблона: по умолчанию — интерфейс атома."""
    return {"code": code, "version": "1.0.0", "target": "atom", **extra}


def _pack(root: Path, name: str, templates_: dict[str, dict], kinds=()) -> Path:
    """Временный пакет: шаблоны — {имя файла без .yaml: тело}, kinds — свои виды атомов."""
    (root / "templates").mkdir(parents=True)
    (root / "pack.yaml").write_text(f"name: {name}\nversion: 1.0.0\n", encoding="utf-8")
    if kinds:
        (root / "vocab").mkdir()
        (root / "vocab" / "kind.yaml").write_text(yaml.safe_dump({"scheme": "kind", "concepts": [
            {"code": k, "label": {"ru": k, "en": k}, "definition": {"ru": f"Вид {k} для теста."}} for k in kinds]},
            allow_unicode=True), encoding="utf-8")
    for file, body in templates_.items():
        (root / "templates" / f"{file}.yaml").write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
    return root


# --- проверка при загрузке ---

def test_check_pack_loads():
    loaded = packs.load_packs([packs.CORE_PACK, CHECK])
    check = next(p for p in loaded if p.name == "check")
    assert {t.code for t in check.templates} == {"rule", "idea"}
    props = {c.code: c for c in check.concepts if c.scheme == "property"}
    assert (props["temperature"].unit, props["temperature"].plausible_min, props["temperature"].plausible_max) \
        == ("Cel", -80, 200)
    assert {code: props[code].unit for code in ("length", "pressure")} == {"length": "m", "pressure": "kPa"}


BAD = {
    "extends_missing": ({"memo": _t("memo", applies_to="memo", extends=["nope"])}, r"memo\.yaml.*nope"),
    "extends_other_target": ({"memo": _t("memo", applies_to="memo", extends=["ent_base"]),
                              "ent_base": _t("ent_base", target="entity")}, r"memo\.yaml.*ent_base.*entity"),
    "cycle": ({"a": _t("a", extends=["b"]), "b": _t("b", extends=["a"])}, r"b\.yaml.*цикл.*a → b → a"),
    "self_cycle": ({"a": _t("a", extends=["a"])}, r"a\.yaml.*цикл.*a → a"),
    "applies_to_unknown": ({"memo": _t("memo", applies_to="nope")}, r"memo\.yaml.*applies_to nope"),
    "applies_to_other_scheme": ({"memo": _t("memo", target="entity", applies_to="memo")},
                                r"memo\.yaml.*applies_to memo"),
    "path": ({"memo": _t("memo", fields=[{"path": "content.vals", "required": True}])},
             r"memo\.yaml.*content\.vals.*vals"),
    "selector_types": ({"memo": _t("memo", fields=[{"path": "sources[].selectors", "selector_types": ["nope"]}])},
                       r"memo\.yaml.*selector_types.*nope"),
    "entity_classes": ({"memo": _t("memo", fields=[{"path": "about", "entity_classes": ["nope"]}])},
                       r"memo\.yaml.*entity_classes.*nope"),
    "links_allowed": ({"memo": _t("memo", links={"allowed": ["refines", "nope"]})}, r"memo\.yaml.*links.*nope"),
    "links_required_rel": ({"memo": _t("memo", links={"required": [{"rel": "nope"}]})}, r"memo\.yaml.*links.*nope"),
    "links_to_classes": ({"memo": _t("memo", links={"required": [{"rel": "about", "to_classes": ["nope"]}]})},
                         r"memo\.yaml.*to_classes.*nope"),
    "pair_twice": ({"memo": _t("memo", applies_to="memo"), "memo_two": _t("memo_two", applies_to="memo")},
                   r"memo_two\.yaml.*atom memo.*memo"),
    "code_twice_in_pack": ({"memo": _t("memo"), "memo_copy": _t("memo")}, r"memo_copy\.yaml.*memo.*memo\.yaml"),
}


@pytest.mark.parametrize("case", BAD)
def test_bad_template_is_rejected_with_file(tmp_path, case):
    body, match = BAD[case]
    bad = _pack(tmp_path / "bad", "bad", body, kinds=["memo"])
    with pytest.raises(packs.PackError, match=match):
        packs.load_packs([packs.CORE_PACK, bad])


@pytest.mark.parametrize("path, match", [
    ("content.vals", "у Content нет поля vals"),
    ("sources.selectors", r"\[\] ставится"),                   # у промежуточного списка нет []
    ("content[].values", r"\[\] ставится"),                    # [] у поля, которое не список
    ("sources[].selectors[]", r"\[\] у последнего поля"),
    ("label.ru.x", "ru.*не класс"),                            # за строкой полей нет
])
def test_bad_rule_path_is_rejected(tmp_path, path, match):
    bad = _pack(tmp_path / "bad", "bad", {"memo": _t("memo", fields=[{"path": path, "required": True}])})
    with pytest.raises(packs.PackError, match=r"memo\.yaml.*" + match):
        packs.load_packs([packs.CORE_PACK, bad])


def test_check_path_returns_last_field():
    assert packs._check_path("content.values", "atom")["multivalued"] is True
    assert packs._check_path("sources[].selectors", "atom")["range"] == "Selector"
    assert packs._check_path("edition_of", "entity")["pattern"].startswith("^(ent:")
    assert packs._check_path("rel", "link")["required"] is True


def test_template_code_in_two_packs_is_rejected(tmp_path):
    a = _pack(tmp_path / "a", "pack_a", {"memo": _t("memo", applies_to="memo")}, kinds=["memo"])
    b = _pack(tmp_path / "b", "pack_b", {"memo_b": _t("memo")})
    with pytest.raises(packs.PackError, match=r"memo_b\.yaml.*шаблон memo.*pack_a"):
        packs.load_packs([packs.CORE_PACK, a, b])


def test_template_overriding_core_is_rejected(tmp_path):
    other = _pack(tmp_path / "other", "other", {"label": _t("has_label")})
    with pytest.raises(packs.PackError, match=r"label\.yaml.*шаблон has_label.*core"):
        packs.load_packs([packs.CORE_PACK, other])


def test_extends_into_other_pack_is_allowed(tmp_path):
    a = _pack(tmp_path / "a", "pack_a", {"base": _t("base", fields=[{"path": "body", "required": True}])})
    b = _pack(tmp_path / "b", "pack_b", {"memo": _t("memo", applies_to="memo", extends=["base", "has_label"])},
              kinds=["memo"])
    assert [p.name for p in packs.load_packs([packs.CORE_PACK, a, b])] == ["core", "pack_a", "pack_b"]


def test_load_vocab_rejects_template_code_twice_before_writing(pg, monkeypatch, tmp_path):
    a = _pack(tmp_path / "a", "pack_a", {"memo": _t("memo")})
    b = _pack(tmp_path / "b", "pack_b", {"memo": _t("memo")})
    monkeypatch.setenv("AMEM_PACKS", os.pathsep.join([str(a), str(b)]))
    with pytest.raises(packs.PackError, match=r"memo\.yaml.*pack_a"):     # а не UniqueViolation template_active
        db.prepare(pg)
    assert pg.execute("SELECT count(*) FROM pack").fetchone()[0] == 0


# --- сведение ---

def _prepare(pg, monkeypatch, *extra: Path) -> dict[str, dict]:
    monkeypatch.setenv("AMEM_PACKS", os.pathsep.join(str(p) for p in (CHECK, *extra)))
    db.prepare(pg)
    return templates.active(pg)


def test_active_reads_bodies_of_active_versions(pg, monkeypatch):
    active = _prepare(pg, monkeypatch)
    assert set(active) == {"has_label", "has_source", "has_value", "decision", "rule", "idea"}
    assert active["rule"]["version"] == "1.0.0" and active["rule"]["applies_to"] == "rule"
    monkeypatch.delenv("AMEM_PACKS")
    db.prepare(pg)
    assert set(templates.active(pg)) == {"has_label", "has_source", "has_value", "decision"}


def test_rules_of_kind_with_own_template(pg, monkeypatch):
    rules = templates.rules_for(_prepare(pg, monkeypatch), "atom", "rule")
    assert rules.templates == ("has_label@1.0.0", "has_source@1.0.0", "has_value@1.0.0", "rule@1.0.0")
    assert rules.high_risk == frozenset({"numeric"})
    assert rules.allowed == frozenset({"refines", "see_also", "about"})
    assert rules.fields["content.values"]["severity"] == "violation"
    assert rules.fields["label"]["required"] is True                         # от интерфейса has_label
    assert rules.fields["content.values[].unit"]["ucum"] is True             # от интерфейса has_value
    assert rules.required_links == ({"rel": "about", "to_classes": ["document"], "severity": "warning"},)


def test_decision_is_always_high_risk(pg, monkeypatch):
    rules = templates.rules_for(_prepare(pg, monkeypatch), "atom", "decision")
    assert rules.templates == (*INTERFACES, "decision@1.0.0")
    assert rules.high_risk == frozenset({"always"})


def test_kind_without_template_gets_only_interfaces(pg, monkeypatch):
    active = _prepare(pg, monkeypatch)
    rules = templates.rules_for(active, "atom", "fact")
    assert rules.templates == INTERFACES
    assert rules.allowed is None and rules.required_links == () and rules.high_risk == frozenset()
    assert set(rules.fields) == {"label", "summary_plain", "sources", "sources[].selectors",
                                 "content.values[].unit", "content.values[].qualifiers[].unit",
                                 "content.table.columns[].unit", "content.formula.symbols[].unit", "qualifiers[].unit"}
    nothing = templates.rules_for(active, "entity", "document")             # у сущностей шаблонов нет
    assert nothing == templates.Rules((), {}, None, (), frozenset())


def test_descendant_rule_replaces_interface_rule(pg, monkeypatch, tmp_path):
    memo = _pack(tmp_path / "memo", "memo", {"memo": _t("memo", applies_to="memo", fields=[
        {"path": "label", "required": True, "severity": "warning"}])}, kinds=["memo"])
    rules = templates.rules_for(_prepare(pg, monkeypatch, memo), "atom", "memo")
    assert rules.templates == (*INTERFACES, "memo@1.0.0")
    assert rules.fields["label"]["severity"] == "warning"
    assert rules.fields["summary_plain"]["severity"] == "violation"         # остальное от has_label — на месте


def test_of_two_interfaces_larger_code_wins(pg, monkeypatch, tmp_path):
    iface = _pack(tmp_path / "iface", "iface", {
        "zz": _t("zz_body", fields=[{"path": "body", "required": True, "severity": "violation"}]),
        "aa": _t("aa_body", fields=[{"path": "body", "required": True, "severity": "warning"}])})
    rules = templates.rules_for(_prepare(pg, monkeypatch, iface), "atom", "fact")
    assert rules.templates == ("aa_body@1.0.0", *INTERFACES, "zz_body@1.0.0")
    assert rules.fields["body"]["severity"] == "violation"


@pytest.fixture
def chain(tmp_path):
    """memo → [note_a, note_b]; note_a → [note_c]; note_b → [note_c, has_label]: note_c встречается дважды."""
    return _pack(tmp_path / "chain", "chain", {
        "memo": _t("memo", applies_to="memo", extends=["note_a", "note_b"], high_risk=["always"]),
        "note_a": _t("note_a", applies_to="note_a", extends=["note_c"], links={"allowed": ["refines"]}),
        "note_b": _t("note_b", applies_to="note_b", extends=["note_c", "has_label"],
                     fields=[{"path": "body", "required": True, "severity": "violation"}],
                     links={"required": [{"rel": "about", "to_classes": ["project"]}]}),
        "note_c": _t("note_c", applies_to="note_c", high_risk=["numeric"],
                     fields=[{"path": "body", "required": True, "severity": "warning"}],
                     links={"allowed": ["see_also"], "required": [
                         {"rel": "about", "to_classes": ["document"]}, {"rel": "see_also"}]}),
    }, kinds=["memo", "note_a", "note_b", "note_c"])


def test_extends_unfolds_left_to_right_once(pg, monkeypatch, chain):
    active = _prepare(pg, monkeypatch, chain)
    rules = templates.rules_for(active, "atom", "memo")
    assert rules.templates == (*INTERFACES, "note_c@1.0.0", "note_a@1.0.0", "note_b@1.0.0", "memo@1.0.0")
    # предок без своих extends — только интерфейсы и он сам
    assert templates.rules_for(active, "atom", "note_c").templates == (*INTERFACES, "note_c@1.0.0")


def test_merge_follows_application_order(pg, monkeypatch, chain):
    rules = templates.rules_for(_prepare(pg, monkeypatch, chain), "atom", "memo")
    assert rules.fields["body"]["severity"] == "violation"                  # note_b применён после note_c
    assert rules.allowed == frozenset({"refines"})                          # последний задавший — note_a
    assert rules.required_links == ({"rel": "about", "to_classes": ["project"]}, {"rel": "see_also"})
    assert rules.high_risk == frozenset({"always", "numeric"})
