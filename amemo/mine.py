"""Пакет «Мои виды» (mine) в базе: свои виды человека (спецификация подпроекта 4, разд. 6a.3).

Пакет mine — строка в таблице pack с именем mine; версия 0.0.N растёт с каждой правкой, digest — canon.content_hash
всех действующих шаблонов mine. Шаблон своего вида — строки template (каждая правка — новая version, template_active
переключается), понятие вида — concept с origin = 'mine' (scheme kind у атома, entity_class у сущности). Код вида,
код шаблона и applies_to совпадают.

Черновик (TemplateDraft контракта) переводится в Template схемы v1:
- поле формы — правило FieldRule (path, required; у about и полей-ссылок — entity_classes из accepts);
- величина content.values[property=X] / qualifiers[property=X] — запись ui.fields и правило content.values /
  qualifiers, обязательное, если обязательна хоть одна величина: отбора по property у FieldRule нет;
- период (type period) — правила valid_from и valid_to (обязательность — у valid_from);
- новое свойство: текстовое поле qualifiers[property=X] с кодом X, которого нет в словаре property, заводит понятие
  property X (origin mine, подпись — из поля, без unit); существующее понятие любого пакета не трогается. Свойство
  уходит вместе с последним своим видом, который на него ссылается, если его нет и в записях;
- подписи, подсказки и типы полей, body и widgets — блок ui.

Проверка — та же, что у пакета из файла: пакет mine собирается из базы и проверяется вместе с пакетами-файлами
(packs._check_templates). Запись — в одной транзакции под своим замком (db.MINE_LOCK): db.load_vocab берёт тот же замок.
Свои виды правит и удаляет только человек (person:).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import yaml
from psycopg.types.json import Jsonb

from . import canon, db, forms, packs
from .model_v1 import Concept, Template

NAME = "mine"
CODE = re.compile(r"[a-z][a-z0-9_]{1,63}")
SCHEMES = forms.SCHEMES                    # target → схема понятия вида
TARGETS = {scheme: target for target, scheme in SCHEMES.items()}
FAMILIES = {"atom": ("source", "work"), "entity": ("object",)}
BODIES = ("wanted", "required", "none")
WIDGETS = ("sources", "links", "around", "values_table", "similar", "children")
FIELD_TYPES = ("object", "record", "quantity", "date", "period", "choice", "tags", "text")
DRAFT_KEYS = frozenset({"label", "target", "family", "description", "form", "body", "widgets"})
FIELD_KEYS = frozenset({"key", "path", "label", "type", "required", "hint", "scheme", "property", "unit", "accepts"})
PERIOD = ("valid_from", "valid_to")
FIRST = (1, 0, 0)


class MineError(ValueError):
    """Отказ «Моих видов»: code — exists | in_use | invalid | not_found | forbidden; issues — замечания черновика
    в форме CheckIssue (path — путь в черновике)."""

    def __init__(self, message: str, *, code: str, issues=()):
        super().__init__(message)
        self.code = code
        self.issues = list(issues)


def _person(agent: str, what: str) -> None:
    if not isinstance(agent, str) or not agent.startswith("person:"):
        raise MineError(f"свои виды {what} только человек (person:), а не {agent}", code="forbidden")


def _version(text: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in text.split("."))
    except ValueError:
        return (0,)


def _issue(code: str, path: str, message: str) -> dict:
    return {"code": "template_invalid", "severity": "violation", "message": message, "path": path, "ref": code}


# --- черновик → понятие и шаблон ---

def _lang(value, path: str, issues: list, code: str, *, required: bool) -> dict | None:
    """LangString черновика: ru — непустая строка, en — строка; None — нет (если можно)."""
    if value is None:
        if required:
            issues.append(_issue(code, f"{path}.ru", "нужна подпись по-русски"))
        return None
    if not isinstance(value, dict) or set(value) - {"ru", "en"}:
        issues.append(_issue(code, path, "ожидается {ru, en}"))
        return None
    ru, en = value.get("ru"), value.get("en")
    if not isinstance(ru, str) or not ru.strip():
        if required or ru is not None or en is not None:
            issues.append(_issue(code, f"{path}.ru", "нужен текст по-русски"))
        return None
    if en is not None and not isinstance(en, str):
        issues.append(_issue(code, f"{path}.en", "ожидается строка"))
        return None
    return {"ru": ru.strip(), **({"en": en.strip()} if en and en.strip() else {})}


def _field(code: str, target: str, i: int, f, issues: list, properties: set[str]) -> list[tuple[str, dict, dict]]:
    """Поле формы черновика → [(путь, правило или {}, запись ui.fields)]; у периода — два пути."""
    at = f"form[{i}]"
    if not isinstance(f, dict):
        issues.append(_issue(code, at, "ожидается объект FormField"))
        return []
    if extra := sorted(set(f) - FIELD_KEYS):
        issues.append(_issue(code, at, f"лишние поля: {', '.join(extra)}"))
    path, ftype, required = f.get("path"), f.get("type"), f.get("required", False)
    label = _lang(f.get("label"), f"{at}.label", issues, code, required=True)
    hint = _lang(f.get("hint"), f"{at}.hint", issues, code, required=False)
    if ftype not in FIELD_TYPES:
        issues.append(_issue(code, f"{at}.type", f"тип {ftype!r}: ожидается один из {', '.join(FIELD_TYPES)}"))
        return []
    if not isinstance(required, bool):
        issues.append(_issue(code, f"{at}.required", "ожидается true или false"))
        return []
    if not isinstance(path, str) or not path:
        issues.append(_issue(code, f"{at}.path", "нужен путь поля в теле записи"))
        return []
    ui = {"path": path, "type": ftype, **({"label": label} if label else {}), **({"hint": hint} if hint else {})}
    prop = packs.UI_PROPERTY.fullmatch(path)
    if prop is not None:
        if target != "atom":
            issues.append(_issue(code, f"{at}.path", "величины есть только у тела атома"))
            return []
        if prop.group(2) not in properties:
            # своё текстовое свойство (qualifiers) заводится вместе с видом; величина с единицей — только из словаря
            if prop.group(1) != "qualifiers" or ftype != "text":
                issues.append(_issue(code, f"{at}.path", f"величины {prop.group(2)} нет в словаре property"))
                return []
            if not CODE.fullmatch(prop.group(2)):
                issues.append(_issue(code, f"{at}.path", f"код свойства {prop.group(2)}: латиница, цифры и _, "
                                                         "с буквы, 2–64 знака"))
                return []
        if f.get("property") not in (None, prop.group(2)):
            issues.append(_issue(code, f"{at}.property", f"путь называет величину {prop.group(2)}, "
                                                         f"а не {f.get('property')}"))
            return []
        # обязательность величины — в ui: общее правило content.values просит лишь хотя бы одно значение
        return [(path, {"path": prop.group(1), "required": required}, {**ui, "required": required})]
    if ftype == "period":
        if path not in (*PERIOD, "valid"):
            issues.append(_issue(code, f"{at}.path", "период задаётся путём valid_from"))
            return []
        ui["path"] = "valid_from"
        first = {"path": "valid_from", **({"required": True} if required else {})}
        return [("valid_from", first, ui), ("valid_to", {"path": "valid_to"}, {})]
    if path not in packs.UI_BASE[target] and forms.form_slot(path, target) is None:
        issues.append(_issue(code, f"{at}.path", f"{path} — не поле формы {target}: ожидается поле тела записи "
                                                 "верхнего уровня, которое заполняет человек, или величина"))
        return []
    rule: dict = {"path": path, **({"required": True} if required else {})}
    accepts = f.get("accepts") if isinstance(f.get("accepts"), dict) else {}
    classes = accepts.get("entity_classes") or []
    if ftype in ("object", "record") and classes:
        if not isinstance(classes, list) or not all(isinstance(c, str) for c in classes):
            issues.append(_issue(code, f"{at}.accepts.entity_classes", "ожидается список кодов"))
            return []
        rule["entity_classes"] = list(classes)
    if path in packs.UI_BASE[target] and len(rule) == 1:
        rule = {}                                  # поле формы показывается и без правила: правило не нужно
    return [(path, rule, ui)]


def build(conn: psycopg.Connection, code: str, draft, *, version: str = "1.0.0") -> tuple[Concept, Template]:
    """Понятие вида и шаблон из черновика; ошибки черновика — MineError(invalid) со всеми замечаниями."""
    if not isinstance(code, str) or not CODE.fullmatch(code):
        raise MineError(f"код вида {code!r}: ожидается [a-z][a-z0-9_]{{1,63}}", code="invalid",
                        issues=[_issue(str(code), "code", "код вида: латиница, цифры и _, с буквы, 2–64 знака")])
    if not isinstance(draft, dict):
        raise MineError("черновик вида: ожидается объект TemplateDraft", code="invalid",
                        issues=[_issue(code, "", "ожидается объект TemplateDraft")])
    issues: list[dict] = []
    if extra := sorted(set(draft) - DRAFT_KEYS):
        issues.append(_issue(code, "", f"лишние поля: {', '.join(extra)}"))
    target = draft.get("target")
    if target not in SCHEMES:
        issues.append(_issue(code, "target", "target: atom или entity"))
        target = None
    family = draft.get("family")
    if target and family not in FAMILIES[target]:
        issues.append(_issue(code, "family", f"семья вида {target}: {' или '.join(FAMILIES[target])}, а не {family!r}"))
    label = _lang(draft.get("label"), "label", issues, code, required=True)
    description = _lang(draft.get("description"), "description", issues, code, required=False)
    body = draft.get("body")
    if body not in BODIES:
        issues.append(_issue(code, "body", f"body: {', '.join(BODIES)}"))
    widgets = draft.get("widgets")
    if not isinstance(widgets, list) or not all(w in WIDGETS for w in widgets) or len(set(widgets)) != len(widgets):
        issues.append(_issue(code, "widgets", f"widgets: список без повторов из {', '.join(WIDGETS)}"))
    form = draft.get("form")
    if not isinstance(form, list):
        issues.append(_issue(code, "form", "form: ожидается список полей"))
        form = []
    properties = {c for (c,) in conn.execute("SELECT code FROM concept WHERE scheme = 'property'").fetchall()}
    rules: dict[str, dict] = {}
    ui_fields: list[dict] = []
    seen: set[str] = set()
    for i, f in enumerate(form if target else []):
        for path, rule, ui in _field(code, target, i, f, issues, properties):
            if path in seen:
                issues.append(_issue(code, f"form[{i}].path", f"путь {path} уже есть в форме"))
                continue
            seen.add(path)
            if ui:
                ui_fields.append(ui)
            if not rule:
                continue
            if rule["path"] in rules:                 # общее правило величин: обязательно, если обязательна хоть одна
                same = rules[rule["path"]]
                same["required"] = same.get("required", False) or rule.get("required", False)
            else:
                rules[rule["path"]] = dict(rule)
    if issues:
        raise MineError(f"вид {code}: черновик не прошёл проверку ({len(issues)})", code="invalid", issues=issues)
    fields = [{k: v for k, v in r.items() if not (k == "required" and v is False)} for r in rules.values()]
    template = {"code": code, "version": version, "target": target, "applies_to": code,
                **({"description": description} if description else {}),
                **({"fields": fields} if fields else {}),
                "ui": {"body": body, "widgets": widgets, **({"fields": ui_fields} if ui_fields else {})}}
    concept = {"scheme": SCHEMES[target], "code": code, "label": label,
               **({"definition": description} if description else {}),
               **({"family": family} if target == "atom" else {})}
    try:
        return (Concept.model_validate_json(json.dumps(concept, ensure_ascii=False), strict=True),
                Template.model_validate_json(json.dumps(template, ensure_ascii=False), strict=True))
    except ValueError as e:
        raise MineError(f"вид {code}: {e}", code="invalid", issues=[_issue(code, "", str(e))]) from e


# --- пакет mine из базы ---

def _concepts(conn: psycopg.Connection) -> dict[str, Concept]:
    rows = conn.execute("SELECT data FROM concept WHERE origin = %s AND scheme IN ('kind', 'entity_class') "
                        "ORDER BY code", (NAME,)).fetchall()
    return {c.code: c for c in (Concept.model_validate(data) for (data,) in rows)}


def _props(conn: psycopg.Connection) -> list[Concept]:
    """Свойства, которые завели свои виды: понятия property с origin mine."""
    rows = conn.execute("SELECT data FROM concept WHERE origin = %s AND scheme = 'property' ORDER BY code",
                        (NAME,)).fetchall()
    return [Concept.model_validate(data) for (data,) in rows]


def _new_props(conn: psycopg.Connection, body: dict) -> list[Concept]:
    """Понятия свойств, которые вводит шаблон своего вида: текстовые поля qualifiers[property=X] с кодом, которого
    нет в словаре property; подпись — из поля ui."""
    known = {c for (c,) in conn.execute("SELECT code FROM concept WHERE scheme = 'property'").fetchall()}
    out: dict[str, Concept] = {}
    for f in (body.get("ui") or {}).get("fields") or []:
        m = packs.UI_PROPERTY.fullmatch(f["path"])
        if m is None or m.group(1) != "qualifiers" or m.group(2) in known or f.get("type") != "text":
            continue
        label = f.get("label") or {"ru": m.group(2)}
        out[m.group(2)] = Concept.model_validate_json(
            json.dumps({"scheme": "property", "code": m.group(2), "label": label}, ensure_ascii=False), strict=True)
    return list(out.values())


def _gc_props(conn: psycopg.Connection) -> None:
    """Убрать свойства mine, на которые больше не ссылается ни свой вид, ни текущая запись, ни действующая связь
    (у атома и у связи — qualifiers)."""
    used = {code for scheme, code in refs(conn) if scheme == "property"}
    for c in _props(conn):
        if c.code in used:
            continue
        in_records = conn.execute(
            "SELECT 1 FROM atom_current WHERE payload->'qualifiers' @> jsonb_build_array(jsonb_build_object("
            "'property', %s::text)) UNION ALL SELECT 1 FROM link WHERE retired_at IS NULL AND qualifiers @> "
            "jsonb_build_array(jsonb_build_object('property', %s::text)) LIMIT 1", (c.code, c.code)).fetchone()
        if in_records is None:
            conn.execute("DELETE FROM concept WHERE scheme = 'property' AND code = %s AND origin = %s",
                         (c.code, NAME))


def _active(conn: psycopg.Connection) -> dict[str, dict]:
    """code → тело действующего шаблона своего вида."""
    rows = conn.execute(
        "SELECT t.code, t.body FROM template_active a JOIN template t ON t.code = a.code AND t.version = a.version "
        "WHERE EXISTS (SELECT 1 FROM concept c WHERE c.code = a.code AND c.origin = %s "
        "AND c.scheme IN ('kind', 'entity_class')) ORDER BY t.code", (NAME,)).fetchall()
    return dict(rows)


def templates(conn: psycopg.Connection) -> list[dict]:
    """Тела действующих шаблонов своих видов по коду."""
    return list(_active(conn).values())


def _digest(bodies) -> str:
    return canon.content_hash({"templates": sorted(bodies, key=lambda b: b["code"])})


def _pack_version(conn: psycopg.Connection) -> str:
    versions = [v for (v,) in conn.execute("SELECT version FROM pack WHERE name = %s", (NAME,)).fetchall()]
    return max(versions, key=_version) if versions else "0.0.0"


def pack_row(conn: psycopg.Connection) -> dict:
    """Последняя версия пакета mine в таблице pack: name, version, digest, requires (как у пакетов в манифесте)."""
    version = _pack_version(conn)
    digest = conn.execute("SELECT digest FROM pack WHERE name = %s AND version = %s", (NAME, version)).fetchone()
    return {"name": NAME, "version": version, "digest": digest[0] if digest else "", "requires": {}}


def _make_pack(version: str, concepts: list[Concept], bodies: list[dict]) -> packs.Pack:
    tpls = [Template.model_validate_json(json.dumps(b, ensure_ascii=False), strict=True) for b in bodies]
    return packs.Pack(name=NAME, version=version, path=Path(NAME), concepts=concepts, templates=tpls,
                      digest=_digest(bodies) if bodies else "",
                      template_files={t.code: Path(NAME) / "templates" / f"{t.code}.yaml" for t in tpls}, requires={})


def as_pack(conn: psycopg.Connection) -> packs.Pack:
    """Пакет mine, собранный из базы: понятия своих видов и их действующие шаблоны."""
    return _make_pack(_pack_version(conn), [*_concepts(conn).values(), *_props(conn)], templates(conn))


def refs(conn: psycopg.Connection) -> set[tuple[str, str]]:
    """Коды словарей, на которые ссылаются действующие шаблоны своих видов: (scheme, code) — классы сущностей и
    типы селекторов правил, виды и классы связей, величины ui.fields и параметров профиля."""
    out: set[tuple[str, str]] = set()
    for body in templates(conn):
        for rule in body.get("fields") or []:
            out |= {("entity_class", c) for c in rule.get("entity_classes") or []}
            out |= {("selector_type", c) for c in rule.get("selector_types") or []}
        links = body.get("links") or {}
        out |= {("rel", r) for r in links.get("allowed") or []}
        for req in links.get("required") or []:
            out.add(("rel", req["rel"]))
            out |= {("entity_class", c) for c in req.get("to_classes") or []}
        for p in body.get("parameters") or []:
            out.add(("property", p["property"]))
        for f in (body.get("ui") or {}).get("fields") or []:
            if (m := packs.UI_PROPERTY.fullmatch(f["path"])) is not None:
                out.add(("property", m.group(2)))
    return out


def _check(loaded: list[packs.Pack], version: str, concepts: list[Concept], bodies: list[dict]) -> None:
    """Проверка пакета mine вместе с пакетами-файлами — та же, что у пакета из файла."""
    packs._check_templates([*loaded, _make_pack(version, concepts, bodies)])


def _bump(conn: psycopg.Connection, now: datetime) -> str:
    """Новая версия пакета mine (0.0.N+1) с digest действующих шаблонов."""
    major, minor, patch = (_version(_pack_version(conn)) + (0, 0, 0))[:3]
    version = f"{major}.{minor}.{patch + 1}"
    conn.execute("INSERT INTO pack (name, version, digest, requires, loaded_at) VALUES (%s, %s, %s, %s, %s)",
                 (NAME, version, _digest(templates(conn)), Jsonb({}), now))
    return version


def _file_codes(loaded: list[packs.Pack]) -> tuple[dict[tuple[str, str], str], dict[str, str]]:
    """(scheme, code) понятий и коды шаблонов пакетов-файлов → имя пакета."""
    concepts = {(c.scheme, c.code): p.name for p in loaded for c in p.concepts}
    tpls = {t.code: p.name for p in loaded for t in p.templates}
    return concepts, tpls


def _save(conn: psycopg.Connection, concept: Concept, template: Template, loaded: list[packs.Pack]) -> bool:
    """Записать понятие и шаблон своего вида в открытой транзакции под MINE_LOCK; True — что-то изменилось.

    Тот же вид (понятие и тело шаблона без version) ничего не меняет; правка — следующая версия шаблона (номер
    тела — если таких версий кода в template ещё нет) и новая версия пакета mine."""
    code = concept.code
    file_concepts, file_templates = _file_codes(loaded)
    # код вида не должен быть занят ни видом атома, ни классом сущности: веб и ссылки различают вид по коду
    owner = (file_templates.get(code) or file_concepts.get(("kind", code))
             or file_concepts.get(("entity_class", code)))
    row = conn.execute("SELECT origin FROM concept WHERE scheme IN ('kind', 'entity_class') AND code = %s "
                       "AND origin <> %s ORDER BY scheme LIMIT 1", (code, NAME)).fetchone()
    if owner is None and row is not None:
        owner = row[0]
    if owner is not None:
        raise MineError(f"код {code} уже занят видом пакета {owner}", code="exists")
    other = conn.execute("SELECT scheme FROM concept WHERE code = %s AND origin = %s AND scheme <> %s "
                         "AND scheme IN ('kind', 'entity_class')", (code, NAME, concept.scheme)).fetchone()
    if other is not None:
        raise MineError(f"вид {code} уже есть для {TARGETS[other[0]]}: target не меняется — удалите вид и "
                        f"создайте заново", code="invalid",
                        issues=[_issue(code, "target", f"вид {code} — {TARGETS[other[0]]}")])
    concepts = _concepts(conn)
    active = _active(conn)
    body = template.model_dump(mode="json", exclude_none=True)
    data = concept.model_dump(mode="json", exclude_none=True)
    old = active.get(code)
    if (old is not None and {**old, "version": ""} == {**body, "version": ""}
            and concepts[code].model_dump(mode="json", exclude_none=True) == data):
        return False
    versions = [v for (v,) in conn.execute("SELECT version FROM template WHERE code = %s", (code,))]
    if versions:
        major, minor, patch = (_version(max(versions, key=_version)) + (0, 0, 0))[:3]
        body["version"] = f"{major}.{minor}.{patch + 1}"
    bodies = [b for c, b in active.items() if c != code] + [body]
    props = _new_props(conn, body)
    try:
        _check(loaded, _pack_version(conn),
               [*(c for k, c in concepts.items() if k != code), concept, *_props(conn), *props], bodies)
    except packs.PackError as e:
        raise MineError(f"вид {code}: {e}", code="invalid", issues=[_issue(code, "", str(e))]) from e
    now = datetime.now(timezone.utc)
    for prop in props:
        db._upsert_concept(conn, prop, NAME, now)
    db._upsert_concept(conn, concept, NAME, now)
    conn.execute("INSERT INTO template (code, version, target, applies_to, body, body_hash, loaded_at) "
                 "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                 (code, body["version"], body["target"], code, Jsonb(body), canon.content_hash(body), now))
    conn.execute("INSERT INTO template_active (code, version) VALUES (%s, %s) "
                 "ON CONFLICT (code) DO UPDATE SET version = EXCLUDED.version", (code, body["version"]))
    _gc_props(conn)                       # правка могла убрать поле со своим свойством
    _bump(conn, now)
    return True


def _norm_field(f: dict) -> tuple:
    path = "valid_from" if f.get("type") == "period" else f.get("path")
    accepts = f.get("accepts") if isinstance(f.get("accepts"), dict) else {}
    return (path, f.get("type"), bool(f.get("required")), json.dumps(f.get("label"), sort_keys=True),
            json.dumps(f.get("hint"), sort_keys=True), tuple(sorted(accepts.get("entity_classes") or [])))


def _norm(draft: dict) -> tuple:
    """Черновик или TemplateView в сравнимом виде: то, что форма показывает человеку, без служебных полей
    (key, unit, scheme, property — они следуют из пути и словаря)."""
    return (json.dumps(draft.get("label"), sort_keys=True), draft.get("target"), draft.get("family"),
            json.dumps(draft.get("description"), sort_keys=True), draft.get("body"), tuple(draft.get("widgets") or ()),
            tuple(_norm_field(f) for f in draft.get("form") or [] if isinstance(f, dict)))


def put(conn: psycopg.Connection, code: str, draft, *, agent: str) -> dict:
    """Свой вид по черновику: новый — шаблон 1.0.0, правка — следующая версия шаблона; тот же черновик ничего не
    меняет. Пакет mine получает новую версию при каждой правке. Вернуть TemplateView вида.

    «Тот же» — и черновик, который совпадает с формой вида из GET /templates: веб присылает обратно форму с
    подписями и подсказками по умолчанию (из словаря property), и пересохранение без правок не должно поднимать
    версию."""
    db.require_autocommit(conn)
    _person(agent, "правит")
    concept, template = build(conn, code, draft)
    loaded = packs.load_packs()
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (db.MINE_LOCK,))
        current = forms.views(conn, target=TARGETS[concept.scheme], code=code) if code in _concepts(conn) else []
        if not (current and current[0]["editable"] and _norm(current[0]) == _norm(draft)):
            _save(conn, concept, template, loaded)
    [view] = forms.views(conn, target=TARGETS[concept.scheme], code=code)
    return view


# --- пакет mine на диске и из подборки ---

def _pack_kinds(pack: packs.Pack) -> list[tuple[Concept, Template]]:
    """Свои виды пакета mine с диска: понятие вида и его шаблон; сначала классы сущностей — на них ссылаются виды
    атомов (about). Пакет не по правилам «Моих видов» — MineError(invalid)."""
    concepts = {c.code: c for c in pack.concepts}
    kinds = []
    for t in pack.templates:
        c = concepts.pop(t.code, None)
        where = f"пакет {pack.name}: шаблон {t.code}"
        if c is None or c.scheme != SCHEMES.get(t.target):
            raise MineError(f"{where}: нет понятия вида {SCHEMES.get(t.target, '?')}.{t.code}", code="invalid")
        if not CODE.fullmatch(t.code) or t.applies_to != t.code:
            raise MineError(f"{where}: код своего вида — [a-z][a-z0-9_]{{1,63}}, applies_to — тот же код",
                            code="invalid")
        family = getattr(c.family, "value", c.family)
        if family not in (FAMILIES["atom"] if t.target == "atom" else (None,)):
            raise MineError(f"{where}: семья вида {c.family!r} не по правилам {t.target}", code="invalid")
        kinds.append((c, t))
    # свойства своих видов (vocab/property.yaml) едут без шаблона: _save заводит их по полям шаблона
    loose = sorted(code for code, c in concepts.items() if c.scheme != "property")
    if loose:
        raise MineError(f"пакет {pack.name}: понятия без шаблона: {', '.join(loose)}", code="invalid")
    return sorted(kinds, key=lambda k: (k[0].scheme != "entity_class", k[0].code))


def read_pack(folder: Path) -> list[tuple[Concept, Template]]:
    """Свои виды из папки пакета mine (packs/mine/ подборки): строгая проверка, как у пакета из файла."""
    try:
        pack = packs.load_pack(folder)
    except packs.PackError as e:
        raise MineError(f"пакет «Мои виды»: {e}", code="invalid") from e
    if pack.name != NAME:
        raise MineError(f"пакет «Мои виды»: имя {pack.name}, а не {NAME}", code="invalid")
    return _pack_kinds(pack)


def write_pack(conn: psycopg.Connection, folder: Path) -> packs.Pack:
    """Записать пакет mine из базы в папку folder как обычный пакет: pack.yaml, vocab/<scheme>.yaml с понятиями
    своих видов и templates/<code>.yaml с действующими шаблонами. Вернуть пакет."""
    pack = as_pack(conn)
    folder = Path(folder)
    (folder / "vocab").mkdir(parents=True, exist_ok=True)
    (folder / "templates").mkdir(exist_ok=True)

    def dump(path: Path, data) -> None:
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    dump(folder / "pack.yaml", {"name": NAME, "version": pack.version,
                                "title": "Мои виды", "description": "Свои виды, собранные из базы."})
    for scheme in sorted({c.scheme for c in pack.concepts}):
        dump(folder / "vocab" / f"{scheme}.yaml",
             {"scheme": scheme, "concepts": [{k: v for k, v in c.model_dump(mode="json", exclude_none=True).items()
                                              if k != "scheme"} for c in pack.concepts if c.scheme == scheme]})
    for t in pack.templates:
        dump(folder / "templates" / f"{t.code}.yaml", t.model_dump(mode="json", exclude_none=True))
    return pack


def compare(conn: psycopg.Connection, kinds: list[tuple[Concept, Template]]) -> tuple[list[str], list[str]]:
    """Свои виды подборки против базы: (коды, которых в базе нет, — их добавит adopt; коллизии — тот же код с другим
    содержимым или код, занятый пакетом из файла). Совпавшие виды (тело шаблона без version) — ни там, ни там."""
    concepts, active = _concepts(conn), _active(conn)
    rows = conn.execute("SELECT scheme, code, origin FROM concept WHERE scheme IN ('kind', 'entity_class') "
                        "AND code = ANY(%s)", ([c.code for c, _ in kinds],)).fetchall()
    taken = {c: o for s, c, o in rows if o != NAME}          # код занят в любой из двух схем
    tpls = {c for (c,) in conn.execute("SELECT code FROM template_active WHERE code = ANY(%s)",
                                       ([c.code for c, _ in kinds],))}
    new, collisions = [], []
    for c, t in kinds:
        if c.code in taken or (c.code in tpls and c.code not in active):
            owner = f"видом пакета {taken[c.code]}" if c.code in taken else "шаблоном пакета"
            collisions.append(f"packs/mine: код своего вида {c.code} уже занят {owner}")
            continue
        if c.code not in concepts:
            new.append(c.code)
            continue
        body = t.model_dump(mode="json", exclude_none=True)
        if (concepts[c.code].model_dump(mode="json", exclude_none=True) != c.model_dump(mode="json", exclude_none=True)
                or {**active.get(c.code, {}), "version": ""} != {**body, "version": ""}):
            collisions.append(f"packs/mine: свой вид {c.code} в базе другой — переименуйте один из них")
    return new, collisions


def adopt(conn: psycopg.Connection, kinds: list[tuple[Concept, Template]], *, agent: str,
          dry_run: bool = False) -> list[str]:
    """Добавить в mine свои виды из подборки (read_pack), которых в базе нет; вернуть их коды. Вид с тем же кодом и
    другим содержимым или код пакета из файла — MineError(exists). Идёт в транзакции вызывающего (или своей):
    импорт пробует виды в транзакции, которую откатывает (dry_run — без проверки, что вливает человек)."""
    db.require_autocommit(conn)
    if not dry_run:
        _person(agent, "добавляет")
    loaded = packs.load_packs()
    added = []
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (db.MINE_LOCK,))
        new, collisions = compare(conn, kinds)
        if collisions:
            raise MineError("; ".join(collisions), code="exists")
        for concept, template in kinds:
            if concept.code in new:
                _save(conn, concept, template, loaded)
                added.append(concept.code)
    return added


def delete(conn: psycopg.Connection, code: str, *, agent: str) -> None:
    """Удалить свой вид: есть записи этого вида (любого статуса) — MineError(in_use); иначе шаблон уходит из
    template_active, понятие удаляется, пакет mine получает новую версию. Старые версии шаблона остаются."""
    db.require_autocommit(conn)
    _person(agent, "удаляет")
    loaded = packs.load_packs()
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (db.MINE_LOCK,))
        concepts = _concepts(conn)
        if code not in concepts:
            raise MineError(f"своего вида {code} нет", code="not_found")
        scheme = concepts[code].scheme
        table, column = ("atom", "kind") if scheme == "kind" else ("entity", "entity_class")
        n = conn.execute(f"SELECT count(*) FROM {table} WHERE {column} = %s", (code,)).fetchone()[0]
        if n:
            raise MineError(f"у вида {code} есть записи: {n} — сначала смените им вид", code="in_use")
        bodies = [b for c, b in _active(conn).items() if c != code]
        try:
            _check(loaded, _pack_version(conn), [*(c for k, c in concepts.items() if k != code), *_props(conn)],
                   bodies)
        except packs.PackError as e:
            raise MineError(f"на вид {code} ссылается другой свой вид: {e}", code="in_use") from e
        conn.execute("DELETE FROM template_active WHERE code = %s", (code,))
        try:
            conn.execute("DELETE FROM concept WHERE scheme = %s AND code = %s", (scheme, code))
        except psycopg.errors.ForeignKeyViolation as e:
            # запись вида появилась после подсчёта (submit не берёт MINE_LOCK): то же, что записи были
            raise MineError(f"у вида {code} появились записи — сначала смените им вид", code="in_use") from e
        _gc_props(conn)                   # свойства, которые были только у этого вида
        _bump(conn, datetime.now(timezone.utc))
