"""Автопроверка записей перед записью в базу: уровни 1–4 (схема и шаблон, привязка к источнику, здравый смысл,
дубли), отчёт, действующие шаблоны, числа и единицы.

submit — единая точка записи знаний: уровни 1–4, затем одна транзакция записи. Отчёт (changeset.check_report)
пишется до ревизий и содержит только план: уровни, замечания, ослабления, шаблоны, плановый статус и риск записей.
Статус существующей записи ставится после records.commit и только у созданной ревизии: commit меняет статус раньше,
чем узнаёт, что тело не изменилось. Пункты очереди — в review_item и в ответе, не в отчёте.

Устройство и правила — docs/superpowers/specs/2026-11-05-amem-subproject-3-autocheck-design.md.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import psycopg

from .. import objects, records, review
from ..ocfl_store import ObjectStore
from . import level1, level2, level3, level4, numbers
from .level1 import Batch, Prepared
from .level2 import SourceCheck
from .report import Report


@dataclass
class Proposal:
    """Предложенная ревизия: новая запись, если record_id нет, иначе новая ревизия существующей.
    Статус агент не предлагает: его ставит автопроверка."""
    target: Literal["atom", "entity"]
    payload: dict
    record_id: uuid.UUID | str | None = None


@dataclass
class Submitted:
    """Ответ записи (разд. 2.3): что сделано и что только поставлено в очередь — «в очереди» не значит «сделано»."""
    state: str                         # approved или rejected
    changeset_id: uuid.UUID
    # отчёт amem.check/1, как он записан в changeset.check_report: план до записи (planned_status, risk);
    # итоговый статус — в records: при created = false он остаётся прежним и с планом расходится
    report: dict
    # label, target, record_id, revision_id, created, status, review_state
    records: list[dict] = field(default_factory=list)
    queued: list[dict] = field(default_factory=list)     # id, reason, label, record_id
    levels: dict[str, str] = field(default_factory=dict)  # «1»–«4» из отчёта и «5»: queued, not_applicable, skipped
    complete: bool = True              # в очереди ничего не появилось


RETIRED = frozenset({"deprecated", "superseded"})
CANDIDATE_CODES = ("conflict", "duplicate", "related")    # кандидаты уровней 3 и 4 — в details пункта


@dataclass
class _Plan:
    """Плановое решение по записи пачки: риск — до транзакции, статус — по статусу, перечитанному под блокировкой."""
    item: Prepared
    risk: list[str]
    warned: bool
    status: str | None = None          # итоговый статус записи; у правки проверенной — прежний verified
    pending: bool = False              # правка проверенной: ревизия ждёт решения человека


class _Retired(Exception):
    """Запись вывели из оборота между уровнями проверки и блокировкой: правка невозможна, транзакция откатывается."""

    def __init__(self, item: Prepared, status: str):
        super().__init__(item.label)
        self.item, self.status = item, status


def submit(conn: psycopg.Connection, store: ObjectStore, docs: Path, proposals: Sequence[Proposal],
           links: Sequence[dict] = (), *, agent: str, activity: uuid.UUID | None = None, reason: str | None = None,
           provider=None) -> Submitted:
    """Проверить пакет уровнями 1–4 и записать его со статусами, итогами сверки и пунктами очереди (разд. 1.1).

    Ошибка (violation) любого уровня — пакет отклонён целиком (records.reject), записей нет. Ошибки окружения
    (StoreError, сбой базы, EmbeddingError явного провайдера) уходят вызывающему: пакета в базе нет."""
    report = Report()
    levels = {"1": "done", "2": "done", "3": "skipped", "4": "skipped"}
    batch = level1.check(conn, proposals, links, report)
    checks = level2.check(conn, store, docs, batch, report, agent=agent)
    if report.has_violations():
        return _reject(conn, report, batch, levels, degraded=[], agent=agent, activity=activity, reason=reason)
    conflicts = level3.check(conn, batch, report)
    degraded = level4.check(conn, batch, report, provider=provider)
    levels["3"] = levels["4"] = "done"
    plans = [_risk(item, report, conflicts) for item in batch.items]
    try:
        with conn.transaction():
            return _write(conn, batch, plans, checks, report, levels, degraded, agent=agent, activity=activity,
                          reason=reason)
    except _Retired as e:
        report.add(1, "violation", "retired_record", e.item.label,
                   f"Запись вывели из оборота (статус {e.status}) во время проверки: сначала верните ей статус",
                   status=e.status)
    except records.RecordError as e:
        report.add(1, "violation", "record_error", _where(str(e), batch), f"Пакет не записан: {e}", error=str(e))
    return _reject(conn, report, batch, levels, degraded=degraded, agent=agent, activity=activity, reason=reason)


def _where(message: str, batch: Batch) -> str:
    """Место позднего отказа: метка записи или связи, с которой начинается сообщение records, иначе — пакет."""
    labels = [it.label for it in batch.items] + [f"links[{i}]" for i in range(len(batch.links))]
    for label in sorted(labels, key=len, reverse=True):
        if message == label or message.startswith(f"{label}:"):
            return label
    return "пакет"


def _reject(conn, report: Report, batch: Batch, levels: dict, *, degraded: list, agent: str, activity,
            reason) -> Submitted:
    """Отклонённый пакет: отчёт без records — записывать нечего; уровень 5 пропущен, очередь пуста."""
    body = report.as_json(levels=levels, records=[], templates=list(batch.templates), degraded=degraded)
    del body["records"]
    cs = records.reject(conn, agent=agent, check_report=body, activity=activity, reason=reason)
    return Submitted("rejected", cs, body, [], [], {**levels, "5": "skipped"}, True)


def _risk(item: Prepared, report: Report, conflicts: dict[str, list[str]]) -> _Plan:
    """Риск записи (разд. 7.1): правила high_risk её шаблонов и противоречие уровня 3; предупреждения — warning."""
    risk = []
    rules = item.rules.high_risk if item.rules is not None else frozenset()
    if "always" in rules:
        risk.append(f"template:{item.code}:always")
    if "numeric" in rules and item.target == "atom" and numbers.atom_numbers(item.payload):
        risk.append(f"template:{item.code}:numeric")
    risk.extend(conflicts.get(item.label, []))
    warned = any(i.severity == "warning" for i in report.for_label(item.label))
    return _Plan(item, risk, warned)


def _decide(plan: _Plan, status: str | None) -> None:
    """Политика по статусу записи, перечитанному под блокировкой (разд. 7.1)."""
    if status in RETIRED:
        raise _Retired(plan.item, status)
    if status == "verified":
        plan.status, plan.pending = "verified", True
        return
    if plan.warned or plan.risk:
        plan.status = "needs_review"
    else:
        plan.status = "draft" if plan.item.target == "atom" else "auto_verified"


def _write(conn, batch: Batch, plans: list[_Plan], checks: dict[str, list[SourceCheck]], report: Report,
           levels: dict, degraded: list, *, agent: str, activity, reason) -> Submitted:
    """Транзакция записи (разд. 7.5): порядок блокировок — агент, объекты, записи по возрастанию id."""
    conn.execute("INSERT INTO agent (id) VALUES (%s) ON CONFLICT (id) DO NOTHING", (agent,))
    conn.execute("SELECT pg_advisory_xact_lock_shared(%s)", (objects.OBJECTS_LOCK,))
    existing = sorted((p for p in plans if p.item.record_id is not None), key=lambda p: p.item.record_id)
    for p in existing:
        t = p.item.target
        row = conn.execute(f"SELECT status FROM {t} WHERE id = %s FOR NO KEY UPDATE", (p.item.record_id,)).fetchone()
        if row is None:
            raise records.RecordError(f"{p.item.label}: такой записи нет")
        _decide(p, row[0])
    for p in plans:
        if p.item.record_id is None:
            _decide(p, None)
    planned = [{"label": p.item.label, "target": p.item.target, "planned_status": p.status, "risk": list(p.risk)}
               for p in plans]
    body = report.as_json(levels=levels, records=planned, templates=list(batch.templates), degraded=degraded)
    items = [records.Item(p.item.target, p.item.payload, p.item.record_id,
                          status=p.status if p.item.record_id is None else None,
                          review_state="pending" if p.pending else "none") for p in plans]
    result = records.commit(conn, items, batch.links, agent=agent, activity=activity, reason=reason,
                            check_report=body)
    cs = result.changeset_id
    at = conn.execute("SELECT created_at FROM changeset WHERE id = %s", (cs,)).fetchone()[0]
    queued: list[dict] = []
    out: list[dict] = []
    for p, rev in zip(plans, result.revisions):
        t, label = rev.target, p.item.label
        if rev.created and p.item.record_id is not None and not p.pending:
            records.set_status_locked(conn, t, rev.record_id, p.status, agent=agent, reason="autocheck", at=at)
        _verdicts(conn, t, rev.revision_id, checks.get(label, []), at)
        if rev.created:
            reasons = _reasons(conn, p, rev)
            if p.item.record_id is not None:
                review.close_stale(conn, t, rev.record_id, at=at)
            details = _details(p, report)
            for why, extra in reasons:
                item = review.insert_item(conn, t, rev.record_id, rev.revision_id, why, changeset_id=cs,
                                          details={**details, **extra}, agent=agent, at=at)
                if item is not None:
                    queued.append({**item, "label": label})
        status = conn.execute(f"SELECT status FROM {t} WHERE id = %s", (rev.record_id,)).fetchone()[0]
        state = conn.execute(f"SELECT review_state FROM {t}_revision WHERE id = %s", (rev.revision_id,)).fetchone()[0]
        out.append({"label": label, "target": t, "record_id": rev.record_id, "revision_id": rev.revision_id,
                    "created": rev.created, "status": status, "review_state": state})
    semantic = any(q["reason"] == "semantic" for q in queued)
    return Submitted("approved", cs, body, out, queued,
                     {**levels, "5": "queued" if semantic else "not_applicable"}, not queued)


def _verdicts(conn, target: str, revision_id: uuid.UUID, checks: list[SourceCheck], at) -> None:
    """Итоги сверки уровня 2 — в строки source ревизии (разд. 4.7); и у ревизии с тем же телом (created = false)."""
    for c in checks:
        if c.verdict is None:
            continue
        conn.execute(f"UPDATE source SET verdict = %s, page = %s, anchor = %s, checked_at = %s "
                     f"WHERE {target}_revision_id = %s AND position = %s",
                     (c.verdict, c.page, c.anchor, at, revision_id, c.position))


def _reasons(conn, plan: _Plan, rev: records.Revision) -> list[tuple[str, dict]]:
    """Причины пунктов созданной ревизии (разд. 7.2): по итогу статуса, аудит и ссылки на старые версии объектов."""
    out: list[tuple[str, dict]] = []
    if plan.pending:
        out.append(("edit", {}))
    elif plan.status == "needs_review":
        out.append(("high_risk" if plan.risk else "warning", {}))
    elif plan.status == "draft":
        out.append(("semantic", {}))
    elif plan.status == "auto_verified" and review.in_audit(rev.revision_id, review.AUDIT_RATE):
        out.append(("audit", {}))
    # под разделяемой блокировкой объектов новых версий не появится: что старое сейчас — старое и при фиксации
    stale = conn.execute(
        f"SELECT s.position, s.object_id, s.object_version, latest.n FROM source s "
        "CROSS JOIN LATERAL (SELECT max(n) AS n FROM object_version v WHERE v.object_id = s.object_id) latest "
        f"WHERE s.{rev.target}_revision_id = %s AND s.object_version < latest.n ORDER BY s.position",
        (rev.revision_id,)).fetchall()
    if stale:
        old = [{"position": pos, "object": f"obj:{oid}", "version": n, "latest": latest}
               for pos, oid, n, latest in stale]
        out.append(("source_changed", {"objects": old}))
    return out


def _details(plan: _Plan, report: Report) -> dict:
    """details пункта: коды замечаний записи, риск, кандидаты уровней 3 и 4."""
    issues = report.for_label(plan.item.label)
    return {"issues": list(dict.fromkeys(i.code for i in issues)), "risk": list(plan.risk),
            "candidates": [{"code": i.code, **i.details} for i in issues if i.code in CANDIDATE_CODES]}
