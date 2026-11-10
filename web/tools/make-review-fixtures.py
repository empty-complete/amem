"""Образцы очереди проверки (часть E): пункты всех причин на записях метеостанции и их полные виды.

Запуск из web/: python3 tools/make-review-fixtures.py
"""
import copy
import json
from pathlib import Path

OUT = Path("src/mocks/fixtures")
recs = {r["ref"]: r for r in json.loads((OUT / "records.json").read_text(encoding="utf-8"))["items"]}
views = json.loads((OUT / "records-b.json").read_text(encoding="utf-8"))
P = "0193b7c2-5e1a-7d40-9f2e-0000000000"
A = lambda n: f"atm:{P}{n:02x}"  # noqa: E731
MANUAL = f"{P}a1"


# записи из руководства — с источником-руководством: очередь группируется по документу (часть J)
FROM_MANUAL = {A(0x09): "в диапазоне от −40 до +60 °C", A(0x0C): None}


def manual_source(quote):
    src = {k: v for k, v in copy.deepcopy(views[A(0x0B)]["sources"][0]).items() if k != "quote"}
    if quote:
        src["quote"] = quote
    else:
        src |= {"selectors": [], "verdict": "external"}
    return src


def view_of(ref):
    if ref in views:
        return copy.deepcopy(views[ref])
    r = recs[ref]
    sources = [manual_source(FROM_MANUAL[ref])] if ref in FROM_MANUAL else []
    return {
        "ref": ref, "target": r["target"], "revision": 1,
        "payload": {"kind": r["kind_or_class"], "label": {"ru": r["label"]}, "summary_plain": {"ru": r["label"] + "."},
                    "about": [a["ref"] for a in r.get("about", [])]},
        "status": r["status"], "review_state": "pending", "recorded_at": r["recorded_at"], "agent": r["agent"],
        "folder": r.get("folder"), "about": r.get("about", []), "ancestors": [], "sources": sources, "open_items": [],
        "usefulness": None,
    }


def item(n, ref, reason, details, created_by="model:checker", state="queued", at="2026-11-07T08:00:00Z", closed=None):
    r = recs[ref]
    return {"id": f"5f0c2a8e-1d3b-4c6a-9e7f-0a1b2c3d4e{n:02x}", "ref": ref, "label": r["label"], "kind_or_class": r["kind_or_class"],
            "reason": reason, "state": state, "details": details, "created_at": at, "created_by": created_by,
            "author": r["agent"], "claimed_by": None, "closed_at": closed}


items = [
    item(0x5F, A(0x0B), "semantic_doubt", {"verdict": "uncertain", "confidence": 0.58, "model": "model:checker",
                                          "note": "Модель сомневается: в тексте два диапазона, взят средний."}, at="2026-11-05T10:12:05Z"),
    item(0x01, A(0x1E), "edit", {"changes": ["label", "body"]}, created_by="model:linker", at="2026-11-07T07:40:00Z"),
    item(0x02, A(0x09), "source_changed", {"object": MANUAL, "from_version": 1, "to_version": 2}, created_by="model:watcher", at="2026-11-06T16:20:00Z"),
    # details — в форме ядра (check._details): коды замечаний, риск, кандидаты
    item(0x03, A(0x0C), "warning", {"issues": ["unit_suspect", "range_wide"], "risk": [], "candidates": []},
         at="2026-11-06T09:00:00Z"),
    item(0x04, A(0x1A), "high_risk", {"rule": "electrical", "message": "Электрическая величина — проверяет человек"}, at="2026-11-07T06:30:00Z"),
    item(0x05, A(0x1F), "imported", {"bundle": "meteo-2025", "from": "Станция прошлого сезона"}, created_by="person:anna", at="2026-11-04T12:00:00Z"),
    item(0x06, A(0x10), "audit", {"note": "Выборочная проверка записей с итогом «проверено автоматически»"}, created_by="person:anna", at="2026-11-07T05:10:00Z"),
    item(0x07, A(0x0E), "calibration", {"note": "Калибровка: сверка решения модели с человеком"}, at="2026-11-03T15:00:00Z"),
    item(0x08, A(0x12), "warning", {"issues": ["superseded"], "risk": [], "candidates": []},
         state="done", at="2026-11-02T10:00:00Z", closed="2026-11-02T11:30:00Z"),
]

full = {}
for it in items:
    v = view_of(it["ref"])
    entry = {"item": it, "record": v, "current": None, "proposed": None, "versions": None}
    if it["reason"] == "edit":
        cur = copy.deepcopy(v["payload"])
        prop = copy.deepcopy(cur)
        prop["label"] = {"ru": "Проверить крепление мачты после сильного ветра"}
        prop["body"] = {"ru": "Хомуты — **верхний, средний и нижний**. Отвес не больше *2°*.\n\n> Записал после бури 3 ноября."}
        entry["current"] = {"revision": v["revision"], "payload": cur}
        entry["proposed"] = {"payload": prop, "changes": ["label", "body"], "agent": "model:linker"}
    if it["reason"] == "source_changed":
        entry["versions"] = {
            "object": MANUAL, "object_name": "Руководство_МС-1.pdf", "page": "12",
            "old": {"version": 1, "text": "Датчик температуры Т-1 измеряет температуру воздуха в диапазоне от −35 до +60 °C."},
            "new": {"version": 2, "text": "Датчик температуры Т-1 измеряет температуру воздуха в диапазоне от −40 до +60 °C с погрешностью не более ±0,3 °C."},
        }
    full[it["id"]] = entry

backups = [
    {"name": "amemo-2026-11-07T03-00.dump", "created_at": "2026-11-07T03:00:00Z", "size": 1843200},
    {"name": "amemo-2026-11-06T03-00.dump", "created_at": "2026-11-06T03:00:00Z", "size": 1826400},
    {"name": "amemo-2026-10-31T03-00.dump", "created_at": "2026-10-31T03:00:00Z", "size": 1702400},
]
(OUT / "review-items.json").write_text(json.dumps(items, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
(OUT / "review-views.json").write_text(json.dumps(full, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
(OUT / "backups.json").write_text(json.dumps(backups, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(len(items), "items")
