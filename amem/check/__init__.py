"""Автопроверка записей перед записью в базу: уровни 1–4 (схема и шаблон, привязка к источнику, здравый смысл,
дубли), отчёт, действующие шаблоны, числа и единицы.

submit — единая точка записи знаний: уровни 1–4, затем одна транзакция записи. Отчёт (changeset.check_report)
пишется до ревизий и содержит только план: уровни, замечания, ослабления, шаблоны, плановый статус и риск записей.
Статус существующей записи ставится после records.commit и только у созданной ревизии: commit меняет статус раньше,
чем узнаёт, что тело не изменилось. Пункты очереди — в review_item и в ответе, не в отчёте.

Записи человека (агент person:, спецификация 3c, разд. 5): уровни 1–4 те же, но статус — verified без риска шаблонов
и без пунктов очереди, кроме source_changed (ссылка на не последнюю версию файла); правка моделью записи, текущую
ревизию которой записал человек, ждёт его решения (pending).

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
LOW_CONFIDENCE = 0.8          # confidence ниже — риск low_confidence, если шаблон его включает
CANDIDATE_CODES = ("conflict", "duplicate", "related")    # кандидаты уровней 3 и 4 — в details пункта


@dataclass
class _Plan:
    """Плановое решение по записи пачки: риск — до транзакции, статус — по статусу, перечитанному под блокировкой."""
    item: Prepared
    risk: list[str]
    warned: bool
    status: str | None = None          # итоговый статус записи; у правки проверенной — прежний verified
    pending: bool = False              # правка проверенной: ревизия ждёт решения человека
    person: bool = False               # пишет человек (person:): verified без риска и очереди
    owner: str | None = None           # агент текущей ревизии существующей записи — читается под блокировкой


class CheckError(ValueError):
    """Неверный вызов submit — до любой записи: пустая пачка, соединение без autocommit, задачи (activity) нет.
    Ошибки данных агента — не исключения, а замечания отчёта."""


class _Retired(Exception):
    """Запись вывели из оборота между уровнями проверки и блокировкой: правка невозможна, транзакция откатывается."""

    def __init__(self, item: Prepared, status: str):
        super().__init__(item.label)
        self.item, self.status = item, status


def submit(conn: psycopg.Connection, store: ObjectStore, docs: Path | None, proposals: Sequence[Proposal],
           links: Sequence[dict] = (), *, agent: str, activity: uuid.UUID | None = None, reason: str | None = None,
           provider=None, on_semantic_error: str = "raise") -> Submitted:
    """Проверить пакет уровнями 1–4 и записать его со статусами, итогами сверки и пунктами очереди (разд. 1.1).

    Ошибка (violation) любого уровня — пакет отклонён целиком (records.reject), записей нет. Ошибки окружения
    (StoreError, сбой базы, EmbeddingError явного провайдера) уходят вызывающему: пакета в базе нет; при
    on_semantic_error="skip" отказ провайдера только ослабляет уровень 4 (degraded отчёта). docs None — папка
    документов не настроена: источник с path получает source_unresolved. Неверный вызов — CheckError до любой
    записи."""
    _check_call(conn, proposals, links, activity)
    level4.check_semantic_error(on_semantic_error)       # и у пакета, который до уровня 4 не дойдёт
    report = Report()
    levels = {"1": "done", "2": "done", "3": "skipped", "4": "skipped"}
    batch = level1.check(conn, proposals, links, report, agent=agent)
    checks = level2.check(conn, store, docs, batch, report, agent=agent)
    if report.has_violations():
        return _reject(conn, report, batch, levels, degraded=[], agent=agent, activity=activity, reason=reason)
    conflicts = level3.check(conn, batch, report)
    degraded = level4.check(conn, batch, report, provider=provider, on_semantic_error=on_semantic_error)
    levels["3"] = levels["4"] = "done"
    person = _is_person(agent)
    plans = [_risk(item, report, conflicts, person=person) for item in batch.items]
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


def _check_call(conn, proposals: Sequence, links: Sequence, activity) -> None:
    """Проверки вызова — те, что records.commit иначе дал бы поздним отказом без метки записи."""
    if not conn.autocommit:
        raise CheckError("submit: нужно соединение с autocommit=True (db.connect): иначе запись не фиксируется")
    if not proposals and not links:
        raise CheckError("submit: пустая пачка — нет ни записей, ни связей")
    if activity is not None and conn.execute("SELECT 1 FROM activity WHERE id = %s", (activity,)).fetchone() is None:
        raise CheckError(f"submit: задачи (activity) {activity} нет")


def _where(message: str, batch: Batch) -> str:
    """Место позднего отказа: метка записи или связи, с которой начинается сообщение records. Сообщения без метки
    (пустая пачка, autocommit, activity) отсекает _check_call; на всякий случай — первая метка пачки."""
    labels = [it.label for it in batch.items] + [f"links[{i}]" for i in range(len(batch.links))]
    for label in sorted(labels, key=len, reverse=True):
        if message == label or message.startswith(f"{label}:"):
            return label
    return labels[0]


def _reject(conn, report: Report, batch: Batch, levels: dict, *, degraded: list, agent: str, activity,
            reason) -> Submitted:
    """Отклонённый пакет: отчёт без records — записывать нечего; уровень 5 пропущен, очередь пуста."""
    body = report.as_json(levels=levels, records=[], templates=list(batch.templates), degraded=degraded)
    del body["records"]
    cs = records.reject(conn, agent=agent, check_report=body, activity=activity, reason=reason)
    return Submitted("rejected", cs, body, [], [], {**levels, "5": "skipped"}, True)


def _is_person(agent: str) -> bool:
    return agent.startswith("person:")


def _risk(item: Prepared, report: Report, conflicts: dict[str, list[str]], *, person: bool = False) -> _Plan:
    """Риск записи (разд. 7.1): правила high_risk её шаблонов и противоречие уровня 3; предупреждения — warning.
    У записи человека риска нет: она и так проверена (замечания остаются в отчёте)."""
    if person:
        return _Plan(item, [], False, person=True)
    risk = []
    rules = item.rules.high_risk if item.rules is not None else frozenset()
    if "always" in rules:
        risk.append(f"template:{item.code}:always")
    if "numeric" in rules and item.target == "atom" and numbers.atom_numbers(item.payload):
        risk.append(f"template:{item.code}:numeric")
    confidence = item.payload.get("confidence") if item.target == "atom" else None
    if "low_confidence" in rules and confidence is not None and confidence < LOW_CONFIDENCE:
        risk.append(f"template:{item.code}:low_confidence")
    risk.extend(conflicts.get(item.label, []))
    warned = any(i.severity == "warning" for i in report.for_label(item.label))
    return _Plan(item, risk, warned)


def _decide(plan: _Plan, status: str | None) -> None:
    """Политика по статусу записи, перечитанному под блокировкой (разд. 7.1), и по агенту (спецификация 3c, разд. 5):
    запись человека — verified; правку моделью записи, текущую ревизию которой записал человек, решает человек.
    Отвергнутая запись (rejected) открытых пунктов не держит (review.CLOSING_STATUSES): пункт edit к ней сразу
    устарел бы и правка зависла бы в pending — поэтому её правка моделью идёт обычным путём, как до 3c."""
    if status in RETIRED:
        raise _Retired(plan.item, status)
    if plan.person:
        plan.status = "verified"
        return
    by_person = plan.owner is not None and _is_person(plan.owner) and status not in review.CLOSING_STATUSES
    if status == "verified" or by_person:
        plan.status, plan.pending = status, True        # статус остаётся прежним до решения человека
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
        p.owner = _owner(conn, t, p.item.record_id)
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
    # @имя записи пачки → её ссылка: кандидаты уровней 3–4 внутри пачки названы по имени, а в пункте очереди
    # человеку нужна запись, которую можно открыть
    named = {p.item.label: f"{records.PREFIX[rev.target]}:{rev.record_id}" for p, rev in zip(plans, result.revisions)
             if p.item.label.startswith("@")}
    for p, rev in zip(plans, result.revisions):
        t, label = rev.target, p.item.label
        if rev.created and p.item.record_id is not None and not p.pending:
            records.set_status_locked(conn, t, rev.record_id, p.status, agent=agent, reason="autocheck", at=at)
        _verdicts(conn, t, rev.revision_id, checks.get(label, []), at)
        if rev.created:
            reasons = _reasons(conn, p, rev)
            if p.item.record_id is not None:
                review.close_stale(conn, t, rev.record_id, at=at)
            details = _details(p, report, named)
            for why, extra in reasons:
                # у source_changed свой вопрос — изменившийся файл: замечаний и кандидатов пакета в нём нет
                item_details = extra if why == "source_changed" else {**details, **extra}
                item = review.insert_item(conn, t, rev.record_id, rev.revision_id, why, changeset_id=cs,
                                          details=item_details, agent=agent, at=at)
                if item is not None:
                    queued.append({**item, "label": label})
        status = conn.execute(f"SELECT status FROM {t} WHERE id = %s", (rev.record_id,)).fetchone()[0]
        state = conn.execute(f"SELECT review_state FROM {t}_revision WHERE id = %s", (rev.revision_id,)).fetchone()[0]
        out.append({"label": label, "target": t, "record_id": rev.record_id, "revision_id": rev.revision_id,
                    "created": rev.created, "status": status, "review_state": state})
    semantic = any(q["reason"] == "semantic" for q in queued)
    return Submitted("approved", cs, body, out, queued,
                     {**levels, "5": "queued" if semantic else "not_applicable"}, not queued)


def _owner(conn, target: str, record_id: uuid.UUID) -> str | None:
    """Агент текущей ревизии записи (под блокировкой записи: новой ревизии не появится)."""
    row = conn.execute(f"SELECT c.agent FROM {target}_current r JOIN changeset c ON c.id = r.changeset_id "
                       f"WHERE r.{target}_id = %s", (record_id,)).fetchone()
    return None if row is None else row[0]


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
    if plan.person:
        pass                       # запись человека проверена им самим; остаётся только вопрос о файле — source_changed
    elif plan.pending:
        out.append(("edit", {}))
    elif plan.status == "needs_review":
        out.append(("high_risk" if plan.risk else "warning", {}))
    elif plan.status == "draft":
        out.append(("semantic", {}))
    elif plan.status == "auto_verified" and review.in_audit(rev.revision_id, review.AUDIT_RATE):
        out.append(("audit", {}))
    # под разделяемой блокировкой объектов новых версий не появится: что старое сейчас — старое и при фиксации
    # details — в форме review.source_changed_details, общей с пересмотром при новой версии (разд. 8.8)
    stale = conn.execute(
        "SELECT s.object_id, array_agg(DISTINCT s.object_version ORDER BY s.object_version), latest.n FROM source s "
        "CROSS JOIN LATERAL (SELECT max(n) AS n FROM object_version v WHERE v.object_id = s.object_id) latest "
        f"WHERE s.{rev.target}_revision_id = %s AND s.object_version < latest.n "
        "GROUP BY s.object_id, latest.n ORDER BY s.object_id",
        (rev.revision_id,)).fetchall()
    if stale:
        out.append(("source_changed", review.source_changed_details(stale)))
    return out


def _details(plan: _Plan, report: Report, named: dict[str, str]) -> dict:
    """details пункта: коды замечаний записи, риск, кандидаты уровней 3 и 4 (кандидат из пачки — ссылкой на запись)."""
    issues = report.for_label(plan.item.label)
    return {"issues": list(dict.fromkeys(i.code for i in issues)), "risk": list(plan.risk),
            "candidates": [{"code": i.code, **c, "ref": named.get(c.get("ref"), c.get("ref"))}
                           for i in issues if i.code in CANDIDATE_CODES for c in i.details.get("candidates", [])]}
