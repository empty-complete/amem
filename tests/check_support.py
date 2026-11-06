"""Построители тел, источников и пакетов для тестов автопроверки (подпроект 3).

Тело по умолчанию проходит уровень 1 с шаблонами ядра: у атома есть подпись, пояснение и источник с местом.
Поле со значением None убирается: atom("@a", label=None) — атом без подписи. Пути источников — документы
фикстуры docs (tests/samples.py)."""
from pathlib import Path

import yaml

CHECK_PACK = Path(__file__).with_name("packs") / "check"
MD = "Заметки/узел.md"
PDF = "НД/СП 99.pdf"


def _body(base: dict, fields: dict) -> dict:
    return {k: v for k, v in {**base, **fields}.items() if v is not None}


def atom(label, /, kind="fact", **fields) -> dict:
    """Атом с @именем label (None — без ref)."""
    name = label.removeprefix("@") if label else "без имени"
    return _body({"ref": label, "kind": kind, "label": {"ru": f"Кронштейн крепится к закладной анкером ({name})"},
                  "summary_plain": {"ru": "Кронштейн держится на одном анкере."}, "sources": [source_md(MD)]}, fields)


def entity(label, /, cls="document", **fields) -> dict:
    """Сущность с @именем label (None — без ref)."""
    name = label.removeprefix("@") if label else "без имени"
    return _body({"ref": label, "entity_class": cls, "label": {"ru": f"Документ {name}"}}, fields)


def source_md(path, quote=None, **kw) -> dict:
    """Источник-заметка: место — раздел «Кронштейн»."""
    return _body({"path": path, "selectors": [{"type": "heading", "value": "Кронштейн"}], "quote": quote}, kw)


def source_pdf(path, page, quote, **kw) -> dict:
    """Источник из PDF: страница и цитата."""
    return _body({"path": path, "selectors": [{"type": "page", "value": str(page)}], "quote": quote}, kw)


def value(prop, amount, unit, **kw) -> dict:
    """Значение величины; amount или unit None — поля нет."""
    return _body({"property": prop, "amount": amount, "unit": unit}, kw)


def pack(root: Path, name: str, templates: dict[str, dict], kinds=()) -> Path:
    """Временный пакет: шаблоны — {имя файла без .yaml: тело}, kinds — свои виды атомов."""
    (root / "templates").mkdir(parents=True)
    (root / "pack.yaml").write_text(f"name: {name}\nversion: 1.0.0\n", encoding="utf-8")
    if kinds:
        (root / "vocab").mkdir()
        (root / "vocab" / "kind.yaml").write_text(yaml.safe_dump({"scheme": "kind", "concepts": [
            {"code": k, "label": {"ru": k, "en": k}, "definition": {"ru": f"Вид {k} для теста."}} for k in kinds]},
            allow_unicode=True), encoding="utf-8")
    for file, body in templates.items():
        (root / "templates" / f"{file}.yaml").write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
    return root
