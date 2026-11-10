"""Карточка сущности: состояния полей, признаки значения, предки по part_of, extra."""
import os
from pathlib import Path

import pytest

from amemo import db, profile, records
from amemo.records import Item
from check_support import atom, entity, value

PACKS = Path(__file__).with_name("packs")
MODEL, PERSON = "model:claude", "person:alice"


@pytest.fixture
def ready(pg, monkeypatch):
    monkeypatch.setenv("AMEMO_PACKS", os.pathsep.join([str(PACKS / "quantities"), str(PACKS / "ontology")]))
    db.prepare(pg)
    return pg


def _entity(conn, label, cls, **fields):
    done = records.commit(conn, [Item("entity", entity(label, cls=cls, **fields))], agent=PERSON)
    return f"ent:{done.revisions[0].record_id}"


def _param(conn, about, prop, amount, unit, *, agent=MODEL, status="draft", **extra):
    body = atom(f"{prop} {amount}", kind="parameter", about=[about], sources=[],
                content={"values": [value(prop, amount, unit, **extra.pop("value_extra", {}))]}, **extra)
    body.setdefault("basis", "author" if agent.startswith("person") else None)
    body = {k: v for k, v in body.items() if v is not None}
    done = records.commit(conn, [Item("atom", body, status=status)], agent=agent)
    return f"atm:{done.revisions[0].record_id}"


def _field(card, prop):
    return next(f for f in card["fields"] if f["property"] == prop)


def test_missing_and_known(ready):
    dev = _entity(ready, "Насос", "device")
    card = profile.card(ready, dev)
    assert card["format"] == "amem.card/1" and card["profile"] == "device@1.0.0"
    assert [f["property"] for f in card["fields"]] == ["mass", "temperature"]
    assert _field(card, "mass")["state"] == "missing" and _field(card, "mass")["required"] is True
    assert _field(card, "temperature")["default"] == {"amount": 20, "unit": "Cel"}
    assert card["summary"]["blockers_open"] == 1
    a = _param(ready, dev, "mass", 12, "kg")
    f = _field(profile.card(ready, dev), "mass")
    assert f["state"] == "known" and f["value"] == {"amount": 12, "unit": "kg"}
    assert f["by"] == "model" and f["status"] == "draft" and f["atoms"] == [a]
    assert profile.card(ready, dev)["summary"]["blockers_open"] == 0


def test_default_basis_is_a_value_only_when_recorded(ready):
    dev = _entity(ready, "Насос", "device")
    assert _field(profile.card(ready, dev), "temperature")["state"] == "missing"
    _param(ready, dev, "temperature", 20, "Cel", basis="default")
    f = _field(profile.card(ready, dev), "temperature")
    assert f["state"] == "known" and f["basis"] == "default"


def test_na_unknown_asked(ready):
    dev = _entity(ready, "Насос", "device")
    _param(ready, dev, "temperature", None, None, value_extra={"value_state": "none"})
    assert _field(profile.card(ready, dev), "temperature")["state"] == "na"
    sensor = _entity(ready, "Датчик", "sensor")
    _param(ready, sensor, "length", None, None, value_extra={"value_state": "unknown"})
    assert _field(profile.card(ready, sensor), "length")["state"] == "missing"
    q = atom("Какова масса?", kind="question", about=[sensor], sources=[], basis="author",
             content={"values": [{"property": "mass", "value_state": "unknown"}]})
    records.commit(ready, [Item("atom", q)], agent=PERSON)
    assert _field(profile.card(ready, sensor), "mass")["state"] == "asked"


def test_conflict_and_preferred(ready):
    dev = _entity(ready, "Насос", "device")
    a = _param(ready, dev, "mass", 12, "kg")
    b = _param(ready, dev, "mass", 12000, "g")          # то же после перевода единиц — не конфликт
    assert _field(profile.card(ready, dev), "mass")["state"] == "known"
    c = _param(ready, dev, "mass", 15, "kg")
    f = _field(profile.card(ready, dev), "mass")
    assert f["state"] == "conflict" and {x["atom"] for x in f["candidates"]} == {a, b, c}
    _param(ready, dev, "mass", 15, "kg", rank="preferred", agent=PERSON, status="verified")
    f = _field(profile.card(ready, dev), "mass")
    assert f["state"] == "known" and f["value"]["amount"] == 15 and f["by"] == "person" and len(f["candidates"]) == 3


def test_retired_atoms_ignored(ready):
    dev = _entity(ready, "Насос", "device")
    a = _param(ready, dev, "mass", 12, "kg")
    records.set_status(ready, "atom", a.split(":")[1], "rejected", agent=PERSON, reason="ошибка")
    assert _field(profile.card(ready, dev), "mass")["state"] == "missing"


def test_ancestors_by_part_of(ready):
    rack = _entity(ready, "Стойка", "device")
    sensor = _entity(ready, "Датчик", "sensor")
    records.commit(ready, [], [{"rel": "part_of", "src": sensor, "dst": rack}], agent=PERSON)
    _param(ready, rack, "mass", 40, "kg")
    card = profile.card(ready, sensor)
    assert [a["entity"]["ref"] for a in card["ancestors"]] == [rack]
    assert _field(card["ancestors"][0], "mass")["state"] == "known"
    assert profile.card(ready, sensor, ancestors=False)["ancestors"] == []
    records.commit(ready, [], [{"rel": "part_of", "src": rack, "dst": sensor}], agent=PERSON)   # цикл
    assert len(profile.card(ready, sensor)["ancestors"]) == 1


def test_entity_without_profile_lists_extra(ready):
    doc = _entity(ready, "Паспорт", "document")
    _param(ready, doc, "mass", 1, "kg")
    card = profile.card(ready, doc)
    assert card["profile"] is None and card["fields"] == []
    assert [e["property"] for e in card["extra"]] == ["mass"]


def test_known_signs_by_source_role_confidence(ready):
    dev = _entity(ready, "Насос", "device")
    _param(ready, dev, "mass", 12, "kg", confidence=0.7)
    f = _field(profile.card(ready, dev), "mass")
    assert f["confidence"] == 0.7 and f["source_role"] is None and f["sources"] == []
    card = profile.card(ready, dev)
    assert card["summary"]["states"] == {"known": 1, "missing": 1}
    assert card["entity"]["entity_class"] == "device" and card["templates"] == ["device@1.0.0"]


def test_sensor_profile_inherits_device(ready):
    sensor = _entity(ready, "Датчик", "sensor")
    card = profile.card(ready, sensor)
    assert card["profile"] == "sensor@1.0.0"
    assert [f["property"] for f in card["fields"]] == ["mass", "temperature", "length"]
    assert _field(card, "temperature")["required"] is True and card["summary"]["blockers_open"] == 2


def test_extra_for_property_outside_profile(ready):
    dev = _entity(ready, "Насос", "device")
    _param(ready, dev, "width", 2, "m")
    card = profile.card(ready, dev)
    assert [e["property"] for e in card["extra"]] == ["width"] and card["extra"][0]["value"] == {"amount": 2, "unit": "m"}


def test_unknown_entity(ready):
    with pytest.raises(LookupError):
        profile.card(ready, "ent:01900000-0000-7000-8000-000000000000")


def test_card_validates_against_model(ready):
    from amemo import model_v1
    rack = _entity(ready, "Стойка", "device")
    sensor = _entity(ready, "Датчик", "sensor")
    records.commit(ready, [], [{"rel": "part_of", "src": sensor, "dst": rack}], agent=PERSON)
    _param(ready, sensor, "mass", 12, "kg")
    _param(ready, sensor, "mass", 15, "kg")
    _param(ready, sensor, "width", 2, "m")
    card = profile.card(ready, sensor)
    model_v1.Card.model_validate(card)
    with pytest.raises(Exception):
        model_v1.Card.model_validate({**card, "format": "amem.card/2"})


def test_two_preferred_disagree_and_deprecated_rank_ignored(ready):
    dev = _entity(ready, "Насос", "device")
    _param(ready, dev, "mass", 12, "kg")
    _param(ready, dev, "mass", 99, "kg", rank="deprecated")      # отложенное значение не спорит с живым
    f = _field(profile.card(ready, dev), "mass")
    assert f["state"] == "known" and f["value"]["amount"] == 12 and f["candidates"] == []
    _param(ready, dev, "mass", 14, "kg", rank="preferred")
    _param(ready, dev, "mass", 15, "kg", rank="preferred")
    assert _field(profile.card(ready, dev), "mass")["state"] == "conflict"


def test_same_value_takes_signs_from_verified_person(ready):
    dev = _entity(ready, "Насос", "device")
    _param(ready, dev, "mass", 12, "kg")                                        # черновик модели
    b = _param(ready, dev, "mass", 12, "kg", agent=PERSON, status="verified")
    _param(ready, dev, "mass", 12, "kg")                                        # новее, но черновик модели
    f = _field(profile.card(ready, dev), "mass")
    assert f["state"] == "known" and f["by"] == "person" and f["status"] == "verified" and f["atoms"] == [b]
    assert len(f["candidates"]) == 2 and b not in {c["atom"] for c in f["candidates"]}


def test_small_values_compared_relatively(ready):
    dev = _entity(ready, "Насос", "device")
    _param(ready, dev, "mass", 1e-12, "kg")
    _param(ready, dev, "mass", 2e-12, "kg")
    assert _field(profile.card(ready, dev), "mass")["state"] == "conflict"


def test_none_with_unknown_is_na(ready):
    dev = _entity(ready, "Насос", "device")
    _param(ready, dev, "mass", None, None, value_extra={"value_state": "none"})
    _param(ready, dev, "mass", None, None, value_extra={"value_state": "unknown"})
    assert _field(profile.card(ready, dev), "mass")["state"] == "na"


def test_none_with_known_is_conflict(ready):
    dev = _entity(ready, "Насос", "device")
    a = _param(ready, dev, "mass", None, None, value_extra={"value_state": "none"})
    b = _param(ready, dev, "mass", 12, "kg")
    f = _field(profile.card(ready, dev), "mass")
    assert f["state"] == "conflict" and {c["atom"] for c in f["candidates"]} == {a, b}


def _question(conn, about, prop, **value_extra):
    q = atom("Какова величина?", kind="question", about=[about], sources=[], basis="author",
             content={"values": [{"property": prop, **value_extra}]})
    return f"atm:{records.commit(conn, [Item('atom', q)], agent=PERSON).revisions[0].record_id}"


def test_unknown_with_question_is_asked(ready):
    dev = _entity(ready, "Насос", "device")
    _param(ready, dev, "mass", None, None, value_extra={"value_state": "unknown"})
    q = _question(ready, dev, "mass", value_state="unknown")
    f = _field(profile.card(ready, dev), "mass")
    assert f["state"] == "asked" and q in f["atoms"]


def test_question_counts_only_with_unknown_value(ready):
    dev = _entity(ready, "Насос", "device")
    _question(ready, dev, "mass", amount=12, unit="kg")         # не вопрос о неизвестной величине
    assert _field(profile.card(ready, dev), "mass")["state"] == "missing"


@pytest.fixture
def interface(ready, tmp_path, monkeypatch):
    """Профиль только из интерфейса (без applies_to) с величиной, которой нет в словаре."""
    from check_support import pack
    extra = pack(tmp_path / "iface", "iface", {"weighted": {
        "code": "weighted", "version": "1.0.0", "target": "entity",
        "parameters": [{"property": "load", "required": True}]}})
    (extra / "vocab").mkdir()
    (extra / "vocab" / "property.yaml").write_text(
        "scheme: property\nconcepts:\n  - {code: load, label: {ru: нагрузка, en: load}, "
        "definition: {ru: \"Нагрузка без единицы в словаре.\"}}\n", encoding="utf-8")
    monkeypatch.setenv("AMEMO_PACKS", os.pathsep.join([str(PACKS / "quantities"), str(PACKS / "ontology"), str(extra)]))
    db.prepare(ready)
    return ready


def test_profile_from_interface_only(interface):
    doc = _entity(interface, "Паспорт", "document")
    card = profile.card(interface, doc)
    assert card["profile"] == "weighted@1.0.0" and [f["property"] for f in card["fields"]] == ["load"]
    sensor = profile.card(interface, _entity(interface, "Датчик", "sensor"))
    assert sensor["profile"] == "sensor@1.0.0"


def test_unit_of_first_value_when_vocab_has_none(interface):
    doc = _entity(interface, "Паспорт", "document")
    _param(interface, doc, "load", 12, "kg")
    _param(interface, doc, "load", 12000, "g")
    assert _field(profile.card(interface, doc), "load")["state"] == "known"
    _param(interface, doc, "load", 13, "kg")
    assert _field(profile.card(interface, doc), "load")["state"] == "conflict"


def test_rules_for_entity(ready):
    rules = profile.rules_for_entity(ready, "sensor")
    assert rules.templates[-2:] == ("device@1.0.0", "sensor@1.0.0")
    assert [p["property"] for p in rules.parameters] == ["mass", "temperature", "length"]
    assert rules.parameter_origins["temperature"] == "sensor@1.0.0"
    assert profile.rules_for_entity(ready, "document").parameters == ()


def test_conflict_atoms_are_live_candidates(ready):
    dev = _entity(ready, "Насос", "device")
    a = _param(ready, dev, "mass", 12, "kg")
    b = _param(ready, dev, "mass", 15, "kg")
    _param(ready, dev, "mass", 99, "kg", rank="deprecated")
    f = _field(profile.card(ready, dev), "mass")
    assert f["state"] == "conflict" and f["atoms"] == sorted([a, b]) == [c["atom"] for c in f["candidates"]]
    n = _param(ready, dev, "temperature", None, None, value_extra={"value_state": "none"})
    k = _param(ready, dev, "temperature", 30, "Cel")
    _param(ready, dev, "temperature", 40, "Cel", rank="deprecated")
    _param(ready, dev, "temperature", None, None, value_extra={"value_state": "unknown"})
    f = _field(profile.card(ready, dev), "temperature")
    assert f["state"] == "conflict" and set(f["atoms"]) == {n, k} == {c["atom"] for c in f["candidates"]}


def test_revisions_sources_keys_and_input(ready, store, docs):
    from amemo import check, lookup
    from amemo.check import Proposal
    from check_support import source_md
    body = atom("@m", kind="parameter", sources=[source_md("заметка.md", "Масса 3 кг.")],
                content={"values": [value("mass", 3, "kg")]})
    rid = check.submit(ready, store, docs, [Proposal("atom", body)], agent=PERSON).records[0]["revision_id"]
    got = lookup.revisions_sources(ready, "atom", [str(rid)])
    assert list(got) == [rid] and got[rid] == lookup.revision_sources(ready, "atom", rid) and got[rid]
    assert lookup.revisions_sources(ready, "atom", []) == {}


def test_card_through_submit_review_and_rebuild(ready, store, docs, monkeypatch):
    """Сквозной путь: check.submit → очередь проверки → карточка; карточка переживает перестройку проекций."""
    from amemo import check, review
    from amemo.check import Proposal
    from check_support import source_md
    monkeypatch.setenv("AMEMO_BACKEND", "none")

    def submit(body, agent, record_id=None):
        done = check.submit(ready, store, docs, [Proposal(body.get("entity_class") and "entity" or "atom", body,
                                                          record_id)], agent=agent)
        assert done.state == "approved", done.report
        return done

    def mass(amount, agent, record_id=None, label=None):
        body = atom("@m", kind="parameter", label={"ru": label or f"Масса {amount} кг"}, about=[sensor],
                    sources=[source_md("заметка.md", f"Масса {amount} кг.")],
                    content={"values": [value("mass", amount, "kg")]})
        return submit(body, agent, record_id)

    done = submit({"ref": "@e", "entity_class": "sensor", "label": {"ru": "Датчик давления"}}, PERSON)
    sensor = f"ent:{done.records[0]['record_id']}"
    assert _field(profile.card(ready, sensor), "mass")["state"] == "missing"

    first = mass(3, MODEL).records[0]["record_id"]                 # черновик модели, источник сверен
    f = _field(profile.card(ready, sensor), "mass")
    assert (f["state"], f["by"], f["status"]) == ("known", "model", "draft") and f["sources"][0]["verdict"] == "ok"

    mass(3, PERSON, first, label="Масса корпуса 3,0 кг")            # правка человека записи модели — статус прежний
    f = _field(profile.card(ready, sensor), "mass")
    assert (f["by"], f["status"]) == ("person", "draft")
    records.set_status(ready, "atom", first, "verified", agent=PERSON)   # подтверждает — отдельным решением
    assert _field(profile.card(ready, sensor), "mass")["status"] == "verified"

    edit = mass(4, MODEL, first)                                    # правка модели записи человека — pending
    f = _field(profile.card(ready, sensor), "mass")
    assert f["value"]["amount"] == 3 and f["by"] == "person"
    [item] = [q for q in edit.queued if q["reason"] == "edit"]
    review.resolve(ready, item["id"], "refuted", agent=PERSON)
    assert _field(profile.card(ready, sensor), "mass")["value"]["amount"] == 3

    other = mass(4, MODEL)                                          # другое значение модели спорит с человеком
    f = _field(profile.card(ready, sensor), "mass")
    assert f["state"] == "conflict" and {(c["by"], c["value"]["amount"]) for c in f["candidates"]} == \
        {("person", 3), ("model", 4)}
    for q in other.queued:
        review.resolve(ready, q["id"], "refuted", agent=PERSON)
    f = _field(profile.card(ready, sensor), "mass")
    assert f["state"] == "known" and f["value"]["amount"] == 3

    q = atom("@q", kind="question", label={"ru": "Какова рабочая температура?"}, about=[sensor], sources=None,
             basis="author", content={"values": [{"property": "temperature", "value_state": "unknown"}]})
    submit(q, PERSON)
    card = profile.card(ready, sensor)
    assert _field(card, "temperature")["state"] == "asked" and card["summary"]["blockers_open"] == 1

    ready.execute("DELETE FROM atom_property")                      # проекция испорчена: стёрта и засорена
    assert _field(profile.card(ready, sensor), "mass")["state"] == "missing"
    ready.execute("INSERT INTO atom_property SELECT id, 'width' FROM atom_revision")
    records.rebuild_projections(ready)
    assert profile.card(ready, sensor) == card
