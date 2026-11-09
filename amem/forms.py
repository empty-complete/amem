"""Форма вида для интерфейса: TemplateView и FormField контракта из шаблонов (спецификация подпроекта 4, разд. 6a.2).

Форма есть у каждого вида атома (словарь kind) и класса сущности (entity_class) — и у вида без своего шаблона:
его форму дают интерфейсы target. Правила сводятся так же, как при проверке записи (check.templates.rules_for),
поэтому форма просит ровно то, что потом проверит check.submit.

Поле формы — правило шаблона, чей путь — поле тела записи, которое заполняет человек (FORM_SKIP — нет: подпись,
пояснение, текст и источники у редактора свои; правило с [] или внутри составного поля — ограничение, а не поле),
плюс поля, которые форма показывает всегда (packs.UI_BASE), плюс величины из ui.fields
(content.values[property=X], qualifiers[property=X]). Профиль сущности (parameters) — не поля формы: это значения
атомов parameter о сущности, их показывает карточка (profile.card); у тела сущности нет content.

Тип — из ui.fields[path].type, иначе по пути (infer). Подпись и подсказка — из ui.fields, иначе из словаря property,
иначе подпись поля записи (LABELS), иначе сам путь. Блок ui сводится по порядку применения шаблонов: поле — по path,
body и widgets — у последнего шаблона, где они заданы. Величины ui заменяют общее поле content.values; правило
content.values просит хотя бы одно значение, поэтому величина обязательна, только если она одна.
"""
from __future__ import annotations

from dataclasses import dataclass

import psycopg

from . import packs, vocab
from .check import templates

BODY_DEFAULT = "wanted"
WIDGETS_DEFAULT = ("sources", "links")
SCHEMES = {"atom": "kind", "entity": "entity_class"}
# поля тела, которые редактор записи показывает сам: правило на них — проверка, а не поле формы
FORM_SKIP = frozenset({"ref", "key", "kind", "entity_class", "label", "summary_plain", "body", "description",
                       "sources", "basis", "provenance", "confidence"})
VALUES = "content.values"
LABELS = {
    "about": {"ru": "О чём", "en": "About"},
    "tags": {"ru": "Теги", "en": "Tags"},
    "codes": {"ru": "Коды", "en": "Codes"},
    "aliases": {"ru": "Другие имена", "en": "Aliases"},
    "valid_from": {"ru": "Действует с", "en": "Valid from"},
    "valid_to": {"ru": "Действует до", "en": "Valid to"},
    "period": {"ru": "Действует", "en": "Valid"},
    "derived_from": {"ru": "Получено из", "en": "Derived from"},
    "rank": {"ru": "Ранг", "en": "Rank"},
    VALUES: {"ru": "Значение", "en": "Value"},
}
# перечни схемы, у которых есть словарь в базе (packs.SERVICE): поле с таким range — выбор из словаря
_ENUM_SCHEMES = packs.SERVICE


@dataclass
class _Vocab:
    active: dict[str, dict]            # code шаблона → тело (template_active)
    properties: dict[str, dict]        # код величины → понятие
    via: dict[str, str]                # поле тела → вид связи, которую оно задаёт (rel.via_field)


def _vocab(conn: psycopg.Connection) -> _Vocab:
    rows = conn.execute("SELECT scheme, code, data FROM concept WHERE scheme IN ('property', 'rel')").fetchall()
    return _Vocab(active=templates.active(conn),
                  properties={code: data for scheme, code, data in rows if scheme == "property"},
                  via={data["via_field"]: code for scheme, code, data in rows if scheme == "rel" and data.get("via_field")})


def _slot(path: str, target: str) -> dict | None:
    """Поле схемы, если путь — поле формы (поле тела верхнего уровня, не составное); иначе None."""
    if path == VALUES:
        return {"multivalued": True, "range": "Value"}
    if "." in path or "[" in path or path in FORM_SKIP:
        return None
    try:
        slot = packs.check_path(path, target)
    except packs.PackError:
        return None
    rng = slot.get("range", "string")
    if rng in packs.schema_classes():
        return None                       # составное поле (Scope, Content, Qualifier…) — у редактора своё
    return slot


def infer(path: str, slot: dict, rule: dict | None, ctx: _Vocab) -> tuple[str, dict]:
    """Тип поля по пути и полю схемы; вторым — уточнения FormField (scheme, accepts)."""
    classes = list((rule or {}).get("entity_classes") or [])
    if path == "about":
        return "object", {"accepts": {"entity_classes": classes, "kinds": []}}
    if path == VALUES:
        return "quantity", {}
    if path in ("valid_from", "valid_to"):
        return "date", {}
    if path == "tags":
        return "tags", {}
    rng = slot.get("range", "string")
    if rng in _ENUM_SCHEMES:
        return "choice", {"scheme": _ENUM_SCHEMES[rng]}
    if path in ctx.via:
        return "record", {"accepts": {"entity_classes": classes, "kinds": [], "rel": ctx.via[path]}}
    if slot.get("multivalued"):
        return "tags", {}
    return "text", {}


def _field(key: str, path: str, ftype: str, *, label: dict, required: bool, hint=None, extra=None) -> dict:
    out = {"key": key, "path": path, "label": label, "type": ftype, "required": required, "hint": hint,
           "scheme": None, "property": None, "unit": None, "accepts": None}
    out.update(extra or {})
    if ftype in ("object", "record") and out["accepts"] is None:
        out["accepts"] = {"entity_classes": [], "kinds": []}
    return out


def _ui(rules: templates.Rules, ctx: _Vocab) -> tuple[dict[str, dict], str | None, list[str] | None]:
    """Блок ui, сведённый по порядку применения шаблонов: поля по path, body и widgets — у последнего, где заданы."""
    fields: dict[str, dict] = {}
    body = widgets = None
    for applied in rules.templates:
        ui = ctx.active[applied.rpartition("@")[0]].get("ui") or {}
        for f in ui.get("fields") or []:
            fields[f["path"]] = f
        body = ui.get("body", body)
        widgets = ui.get("widgets", widgets)
    return fields, body, widgets


def _form(ctx: _Vocab, target: str, code: str) -> tuple[list[dict], str, list[str]]:
    rules = templates.rules_for(ctx.active, target, code)
    ui, body, widgets = _ui(rules, ctx)
    base = packs.UI_BASE[target]
    paths = [p for p in base[:1] if target == "atom"]                   # about — первым
    paths += [p for p in rules.fields if p not in paths and _slot(p, target) is not None]
    props = [p for p in ui if packs.UI_PROPERTY.fullmatch(p)]
    if any(p.startswith(VALUES) for p in props) and VALUES in paths:
        at = paths.index(VALUES)                                       # величины ui заменяют общее «значение»
        paths[at:at + 1] = [p for p in props if p.startswith(VALUES)]
    paths += [p for p in props if p not in paths]
    paths += [p for p in base if p not in paths]
    period = "valid_from" in paths and "valid_to" in paths
    n_values = sum(1 for p in paths if p.startswith(VALUES + "["))

    out = []
    for path in paths:
        if period and path == "valid_to":
            continue
        own = ui.get(path) or {}
        prop = packs.UI_PROPERTY.fullmatch(path)
        extra: dict = {}
        if prop is not None:
            is_value = prop.group(1) == VALUES
            key, concept = prop.group(2), ctx.properties.get(prop.group(2)) or {}
            ftype = "quantity" if is_value else "text"
            # правило content.values просит хотя бы одно значение: обязательно поле, только если величина одна
            required = is_value and n_values == 1 and bool((rules.fields.get(VALUES) or {}).get("required"))
            if is_value:
                extra = {"property": key, "unit": concept.get("unit")}
            label, hint = concept.get("label"), concept.get("definition")
        else:
            rule = rules.fields.get(path)
            if period and path == "valid_from":
                key, ftype = "valid", "period"
                required = any((rules.fields.get(p) or {}).get("required") for p in ("valid_from", "valid_to"))
                label = LABELS["period"]
            else:
                key = "value" if path == VALUES else path
                ftype, extra = infer(path, _slot(path, target) or {}, rule, ctx)
                required = bool((rule or {}).get("required"))
                label = LABELS.get(path)
            hint = None
        if own.get("type"):
            ftype = own["type"]
        out.append(_field(key, path, ftype, label=own.get("label") or label or {"ru": path, "en": path},
                          hint=own.get("hint") or hint, required=required, extra=extra))
    return out, body or BODY_DEFAULT, list(widgets or WIDGETS_DEFAULT)


def form(conn: psycopg.Connection, target: str, code: str) -> list[dict]:
    """FormField[] вида code (target atom или entity)."""
    return _form(_vocab(conn), target, code)[0]


def _counts(conn: psycopg.Connection) -> dict[tuple[str, str], int]:
    """Число записей каждого вида и класса (любого статуса) — одним запросом."""
    rows = conn.execute("SELECT 'atom', kind, count(*) FROM atom GROUP BY kind "
                        "UNION ALL SELECT 'entity', entity_class, count(*) FROM entity GROUP BY entity_class").fetchall()
    return {(target, code): n for target, code, n in rows}


def views(conn: psycopg.Connection, *, target: str | None = None, code: str | None = None) -> list[dict]:
    """TemplateView[] видов и классов (target — только atom или entity; code — один вид), по target и коду."""
    ctx = _vocab(conn)
    counts = _counts(conn)
    targets = [target] if target else list(SCHEMES)
    out = []
    for t in targets:
        rows = conn.execute("SELECT code, data, origin FROM concept WHERE scheme = %s "
                            "AND (%s::text IS NULL OR code = %s) ORDER BY code", (SCHEMES[t], code, code)).fetchall()
        own = {body["applies_to"]: body for body in ctx.active.values()
               if body["target"] == t and body.get("applies_to")}
        for c, data, origin in rows:
            fields, body, widgets = _form(ctx, t, c)
            template = own.get(c) or {}
            out.append({
                "code": c, "pack": origin, "label": data["label"], "target": t, "applies_to": c,
                "description": template.get("description") or data.get("definition"),
                "family": "object" if t == "entity" else data.get("family") or vocab.DEFAULT_FAMILY,
                "form": fields, "body": body, "widgets": widgets,
                "editable": origin == "mine", "records": counts.get((t, c), 0),
            })
    return out
