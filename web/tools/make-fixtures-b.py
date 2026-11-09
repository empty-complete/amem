"""Образцы части B (чтение) на данных метеостанции МС-1 — те же ref, что в records.json части A.

Запуск из web/: python3 tools/make-fixtures-b.py — перезаписывает src/mocks/fixtures/*-b JSON.
"""
import json
from pathlib import Path

OUT = Path("src/mocks/fixtures")
P = "0193b7c2-5e1a-7d40-9f2e-0000000000"
E = lambda n: f"ent:{P}{n:02x}"  # noqa: E731
A = lambda n: f"atm:{P}{n:02x}"  # noqa: E731
MANUAL, SHEET = f"{P}a1", f"{P}a2"
ru = lambda s: {"ru": s}  # noqa: E731

ST, T1, B2, MAST, SITE = (
    {"ref": E(1), "label": "Метеостанция МС-1", "entity_class": "artifact"},
    {"ref": E(2), "label": "Датчик температуры Т-1", "entity_class": "artifact"},
    {"ref": E(3), "label": "Датчик влажности В-2", "entity_class": "artifact"},
    {"ref": E(5), "label": "Мачта М-2", "entity_class": "artifact"},
    {"ref": E(8), "label": "Метеоплощадка", "entity_class": "project"},
)
Q12 = "Погрешность ±2 % в диапазоне от 10 до 90 %"
manual_src = lambda quote, verdict="ok": {  # noqa: E731
    "object": MANUAL, "object_name": "Руководство_МС-1.pdf", "object_kind": "file",
    "media_type": "application/pdf", "object_version": 2,
    "selectors": [{"type": "page", "value": "2", "label": "12"}], "quote": quote, "role": "primary", "verdict": verdict,
}


def view(ref, payload, *, status="verified", review="none", agent="model:extractor", at="2026-11-05T10:12:00Z",
         folder="Области/Приборы", about=(), ancestors=(), sources=(), open_items=(), revision=1, target="atom",
         basis_source=False):
    if basis_source:  # заметка о файле: ссылается на него как на источник, без цитаты
        sources = [{k: v for k, v in manual_src("").items() if k != "quote"} | {"selectors": [], "verdict": "external", "role": "primary"}]
    return {"ref": ref, "target": target, "revision": revision, "payload": payload, "status": status,
            "review_state": review, "recorded_at": at, "agent": agent, "folder": folder, "about": list(about),
            "ancestors": list(ancestors), "sources": list(sources), "open_items": list(open_items), "usefulness": None}


BODY_A3 = """## Суть источника
Погрешность нормируется только в середине шкалы. У краёв — у сухого воздуха и у тумана — производитель не обещает ничего.

## Моя мысль
Зимой влажность у нас часто выше 90 %, а значит, погрешность в эти дни неизвестна. Точку росы по формуле Магнуса

$$T_d = \\frac{b\\,\\gamma(T,RH)}{a - \\gamma(T,RH)}, \\qquad \\gamma = \\ln\\frac{RH}{100} + \\frac{aT}{b+T}$$

при $RH > 90\\,\\%$ лучше считать с запасом. См. [[Нужен ли обогрев В-2 зимой?]] и [[Точка росы]]."""

records = {
    A(0x0B): view(A(0x0B), {
        "kind": "parameter", "label": ru("Погрешность влажности В-2: ±2 %"),
        "summary_plain": ru("Датчик влажности В-2 измеряет с погрешностью ±2 %, но только в диапазоне от 10 до 90 %."),
        "body": ru(BODY_A3), "about": [E(3)],
        "content": {"values": [{"property": "humidity_error", "label": ru("Погрешность"), "value_text": "±2", "unit": "%",
                                "qualifiers": [{"property": "range", "label": ru("в диапазоне"), "lower_bound": 10,
                                                "upper_bound": 90, "unit": "%"}]}]},
        "tags": ["метрология", "зима"], "qualifiers": [{"property": "maturity", "label": ru("Зрелость"), "value_text": "🌱 росток"}],
        "confidence": 0.82, "sources": [{"object": MANUAL, "object_version": 2, "selectors": [{"type": "page", "value": "2", "label": "12"}], "quote": Q12}],
    }, status="needs_review", review="pending", about=[B2], ancestors=[SITE, ST], sources=[manual_src(Q12)],
       open_items=[{"id": "5f0c2a8e-1d3b-4c6a-9e7f-0a1b2c3d4e5f", "ref": A(0x0B), "label": "Погрешность влажности В-2: ±2 %",
                    "kind_or_class": "parameter", "reason": "semantic_doubt", "state": "queued",
                    "details": {"note": "Модель сомневается: в тексте два диапазона, взят средний."},
                    "created_at": "2026-11-05T10:12:05Z", "created_by": "model:checker"}]),
    A(0x16): view(A(0x16), {
        "kind": "lesson", "label": ru("В-2 завышает влажность при обмерзании"),
        "summary_plain": ru("Когда на решётке В-2 иней, датчик показывает 97–100 %, хотя воздух суше."),
        "body": ru("Заметили в ноябре: утром после заморозка показания застывают у 100 % на час-два.\n\n"
                   "- сверили с психрометром — расхождение до 12 %;\n- после оттаивания всё возвращается.\n\n"
                   "Связано с [[Погрешность влажности В-2: ±2 %]]: вне диапазона 10–90 % производитель ничего не обещает."),
        "about": [E(3)], "tags": ["зима"],
    }, agent="person:anna", at="2026-11-06T08:40:00Z", about=[B2], ancestors=[SITE, ST], sources=[
        manual_src("Погрешность ±2 % в диапазоне от 10 до 90 %, вне его погрешность не нормируется.", "fuzzy"),
        {"object": SHEET, "object_name": "Наблюдения_ноябрь.xlsx", "object_kind": "file",
         "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "object_version": 1,
         "selectors": [{"type": "sheet", "value": "В-2"}, {"type": "range", "value": "B4:C9"}], "role": "secondary",
         "verdict": "by_locator"},
    ]),
    A(0x1E): view(A(0x1E), {
        "kind": "note", "label": ru("Проверить крепление мачты после ветра"),
        "summary_plain": ru("После порывов больше 15 м/с подтянуть хомуты мачты М-2 и проверить отвес."),
        "body": ru("Хомуты — **верхний и средний**. Отвес не больше *2°*.\n\n> Записал после бури 3 ноября."),
        "about": [E(5)], "basis": "author",
    }, status="draft", agent="person:anna", at="2026-11-04T17:02:00Z", folder=None, about=[MAST], ancestors=[SITE, ST]),
    A(0x14): view(A(0x14), {
        "kind": "term", "label": ru("Точка росы"),
        "summary_plain": ru("Температура, до которой надо охладить воздух, чтобы пар начал конденсироваться."),
        "body": ru("Приближение Магнуса: $T_d = \\frac{b\\gamma}{a-\\gamma}$, где $a = 17{,}62$, $b = 243{,}12$ °C."),
        "about": [E(3)],
    }, folder="Ресурсы/Методики и термины", about=[B2], ancestors=[SITE, ST], sources=[{k: v for k, v in manual_src("").items() if k != "quote"} | {"selectors": [], "verdict": "external", "role": "secondary"}]),
    E(3): view(E(3), {
        "entity_class": "artifact", "label": ru("Датчик влажности В-2"), "codes": ["В-2"],
        "description": ru("Ёмкостный датчик относительной влажности в составе МС-1."),
    }, target="entity", folder="Проекты/Метеоплощадка", ancestors=[SITE, ST]),
    f"note-{MANUAL}": view(A(0x20), {
        "kind": "note", "label": ru("Руководство МС-1 — о чём файл"),
        "summary_plain": ru("Руководство по эксплуатации метеостанции: комплект, датчики, монтаж и обслуживание."),
        "body": ru("Главное для нас — раздел **4.2** с диапазонами и погрешностями датчиков. Монтаж и обслуживание ещё не разобраны."),
        "sources": [{"object": MANUAL, "object_version": 2, "selectors": []}],
    }, folder="Ресурсы/Источники", agent="person:anna", basis_source=True),
}
records[A(0x20)] = records.pop(f"note-{MANUAL}")

# содержание сверх значений (часть I): формула с обозначениями и таблица — как у записей пакетов области
records[A(0x21)] = view(A(0x21), {
    "kind": "method", "label": ru("Точка росы по формуле Магнуса"),
    "summary_plain": ru("Точка росы считается по температуре и относительной влажности воздуха."),
    "about": [E(3)], "basis": "author",
    "content": {"formula": {
        "latex": "T_d = \\frac{b\\,\\gamma}{a - \\gamma}, \\quad \\gamma = \\ln\\frac{RH}{100} + \\frac{aT}{b+T}",
        "plain": "Td = b·γ / (a − γ), γ = ln(RH/100) + a·T / (b + T)",
        "symbols": [
            {"symbol": "T_d", "label": ru("точка росы"), "unit": "Cel"},
            {"symbol": "T", "label": ru("температура воздуха"), "unit": "Cel"},
            {"symbol": "RH", "label": ru("относительная влажность"), "unit": "%"},
            {"symbol": "a", "label": ru("коэффициент, 17,62")},
            {"symbol": "b", "label": ru("коэффициент, 243,12"), "unit": "Cel"},
        ]}},
}, folder="Ресурсы/Методики и термины", agent="person:anna", about=[B2])
records[A(0x22)] = view(A(0x22), {
    "kind": "fact", "label": ru("В-2 и психрометр: наблюдения 1–9 ноября"),
    "summary_plain": ru("При инее В-2 показывает на 10–11 % больше психрометра."),
    "about": [E(3)], "basis": "author",
    "content": {"table": {
        "columns": [{"code": "date", "label": ru("Дата")}, {"code": "v2", "label": ru("В-2"), "unit": "%"},
                    {"code": "psy", "label": ru("Психрометр"), "unit": "%"}, {"code": "t", "label": ru("T"), "unit": "Cel"},
                    {"code": "frost", "label": ru("Иней")}],
        "rows": [["01.11", 71, 70, 3.2, None], ["03.11", 99, 88, -2.4, "да"], ["04.11", 100, 89, -4.0, "да"],
                 {"date": "08.11", "v2": 87, "psy": 85, "t": 0.4}],
    }},
}, folder="Области/Приборы", agent="person:anna", about=[B2])

card = {
    "format": "amem.card/1", "entity": B2, "profile": "sensor", "templates": ["sensor"],
    "ancestors": [SITE, ST],
    "fields": [
        {"property": "range", "label": "Диапазон", "required": True, "group": "Измерение", "state": "known",
         "value": {"lower_bound": 0, "upper_bound": 100, "unit": "%"}, "atoms": [A(0x1D)], "by": "model", "status": "verified",
         "sources": [{"object": MANUAL, "label": "Руководство МС-1, с. 12"}]},
        {"property": "error", "label": "Погрешность", "required": True, "group": "Измерение", "state": "conflict",
         "atoms": [A(0x0B), A(0x16)], "candidates": [
             {"value": {"value_text": "±2", "unit": "%"}, "atom": A(0x0B), "quote": Q12, "source": "Руководство МС-1, с. 12"},
             {"value": {"value_text": "до 12", "unit": "%"}, "atom": A(0x16), "quote": "расхождение до 12 % при инее", "source": "Наблюдения, ноябрь, B4:C9"}]},
        {"property": "operating_temperature", "label": "Рабочая температура", "required": True, "group": "Условия",
         "state": "missing", "hint": "паспорт датчика, раздел «Условия эксплуатации»"},
        {"property": "heating", "label": "Обогрев", "required": False, "group": "Условия", "state": "asked",
         "ask": "Нужен ли обогрев В-2 зимой?", "atoms": [A(0x18)]},
        {"property": "ip", "label": "Степень защиты", "required": False, "group": "Условия", "state": "known",
         "value": {"value_text": "IP65"}, "atoms": [A(0x10)], "inherited_from": "Метеостанция МС-1"},
        {"property": "pressure_response", "label": "Отклик на давление", "required": False, "group": "Измерение", "state": "na"},
        {"property": "poll_interval", "label": "Интервал опроса", "required": False, "group": "Опрос", "state": "missing",
         "default": {"amount": 60, "unit": "s"}, "basis": "default"},
    ],
    "extra": [], "summary": {"known": 2, "total": 7},
}

objects = {
    MANUAL: {"id": MANUAL, "kind": "file", "original_name": "Руководство_МС-1.pdf", "media_type": "application/pdf",
             "url": None, "logical_paths": ["~/Документы/Метео/Руководство_МС-1.pdf"], "status": "partial", "pages": 2, "sheets": None,
             "versions": [{"n": 1, "digest": "sha256:9a1c…e04", "size": 38211, "recorded_at": "2026-10-28T09:00:00Z", "cited_by": 0},
                          {"n": 2, "digest": "sha256:4be7…a91", "size": 40666, "recorded_at": "2026-11-03T11:30:00Z", "cited_by": 3}],
             "cited_by": [
                 {"record": {"ref": A(0x0B), "label": "Погрешность влажности В-2: ±2 %", "kind": "parameter"}, "version": 2,
                  "selectors": [{"type": "page", "value": "2", "label": "12"}], "quote": Q12, "verdict": "ok"},
                 {"record": {"ref": A(0x16), "label": "В-2 завышает влажность при обмерзании", "kind": "lesson"}, "version": 2,
                  "selectors": [{"type": "page", "value": "2", "label": "12"}], "quote": "вне его погрешность не нормируется", "verdict": "fuzzy"},
                 {"record": {"ref": A(0x09), "label": "Диапазон температуры Т-1: −40…+60 °C", "kind": "parameter"}, "version": 2,
                  "selectors": [{"type": "page", "value": "2", "label": "12"}], "quote": "в диапазоне от −40 до +60 °C", "verdict": "ok"}]},
    SHEET: {"id": SHEET, "kind": "file", "original_name": "Наблюдения_ноябрь.xlsx",
            "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "url": None,
            "logical_paths": ["~/Документы/Метео/Наблюдения_ноябрь.xlsx"], "status": "partial", "pages": 3, "sheets": ["Т-1", "В-2", "Д-3"],
            "versions": [{"n": 1, "digest": "sha256:77d0…3c2", "size": 18432, "recorded_at": "2026-11-06T08:30:00Z", "cited_by": 1}],
            "cited_by": [{"record": {"ref": A(0x16), "label": "В-2 завышает влажность при обмерзании", "kind": "lesson"}, "version": 1,
                          "selectors": [{"type": "sheet", "value": "В-2"}, {"type": "range", "value": "B4:C9"}], "quote": None, "verdict": "by_locator"}]},
}
text_manual = {"pages": [
    "4.1 Комплект\nМетеостанция МС-1 поставляется с мачтой М-2, тремя датчиками и блоком питания 12 В.\nДанные передаются по линии RS-485 раз в минуту.",
    "4.2 Датчики\nДатчик температуры Т-1 измеряет температуру воздуха в диапазоне от −40 до +60 °C с погрешностью не более ±0,3 °C.\n"
    "При температуре ниже −40 °C показания датчика Т-1 не нормируются.\nДатчик влажности В-2 измеряет относительную влажность от 0 до 100 %.\n"
    "Погрешность ±2 % в диапазоне от 10 до 90 %, вне его погрешность не нормируется."]}
sheet = {"name": "В-2", "range": "A1:E10", "rows": [
    ["Дата", "В-2, %", "Психрометр, %", "T, °C", "Иней"],
    ["01.11", 71, 70, 3.2, None], ["02.11", 78, 76, 1.1, None],
    ["03.11", 99, 88, -2.4, "да"], ["04.11", 100, 89, -4.0, "да"], ["05.11", 97, 87, -3.1, "да"],
    ["06.11", 98, 90, -1.8, "да"], ["07.11", 100, 91, -2.2, "да"], ["08.11", 87, 85, 0.4, None], ["09.11", 74, 73, 2.0, None]]}

ev = lambda t, i, at, **kw: {"type": t, "id": f"ev-{i}", "at": at, **kw}  # noqa: E731
lab = {A(0x0B): "Погрешность влажности В-2: ±2 %", A(0x16): "В-2 завышает влажность при обмерзании",
       A(0x1E): "Проверить крепление мачты после ветра", A(0x18): "Нужен ли обогрев В-2 зимой?", A(0x10): "Степень защиты МС-1: IP65"}
changes = {"ref": None, "since": None, "until": None, "events": [
    ev("revision", 1, "2026-11-07T09:14:00Z", ref=A(0x16), label=lab[A(0x16)], agent="person:anna", revision=2),
    ev("link_created", 2, "2026-11-07T09:15:00Z", ref=A(0x16), label=lab[A(0x16)], agent="person:anna", rel="see_also", src=A(0x16), dst=A(0x0B)),
    ev("review", 3, "2026-11-07T08:02:00Z", ref=A(0x10), label=lab[A(0x10)], agent="person:anna", review_state="accepted"),
    ev("revision", 4, "2026-11-06T20:11:00Z", ref=A(0x18), label=lab[A(0x18)], agent="model:extractor", revision=1),
    ev("status", 5, "2026-11-06T19:40:00Z", ref=A(0x0B), label=lab[A(0x0B)], agent="model:checker", status="needs_review"),
    ev("link_retired", 6, "2026-11-06T12:00:00Z", ref=A(0x0B), label=lab[A(0x0B)], agent="model:linker", rel="see_also", src=A(0x0B), dst=A(0x14)),
    ev("revision", 7, "2026-11-04T17:02:00Z", ref=A(0x1E), label=lab[A(0x1E)], agent="person:anna", revision=1),
    ev("revision", 8, "2026-11-04T08:30:00Z", ref=A(0x0B), label=lab[A(0x0B)], agent="model:extractor", revision=1),
]}
history_a3 = {"ref": A(0x0B), "since": None, "until": None, "events": [e for e in changes["events"] if e.get("ref") == A(0x0B)]}
links_a3 = [
    {"id": "ln-1", "rel": "see_also", "direction": "out", "other": {"ref": A(0x18), "label": lab[A(0x18)], "kind": "question"}, "note": None, "confidence": None},
    {"id": "ln-2", "rel": "see_also", "direction": "in", "other": {"ref": A(0x16), "label": lab[A(0x16)], "kind": "lesson"}, "note": None, "confidence": None},
    {"id": "ln-3", "rel": "related", "direction": "out", "other": {"ref": A(0x14), "label": "Точка росы", "kind": "term"}, "note": None, "confidence": 0.7},
]
hit = lambda n, label, kind, about, score: {"ref": A(n), "revision": 1, "label": label, "snippet": label, "status": "verified",  # noqa: E731
                                           "review_state": "none", "kind": kind, "about": [about], "score": score,
                                           "matches": [{"channel": "semantic", "rank": 1}]}
similar_a3 = {"recipe": "similar", "semantic": "used", "candidate_count": 3, "retrieval_id": None, "items": [
    hit(0x1D, "Диапазон влажности В-2: 0…100 %", "parameter", B2, 0.81),
    hit(0x0A, "Погрешность температуры Т-1: ±0,3 °C", "parameter", T1, 0.74),
    hit(0x16, "В-2 завышает влажность при обмерзании", "lesson", B2, 0.69)]}

files = {"records-b.json": records, "card-e3.json": card, "objects-b.json": objects, "text-manual.json": text_manual,
         "sheet-v2.json": sheet, "changes.json": changes, "history-a3.json": history_a3, "links-a3.json": links_a3,
         "similar-a3.json": similar_a3}
for name, data in files.items():
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print("ok", ", ".join(files))
