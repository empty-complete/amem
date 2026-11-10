"""Образец базы «метеостанция» для веб-UI на настоящей службе: e2e (compose, профиль web) и снимки README.

То же содержание, что у моков веба (web/src/mocks/fixtures): метеостанция МС-1 с датчиками, руководство PDF с
цитатами на страницах, журнал наблюдений xlsx, заметки человека, папки PARA и очередь проверки с открытыми
пунктами. Всё пишется через amemo.api, как пишут агенты и человек, — значит, проходит автопроверку, а статусы и
очередь получаются настоящие.

Настройки — те же, что у службы (settings.load: AMEMO_DSN, AMEMO_DATA, AMEMO_DOCS, AMEMO_AGENT, amemo.toml).
Запуск: python tools/seed_sample.py [--force]; база с записями без --force — отказ (код 2).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "web" / "src" / "mocks" / "fixtures"
MODEL = "model:extractor"
MANUAL = "Метео/Руководство_МС-1.pdf"
SHEET = "Метео/Наблюдения_В-2.xlsx"
NOTE = "Заметки/Обход площадки.md"

ROWS = [
    ["Дата", "В-2, %", "Психрометр, %", "T, °C", "Иней"],
    ["01.11", 71, 70, 3.2, None],
    ["02.11", 78, 76, 1.1, None],
    ["03.11", 99, 88, -2.4, "да"],
    ["04.11", 100, 89, -4.0, "да"],
    ["05.11", 97, 87, -3.1, "да"],
    ["06.11", 98, 90, -1.8, "да"],
    ["07.11", 100, 91, -2.2, "да"],
    ["08.11", 87, 85, 0.4, None],
    ["09.11", 74, 73, 2.0, None],
]
NOTE_MD = """# Обход площадки

## Мачта
Мачту М-2 после сильного ветра проверить: растяжки и крепление к основанию.

## Иней
Утром 03.11 на корпусе В-2 иней, показания 99–100 % при психрометре 88 %.
"""


def ru(text: str) -> dict:
    return {"ru": text}


def pdf(page: int, quote: str, label: str) -> dict:
    return {"path": MANUAL, "selectors": [{"type": "page", "value": str(page), "label": label}], "quote": quote}


def write_docs(docs: Path) -> None:
    """Файлы-источники в папке документов: руководство (тот же PDF, что у моков), журнал xlsx, заметка."""
    import openpyxl

    (docs / "Метео").mkdir(parents=True, exist_ok=True)
    (docs / "Заметки").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / "manual.pdf", docs / MANUAL)
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "В-2"
    for row in ROWS:
        sheet.append(row)
    book.save(docs / SHEET)
    (docs / NOTE).write_text(NOTE_MD, encoding="utf-8")


def entities() -> list[dict]:
    def ent(ref, cls, label, **kw):
        return {"target": "entity", "payload": {"ref": ref, "entity_class": cls, "label": ru(label), **kw}}

    return [
        ent("@site", "project", "Метеоплощадка", description=ru("Площадка с метеостанцией МС-1 у корпуса.")),
        ent("@ms1", "artifact", "Метеостанция МС-1", codes=["мс-1"]),
        ent("@t1", "artifact", "Датчик температуры Т-1", codes=["т-1"]),
        ent("@v2", "artifact", "Датчик влажности В-2", codes=["в-2"]),
        ent("@d3", "artifact", "Датчик давления Д-3", codes=["д-3"]),
        ent("@mast", "artifact", "Мачта М-2", codes=["м-2"]),
        ent("@manual", "document", "Руководство МС-1"),
    ]


def facts() -> list[dict]:
    def atom(ref, kind, label, summary, about, source, **kw):
        return {"target": "atom", "payload": {"ref": ref, "kind": kind, "label": ru(label), "summary_plain": ru(summary),
                                              "about": about, "sources": [source], **kw}}

    return [
        atom("@t1_range", "parameter", "Диапазон температуры Т-1: −40…+60 °C",
             "Т-1 измеряет температуру воздуха от −40 до +60 °C.", ["@t1"],
             pdf(2, "в диапазоне от −40 до +60 °C", "12"),
             content={"values": [{"property": "temperature_range", "lower_bound": -40, "upper_bound": 60,
                                  "unit": "Cel"}]}, tags=["метрология"]),
        atom("@t1_error", "parameter", "Погрешность температуры Т-1: ±0,3 °C",
             "Т-1 ошибается не больше чем на 0,3 градуса.", ["@t1"],
             pdf(2, "с погрешностью не более ±0,3 °C", "12"),
             content={"values": [{"property": "temperature_error", "amount": 0.3, "value_text": "±0,3", "unit": "Cel"}]},
             tags=["метрология"]),
        atom("@t1_cold", "fact", "Ниже −40 °C показания Т-1 не нормируются",
             "В сильный мороз Т-1 показывает что-то, но производитель за это не отвечает.", ["@t1"],
             pdf(2, "При температуре ниже −40 °C показания датчика Т-1 не нормируются.", "12")),
        atom("@v2_range", "parameter", "Диапазон влажности В-2: 0…100 %",
             "В-2 измеряет относительную влажность во всём диапазоне.", ["@v2"],
             pdf(2, "Датчик влажности В-2 измеряет относительную влажность от 0 до 100 %.", "12"),
             content={"values": [{"property": "humidity_range", "lower_bound": 0, "upper_bound": 100, "unit": "%"}]}),
        atom("@v2_error", "parameter", "Погрешность влажности В-2: ±2 %",
             "В-2 измеряет с погрешностью ±2 %, но только в диапазоне от 10 до 90 %.", ["@v2"],
             pdf(2, "Погрешность ±2 % в диапазоне от 10 до 90 %", "12"),
             content={"values": [{"property": "humidity_error", "amount": 2, "value_text": "±2", "unit": "%",
                                  "qualifiers": [{"property": "range", "lower_bound": 10, "upper_bound": 90,
                                                  "unit": "%"}]}]},
             tags=["метрология", "зима"], confidence=0.82,
             body=ru("## Суть источника\nПогрешность нормируется только в середине шкалы. У краёв — у сухого воздуха "
                     "и у тумана — производитель не обещает ничего.\n\n## Формула\nТочка росы по Магнусу:\n\n"
                     "$$T_d = \\frac{b\\,\\gamma}{a - \\gamma}, \\qquad \\gamma = \\ln\\frac{RH}{100} + "
                     "\\frac{aT}{b+T}$$")),
        atom("@ms1_power", "parameter", "Напряжение питания МС-1: 12 В",
             "Станция работает от блока питания 12 вольт.", ["@ms1"],
             pdf(1, "блоком питания 12 В", "11"),
             content={"values": [{"property": "supply_voltage", "amount": 12, "unit": "V"}]}),
        atom("@ms1_rs485", "fact", "Данные МС-1 передаются по RS-485",
             "Станция отдаёт данные по линии RS-485 раз в минуту.", ["@ms1"],
             pdf(1, "Данные передаются по линии RS-485 раз в минуту.", "11")),
        atom("@ms1_kit", "fact", "МС-1 поставляется с мачтой М-2 и тремя датчиками",
             "В комплекте станции мачта, три датчика и блок питания.", ["@ms1", "@mast"],
             pdf(1, "Метеостанция МС-1 поставляется с мачтой М-2, тремя датчиками и блоком питания 12 В.", "11")),
        atom("@frost", "fact", "Иней на корпусе завышает показания В-2",
             "При инее В-2 показывает 99–100 %, а психрометр — около 88 %.", ["@v2"],
             {"path": SHEET, "selectors": [{"type": "sheet", "value": "В-2"}, {"type": "range", "value": "A4:E8"}]},
             tags=["зима"]),
    ]


def links() -> list[dict]:
    part = [("@t1", "@ms1"), ("@v2", "@ms1"), ("@d3", "@ms1"), ("@mast", "@ms1"), ("@ms1", "@site")]
    return [{"rel": "part_of", "src": s, "dst": d} for s, d in part] + [
        {"rel": "contradicts", "src": "@frost", "dst": "@v2_range", "note": ru("при инее шкала врёт у верхнего края")},
    ]


def person_notes(refs: dict[str, str]) -> list[dict]:
    def note(ref, kind, label, body, about, **kw):
        return {"target": "atom", "payload": {"ref": ref, "kind": kind, "label": ru(label), "summary_plain": ru(label),
                                              "body": ru(body), "about": about, "basis": "author", **kw}}

    return [
        note("@mast_2m", "decision", "Ставим мачту на 2 м",
             "Датчики не ниже 2 м от земли — так снег не заметает их зимой.", [refs["@mast"]]),
        note("@heating", "question", "Нужен ли обогрев В-2 зимой?",
             "Иней на корпусе даёт 99–100 %. Обогрев или другой датчик?", [refs["@v2"]]),
        note("@after_wind", "note", "Проверить крепление мачты после ветра",
             "Растяжки и основание. Записать, что нашли.", [refs["@mast"]]),
        note("@dew", "term", "Точка росы",
             "Температура, при которой пар в воздухе становится насыщенным и выпадает роса или иней.", []),
        note("@magnus", "method", "Точка росы по формуле Магнуса",
             "Считаем по температуре и влажности с В-2 и Т-1.", [refs["@v2"], refs["@t1"]],
             content={"formula": {
                 "latex": "T_d = \\frac{b\\,\\gamma}{a - \\gamma}, \\quad "
                          "\\gamma = \\ln\\frac{RH}{100} + \\frac{aT}{b+T}",
                 "plain": "Td = b·γ / (a − γ), γ = ln(RH/100) + a·T / (b + T)",
                 "symbols": [{"symbol": "T_d", "label": ru("точка росы"), "unit": "Cel"},
                             {"symbol": "T", "label": ru("температура воздуха"), "unit": "Cel"},
                             {"symbol": "RH", "label": ru("относительная влажность"), "unit": "%"}]}}),
        note("@frost_log", "fact", "В-2 и психрометр: наблюдения с инеем",
             "Сводка журнала: при инее В-2 показывает на 10–11 % больше психрометра.", [refs["@v2"]],
             content={"table": {
                 "columns": [{"code": "date", "label": ru("Дата")}, {"code": "v2", "label": ru("В-2"), "unit": "%"},
                             {"code": "psy", "label": ru("Психрометр"), "unit": "%"},
                             {"code": "t", "label": ru("T"), "unit": "Cel"}],
                 "rows": [["03.11", 99, 88, -2.4], ["04.11", 100, 89, -4.0], ["05.11", 97, 87, -3.1]]}}),
    ]


FOLDERS = {
    "Проекты/Метеоплощадка": ["@site", "@ms1", "@mast", "@ms1_power", "@ms1_rs485", "@ms1_kit", "@mast_2m",
                              "@heating", "@after_wind"],
    "Области/Приборы": ["@t1", "@v2", "@d3", "@t1_range", "@t1_error", "@t1_cold", "@v2_range", "@v2_error",
                        "@frost", "@frost_log"],
    "Ресурсы/Источники": ["@manual"],
    "Ресурсы/Методики и термины": ["@dew", "@magnus"],
}


def seed(conn, store, docs: Path, person: str) -> dict:
    from amemo import api

    write_docs(docs)
    first = api.submit(conn, store, docs, agent=MODEL, proposals=entities() + facts(), links=links(),
                       reason="разбор руководства МС-1 и журнала В-2")
    refs = {p["payload"]["ref"]: r["ref"] for p, r in zip(entities() + facts(), first["records"], strict=True)}
    second = api.submit(conn, store, docs, agent=person, proposals=person_notes(refs), reason="заметки с обхода")
    refs |= {p["payload"]["ref"]: r["ref"] for p, r in zip(person_notes(refs), second["records"], strict=True)}

    for folder, names in FOLDERS.items():
        api.folder_create(conn, folder, agent=person)
        for name in names:
            api.record_folder(conn, refs[name], folder, agent=person)

    # человек разбирает часть очереди: подтверждённое — verified; два пункта остаются открытыми для проверки в UI
    keep = {refs["@v2_error"], refs["@frost"]}
    for item in api.review_items(conn, state="queued"):
        if item["ref"] not in keep:
            api.review_resolve(conn, item["id"], agent=person, outcome="confirmed", note="сверено с руководством")
    return {"records": len(refs), "open": len(api.review_items(conn, state="queued"))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="писать и в базу, где уже есть записи")
    args = ap.parse_args(argv)

    from amemo import api, db, settings
    from amemo.ocfl_store import ObjectStore

    s = settings.load()
    if s.docs is None:
        print("amemo: нужна папка документов — AMEMO_DOCS", file=sys.stderr)
        return 2
    with db.connect(s.dsn) as conn:
        db.prepare(conn)
        counts = api.base(conn)["counts"]
        if counts["atoms"] + counts["entities"] and not args.force:
            print("amemo: в базе уже есть записи — образец пишется в пустую базу (или --force)", file=sys.stderr)
            return 2
        try:
            result = seed(conn, ObjectStore(s.data), s.docs, s.agent)
        except api.CheckRejected as e:
            print(f"amemo: {e}", file=sys.stderr)
            for issue in e.issues:
                print(f"  {issue['severity']}: {issue['ref']} {issue['path'] or ''}: {issue['message']}", file=sys.stderr)
            return 1
    print(f"образец записан: записей {result['records']}, открытых пунктов проверки {result['open']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
