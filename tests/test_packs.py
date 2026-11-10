"""Пакеты домена: ядро как пакет, расширение пакетом-примером, ошибки загрузки, таблица pack.

Обе половины каждого правила: код ядра принимается, чужой отклоняется (RecordError и внешний ключ);
пакет-пример добавляет коды; конфликты и исчезновение кодов — ошибки с местом."""
import shutil
from collections import Counter
from pathlib import Path

import psycopg
import pytest
import yaml

from amemo import db, packs, records
from amemo.ids import uuid7
from amemo.records import Item

AGENT = "model:claude"
EXAMPLE = Path(__file__).with_name("packs") / "example"


def _pack(tmp_path, name, scheme="kind", code="idea", definition="Мысль."):
    """Минимальный пакет с одним понятием."""
    (tmp_path / "vocab").mkdir(parents=True)
    (tmp_path / "pack.yaml").write_text(f"name: {name}\nversion: 1.0.0\n", encoding="utf-8")
    (tmp_path / "vocab" / f"{scheme}.yaml").write_text(
        yaml.safe_dump({"scheme": scheme, "concepts": [
            {"code": code, "label": {"ru": code, "en": code}, "definition": {"ru": definition}}]},
            allow_unicode=True), encoding="utf-8")
    return tmp_path


def _commit_atom(pg, kind):
    return records.commit(pg, [Item("atom", {"kind": kind, "label": {"ru": "Проверка"}, "sources": []})],
                          agent=AGENT)


# --- словарь ядра и служебные перечни ---

def test_core_vocabulary_sizes():
    counts = Counter(c.scheme for c in packs.load_pack(packs.CORE_PACK).concepts)
    assert counts["kind"] == 9 and counts["entity_class"] == 9
    assert counts["rel"] == 12 and counts["selector_type"] == 13
    assert Counter(c.scheme for c in packs.service_concepts())["status"] == 7


def test_all_concepts_have_ru_and_en_labels():
    core = packs.load_pack(packs.CORE_PACK).concepts
    for c in core + packs.service_concepts():
        assert c.label.ru and c.label.en, f"{c.scheme}.{c.code}: нет подписи ru или en"
        assert c.definition and c.definition.ru, f"{c.scheme}.{c.code}: нет определения"


def test_relations_describe_ends_and_inverse():
    rel = {c.code: c for c in packs.load_pack(packs.CORE_PACK).concepts if c.scheme == "rel"}
    for code, c in rel.items():
        assert c.pairs, code
        assert c.inverse_label and c.inverse_label.ru, code
        assert isinstance(c.symmetric, bool), code
    assert rel["about"].pairs == ["atom>entity"]
    assert {code for code, c in rel.items() if c.via_field} == {"about", "derived_from"}
    assert {code for code, c in rel.items() if c.symmetric} == {"contradicts", "same_as", "see_also"}


def test_no_duplicates_in_core():
    codes = Counter((c.scheme, c.code) for c in packs.load_pack(packs.CORE_PACK).concepts)
    assert [k for k, n in codes.items() if n > 1] == []


def test_unknown_annotation_is_an_error(tmp_path, monkeypatch):
    schema = yaml.safe_load(packs.SCHEMA_FILE.read_text(encoding="utf-8"))
    schema["enums"]["Status"]["permissible_values"]["draft"]["annotations"]["labl_ru"] = "опечатка"
    broken = tmp_path / "amemo_v1.yaml"
    broken.write_text(yaml.safe_dump(schema, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(packs, "SCHEMA_FILE", broken)
    with pytest.raises(packs.PackError, match="Status.draft.*labl_ru"):
        packs.service_concepts()


def test_bad_vocabulary_file_names_the_file(tmp_path):
    (tmp_path / "pack.yaml").write_text("name: bad\nversion: 1.0.0\n", encoding="utf-8")
    (tmp_path / "vocab").mkdir()
    (tmp_path / "vocab" / "broken.yaml").write_text(
        "scheme: property\nconcepts:\n  - {code: w, label: {ru: w, en: w}, unit: kPa, plausible_min: '0.1'}\n",
        encoding="utf-8")
    with pytest.raises(packs.PackError, match="broken.yaml"):
        packs.load_pack(tmp_path)


# --- согласованность пакетов ---

def test_core_override_is_rejected(tmp_path):
    other = _pack(tmp_path, "other", code="fact")
    with pytest.raises(packs.PackError, match="переопределение кода ядра"):
        packs.load_packs([packs.CORE_PACK, other])


def test_two_packs_one_code_is_rejected(tmp_path):
    a = _pack(tmp_path / "a", "pack_a", definition="Одно определение.")
    b = _pack(tmp_path / "b", "pack_b", definition="Другое определение.")
    with pytest.raises(packs.PackError, match="pack_b.*уже задаёт пакет pack_a"):
        packs.load_packs([packs.CORE_PACK, a, b])


def test_pack_twice_is_rejected(tmp_path):
    a = _pack(tmp_path / "a", "pack_a")
    b = _pack(tmp_path / "b", "pack_a")
    with pytest.raises(packs.PackError, match="встречается дважды"):
        packs.load_packs([packs.CORE_PACK, a, b])


# --- запись значений из пакетов ---

def test_core_kind_accepted_foreign_rejected(pg):
    db.prepare(pg)
    _commit_atom(pg, "fact")                                   # код ядра принимается
    with pytest.raises(records.RecordError, match="кода нет в загруженных пакетах"):
        _commit_atom(pg, "no_such_kind")
    # и на уровне базы — внешний ключ, без приложения
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        pg.execute("INSERT INTO atom (id, kind, status, created_at, status_changed_at) "
                   "VALUES (%s, 'no_such_kind', 'draft', now(), now())", (uuid7(),))


def test_example_pack_adds_codes_and_template(pg, monkeypatch, tmp_path):
    example = shutil.copytree(EXAMPLE, tmp_path / "example")
    monkeypatch.setattr(packs, "discover", lambda: [packs.CORE_PACK, example])
    db.prepare(pg)
    _commit_atom(pg, "idea")
    records.commit(pg, [Item("entity", {"entity_class": "collection", "label": {"ru": "Подборка"}})], agent=AGENT)
    origin = pg.execute("SELECT origin FROM concept WHERE scheme = 'kind' AND code = 'idea'").fetchone()[0]
    assert origin == "example"
    assert pg.execute("SELECT 1 FROM template WHERE code = 'idea' AND version = '1.0.0'").fetchone()
    # чужой код и с пакетом-примером не проходит
    with pytest.raises(records.RecordError, match="кода нет в загруженных пакетах"):
        _commit_atom(pg, "norm")


def test_same_version_other_content_is_rejected(pg, monkeypatch, tmp_path):
    example = shutil.copytree(EXAMPLE, tmp_path / "example")
    monkeypatch.setattr(packs, "discover", lambda: [packs.CORE_PACK, example])
    db.prepare(pg)
    (example / "pack.yaml").write_text((example / "pack.yaml").read_text(encoding="utf-8") + "# другая правка\n",
                                       encoding="utf-8")
    with pytest.raises(db.MigrationError, match="пакет example 1.0.0.*поднимите версию"):
        db.load_vocab(pg)


def test_pack_table_stores_version_and_digest(pg):
    db.prepare(pg)
    rows = pg.execute("SELECT name, version, digest FROM pack").fetchall()
    assert [(r[0], r[1]) for r in rows] == [("core", "1.4.1")]
    assert all(len(r[2]) == 64 for r in rows)
    db.prepare(pg)                                             # повторно — без ошибок и дублей
    assert pg.execute("SELECT count(*) FROM pack").fetchone()[0] == 1


def test_disappeared_used_code_is_rejected(pg, monkeypatch, tmp_path):
    example = shutil.copytree(EXAMPLE, tmp_path / "example")
    monkeypatch.setattr(packs, "discover", lambda: [packs.CORE_PACK, example])
    db.prepare(pg)
    _commit_atom(pg, "idea")
    monkeypatch.setattr(packs, "discover", lambda: [packs.CORE_PACK])
    with pytest.raises(db.MigrationError, match="example.*исчез код"):
        db.load_vocab(pg)
    # ошибка откатила всю загрузку: понятие на месте
    assert pg.execute("SELECT 1 FROM concept WHERE scheme = 'kind' AND code = 'idea'").fetchone()


def test_disappeared_unused_code_is_removed(pg, monkeypatch, tmp_path):
    example = shutil.copytree(EXAMPLE, tmp_path / "example")
    monkeypatch.setattr(packs, "discover", lambda: [packs.CORE_PACK, example])
    db.prepare(pg)
    monkeypatch.setattr(packs, "discover", lambda: [packs.CORE_PACK])
    db.load_vocab(pg)
    assert pg.execute("SELECT count(*) FROM concept WHERE origin = 'example'").fetchone()[0] == 0
