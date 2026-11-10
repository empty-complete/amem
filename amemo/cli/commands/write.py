"""Запись: submit пакета, очередь проверки (review), папки (folders) — операции api, права — как у службы.

Файл submit — то же тело, что у POST /submit: {proposals, links?, reason?}; «-» — читать stdin. Отказ проверки —
код 5 и отчёт (замечания с местом). Модель не создаёт, не удаляет и не переименовывает папки и решает в очереди
только semantic — это проверяет api, у CLI своих правил нет.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ..errors import USAGE, CliError
from . import add, group

NO_FOLDER = "-"                     # «без папки» в move, как в контракте


def register(sub, shared) -> None:
    p = add(sub, shared, "submit", "записать пакет предложений (тело как у POST /submit)", run_submit)
    p.add_argument("file", metavar="FILE.json", help="файл пакета {proposals, links?, reason?}; «-» — stdin")

    _, review = group(sub, shared, "review", "очередь проверки")
    p = add(review, shared, "list", "пункты очереди", run_review_list)
    p.add_argument("--state", help="queued, claimed, done, obsolete")
    p.add_argument("--reason", help="причина пункта (semantic, edit, …)")
    p.add_argument("--record", help="пункты одной записи: atm:/ent: или UUID")
    p.add_argument("--limit", type=int, help="сколько пунктов (до 500, по умолчанию 100)")
    p = add(review, shared, "claim", "взять пункты, которые агент вправе решать", run_review_claim)
    p.add_argument("--reason", action="append", help="только эти причины (можно несколько раз)")
    p.add_argument("--limit", type=int, help="сколько пунктов (по умолчанию 1)")
    p = add(review, shared, "release", "вернуть взятый пункт в очередь", run_review_release)
    p.add_argument("item", metavar="ID", help="id пункта")
    p = add(review, shared, "resolve", "решить пункт", run_review_resolve)
    p.add_argument("item", metavar="ID", help="id пункта")
    p.add_argument("outcome", metavar="ИСХОД", help="confirmed, refuted (модель — ещё partial, uncertain)")
    p.add_argument("--confidence", type=float, help="уверенность 0–1 (модели обязательна)")
    p.add_argument("--note", help="пояснение решения")
    p = add(review, shared, "stats", "метрики очереди", run_review_stats)
    p.add_argument("--days", type=int, help="окно, дней (по умолчанию 7)")

    folders, inner = group(sub, shared, "folders", "папки: дерево, создать, удалить, переименовать, перенести")
    folders.set_defaults(run=run_folders_tree)          # amemo folders — дерево
    add(inner, shared, "tree", "дерево папок со счётчиками", run_folders_tree)
    p = add(inner, shared, "create", "создать папку (только человек)", run_folders_create)
    p.add_argument("path", metavar="ПУТЬ")
    p = add(inner, shared, "delete", "удалить пустую папку (только человек)", run_folders_delete)
    p.add_argument("path", metavar="ПУТЬ")
    p = add(inner, shared, "rename", "переименовать папку с вложенными и записями (только человек)",
            run_folders_rename)
    p.add_argument("path", metavar="ПУТЬ")
    p.add_argument("new_path", metavar="НОВЫЙ_ПУТЬ")
    p = add(inner, shared, "move", "переложить запись в папку («-» — без папки)", run_folders_move)
    p.add_argument("ref", metavar="REF", help="ссылка atm:/ent: или текст")
    p.add_argument("folder", metavar="ПАПКА")


# --- submit ---

def _read_json(name: str) -> dict:
    if name == "-":
        raw, where = sys.stdin.read(), "stdin"
    else:
        raw, where = Path(name).read_text(encoding="utf-8"), name
    try:
        body = json.loads(raw)
    except ValueError as e:
        raise CliError(f"{where}: не JSON: {e}", exit=USAGE, code="bad_file") from None
    if not isinstance(body, dict):
        raise CliError(f"{where}: нужен объект {{proposals, links?, reason?}}, как тело POST /submit", exit=USAGE,
                       code="bad_file")
    unknown = sorted(set(body) - {"proposals", "links", "reason"})
    if unknown:
        raise CliError(f"{where}: неизвестные поля {', '.join(unknown)}; допустимы proposals, links, reason",
                       exit=USAGE, code="bad_file")
    return body


def run_submit(ctx, args) -> int:
    from ... import api

    body = _read_json(args.file)
    conn = ctx.connect()
    result = api.submit(conn, ctx.store(), ctx.settings.docs, agent=ctx.agent, proposals=body.get("proposals"),
                        links=body.get("links"), reason=body.get("reason"), provider=ctx.provider())
    ctx.emit(result, submit_text)
    return 0


def submit_text(result: dict) -> str:
    lines = [f"Записано от пакета {result['changeset_id']}: записей {len(result['records'])}"
             + ("" if result["complete"] else " (проверка неполная)")]
    for rec in result["records"]:
        mark = "новая" if rec["created"] else "ревизия"
        lines.append(f"  {rec['label']} → {rec['ref']}  {rec['status']}  ({mark})")
    for item in result["queued"]:
        lines.append(f"  на проверку: {item['reason']}  {item['ref']}  пункт {item['id']}")
    for warning in result["warnings"]:
        where = warning["ref"] + (f": {warning['path']}" if warning["path"] else "")
        lines.append(f"  предупреждение {warning['code']}  {where} — {warning['message']}")
    return "\n".join(lines)


# --- очередь ---

def _item_line(item: dict) -> str:
    label = item.get("label") or item["ref"]
    return f"{item['id']}  {item['reason']}  {item['state']}  {label}  ({item['ref']})"


def run_review_list(ctx, args) -> int:
    from ... import api

    items = api.review_items(ctx.connect(), state=args.state, reason=args.reason, record=args.record,
                             limit=args.limit)
    ctx.emit(items, lambda found: "\n".join(_item_line(i) for i in found) or "Пунктов нет.")
    return 0


def run_review_claim(ctx, args) -> int:
    from ... import api

    items = api.review_claim(ctx.connect(), agent=ctx.agent, reasons=args.reason, limit=args.limit)

    def text(found):
        if not found:
            return "Решать нечего: свободных пунктов для этого агента нет."
        return "\n".join(f"{_item_line(i)}  до {i['claimed_until']}" for i in found)
    ctx.emit(items, text)
    return 0


def run_review_release(ctx, args) -> int:
    from ... import api

    done = api.review_release(ctx.connect(), args.item, agent=ctx.agent)
    ctx.emit(done, f"Пункт {done['id']} возвращён в очередь.")
    return 0


def run_review_resolve(ctx, args) -> int:
    from ... import api

    done = api.review_resolve(ctx.connect(), args.item, agent=ctx.agent, outcome=args.outcome, note=args.note,
                              confidence=args.confidence)
    text = f"Решено: статус записи {done['status']}"
    if done["queued"]:
        text += f"; новые пункты: {', '.join(done['queued'])}"
    ctx.emit(done, text)
    return 0


def run_review_stats(ctx, args) -> int:
    from ... import api

    ctx.emit(api.review_stats(ctx.connect(), days=args.days))
    return 0


# --- папки ---

def tree_text(tree: dict) -> str:
    lines = []

    def walk(nodes, depth):
        for node in nodes:
            lines.append(f"{'  ' * depth}{node['name']}  ({node['count']})")
            walk(node["children"], depth + 1)
    walk(tree["folders"], 0)
    lines.append(f"без папки: {tree['unfiled']}; всего записей: {tree['total']}")
    return "\n".join(lines)


def run_folders_tree(ctx, args) -> int:
    from ... import api

    ctx.emit(api.folder_tree(ctx.connect()), tree_text)
    return 0


def run_folders_create(ctx, args) -> int:
    from ... import api

    made = api.folder_create(ctx.connect(), args.path, agent=ctx.agent)
    ctx.emit(made, f"Папка создана: {made['path']}")
    return 0


def run_folders_delete(ctx, args) -> int:
    from ... import api

    api.folder_delete(ctx.connect(), args.path, agent=ctx.agent)
    ctx.emit({"path": args.path, "deleted": True}, f"Папка удалена: {args.path}")
    return 0


def run_folders_rename(ctx, args) -> int:
    from ... import api

    done = api.folder_rename(ctx.connect(), args.path, args.new_path, agent=ctx.agent)
    ctx.emit(done, lambda d: f"Папка {d['from']} → {d['to']}" if "from" in d else None)
    return 0


def run_folders_move(ctx, args) -> int:
    from ... import api

    conn = ctx.connect()
    folder = None if args.folder == NO_FOLDER else args.folder
    moved = api.record_folder(conn, api.pick(conn, args.ref), folder, agent=ctx.agent)
    ctx.emit(moved, f"{moved['label']} ({moved['ref']}) → {moved.get('folder') or 'без папки'}")
    return 0
