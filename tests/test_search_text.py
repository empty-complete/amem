"""Детерминированный текст поисковой проекции и нормализация обозначений."""
import copy

import pytest

from amemo.search import normalize_code, search_text


@pytest.mark.parametrize("value", ["Вн-45", "вн–45", "ВН - 45", "BH-45"])
def test_code_normalization_unifies_spelling(value):
    assert normalize_code(value) == "вн-45"


def test_code_normalization_keeps_letter_hyphen_and_punctuation():
    assert normalize_code("КБ - 14") == "кб-14"
    assert normalize_code("КБ-14") != normalize_code("кб14")
    assert normalize_code(" Z50 . 0214 ") == "z50.0214"
    assert normalize_code("Ёлка") == "елка"


@pytest.mark.parametrize("value", ["", "   ", None, 42])
def test_code_normalization_rejects_empty_and_non_string(value):
    with pytest.raises(ValueError):
        normalize_code(value)


def atom_payload():
    return {
        "kind": "norm",
        "label": {"ru": "Ветровое давление"},
        "summary_plain": {"ru": "Простое объяснение"},
        "body": {"ru": "Основное утверждение"},
        "aliases": ["Ветровая нагрузка", "Ветровая нагрузка"],
        "codes": ["Вн-45", "вн–45"],
        "retrieval_context": {"ru": "Таблица 11.1"},
        "content": {
            "values": [{"label": {"ru": "Район"}, "value_text": "II"}],
            "table": {"columns": [{"code": "cell", "label": {"ru": "Значение"}}],
                      "rows": [["Текстовая ячейка", 0.4]]},
        },
        "about": ["ent:01929f3a-7c4e-7b21-9a6f-3d2c8e1f0a55"],
        "sources": [{"object": "obj:01929f3a-7c4e-7b21-9a6f-3d2c8e1f0a55",
                     "quote": "Цитата источника не индексируется"}],
    }


def test_atom_text_is_weighted_and_excludes_sources():
    text = search_text(atom_payload(), "atom")
    assert text.weighted["A"] == ("Ветровое давление",)
    assert text.weighted["B"] == ("Простое объяснение", "Основное утверждение")
    assert "Район" in text.weighted["C"]
    assert "Значение" in text.weighted["C"]
    assert "Текстовая ячейка" in text.weighted["C"]
    assert text.weighted["D"] == ("Ветровая нагрузка", "Вн-45", "вн–45", "Таблица 11.1")
    assert text.codes == ("вн-45",)
    assert "01929f3a" not in text.document
    assert "Цитата источника" not in text.document
    assert "columns" not in text.document
    assert "sources" not in text.document


def test_text_does_not_depend_on_dict_order_or_duplicate_fragments():
    first = atom_payload()
    second = copy.deepcopy(first)
    second = {key: second[key] for key in reversed(list(second))}
    second["content"] = {key: second["content"][key] for key in reversed(list(second["content"]))}
    assert search_text(first, "atom") == search_text(second, "atom")


def test_entity_description_is_content_and_aliases_are_context():
    text = search_text({
        "entity_class": "standard",
        "label": {"ru": "СП 20"},
        "description": {"ru": "Нагрузки и воздействия"},
        "aliases": ["Свод правил"],
        "codes": ["Z50.0214"],
    }, "entity")
    assert text.weighted["A"] == ("СП 20",)
    assert text.weighted["B"] == ()
    assert text.weighted["C"] == ("Нагрузки и воздействия",)
    assert text.weighted["D"] == ("Свод правил", "Z50.0214")
    assert text.codes == ("z50.0214",)


def test_empty_document_is_valid_and_input_is_not_mutated():
    payload = {"kind": "fact", "codes": []}
    before = copy.deepcopy(payload)
    text = search_text(payload, "atom")
    assert text.document == ""
    assert all(text.weighted[weight] == () for weight in "ABCD")
    assert text.codes == ()
    assert payload == before
