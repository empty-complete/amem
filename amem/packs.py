"""Пакеты домена: словари и шаблоны ядра и расширений.

Ядро — тоже пакет (amem/packs/core). Другие пакеты — каталоги, перечисленные в настройке AMEM_PACKS
(через os.pathsep). Пакет — каталог: pack.yaml (name, version, title, description, license),
vocab/*.yaml (понятия в формате model_v1.Concept), templates/*.yaml (шаблоны model_v1.Template),
skills/*.md (тексты для агентов — раздаёт установщик сервера, здесь не читаются).

Правила совместной загрузки (проверяет load_packs, до записи в базу):
- пакет не переопределяет код ядра;
- один код в одной схеме не задаётся двумя пакетами по-разному (и одинаково тоже — иначе непонятно,
  чьё понятие удалять при исчезновении кода из пакета);
- один пакет не встречается дважды.

Служебные перечни (Status, Rank, ValueState, SourceRole, Visibility) остаются закрытыми
перечислениями amem/schema/amem_v1.yaml и грузятся в concept с origin='schema' — как раньше.
Опечатка в аннотации или в файле словаря — ошибка с указанием места.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from .model_v1 import Concept, Template

SCHEMA_FILE = Path(__file__).with_name("schema") / "amem_v1.yaml"
CORE_PACK = Path(__file__).with_name("packs") / "core"

# закрытые служебные перечисления схемы → схемы понятий в базе
SERVICE = {
    "Status": "status",
    "Rank": "rank",
    "ValueState": "value_state",
    "SourceRole": "source_role",
    "Visibility": "visibility",
}
# допустимые аннотации значений служебных перечислений; любая другая — опечатка
ANNOTATIONS = {"label_ru", "label_en", "definition_ru", "definition_en", "inverse_label_ru", "inverse_label_en"}


class PackError(ValueError):
    pass


@dataclass
class Pack:
    name: str
    version: str
    path: Path
    concepts: list[Concept]
    templates: list[Template]
    digest: str                       # sha256 содержимого pack.yaml, vocab/ и templates/


def _read(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise PackError(f"{path}: ошибка YAML: {e}") from e


def _text(ann: dict, key: str) -> dict | None:
    if not ann.get(f"{key}_ru"):
        return None
    return {"ru": ann[f"{key}_ru"], **({"en": ann[f"{key}_en"]} if ann.get(f"{key}_en") else {})}


def service_concepts() -> list[Concept]:
    """Понятия закрытых служебных перечислений схемы (статусы, роли источников и т. п.)."""
    enums = _read(SCHEMA_FILE)["enums"]
    out = []
    for enum_name, scheme in SERVICE.items():
        for code, pv in enums[enum_name]["permissible_values"].items():
            ann = (pv or {}).get("annotations") or {}
            where = f"{SCHEMA_FILE.name}: {enum_name}.{code}"
            unknown = set(ann) - ANNOTATIONS
            if unknown:
                raise PackError(f"{where}: неизвестные аннотации {sorted(unknown)}")
            data = {"scheme": scheme, "code": code, "label": _text(ann, "label"),
                    "definition": _text(ann, "definition"), "inverse_label": _text(ann, "inverse_label")}
            try:
                out.append(Concept.model_validate(data, strict=True))
            except ValueError as e:
                raise PackError(f"{where}: {e}") from e
    return out


def load_pack(path: Path) -> Pack:
    """Пакет из каталога: манифест, понятия и шаблоны в строгой проверке, digest содержимого."""
    path = Path(path)
    manifest = _read(path / "pack.yaml")
    if not isinstance(manifest, dict) or not manifest.get("name") or not manifest.get("version"):
        raise PackError(f"{path / 'pack.yaml'}: нужны name и version")
    name, version = str(manifest["name"]), str(manifest["version"])

    concepts = []
    for file in sorted((path / "vocab").glob("*.yaml")) if (path / "vocab").is_dir() else []:
        data = _read(file)
        if not isinstance(data, dict) or not data.get("scheme") or not data.get("concepts"):
            raise PackError(f"{file}: нужны scheme и непустой список concepts")
        for c in data["concepts"]:
            try:
                concepts.append(Concept.model_validate({"scheme": data["scheme"], **c}, strict=True))
            except ValueError as e:
                raise PackError(f"{file}: {c.get('code', '?')}: {e}") from e

    templates = []
    for file in sorted((path / "templates").glob("*.yaml")) if (path / "templates").is_dir() else []:
        try:
            # строгая проверка JSON — как у входа сервера: строки-перечисления принимаются, "no" вместо true — нет
            templates.append(Template.model_validate_json(
                json.dumps(_read(file), ensure_ascii=False), strict=True))
        except ValueError as e:
            raise PackError(f"{file}: {e}") from e

    digest = hashlib.sha256()
    for file in sorted(p for p in path.rglob("*") if p.is_file() and p.suffix in (".yaml", ".md")):
        digest.update(file.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(file.read_bytes())
        digest.update(b"\0")
    return Pack(name=name, version=version, path=path, concepts=concepts, templates=templates,
                digest=digest.hexdigest())


def discover() -> list[Path]:
    """Ядро + каталоги из AMEM_PACKS."""
    extra = [Path(p) for p in os.environ.get("AMEM_PACKS", "").split(os.pathsep) if p]
    return [CORE_PACK, *extra]


def load_packs(paths: list[Path] | None = None) -> list[Pack]:
    """Пакеты для загрузки в базу; все проверки согласованности — здесь, с местом ошибки."""
    packs = [load_pack(p) for p in (discover() if paths is None else paths)]
    if not any(p.name == "core" for p in packs):
        raise PackError("ядро (пакет core) обязательно")
    seen_packs = set()
    for p in packs:
        if p.name in seen_packs:
            raise PackError(f"пакет {p.name}: встречается дважды ({p.path})")
        seen_packs.add(p.name)

    core = next(p for p in packs if p.name == "core")
    core_codes = {(c.scheme, c.code) for c in core.concepts}
    owners: dict[tuple[str, str], str] = {}
    for p in packs:
        if p.name == "core":
            continue
        for c in p.concepts:
            key = (c.scheme, c.code)
            if key in core_codes:
                raise PackError(f"пакет {p.name}: {c.scheme}.{c.code} — переопределение кода ядра")
            if key in owners:
                raise PackError(f"пакет {p.name}: {c.scheme}.{c.code} — код уже задаёт пакет {owners[key]}")
            owners[key] = p.name
    return packs
