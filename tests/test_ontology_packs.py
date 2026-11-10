"""Зависимости пакетов: requires, порядок загрузки, циклы, broader."""
import os
from pathlib import Path

import pytest
import yaml

from amemo import db, packs

QUANTITIES = Path(__file__).with_name("packs") / "quantities"


def _pack(root: Path, name: str, version="1.0.0", requires=None, vocab=None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    manifest = {"name": name, "version": version}
    if requires:
        manifest["requires"] = requires
    (root / "pack.yaml").write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    for scheme, concepts in (vocab or {}).items():
        (root / "vocab").mkdir(exist_ok=True)
        (root / "vocab" / f"{scheme}.yaml").write_text(
            yaml.safe_dump({"scheme": scheme, "concepts": concepts}, allow_unicode=True), encoding="utf-8")
    return root


def _kind(code, broader=None):
    c = {"code": code, "label": {"ru": code, "en": code}, "definition": {"ru": f"Вид {code}."}}
    if broader:
        c["broader"] = broader
    return c


def test_requires_satisfied_and_ordered(tmp_path):
    a = _pack(tmp_path / "a", "a", requires={"quantities": ">=1.0.0,<2"})
    loaded = packs.load_packs([packs.CORE_PACK, a, QUANTITIES])
    assert [p.name for p in loaded] == ["core", "quantities", "a"]
    assert loaded[2].requires == {"quantities": ">=1.0.0,<2"}


def test_requires_missing_names_pack(tmp_path):
    a = _pack(tmp_path / "a", "a", requires={"quantities": ">=1.0.0"})
    with pytest.raises(packs.PackError, match="пакет a требует quantities >=1.0.0"):
        packs.load_packs([packs.CORE_PACK, a])


def test_requires_version_out_of_range(tmp_path):
    a = _pack(tmp_path / "a", "a", requires={"quantities": ">=2.0.0"})
    with pytest.raises(packs.PackError, match="загружен 1.0.0"):
        packs.load_packs([packs.CORE_PACK, a, QUANTITIES])


def test_requires_cycle(tmp_path):
    a = _pack(tmp_path / "a", "a", requires={"b": ">=1.0.0"})
    b = _pack(tmp_path / "b", "b", requires={"a": ">=1.0.0"})
    with pytest.raises(packs.PackError, match="цикл.*a → b → a|цикл.*b → a → b"):
        packs.load_packs([packs.CORE_PACK, a, b])


def test_requires_core_explicit_is_checked(tmp_path):
    a = _pack(tmp_path / "a", "a", requires={"core": ">=9.0.0"})
    with pytest.raises(packs.PackError, match="требует core >=9.0.0"):
        packs.load_packs([packs.CORE_PACK, a])


def test_bad_requires_shape(tmp_path):
    a = _pack(tmp_path / "a", "a", requires=["quantities"])
    with pytest.raises(packs.PackError, match="requires: ожидается отображение"):
        packs.load_packs([packs.CORE_PACK, a])


def test_bad_requires_specifier(tmp_path):
    a = _pack(tmp_path / "a", "a", requires={"quantities": "около 1"})
    with pytest.raises(packs.PackError, match="requires: quantities"):
        packs.load_packs([packs.CORE_PACK, a, QUANTITIES])


def test_broader_must_exist(tmp_path):
    a = _pack(tmp_path / "a", "a", vocab={"kind": [_kind("idea", broader="thought")]})
    with pytest.raises(packs.PackError, match="broader thought — нет в словаре kind"):
        packs.load_packs([packs.CORE_PACK, a])


def test_broader_across_packs_ok(tmp_path):
    a = _pack(tmp_path / "a", "a", requires={"quantities": ">=1.0.0"},
              vocab={"property": [{"code": "span", "label": {"ru": "пролёт", "en": "span"},
                                   "definition": {"ru": "Пролёт."}, "unit": "m", "broader": "length"}]})
    assert packs.load_packs([packs.CORE_PACK, a, QUANTITIES])


def test_pack_table_keeps_requires(pg, monkeypatch, tmp_path):
    a = _pack(tmp_path / "a", "a", requires={"quantities": ">=1.0.0,<2"})
    monkeypatch.setenv("AMEMO_PACKS", f"{QUANTITIES}{os.pathsep}{a}")
    db.prepare(pg)
    row = pg.execute("SELECT requires FROM pack WHERE name = 'a'").fetchone()
    assert row[0] == {"quantities": ">=1.0.0,<2"}
    assert pg.execute("SELECT requires FROM pack WHERE name = 'core'").fetchone()[0] == {}


def test_requires_accepts_prerelease(tmp_path):
    """2.0.0rc1 подходит под >=1.0: по умолчанию packaging предварительные версии отбрасывает."""
    dep = _pack(tmp_path / "dep", "dep", version="2.0.0rc1")
    a = _pack(tmp_path / "a", "a", requires={"dep": ">=1.0"})
    assert [p.name for p in packs.load_packs([packs.CORE_PACK, a, dep])] == ["core", "dep", "a"]


def test_missing_core_is_pack_error(tmp_path):
    a = _pack(tmp_path / "a", "a")
    with pytest.raises(packs.PackError, match="ядро"):
        packs.load_packs([a])
    with pytest.raises(packs.PackError, match="ядро"):
        packs._ordered([packs.load_pack(a)])
