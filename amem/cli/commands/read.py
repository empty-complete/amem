"""Чтение: search (шаг 1), timeline (шаг 2), get (шаг 3), card — операции api, как у HTTP.

Явный `amem search` пишет строку в журнал запросов (amem/journal.py), как /search службы; --json на это не влияет.
REF у timeline, get и card — ссылка atm:/ent: или текст: текст ищется лексически (api.pick) и без явного лидера
даёт код 3 со списком кандидатов.
"""
from __future__ import annotations

import time

from . import add

SNIPPET = 160                       # знаков сниппета в текстовом выводе


def register(sub, shared) -> None:
    p = add(sub, shared, "search", "поиск (шаг 1): марки, полнотекстовый и смысловой каналы", run_search)
    p.add_argument("query", nargs="+", metavar="ЗАПРОС", help="текст или марка")
    p.add_argument("--kind", action="append", help="вид атома (можно несколько раз)")
    p.add_argument("--class", dest="entity_class", action="append", help="класс сущности (можно несколько раз)")
    p.add_argument("--status", action="append", help="статус (можно несколько раз)")
    p.add_argument("--target", choices=("atom", "entity"), help="только атомы или только сущности")
    p.add_argument("--limit", type=int, help="сколько находок (1–100, по умолчанию 10)")

    p = add(sub, shared, "timeline", "что вокруг записи (шаг 2): последние события и связи", run_timeline)
    p.add_argument("ref", metavar="REF", help="ссылка atm:/ent: или текст")
    p.add_argument("--limit", type=int, help="сколько последних событий (по умолчанию 10)")

    p = add(sub, shared, "get", "полные записи (шаг 3): тело, источники, открытые пункты", run_get)
    p.add_argument("refs", nargs="+", metavar="REF", help="ссылки atm:/ent: или текст")

    p = add(sub, shared, "card", "карточка сущности (amem.card/1)", run_card)
    p.add_argument("ref", metavar="REF", help="ссылка ent: или текст")
    p.add_argument("--no-ancestors", action="store_true", help="без полей предков")


def run_search(ctx, args) -> int:
    from ... import api, journal, private

    query = " ".join(args.query)
    conn = ctx.connect()
    started = time.monotonic()
    result = api.search(conn, query, agent=ctx.agent, kind=args.kind, status=args.status,
                        entity_class=args.entity_class, target=args.target, limit=args.limit,
                        provider=ctx.provider())
    row = conn.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()
    journal.record(ctx.settings.query_log, recipe=result["recipe"], query=private.strip(query), agent=ctx.agent,
                   base_id=row[0] if row else None, count=len(result["items"]),
                   duration_ms=(time.monotonic() - started) * 1000, retrieval_id=result["retrieval_id"])
    ctx.emit(result, search_text)
    return 0


def _kind(item: dict) -> str:
    kind = item.get("kind") or item.get("entity_class") or item.get("kind_or_class")
    return f"  [{kind}]" if kind else ""


def _short(text, limit: int = SNIPPET) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def search_text(result: dict) -> str:
    items = result["items"]
    if not items:
        lines = ["Ничего не найдено."]
    else:
        lines = []
        for n, item in enumerate(items, 1):
            lines.append(f"{n}. {item['label']}{_kind(item)}  {item['status']}")
            snippet = _short(item.get("snippet"))
            lines.append(f"   {item['ref']}" + (f" — {snippet}" if snippet else ""))
    footer = f"найдено: {len(items)}"
    if result.get("semantic") != "used":
        footer += "; смысловой канал не использован"
    if result.get("retrieval_id"):
        footer += f"; выдача {result['retrieval_id']}"
    return "\n".join(lines + [footer])


def run_timeline(ctx, args) -> int:
    from ... import api

    conn = ctx.connect()
    ctx.emit(api.timeline(conn, api.pick(conn, args.ref), limit=args.limit), timeline_text)
    return 0


def timeline_text(view: dict) -> str:
    rec = view["record"]
    lines = [f"{rec['label']}{_kind(rec)}  {rec['status']}  ({rec['ref']})"]
    if rec.get("folder"):
        lines.append(f"папка: {rec['folder']}")
    events = view["events"]
    lines.append(f"События (последние {len(events)} из {view['total_events']}):")
    for event in events:
        detail = ""
        if event["type"] == "status":
            detail = f"{event.get('from') or '—'} → {event.get('to') or '—'}"
        elif event["type"] == "folder":
            detail = f"{event.get('from') or '—'} → {event.get('to') or '—'}"
        elif event["type"] in ("revision", "review"):
            detail = " ".join(str(event[key]) for key in ("n", "outcome", "method") if event.get(key) is not None)
        lines.append(f"  {event['at']}  {event['type']}  {event.get('agent') or ''}  {detail}".rstrip())
    if view["links"]:
        lines.append("Связи:")
        for link in view["links"]:
            arrow = "→" if link["direction"] == "out" else "←"
            other = link["other"]
            lines.append(f"  {arrow} {link['rel']}  {other['label']}  ({other['ref']})")
    return "\n".join(lines)


def run_get(ctx, args) -> int:
    from ... import api

    conn = ctx.connect()
    views = [api.record(conn, api.pick(conn, ref)) for ref in args.refs]
    ctx.emit(views, lambda found: "\n\n".join(record_text(view) for view in found))
    return 0


def _lang(value) -> str | None:
    if isinstance(value, dict):
        return value.get("ru") or value.get("en") or next((v for v in value.values() if isinstance(v, str)), None)
    return value if isinstance(value, str) else None


def record_text(view: dict) -> str:
    payload = view["payload"]
    label = _lang(payload.get("label")) or view["ref"]
    kind = payload.get("kind") or payload.get("entity_class")
    lines = [f"{label}" + (f"  [{kind}]" if kind else "") + f"  {view['status']}",
             f"{view['ref']}  ревизия {view['revision']}, {view['recorded_at']}, {view['agent']}"]
    if view.get("folder"):
        lines.append(f"папка: {view['folder']}")
    if view["about"]:
        lines.append("о чём: " + "; ".join(f"{a['label']} ({a['ref']})" for a in view["about"]))
    summary = _lang(payload.get("summary_plain")) or _lang(payload.get("summary"))
    if summary:
        lines.append(summary)
    for source in view["sources"]:
        name = source.get("object_name") or source["object"]
        quote = _short(source.get("quote"), 120)
        verdict = source.get("verdict") or "не сверялся"
        lines.append(f"  источник: {name} (версия {source['object_version']}, {verdict})"
                     + (f" — «{quote}»" if quote else ""))
    for item in view["open_items"]:
        lines.append(f"  на проверке: {item['reason']} {item['state']}  {item['id']}")
    if view.get("usefulness") is not None:
        lines.append(f"полезность: {view['usefulness']}")
    return "\n".join(lines)


def run_card(ctx, args) -> int:
    from ... import api

    conn = ctx.connect()
    card = api.card(conn, api.pick(conn, args.ref, target="entity"), ancestors=not args.no_ancestors)
    ctx.emit(card, card_text)
    return 0


def card_text(card: dict) -> str:
    entity = card["entity"]
    lines = [f"{entity['label']}  [{entity['entity_class']}]  ({entity['ref']})"]
    if card.get("ancestors"):
        lines.append("в составе: " + " / ".join(a["label"] for a in card["ancestors"]))
    for field in card["fields"]:
        name = field.get("label") or field["property"]
        value = field.get("value")
        if isinstance(value, dict):
            value = " ".join(str(value[k]) for k in ("value", "unit", "text") if value.get(k) is not None) or value
        shown = "—" if value is None else value
        mark = "*" if field.get("required") else " "
        lines.append(f" {mark}{name}: {shown}  ({field['state']})")
    return "\n".join(lines)
