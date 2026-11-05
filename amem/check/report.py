"""Замечания автопроверки и отчёт формата amem.check/1 (спецификация подпроекта 3, разд. 2).

Замечание — уровень 1–4, важность из Severity, код из закрытого перечня CheckCode схемы, место (метка записи
@имя, items[i] или links[i] и путь поля через «: »), текст для человека и details для машины.
Код, важность или уровень вне схемы — ошибка программы, а не данных: AssertionError, в отчёт такое не попадает.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .. import model_v1

FORMAT = "amem.check/1"
CODES = frozenset(c.value for c in model_v1.CheckCode)
SEVERITIES = frozenset(s.value for s in model_v1.Severity)
LEVELS = (1, 2, 3, 4)


@dataclass
class Issue:
    level: int
    severity: str
    code: str
    where: str
    message: str
    details: dict = field(default_factory=dict)


class Report:
    """Замечания всех уровней в порядке появления."""

    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def add(self, level: int, severity: str, code: str, where: str, message: str, **details) -> Issue:
        if code not in CODES:
            raise AssertionError(f"код замечания {code!r} — не из перечня CheckCode")
        if severity not in SEVERITIES:
            raise AssertionError(f"важность {severity!r} — не из перечня Severity")
        if level not in LEVELS:
            raise AssertionError(f"уровень {level!r}: у замечания он от 1 до 4")
        issue = Issue(level, severity, code, where, message, details)
        self.issues.append(issue)
        return issue

    def violations(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "violation"]

    def for_label(self, label: str) -> list[Issue]:
        """Замечания записи: место — сама метка или метка и путь поля («@a1: sources[0]»), но не «@a10»."""
        return [i for i in self.issues if i.where == label or i.where.startswith(f"{label}:")]

    def as_json(self, *, levels: dict, records: list, templates: list, degraded: list) -> dict:
        """Отчёт amem.check/1 (model_v1.CheckReport)."""
        return {"format": FORMAT, "levels": dict(levels), "issues": [asdict(i) for i in self.issues],
                "degraded": list(degraded), "templates": list(templates), "records": list(records)}
