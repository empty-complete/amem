"""Пакеты домена: словари и шаблоны ядра и расширений.

Ядро — тоже пакет (amem/packs/core). Другие пакеты — каталоги, перечисленные в настройке AMEM_PACKS
(через os.pathsep). Пакет — каталог: pack.yaml (name, version, title, description, license),
vocab/*.yaml (понятия в формате model_v1.Concept), templates/*.yaml (шаблоны model_v1.Template),
skills/*.md (тексты для агентов — раздаёт установщик сервера, здесь не читаются).

Правила совместной загрузки (проверяет load_packs, до записи в базу):
- пакет не переопределяет код ядра;
- один код в одной схеме не задаётся двумя пакетами по-разному (и одинаково тоже — иначе непонятно,
  чьё понятие удалять при исчезновении кода из пакета);
- один пакет не встречается дважды;
- requires пакета (имя → диапазон версий, packaging.SpecifierSet) выполнены, циклов нет; пакеты идут
  в топологическом порядке — ядро первым, зависимость раньше зависимого;
- broader понятия ведёт на код той же схемы в загружаемых пакетах.

Шаблоны любого пакета проверяются там же (спецификация подпроекта 3, разд. 3.6), ошибка называет файл шаблона:
- один code шаблона — не больше чем в одном пакете, одна пара (target, applies_to) — не больше чем у одного шаблона;
- код applies_to есть в словаре загружаемых пакетов (kind, entity_class или rel — по target);
- extends ведёт на шаблон того же target, наследование без циклов;
- пути правил ведут на настоящие поля схемы (check_path), коды selector_types, entity_classes, links — из словарей;
- ключи блока ui.fields — пути правил шаблона, его предков по extends и интерфейсов его target, поля, которые
  форма показывает всегда (UI_BASE), или величина content.values[property=X] / qualifiers[property=X] из словаря
  property (_check_ui); блок ui бывает только у atom и entity.

Служебные перечни (Status, Rank, ValueState, SourceRole, Visibility) остаются закрытыми
перечислениями amem/schema/amem_v1.yaml и грузятся в concept с origin='schema' — как раньше.
Семья family (source или work) задаётся только у видов атома (scheme kind); вид без неё — work (amem/vocab.py).
Опечатка в аннотации или в файле словаря — ошибка с указанием места.
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

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
# тело записи, от которого идут пути правил шаблона, и схема понятий, из которой берётся applies_to
ROOTS = {"atom": "AtomPayload", "entity": "EntityPayload", "link": "LinkPayload"}
APPLIES_TO = {"atom": "kind", "entity": "entity_class", "link": "rel"}
# поля, которые форма вида показывает всегда (amem/forms.py): их подписи ui.fields может задать без правила
UI_BASE = {"atom": ("about", "tags"), "entity": ("codes",)}
# путь величины в ui.fields: список тела записи и код property
UI_PROPERTY = re.compile(r"(content\.values|qualifiers)\[property=([a-z][a-z0-9_]*)\]")


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
    template_files: dict[str, Path]   # code шаблона → его файл: ошибки согласованности называют файл
    requires: dict[str, str]          # имя пакета → диапазон версий (packaging.SpecifierSet)


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


@functools.lru_cache(maxsize=None)
def _classes(schema_file: Path) -> dict:
    return _read(schema_file)["classes"]


def schema_classes() -> frozenset[str]:
    """Имена классов схемы v1: поле с таким range — составное (Scope, Content, LangString…), а не значение."""
    return frozenset(_classes(SCHEMA_FILE))


def field_attrs(class_name: str) -> dict:
    """Поля класса схемы вместе с полями предков (is_a); поле потомка важнее."""
    classes = _classes(SCHEMA_FILE)
    cls, attrs = classes[class_name], {}
    while True:
        attrs = {**(cls.get("attributes") or {}), **attrs}
        if "is_a" not in cls:
            return attrs
        cls = classes[cls["is_a"]]


def check_path(path: str, target: str) -> dict:
    """Пройти путь правила шаблона по полям LinkML от тела записи target; вернуть описание последнего поля.

    [] — «каждый элемент списка, дальше вглубь»: стоит у промежуточных списков (sources[].edition)
    и не ставится у последнего поля — правило тогда относится ко всему списку (sources[].selectors).
    Ошибка — PackError без файла: файл добавляет вызывающий."""
    classes, class_name, field = _classes(SCHEMA_FILE), ROOTS[target], None
    segments = path.split(".")
    slot: dict = {}
    for i, segment in enumerate(segments):
        name, each = segment.removesuffix("[]"), segment.endswith("[]")
        if class_name not in classes:
            raise PackError(f"{path}: поле {field} — {class_name}, а не класс; дальше по пути идти некуда")
        attrs = field_attrs(class_name)
        if name not in attrs:
            raise PackError(f"{path}: у {class_name} нет поля {name}")
        slot = attrs[name] or {}
        if i == len(segments) - 1:
            if each:
                raise PackError(f"{path}: [] у последнего поля не нужен — правило относится ко всему списку")
        elif each != bool(slot.get("multivalued")):
            raise PackError(f"{path}: [] ставится ровно у промежуточных списков, а {name} "
                            f"{'— список' if slot.get('multivalued') else 'не список'}")
        class_name, field = slot.get("range", "string"), name
    return slot


def _check_template(t: Template, file: Path, by_code: dict[str, Template], codes: dict[str, set[str]],
                    properties: dict[str, str | None]) -> None:
    """Шаблон по отдельности: applies_to, extends, пути и коды правил полей, связей и параметров профиля.

    properties — код величины → её единица: умолчание профиля должно переводиться в единицу величины,
    иначе карточка покажет число, которое не с чем сравнить."""
    target = t.target
    if t.applies_to and t.applies_to not in codes.get(APPLIES_TO[target], set()):
        raise PackError(f"{file}: applies_to {t.applies_to} — нет в словаре {APPLIES_TO[target]} загружаемых пакетов")
    for parent in t.extends or []:
        if parent not in by_code:
            raise PackError(f"{file}: extends: нет шаблона {parent}")
        if by_code[parent].target != t.target:
            raise PackError(f"{file}: extends: {parent} — шаблон для {by_code[parent].target}, а не для {target}")

    def unknown(scheme: str, values) -> list[str]:
        return [v for v in values or [] if v not in codes.get(scheme, set())]

    for rule in t.fields or []:
        try:
            check_path(rule.path, target)
        except PackError as e:
            raise PackError(f"{file}: {e}") from e
        for attr, scheme in (("selector_types", "selector_type"), ("entity_classes", "entity_class")):
            if bad := unknown(scheme, getattr(rule, attr)):
                raise PackError(f"{file}: {rule.path}: {attr} {bad} — нет в словаре {scheme} загружаемых пакетов")
    links = t.links
    if links is not None:
        rels = list(links.allowed or []) + [req.rel for req in links.required or []]
        if bad := unknown("rel", rels):
            raise PackError(f"{file}: links: виды связей {bad} — нет в словаре rel загружаемых пакетов")
        for req in links.required or []:
            if bad := unknown("entity_class", req.to_classes):
                raise PackError(f"{file}: links: {req.rel}: to_classes {bad} — нет в словаре entity_class")
    _check_parameters(t, file, codes, properties)
    _check_ui(t, file, by_code, codes)


def _rule_paths(t: Template, by_code: dict[str, Template]) -> set[str]:
    """Пути правил, действующих на запись шаблона: свои, предков по extends и интерфейсов того же target."""
    paths: set[str] = set()
    seen: set[str] = set()

    def collect(code: str) -> None:
        if code in seen or code not in by_code:     # цикл и неизвестный extends отвергают другие проверки
            return
        seen.add(code)
        for parent in by_code[code].extends or []:
            collect(parent)
        paths.update(rule.path for rule in by_code[code].fields or [])

    collect(t.code)
    for code, other in by_code.items():
        if other.target == t.target and not other.applies_to:
            collect(code)
    return paths


def _check_ui(t: Template, file: Path, by_code: dict[str, Template], codes: dict[str, set[str]]) -> None:
    """Блок ui: только у atom и entity; путь поля — правило, поле формы или величина словаря; без повторов."""
    if t.ui is None:
        return
    if t.target not in UI_BASE:
        raise PackError(f"{file}: ui — только у шаблонов atom и entity, а не {t.target}")
    allowed = _rule_paths(t, by_code) | set(UI_BASE[t.target])
    seen: set[str] = set()
    for field in t.ui.fields or []:
        where = f"{file}: шаблон {t.code}: ui.fields: {field.path}"
        if field.path in seen:
            raise PackError(f"{where} — путь повторяется")
        seen.add(field.path)
        prop = UI_PROPERTY.fullmatch(field.path)
        if prop is not None:
            if t.target != "atom":
                raise PackError(f"{where} — величины есть только у тела атома")
            if prop.group(2) not in codes.get("property", set()):
                raise PackError(f"{where} — property {prop.group(2)} нет в словаре property загружаемых пакетов")
        elif field.path not in allowed:
            raise PackError(f"{where} — нет правила с таким путём ни у шаблона, ни у его предков и интерфейсов")


def _check_parameters(t: Template, file: Path, codes: dict[str, set[str]], properties: dict[str, str | None]) -> None:
    """Раздел parameters: профиль бывает только у сущностей, величина и origin — из словарей, умолчание — в UCUM."""
    params = t.parameters or []
    if params and t.target != "entity":
        raise PackError(f"{file}: parameters — только у шаблонов target entity")
    seen: set[str] = set()
    for rule in params:
        where = f"{file}: parameters: {rule.property}"
        if rule.property in seen:                # сведение идёт по property: повтор в одном шаблоне — двусмысленность
            raise PackError(f"{file}: parameters: property {rule.property} повторяется")
        seen.add(rule.property)
        if rule.property not in codes.get("property", set()):
            raise PackError(f"{file}: parameters: property {rule.property} — нет в словаре property загружаемых пакетов")
        if rule.origin and rule.origin not in codes.get("parameter_origin", set()):
            raise PackError(f"{where}: origin {rule.origin} — нет в словаре parameter_origin загружаемых пакетов")
        default = rule.default
        if default is not None and default.unit is not None:
            from .check import units             # локальный импорт: units тянет pint, загрузке без умолчаний он не нужен
            if not units.is_ucum(default.unit):
                raise PackError(f"{where}: default.unit {default.unit} — не код UCUM")
            prop_unit = properties.get(rule.property)
            if prop_unit and units.convert(1.0, default.unit, prop_unit) is None:
                raise PackError(f"{where}: default.unit {default.unit} не переводится в {prop_unit}")


def _check_templates(packs: list[Pack]) -> None:
    """Шаблоны всех загружаемых пакетов вместе: коды и пары не повторяются, ссылки ведут на настоящее."""
    codes: dict[str, set[str]] = {}
    for p in packs:
        for c in p.concepts:
            codes.setdefault(c.scheme, set()).add(c.code)
    properties = {c.code: c.unit for p in packs for c in p.concepts if c.scheme == "property"}
    by_code: dict[str, Template] = {}
    files: dict[str, Path] = {}
    owner: dict[str, str] = {}
    pairs: dict[tuple[str, str], str] = {}
    for p in packs:
        for t in p.templates:
            file = p.template_files[t.code]
            if t.code in by_code:
                raise PackError(f"{file}: шаблон {t.code} уже задаёт пакет {owner[t.code]} ({files[t.code]})")
            if t.applies_to:
                pair = (t.target, t.applies_to)
                if pair in pairs:
                    raise PackError(f"{file}: шаблон для {pair[0]} {pair[1]} уже задаёт {pairs[pair]} "
                                    f"({files[pairs[pair]]})")
                pairs[pair] = t.code
            by_code[t.code], files[t.code], owner[t.code] = t, file, p.name
    for code, t in by_code.items():
        _check_template(t, files[code], by_code, codes, properties)

    done: set[str] = set()

    def walk(code: str, chain: tuple[str, ...]) -> None:
        if code in done:
            return
        for parent in by_code[code].extends or []:
            if parent in chain + (code,):
                loop = chain[chain.index(parent):] if parent in chain else ()
                raise PackError(f"{files[code]}: цикл в extends: {' → '.join(loop + (code, parent))}")
            walk(parent, chain + (code,))
        done.add(code)

    for code in by_code:
        walk(code, ())


def load_pack(path: Path) -> Pack:
    """Пакет из каталога: манифест, понятия и шаблоны в строгой проверке, digest содержимого."""
    path = Path(path)
    manifest = _read(path / "pack.yaml")
    if not isinstance(manifest, dict) or not manifest.get("name") or not manifest.get("version"):
        raise PackError(f"{path / 'pack.yaml'}: нужны name и version")
    name, version = str(manifest["name"]), str(manifest["version"])
    requires = manifest.get("requires") or {}
    if not isinstance(requires, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in requires.items()):
        raise PackError(f"{path / 'pack.yaml'}: requires: ожидается отображение имя → диапазон версий")
    for dep, spec in requires.items():
        try:
            SpecifierSet(spec)
        except InvalidSpecifier as e:
            raise PackError(f"{path / 'pack.yaml'}: requires: {dep}: {e}") from e

    concepts = []
    for file in sorted((path / "vocab").glob("*.yaml")) if (path / "vocab").is_dir() else []:
        data = _read(file)
        if not isinstance(data, dict) or not data.get("scheme") or not data.get("concepts"):
            raise PackError(f"{file}: нужны scheme и непустой список concepts")
        for c in data["concepts"]:
            code = c.get("code", "?") if isinstance(c, dict) else "?"
            try:
                # строгая проверка JSON, как у шаблонов: перечисления (family, status) принимаются строками
                concept = Concept.model_validate_json(
                    json.dumps({"scheme": data["scheme"], **c}, ensure_ascii=False), strict=True)
            except (TypeError, ValueError) as e:
                raise PackError(f"{file}: {code}: {e}") from e
            if concept.family is not None and concept.scheme != "kind":
                raise PackError(f"{file}: {code}: family бывает только у вида атома (scheme kind), "
                                f"а не у {concept.scheme}")
            concepts.append(concept)

    templates, template_files = [], {}
    for file in sorted((path / "templates").glob("*.yaml")) if (path / "templates").is_dir() else []:
        try:
            # строгая проверка JSON — как у входа сервера: строки-перечисления принимаются, "no" вместо true — нет
            t = Template.model_validate_json(json.dumps(_read(file), ensure_ascii=False), strict=True)
        except ValueError as e:
            raise PackError(f"{file}: {e}") from e
        if t.code in template_files:
            raise PackError(f"{file}: шаблон {t.code} уже задан в {template_files[t.code].name}")
        templates.append(t)
        template_files[t.code] = file

    digest = hashlib.sha256()
    for file in sorted(p for p in path.rglob("*") if p.is_file() and p.suffix in (".yaml", ".md")):
        digest.update(file.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(file.read_bytes())
        digest.update(b"\0")
    return Pack(name=name, version=version, path=path, concepts=concepts, templates=templates,
                digest=digest.hexdigest(), template_files=template_files, requires=requires)


def _ordered(packs: list[Pack]) -> list[Pack]:
    """Ядро первым, дальше — топологический порядок по requires; версии проверены; цикл — ошибка с цепочкой."""
    by_name = {p.name: p for p in packs}
    if "core" not in by_name:
        raise PackError("ядро (пакет core) обязательно")
    for p in packs:
        for dep, spec in p.requires.items():
            if dep not in by_name:
                raise PackError(f"пакет {p.name} требует {dep} {spec}, он не загружается")
            try:
                have = Version(by_name[dep].version)
            except InvalidVersion as e:
                raise PackError(f"пакет {dep}: версия {by_name[dep].version!r} — не semver") from e
            # предварительные версии (2.0.0rc1) тоже подходят под диапазон: иначе >=1.0 их бы не принял
            if not SpecifierSet(spec).contains(have, prereleases=True):
                raise PackError(f"пакет {p.name} требует {dep} {spec}, загружен {by_name[dep].version}")
    order: list[Pack] = []
    done: set[str] = set()

    def visit(name: str, chain: tuple[str, ...]) -> None:
        if name in done:
            return
        if name in chain:
            loop = chain[chain.index(name):] + (name,)
            raise PackError(f"цикл в requires: {' → '.join(loop)}")
        for dep in sorted(by_name[name].requires):
            visit(dep, chain + (name,))
        done.add(name)
        order.append(by_name[name])

    visit("core", ())
    for name in sorted(by_name):
        visit(name, ())
    return order


def _check_broader(packs: list[Pack]) -> None:
    """broader ведёт на код той же схемы — в своём пакете, ядре или другом загружаемом пакете."""
    codes: dict[str, set[str]] = {}
    for p in packs:
        for c in p.concepts:
            codes.setdefault(c.scheme, set()).add(c.code)
    for p in packs:
        for c in p.concepts:
            if c.broader and c.broader not in codes.get(c.scheme, set()):
                raise PackError(f"пакет {p.name}: {c.scheme}.{c.code}: broader {c.broader} — "
                                f"нет в словаре {c.scheme} загружаемых пакетов")


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
    packs = _ordered(packs)

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
    _check_broader(packs)
    _check_templates(packs)
    return packs
