"""Действующие шаблоны и их сведение для одной записи (спецификация подпроекта 3, разд. 3.2).

Набор шаблонов записи: все интерфейсы её target (applies_to пуст) по возрастанию кода, затем шаблон её кода.
Каждый шаблон раскрывается: сначала его extends слева направо (рекурсивно), затем собственные правила; шаблон,
уже применённый в этом наборе, второй раз не применяется. Правило, применённое позже, заменяет прежнее с тем же
path — так потомок заменяет предка, а из двух несвязанных интерфейсов действует тот, чей код больше.

Циклов, чужих target и ссылок на несуществующие шаблоны здесь нет: их отвергает packs.load_packs до записи в базу,
а template_active переписывается только из проверенных пакетов.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Rules:
    templates: tuple[str, ...]                 # code@version в порядке применения
    fields: dict[str, dict]                    # path → правило FieldRule (json), сведённое по path
    allowed: frozenset[str] | None             # None — исходящие связи не ограничены
    required_links: tuple[dict, ...]           # RequiredLink (json), сведённые по rel
    high_risk: frozenset[str]
    # чьё правило действует — замечание называет шаблон: path → code@version, rel обязательной связи → code@version
    field_origins: dict[str, str] = field(default_factory=dict)
    link_origins: dict[str, str] = field(default_factory=dict)


def active(conn) -> dict[str, dict]:
    """code → тело шаблона (с version) из template_active ⋈ template."""
    rows = conn.execute("SELECT t.code, t.body FROM template_active a "
                        "JOIN template t ON t.code = a.code AND t.version = a.version ORDER BY t.code").fetchall()
    return {code: body for code, body in rows}


def rules_for(active: dict[str, dict], target: str, code: str) -> Rules:
    """Интерфейсы target по возрастанию кода, затем шаблон applies_to = code; extends — слева направо."""
    order: list[str] = []
    seen: set[str] = set()

    def apply(name: str) -> None:
        if name in seen:                       # отметка до раскрытия: повтор в цепочке не применяется второй раз
            return
        seen.add(name)
        for parent in active[name].get("extends") or []:
            apply(parent)
        order.append(name)

    of_target = {name: t for name, t in active.items() if t["target"] == target}
    for name in sorted(name for name, t in of_target.items() if not t.get("applies_to")):
        apply(name)
    own = next((name for name, t in of_target.items() if t.get("applies_to") == code), None)
    if own is not None:
        apply(own)

    fields: dict[str, dict] = {}
    required: dict[str, dict] = {}
    field_origins: dict[str, str] = {}
    link_origins: dict[str, str] = {}
    allowed: frozenset[str] | None = None
    high_risk: set[str] = set()
    for name in order:
        t = active[name]
        applied = f"{name}@{t['version']}"
        for rule in t.get("fields") or []:
            fields[rule["path"]] = dict(rule)
            field_origins[rule["path"]] = applied
        links = t.get("links") or {}
        if links.get("allowed") is not None:
            allowed = frozenset(links["allowed"])
        for req in links.get("required") or []:
            required[req["rel"]] = dict(req)
            link_origins[req["rel"]] = applied
        high_risk.update(t.get("high_risk") or [])
    return Rules(templates=tuple(f"{name}@{active[name]['version']}" for name in order), fields=fields,
                 allowed=allowed, required_links=tuple(required.values()), high_risk=frozenset(high_risk),
                 field_origins=field_origins, link_origins=link_origins)
