"""Шаблоны пакетов: читаются строго, пути ведут на настоящие поля схемы, правила осмысленны и не повторяются,
наследование без циклов. Движок проверяется на ядре и на пакете-примере tests/packs/example.

Обход путей по схеме — packs.check_path: тот же, что проверяет шаблоны любого пакета при загрузке."""
from pathlib import Path

import pytest
import yaml

from amemo import packs

SCHEMA = yaml.safe_load(packs.SCHEMA_FILE.read_text(encoding="utf-8"))
REF_ENT = "^(ent:"          # так начинается шаблон поля-ссылки на сущность
EXAMPLE = Path(__file__).with_name("packs") / "example"


def _unit_paths(class_name: str, prefix: str = "", seen: tuple = ()) -> set[str]:
    """Все пути к полям unit, достижимые из класса, — чтобы has_value не пропустил ни одного."""
    out = set()
    for name, slot in packs.field_attrs(class_name).items():
        slot = slot or {}
        rng = slot.get("range", "string")
        if name == "unit":
            out.add(prefix + name)
        elif rng in SCHEMA["classes"] and rng != "Any" and rng not in seen:
            step = name + ("[]" if slot.get("multivalued") else "")
            out |= _unit_paths(rng, f"{prefix}{step}.", seen + (class_name,))
    return out


PACKS = packs.load_packs([packs.CORE_PACK, EXAMPLE])
TEMPLATES = [t for p in PACKS for t in p.templates]
BY_CODE = {t.code: t for t in TEMPLATES}
# коды, которыми может быть applies_to: вид атома, класс сущности, вид связи — из понятий пакетов
APPLIES_TO = {
    "atom": {c.code for p in PACKS for c in p.concepts if c.scheme == "kind"},
    "entity": {c.code for p in PACKS for c in p.concepts if c.scheme == "entity_class"},
    "link": {c.code for p in PACKS for c in p.concepts if c.scheme == "rel"},
}


@pytest.mark.parametrize("t", TEMPLATES, ids=[t.code for t in TEMPLATES])
def test_template_rules_point_to_real_fields(t):
    for rule in t.fields or []:
        slot = packs.check_path(rule.path, t.target)
        last = rule.path.split(".")[-1]
        # правило без проверок — поле формы (спецификация разд. 6a.2): бывает только у шаблона с блоком ui
        assert rule.required or rule.min_count or rule.ucum or rule.selector_types or rule.entity_classes \
            or t.ui is not None, f"{t.code}: правило {rule.path} ничего не проверяет и не поле формы (нет ui)"
        if rule.ucum:
            assert last == "unit", f"{t.code}: ucum у поля {rule.path}"
        if rule.selector_types:
            assert last == "selectors", f"{t.code}: selector_types у поля {rule.path}"
        if rule.min_count is not None:
            assert slot.get("multivalued"), f"{t.code}: min_count у поля, которое не список: {rule.path}"
        if rule.entity_classes:
            assert str(slot.get("pattern", "")).startswith(REF_ENT), f"{t.code}: entity_classes у поля не-ссылки: {rule.path}"
    paths = [rule.path for rule in t.fields or []]
    assert len(paths) == len(set(paths)), f"{t.code}: путь повторяется — правила одного поля пишутся одним правилом"


def test_template_codes_targets_and_inheritance():
    assert len(BY_CODE) == len(TEMPLATES)
    applied = [(t.target, t.applies_to) for t in TEMPLATES if t.applies_to]
    assert len(applied) == len(set(applied)), "у вида или класса может быть только один шаблон"
    for t in TEMPLATES:
        if t.applies_to:
            assert t.applies_to in APPLIES_TO[t.target], t.code
        for parent in t.extends or []:
            assert parent in BY_CODE, f"{t.code}: нет шаблона {parent}"
            assert BY_CODE[parent].target == t.target, f"{t.code}: {parent} — для другого target"
    # ядро — интерфейсы для всех записей; свой шаблон вида — у пакета-примера
    assert {"has_label", "has_source", "has_value"} <= {t.code for t in TEMPLATES if not t.applies_to}
    assert BY_CODE["idea"].applies_to == "idea" and BY_CODE["idea"].extends == ["has_label"]


def test_template_inheritance_has_no_cycles():
    def walk(code, chain):
        assert code not in chain, f"цикл в extends: {' → '.join(chain + (code,))}"
        for parent in BY_CODE[code].extends or []:
            walk(parent, chain + (code,))

    for code in BY_CODE:
        walk(code, ())


def test_link_rules_are_consistent():
    rels = {c.code: c for p in PACKS for c in p.concepts if c.scheme == "rel"}
    via_field = {code for code, c in rels.items() if c.via_field}
    for t in TEMPLATES:
        if not t.links:
            continue
        for req in t.links.required or []:
            assert req.rel in set(t.links.allowed or []) | via_field, f"{t.code}: обязательная связь {req.rel} не разрешена"
            if req.to_classes:
                assert any(p.endswith(">entity") for p in rels[req.rel].pairs or []), \
                    f"{t.code}: to_classes у связи {req.rel}, которая не ведёт к сущности"


def test_has_value_checks_every_unit():
    covered = {rule.path for rule in BY_CODE["has_value"].fields if rule.ucum}
    assert covered == _unit_paths("AtomPayload")


def test_bad_template_file_names_the_file(tmp_path):
    (tmp_path / "pack.yaml").write_text("name: bad\nversion: 1.0.0\n", encoding="utf-8")
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "bad.yaml").write_text(
        "code: bad\nversion: 1.0.0\ntarget: atom\nfields:\n  - {path: label, required: \"no\"}\n", encoding="utf-8")
    with pytest.raises(packs.PackError, match="bad.yaml"):
        packs.load_pack(tmp_path)


def test_yaml_syntax_error_names_the_file(tmp_path):
    (tmp_path / "pack.yaml").write_text("name: bad\nversion: 1.0.0\n", encoding="utf-8")
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "broken.yaml").write_text("code: [broken\n", encoding="utf-8")
    with pytest.raises(packs.PackError, match="broken.yaml"):
        packs.load_pack(tmp_path)
