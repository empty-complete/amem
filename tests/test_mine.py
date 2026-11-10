"""Пакет «Мои виды» в базе (подпроект 4, часть 4d, задача 18; спецификация разд. 6a.3).

Свои виды — понятия origin = 'mine', шаблоны в template и template_active, версии пакета mine в pack.
Всё — на настоящей базе (PostgreSQL 18 и 16)."""
import os
from pathlib import Path

import pytest
import yaml

from amem import check, db, forms, mine

PACKS = Path(__file__).with_name("packs")
PERSON = "person:ann"
MODEL = "model:bot"


def draft(**extra) -> dict:
    """Черновик вида атома: о чём (обязательно), величина массы, период, теги."""
    return {"label": {"ru": "Взвешивание", "en": "Weighing"}, "target": "atom", "family": "source",
            "description": {"ru": "Масса изделия на дату."},
            "form": [
                {"key": "about", "path": "about", "label": {"ru": "Что взвесили"}, "type": "object", "required": True},
                {"key": "mass", "path": "content.values[property=mass]", "label": {"ru": "Масса"},
                 "type": "quantity", "required": True, "property": "mass"},
                {"key": "valid", "path": "valid_from", "label": {"ru": "Когда"}, "type": "period"},
                {"key": "tags", "path": "tags", "label": {"ru": "Теги"}, "type": "tags"},
            ],
            "body": "wanted", "widgets": ["sources", "values_table"], **extra}


@pytest.fixture
def kb(pg, monkeypatch):
    monkeypatch.setenv("AMEM_PACKS", str(PACKS / "quantities"))
    db.prepare(pg)
    return pg


def _versions(conn, code="weighing"):
    template = conn.execute("SELECT version FROM template_active WHERE code = %s", (code,)).fetchone()
    pack = conn.execute("SELECT version FROM pack WHERE name = 'mine' ORDER BY loaded_at DESC, version DESC "
                        "LIMIT 1").fetchone()
    return (template[0] if template else None), (pack[0] if pack else None)


def test_put_creates_kind_template_and_pack(kb, store, docs):
    view = mine.put(kb, "weighing", draft(), agent=PERSON)
    assert (view["code"], view["pack"], view["editable"], view["family"]) == ("weighing", "mine", True, "source")
    origin, data = kb.execute("SELECT origin, data FROM concept WHERE scheme = 'kind' AND code = 'weighing'").fetchone()
    assert origin == "mine" and data["family"] == "source" and data["label"]["ru"] == "Взвешивание"
    assert _versions(kb) == ("1.0.0", "0.0.1")
    body = kb.execute("SELECT body FROM template WHERE code = 'weighing'").fetchone()[0]
    assert {r["path"]: r.get("required", False) for r in body["fields"]} == {
        "about": True, "content.values": True, "valid_from": False, "valid_to": False}
    assert (body["ui"]["body"], body["ui"]["widgets"]) == ("wanted", ["sources", "values_table"])
    by = {f["key"]: f for f in view["form"]}
    assert (by["mass"]["type"], by["mass"]["unit"], by["mass"]["required"]) == ("quantity", "kg", True)
    assert (by["valid"]["type"], by["valid"]["label"]) == ("period", {"ru": "Когда"})
    assert by["about"]["required"] and by["about"]["label"] == {"ru": "Что взвесили"}
    # запись своего вида проходит те же проверки, что запись вида из пакета
    atom = {"kind": "weighing", "label": {"ru": "Кронштейн весит 2 кг"}, "summary_plain": {"ru": "Два килограмма."},
            "basis": "author", "content": {"values": [{"property": "mass", "amount": 2, "unit": "kg"}]}}
    done = check.submit(kb, store, docs, [check.Proposal("atom", atom)], agent=PERSON)
    assert done.state != "rejected", done.report["issues"]
    missing = check.submit(kb, store, docs, [check.Proposal("atom", {k: v for k, v in atom.items() if k != "content"})], agent=PERSON)
    assert missing.state == "rejected"                      # величина обязательна: правило content.values


def test_same_draft_changes_nothing_other_draft_bumps(kb):
    mine.put(kb, "weighing", draft(), agent=PERSON)
    mine.put(kb, "weighing", draft(), agent=PERSON)
    assert _versions(kb) == ("1.0.0", "0.0.1")
    view = mine.put(kb, "weighing", draft(body="none"), agent=PERSON)
    assert view["body"] == "none" and _versions(kb) == ("1.0.1", "0.0.2")
    assert {v for (v,) in kb.execute("SELECT version FROM template WHERE code = 'weighing'")} == {"1.0.0", "1.0.1"}
    mine.put(kb, "weighing", draft(label={"ru": "Вес"}), agent=PERSON)       # подпись вида — тоже правка
    assert _versions(kb) == ("1.0.2", "0.0.3")


@pytest.mark.parametrize("code", ["fact", "has_label"])
def test_code_of_a_file_pack_is_taken(kb, code):
    """Код вида пакета-файла и код шаблона-интерфейса заняты."""
    with pytest.raises(mine.MineError) as e:
        mine.put(kb, code, draft(), agent=PERSON)
    assert e.value.code == "exists" and _versions(kb) == (None, None)


def test_property_code_is_not_a_kind_code_clash(kb):
    """Код величины — другая схема: вид mass допустим, если шаблона и вида mass нет."""
    view = mine.put(kb, "mass", draft(), agent=PERSON)
    assert view["code"] == "mass"


@pytest.mark.parametrize("code", ["A", "x", "1abc", "has-dash", "a" * 65, ""])
def test_bad_code(kb, code):
    with pytest.raises(mine.MineError) as e:
        mine.put(kb, code, draft(), agent=PERSON)
    assert e.value.code == "invalid"


@pytest.mark.parametrize("change, path", [
    ({"form": [{"key": "x", "path": "scope", "label": {"ru": "Охват"}, "type": "text"}]}, "form[0].path"),
    ({"form": [{"key": "x", "path": "no_such_field", "label": {"ru": "Нет"}, "type": "text"}]}, "form[0].path"),
    ({"form": [{"key": "x", "path": "content.values[property=nope]", "label": {"ru": "Нет"}, "type": "quantity"}]},
     "form[0].path"),
    ({"form": [{"key": "x", "path": "tags", "label": {"ru": ""}, "type": "tags"}]}, "form[0].label.ru"),
    ({"form": [{"key": "x", "path": "tags", "label": {"ru": "Т"}, "type": "colour"}]}, "form[0].type"),
    ({"label": {"ru": " "}}, "label.ru"),
    ({"body": "maybe"}, "body"),
    ({"widgets": ["sources", "sources"]}, "widgets"),
])
def test_draft_failing_the_check_is_invalid_with_issues(kb, change, path):
    with pytest.raises(mine.MineError) as e:
        mine.put(kb, "weighing", draft(**change), agent=PERSON)
    assert e.value.code == "invalid"
    assert path in [i["path"] for i in e.value.issues], e.value.issues
    assert all(i["severity"] == "violation" and i["ref"] == "weighing" for i in e.value.issues)
    assert _versions(kb) == (None, None)


def test_entity_classes_must_exist(kb):
    """Проверка пакета вместе с пакетами-файлами: класс сущности в accepts — из словаря."""
    form = [{"key": "about", "path": "about", "label": {"ru": "О чём"}, "type": "object",
             "accepts": {"entity_classes": ["no_such_class"], "kinds": []}}]
    with pytest.raises(mine.MineError) as e:
        mine.put(kb, "weighing", draft(form=form), agent=PERSON)
    assert e.value.code == "invalid" and "no_such_class" in e.value.issues[0]["message"]


@pytest.mark.parametrize("target, family", [("atom", "object"), ("entity", "work"), ("atom", None)])
def test_family_by_target(kb, target, family):
    with pytest.raises(mine.MineError) as e:
        mine.put(kb, "weighing", draft(target=target, family=family, form=[]), agent=PERSON)
    assert e.value.code == "invalid" and "family" in [i["path"] for i in e.value.issues]


def test_entity_kind(kb):
    form = [{"key": "codes", "path": "codes", "label": {"ru": "Марки"}, "type": "tags"}]
    view = mine.put(kb, "rig", draft(target="entity", family="object", form=form, widgets=["children"]), agent=PERSON)
    assert (view["target"], view["family"], view["editable"]) == ("entity", "object", True)
    assert kb.execute("SELECT origin FROM concept WHERE scheme = 'entity_class' AND code = 'rig'").fetchone() == ("mine",)
    with pytest.raises(mine.MineError) as e:          # величины — только у атома
        mine.put(kb, "rig2", draft(target="entity", family="object"), agent=PERSON)
    assert e.value.code == "invalid"


def test_delete(kb, store, docs):
    mine.put(kb, "weighing", draft(), agent=PERSON)
    atom = {"kind": "weighing", "label": {"ru": "Кронштейн весит 2 кг"}, "summary_plain": {"ru": "Два килограмма."},
            "basis": "author", "content": {"values": [{"property": "mass", "amount": 2, "unit": "kg"}]}}
    assert check.submit(kb, store, docs, [check.Proposal("atom", atom)], agent=PERSON).state != "rejected"
    with pytest.raises(mine.MineError) as e:
        mine.delete(kb, "weighing", agent=PERSON)
    assert e.value.code == "in_use"
    mine.put(kb, "spare", draft(), agent=PERSON)
    assert _versions(kb, "spare") == ("1.0.0", "0.0.2")
    mine.delete(kb, "spare", agent=PERSON)
    assert _versions(kb, "spare") == (None, "0.0.3")
    assert kb.execute("SELECT count(*) FROM concept WHERE code = 'spare'").fetchone()[0] == 0
    assert kb.execute("SELECT count(*) FROM template WHERE code = 'spare'").fetchone()[0] == 1   # старая версия
    assert [t["code"] for t in mine.templates(kb)] == ["weighing"]
    with pytest.raises(mine.MineError) as e:
        mine.delete(kb, "spare", agent=PERSON)
    assert e.value.code == "not_found"
    with pytest.raises(mine.MineError) as e:          # вид пакета-файла — не свой
        mine.delete(kb, "fact", agent=PERSON)
    assert e.value.code == "not_found"
    # заново после удаления — следующая версия шаблона, а не повтор 1.0.0
    mine.put(kb, "spare", draft(body="none"), agent=PERSON)
    assert _versions(kb, "spare")[0] == "1.0.1"


def test_my_kinds_survive_prepare(kb):
    mine.put(kb, "weighing", draft(), agent=PERSON)
    mine.put(kb, "weighing", draft(body="none"), agent=PERSON)
    db.prepare(kb)
    db.prepare(kb)
    assert _versions(kb) == ("1.0.1", "0.0.2")
    assert kb.execute("SELECT origin FROM concept WHERE scheme = 'kind' AND code = 'weighing'").fetchone() == ("mine",)
    [view] = forms.views(kb, target="atom", code="weighing")
    assert view["editable"] and view["body"] == "none"
    pack = mine.as_pack(kb)
    assert (pack.name, pack.version, [t.code for t in pack.templates]) == ("mine", "0.0.2", ["weighing"])


def test_file_pack_with_the_code_of_my_kind_is_refused(kb, tmp_path, monkeypatch):
    mine.put(kb, "weighing", draft(), agent=PERSON)
    root = tmp_path / "later"
    (root / "vocab").mkdir(parents=True)
    (root / "pack.yaml").write_text("name: later\nversion: 1.0.0\n", encoding="utf-8")
    (root / "vocab" / "kind.yaml").write_text(yaml.safe_dump(
        {"scheme": "kind", "concepts": [{"code": "weighing", "label": {"ru": "взвешивание"}}]}, allow_unicode=True),
        encoding="utf-8")
    monkeypatch.setenv("AMEM_PACKS", os.pathsep.join([str(PACKS / "quantities"), str(root)]))
    with pytest.raises(db.MigrationError, match="weighing"):
        db.prepare(kb)
    assert kb.execute("SELECT origin FROM concept WHERE scheme = 'kind' AND code = 'weighing'").fetchone() == ("mine",)


def test_model_cannot_put_or_delete(kb):
    with pytest.raises(mine.MineError) as e:
        mine.put(kb, "weighing", draft(), agent=MODEL)
    assert e.value.code == "forbidden"
    mine.put(kb, "weighing", draft(), agent=PERSON)
    with pytest.raises(mine.MineError) as e:
        mine.delete(kb, "weighing", agent=MODEL)
    assert e.value.code == "forbidden"
    assert _versions(kb) == ("1.0.0", "0.0.1")
