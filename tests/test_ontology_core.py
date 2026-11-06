"""Ядро 1.2.0: заметка, изделие, прямоугольник и has_source со skip_if_set."""
from amem import packs

CORE = packs.load_pack(packs.CORE_PACK)


def _codes(scheme):
    return {c.code for c in CORE.concepts if c.scheme == scheme}


def test_core_version():
    assert CORE.version == "1.2.0"


def test_core_new_codes():
    assert "note" in _codes("kind")
    assert "artifact" in _codes("entity_class")
    assert "bbox" in _codes("selector_type")


def test_has_source_skips_when_basis_set():
    t = next(t for t in CORE.templates if t.code == "has_source")
    assert t.version == "1.1.0"
    assert {r.path: r.skip_if_set for r in t.fields} == {"sources": "basis", "sources[].selectors": "basis"}


def test_note_template():
    t = next(t for t in CORE.templates if t.code == "note")
    assert t.applies_to == "note" and t.extends == ["has_label"]
    body = next(r for r in t.fields if r.path == "body")
    assert body.required is True and body.severity == "warning"
    assert t.links is None
