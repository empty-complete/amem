"""Схема v1: примеры из исследования проходят и Pydantic, и JSON Schema; неверные данные отклоняются обеими."""
import json
from pathlib import Path

import pytest
import yaml

from v1_support import JSON_SCHEMA, changed, example, json_errors, pydantic_errors

SCHEMA_YAML = Path(__file__).resolve().parents[1] / "amem" / "schema" / "amem_v1.yaml"

VALID = [
    ("AtomPayload", "atom_fact.yaml"),
    ("AtomPayload", "atom_formula_10_1.yaml"),
    ("AtomPayload", "atom_table_11_1.yaml"),
    ("EntityPayload", "entity_sp20.yaml"),
    ("EntityPayload", "entity_sp20_2016.yaml"),
    ("LinkPayload", "link_depends_on.yaml"),
    ("Bundle", "bundle.yaml"),
]


@pytest.mark.parametrize("class_name, name", VALID)
def test_valid_examples(class_name, name):
    data = example(name)
    assert pydantic_errors(class_name, data) == []
    assert json_errors(class_name, data) == []


ATOM_V4 = "atm:9b2e4c1a-1d2f-4c3b-8a9e-1f2e3d4c5b6a"     # UUID версии 4, а не 7
ATOM_V7 = "atm:01929f3a-7c4e-7b21-9a6f-3d2c8e1f0a55"

INVALID = {
    "старый вид «таблица»": lambda d: d.update(kind="таблица"),
    "about ведёт на атом": lambda d: d.update(about=[ATOM_V7]),
    "старое поле props": lambda d: d.update(props={"w0, кПа": 0.3}),
    "нет подписи": lambda d: d.pop("label"),
    "подпись без слотов": lambda d: d.update(label={}),
    "подпись с null в обоих слотах": lambda d: d.update(label={"ru": None, "en": None}),
    "подпись с неизвестным языком": lambda d: d.update(label={"de": "Winddruck"}),
    "ссылка с UUID v4": lambda d: d.update(about=[ATOM_V4.replace("atm:", "ent:")]),
    "единица в коде столбца": lambda d: d["content"]["table"]["columns"][1].update(code="w0, кПа"),
    "неизвестный селектор": lambda d: d["sources"][0]["selectors"].append({"type": "стр", "value": "27"}),
    "редакция строкой вместо даты": lambda d: d.update(valid_from="2016 с изм. № 1–6"),
    "временное имя без @": lambda d: d.update(ref="sp20"),
    "число строкой": lambda d: d["content"].update(values=[{"property": "wind_pressure_norm", "amount": "0.30", "unit": "kPa"}]),
    "булево вместо числа": lambda d: d["content"].update(values=[{"property": "wind_pressure_norm", "amount": True, "unit": "kPa"}]),
    "дата числом": lambda d: d.update(valid_from=1496534400),
    "метка с объектом": lambda d: d.update(tags=["объект:кампус"]),
    "метка с объектом и пробелом": lambda d: d.update(tags=["объект: кампус"]),
    "метка с другой приставкой": lambda d: d.update(tags=["prj:campus"]),
}


@pytest.mark.parametrize("change", INVALID.values(), ids=INVALID.keys())
def test_invalid_atoms_rejected(change):
    data = changed("atom_table_11_1.yaml", change)
    assert pydantic_errors("AtomPayload", data)
    assert json_errors("AtomPayload", data)


LABELS = {
    "только ru": {"ru": "Нормативное значение ветрового давления"},
    "только en": {"en": "Normative wind pressure"},
    "оба слота": {"ru": "Нормативное значение ветрового давления", "en": "Normative wind pressure"},
    "en и null в ru": {"ru": None, "en": "Normative wind pressure"},
}


@pytest.mark.parametrize("label", LABELS.values(), ids=LABELS.keys())
def test_lang_string_needs_one_slot(label):
    """LangString: хотя бы один из слотов ru, en — строка; ни один по отдельности не обязателен."""
    data = changed("atom_table_11_1.yaml", lambda d: d.update(label=label, summary_plain=label))
    assert pydantic_errors("AtomPayload", data) == []
    assert json_errors("AtomPayload", data) == []


def test_tags_with_designations_accepted():
    """Метка — свободный текст, в нём бывают обозначения норм с двоеточием; запрещена только приставка «объект:…»."""
    data = changed("atom_table_11_1.yaml",
                   lambda d: d.update(tags=["ISO 6946:2017", "EN 1991-1-3:2003", "масштаб 1:100", "навес"]))
    assert pydantic_errors("AtomPayload", data) == []
    assert json_errors("AtomPayload", data) == []


@pytest.mark.parametrize("change", [
    lambda d: d.update(confidence=1.5),
    lambda d: d.update(confidence="0.5"),
    lambda d: d.update(confidence=True),
    lambda d: d.update(rel="см_также"),
    lambda d: d.update(src="obj:01929f3a-7c4e-7b21-9a6f-3d2c8e1f0a55"),
], ids=["уверенность больше 1", "уверенность строкой", "уверенность булева", "русский код связи",
        "связь от объекта-файла"])
# about и derived_from связью отклоняет уже запись (records): у них via_field, схема этого не проверяет
def test_invalid_links_rejected(change):
    data = changed("link_depends_on.yaml", change)
    assert pydantic_errors("LinkPayload", data)
    assert json_errors("LinkPayload", data)


FOREIGN_PREFIX = {
    "редакция источника — атом": ("AtomPayload", "atom_table_11_1.yaml",
                                  lambda d: d["sources"][0].update(edition=ATOM_V7)),
    "термин обозначения — сущность": ("AtomPayload", "atom_formula_10_1.yaml",
                                      lambda d: d["content"]["formula"]["symbols"][1].update(term="ent:sp20_13330")),
    "объект в scope — атом": ("AtomPayload", "atom_fact.yaml",
                              lambda d: d["scope"].update(project=ATOM_V7)),
    "edition_of — атом": ("EntityPayload", "entity_sp20_2016.yaml",
                          lambda d: d.update(edition_of=ATOM_V7)),
    "derived_from — сущность": ("AtomPayload", "atom_table_11_1.yaml",
                                lambda d: d.update(derived_from=["ent:sp20_13330"])),
}


@pytest.mark.parametrize("class_name, name, change", FOREIGN_PREFIX.values(), ids=FOREIGN_PREFIX.keys())
def test_reference_with_wrong_prefix_rejected(class_name, name, change):
    data = changed(name, change)
    assert pydantic_errors(class_name, data)
    assert json_errors(class_name, data)


# Python-библиотека jsonschema ищет шаблон через re.search, и `$` у неё совпадает перед завершающим переводом строки;
# NaN она считает числом. Сервер проверяет вход моделями Pydantic (fullmatch, NaN и Infinity запрещены) — поэтому тут только они.
PYDANTIC_ONLY = {
    "ключ с переводом строки в конце": ("EntityPayload", "entity_sp20.yaml",
                                        lambda d: d.update(key="sp20_13330\n")),
    "число NaN": ("AtomPayload", "atom_fact.yaml",
                  lambda d: d["content"]["values"][0].update(amount=float("nan"))),
}


@pytest.mark.parametrize("class_name, name, change", PYDANTIC_ONLY.values(), ids=PYDANTIC_ONLY.keys())
def test_pydantic_only_rejections(class_name, name, change):
    assert pydantic_errors(class_name, changed(name, change))


def test_entity_class_required():
    data = changed("entity_sp20.yaml", lambda d: d.pop("entity_class"))
    assert pydantic_errors("EntityPayload", data)
    assert json_errors("EntityPayload", data)


def test_table_rows_are_lists():
    """Строки таблицы — списки значений: генератор JSON Schema сам этого не разрешает (см. tools/gen_schema.py)."""
    data = example("atom_table_11_1.yaml")
    assert data["content"]["table"]["rows"][2] == ["II", 0.30]
    assert "array" in json.loads(JSON_SCHEMA.read_text(encoding="utf-8"))["$defs"]["Any"]["type"]
    assert json_errors("AtomPayload", data) == []
    assert pydantic_errors("AtomPayload", data) == []


def test_open_codes_have_code_pattern():
    """kind, entity_class и rel — не перечисления, а строки с шаблоном кода: значения дают пакеты."""
    schema = yaml.safe_load(SCHEMA_YAML.read_text(encoding="utf-8"))
    assert not {"Kind", "EntityClass", "Rel", "LinkRel", "SelectorType"} & set(schema["enums"])
    for cls, field in [("AtomPayload", "kind"), ("EntityPayload", "entity_class"), ("LinkPayload", "rel")]:
        slot = schema["classes"][cls]["attributes"][field]
        assert slot["range"] == "string" and slot["pattern"] == "^[a-z][a-z0-9_]*$", (cls, field)


UUID_A = "01929f3a-7c4e-7b21-9a6f-3d2c8e1f0a55"
UUID_B = "01929f3a-7c4e-7b21-9a6f-3d2c8e1f0a56"
DIGEST = "sha256:" + "0123456789abcdef" * 4       # хэш файла
HASH = "sha256-c1:" + "0123456789abcdef" * 4      # хэш канонического тела ревизии (amem/canon.py)

RECORDS = {
    "Atom": {"kind": "fact", "label": {"ru": "Факт"}, "id": UUID_A, "schema_version": "amem.atom/1", "revision": 1,
             "content_hash": HASH, "status": "auto_verified", "agent": "model:claude"},
    "Entity": {"entity_class": "document", "label": {"ru": "СП 20.13330"}, "id": UUID_A, "schema_version": "amem.entity/1",
               "revision": 1, "content_hash": HASH, "status": "draft", "agent": "person:filipp"},
    "Link": {"id": UUID_A, "rel": "depends_on", "src": f"atm:{UUID_A}", "dst": "ent:sp20_13330",
             "created_at": "2026-10-19T12:00:00+05:00"},
    "ObjectRecord": {"id": UUID_A, "kind": "file", "versions": [{"n": 1, "digest": DIGEST}]},
    "Changeset": {"id": UUID_B, "agent": "model:claude", "state": "approved"},
}


@pytest.mark.parametrize("class_name", RECORDS)
def test_record_classes(class_name):
    """Классы записей (то, что отдаёт сервер): по минимальному образцу, обе проверки согласны."""
    assert pydantic_errors(class_name, RECORDS[class_name]) == []
    assert json_errors(class_name, RECORDS[class_name]) == []


@pytest.mark.parametrize("class_name, change", [
    ("Atom", lambda d: d.update(schema_version="amem.atom/١")),     # арабо-индийская цифра: \d принял бы её, [0-9] — нет
    ("Atom", lambda d: d.update(schema_version="atomdb.atom/1")),     # версия до переименования не принимается
    ("Entity", lambda d: d.update(schema_version="atomdb.entity/1")),
    ("Changeset", lambda d: d.update(agent="claude")),                 # агент — person:… или model:…
    ("Atom", lambda d: d.update(content_hash=DIGEST)),                 # у хэша ревизии — метка версии канонизации
    ("Entity", lambda d: d.update(content_hash=DIGEST)),
    ("Atom", lambda d: d.update(content_hash=HASH.replace("-c1:", "-c0:"))),   # версии с 1
    ("Atom", lambda d: d.update(content_hash=HASH.replace("-c1:", "-c01:"))),  # одна версия — одно написание
], ids=["цифра не из ASCII в schema_version", "версия atomdb у атома", "версия atomdb у сущности", "агент без приставки", "хэш ревизии без метки канонизации", "хэш сущности без метки", "метка c0", "метка c01"])
def test_record_classes_reject_bad_values(class_name, change):
    data = dict(RECORDS[class_name])
    change(data)
    assert pydantic_errors(class_name, data)
    assert json_errors(class_name, data)


def test_server_ids_match_schema():
    """id, которые выдаёт сервер (amem/ids.py), проходят шаблоны id и ссылок схемы."""
    from amem.ids import uuid7

    atom = {**RECORDS["Atom"], "id": str(uuid7()), "about": [f"ent:{uuid7()}"], "changeset": str(uuid7())}
    assert pydantic_errors("Atom", atom) == []
    assert json_errors("Atom", atom) == []
