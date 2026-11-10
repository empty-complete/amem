"""English sample base "North Ridge weather network" for the README screenshots (docs/assets/readme/en).

A fictional network of four automatic weather stations: an operating manual, sensor datasheets and a calibration
report (PDF), a maintenance log (xlsx) and field notes (Markdown), about 70 records with quotes on real pages,
a domain pack with station and sensor profiles (tools/sample_en/pack) and an open review queue. Everything is
written through amem.api, the way agents and people write, so statuses and the queue are real.

Text goes to the `en` slot of every LangString: schema v1 needs one of `ru`, `en`, and the English UI shows `en`.

Settings are the service's (settings.load: AMEM_DSN, AMEM_DATA, AMEM_DOCS, AMEM_AGENT, amem.toml); the pack is
added to AMEM_PACKS here, the service needs the same AMEM_PACKS to show the profiles.
Run: python tools/seed_sample_en.py [--force]; a base that already has records is refused without --force (code 2).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "tools" / "sample_en" / "pack"
MODEL = "model:extractor"
MANUAL = "Network/WS-100 station manual.pdf"
SHEETS = "Network/Sensor datasheets.pdf"
CALIB = "Network/Calibration report 2026.pdf"
LOG = "Network/Maintenance log.xlsx"
NOTES = "Notes/Site visits.md"

# printed page label → paragraphs; the first one is the heading
MANUAL_PAGES = {
    "3": ["2 Delivery set",
          "The WS-100 automatic weather station ships with a 10 m mast, a TH-20 temperature and humidity sensor, "
          "a PB-10 barometer, an AN-5 anemometer, an RG-2 rain gauge and a DL-4 data logger.",
          "The station runs on 12 V from a 20 W solar panel and a 26 Ah battery.",
          "With a full battery the station keeps working for 7 days without sun."],
    "4": ["3 Data",
          "The DL-4 logger samples every sensor once every 60 s and stores 10-minute averages.",
          "Data are sent over LoRaWAN every 10 minutes.",
          "If the link is lost, the logger keeps 90 days of data.",
          "The enclosure is rated IP65."],
    "5": ["4 Installation and maintenance",
          "Mount the TH-20 sensor in a radiation shield at 2 m above the ground.",
          "Mount the AN-5 anemometer at the top of the 10 m mast, away from buildings and trees.",
          "Clean the RG-2 funnel and check the mast guy wires every 6 months.",
          "Operating temperature of the station: from -40 to +60 °C."],
}
SHEET_PAGES = {
    "1": ["TH-20 temperature and humidity sensor",
          "Temperature range: -40 to +60 °C, accuracy ±0.2 °C.",
          "Humidity range: 0 to 100 %RH.",
          "Humidity accuracy: ±2 %RH from 10 to 90 %RH.",
          "Outside 10 to 90 %RH the humidity accuracy is not specified.",
          "Supply voltage: 5 to 24 V DC."],
    "2": ["PB-10 barometer",
          "Pressure range: 500 to 1100 hPa.",
          "Accuracy: ±0.3 hPa at 20 °C.",
          "Long-term drift: less than 0.1 hPa per year."],
    "3": ["AN-5 cup anemometer",
          "Wind speed range: 0.5 to 60 m/s.",
          "Accuracy: ±0.3 m/s up to 10 m/s.",
          "Starting threshold: 0.5 m/s.",
          "A heated version is available for icing conditions."],
    "4": ["RG-2 tipping bucket rain gauge",
          "Collecting area: 200 cm², resolution 0.2 mm per tip.",
          "Accuracy: ±2 % up to 50 mm/h.",
          "Snow is not measured unless the heated funnel kit is installed."],
}
CALIB_PAGES = {
    "1": ["Calibration results, March 2026",
          "WS-1 Ridge Top: the TH-20 reads humidity 3.1 %RH high against the reference.",
          "WS-1 Ridge Top: temperature is within ±0.1 °C of the reference.",
          "WS-2 Lake Shore: the PB-10 reads 0.4 hPa low; adjusted on site.",
          "WS-3 Valley Farm: all sensors are within specification.",
          "WS-4 Airfield: the AN-5 bearing is worn, the starting threshold is 1.2 m/s; a replacement is ordered."],
}
LOG_ROWS = [
    ["Date", "Station", "Finding", "Action"],
    ["2026-01-14", "WS-1", "Frost on the TH-20 shield, humidity at 99-100 %RH", "Shield cleaned"],
    ["2026-01-15", "WS-1", "Humidity still at 100 %RH in the morning", "Compared with a psychrometer: 88 %RH"],
    ["2026-02-03", "WS-4", "No data for 3 days", "LoRaWAN gateway restarted; logger kept the data"],
    ["2026-03-10", "WS-2", "Guy wire loose after a storm", "Wire tightened"],
    ["2026-10-21", "WS-3", "Rain gauge funnel clogged by leaves", "Funnel cleaned"],
    ["2026-10-28", "WS-3", "Funnel clogged by leaves again", "Gauge to be moved away from the oaks"],
    ["2026-12-09", "WS-1", "Battery flat after 5 days of fog", "Battery charged; heated sensors to be decided"],
]
NOTES_MD = """# Site visits

## WS-1 Ridge Top
Icing on the anemometer cups twice in January. Ask for the heated AN-5.

## WS-3 Valley Farm
The oaks drop leaves into the rain gauge every autumn.

## Winter
Fog and short days drain the battery faster than the manual says.
"""


def text(value: str) -> dict:
    return {"en": value}       # an English base: LangString needs one of ru, en


def page(path: str, n: int, label: str, quote: str) -> dict:
    return {"path": path, "selectors": [{"type": "page", "value": str(n), "label": label}], "quote": quote}


def manual(label: str, quote: str) -> dict:
    return page(MANUAL, list(MANUAL_PAGES).index(label) + 1, label, quote)


def sheet(label: str, quote: str) -> dict:
    return page(SHEETS, list(SHEET_PAGES).index(label) + 1, label, quote)


def calib(quote: str) -> dict:
    return page(CALIB, 1, "1", quote)


def log(cells: str) -> dict:
    return {"path": LOG, "selectors": [{"type": "sheet", "value": "Log"}, {"type": "range", "value": cells}]}


def write_pdf(path: Path, pages: dict[str, list[str]], title: str) -> None:
    import pymupdf

    doc = pymupdf.open()
    for label, lines in pages.items():
        p = doc.new_page(width=595, height=842)
        y = 72
        for i, line in enumerate(lines):
            size = 15 if i == 0 else 11
            p.insert_textbox(pymupdf.Rect(72, y, 523, y + 80), line, fontname="helv", fontsize=size)
            y += 46 if i == 0 else (40 if len(line) < 80 else 58)
        p.insert_text((290, 800), label, fontname="helv", fontsize=9)
    doc.set_metadata({"title": title, "author": "amem sample"})
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path, garbage=4, deflate=True)


def write_docs(docs: Path) -> None:
    import openpyxl

    write_pdf(docs / MANUAL, MANUAL_PAGES, "WS-100 automatic weather station: operating manual (sample)")
    write_pdf(docs / SHEETS, SHEET_PAGES, "WS-100 sensors: datasheets (sample)")
    write_pdf(docs / CALIB, CALIB_PAGES, "North Ridge network: calibration report 2026 (sample)")
    book = openpyxl.Workbook()
    ws = book.active
    ws.title = "Log"
    for row in LOG_ROWS:
        ws.append(row)
    book.save(docs / LOG)
    (docs / NOTES).parent.mkdir(parents=True, exist_ok=True)
    (docs / NOTES).write_text(NOTES_MD, encoding="utf-8")


def entities() -> list[dict]:
    def ent(ref, cls, label, **kw):
        return {"target": "entity", "payload": {"ref": ref, "entity_class": cls, "label": text(label), **kw}}

    return [
        ent("@net", "project", "North Ridge weather network",
            description=text("Four automatic weather stations on the ridge, by the lake, on a farm and at the airfield.")),
        ent("@ws100", "station", "WS-100 automatic weather station", codes=["ws-100"]),
        ent("@ws1", "station", "WS-1 Ridge Top", codes=["ws-1"]),
        ent("@ws2", "station", "WS-2 Lake Shore", codes=["ws-2"]),
        ent("@ws3", "station", "WS-3 Valley Farm", codes=["ws-3"]),
        ent("@ws4", "station", "WS-4 Airfield", codes=["ws-4"]),
        ent("@th20", "sensor", "TH-20 temperature and humidity sensor", codes=["th-20"]),
        ent("@pb10", "sensor", "PB-10 barometer", codes=["pb-10"]),
        ent("@an5", "sensor", "AN-5 cup anemometer", codes=["an-5"]),
        ent("@rg2", "sensor", "RG-2 rain gauge", codes=["rg-2"]),
        ent("@dl4", "artifact", "DL-4 data logger", codes=["dl-4"]),
        ent("@mast", "artifact", "10 m mast"),
        ent("@manual", "document", "WS-100 operating manual"),
        ent("@sheets", "document", "WS-100 sensor datasheets"),
        ent("@calib", "document", "Calibration report 2026"),
    ]


def value(prop, unit, amount=None, low=None, high=None, **kw) -> dict:
    v = {"property": prop, "unit": unit, **kw}
    if amount is not None:
        v["amount"] = amount
    if low is not None:
        v["lower_bound"], v["upper_bound"] = low, high
    return v


def facts() -> list[dict]:
    def atom(ref, kind, label, summary, about, source, values=None, **kw):
        body = {"ref": ref, "kind": kind, "label": text(label), "summary_plain": text(summary), "about": about,
                "sources": [source], **kw}
        if values:
            body["content"] = {"values": values}
        return {"target": "atom", "payload": body}

    p = "parameter"
    return [
        # operating manual
        atom("@kit", "fact", "WS-100 ships with a 10 m mast, four sensors and a DL-4 logger",
             "The delivery set: mast, TH-20, PB-10, AN-5, RG-2 and the DL-4 data logger.",
             ["@ws100", "@mast", "@th20", "@pb10", "@an5", "@rg2", "@dl4"],
             manual("3", "ships with a 10 m mast, a TH-20 temperature and humidity sensor, a PB-10 barometer, "
                         "an AN-5 anemometer, an RG-2 rain gauge and a DL-4 data logger")),
        atom("@volt", p, "WS-100 supply voltage: 12 V", "The station runs on 12 volts.", ["@ws100"],
             manual("3", "The station runs on 12 V"), [value("supply_voltage", "V", 12)]),
        atom("@solar", p, "WS-100 solar panel: 20 W", "A 20 W solar panel charges the battery.", ["@ws100"],
             manual("3", "from a 20 W solar panel"), [value("solar_panel_power", "W", 20)]),
        atom("@battery", p, "WS-100 battery capacity: 26 Ah", "The battery holds 26 ampere-hours.", ["@ws100"],
             manual("3", "a 26 Ah battery"), [value("battery_capacity", "A.h", 26)]),
        atom("@autonomy", p, "WS-100 runs 7 days without sun", "A full battery lasts 7 days with no sun.", ["@ws100"],
             manual("3", "With a full battery the station keeps working for 7 days without sun."),
             [value("battery_autonomy", "d", 7)]),
        atom("@sampling", p, "DL-4 samples every sensor every 60 s",
             "The logger reads each sensor once every 60 s and stores 10-minute averages.", ["@ws100", "@dl4"],
             manual("4", "samples every sensor once every 60 s and stores 10-minute averages"),
             [value("sampling_interval", "s", 60)]),
        atom("@transmit", p, "Data go out over LoRaWAN every 10 minutes", "The logger sends data every 10 minutes.",
             ["@ws100", "@dl4"], manual("4", "Data are sent over LoRaWAN every 10 minutes."),
             [value("transmit_interval", "min", 10)]),
        atom("@retention", p, "DL-4 keeps 90 days of data without a link",
             "If the link is lost, nothing is lost for 90 days.", ["@ws100", "@dl4"],
             manual("4", "If the link is lost, the logger keeps 90 days of data."), [value("data_retention", "d", 90)]),
        atom("@ip65", "fact", "The WS-100 enclosure is rated IP65", "Dust-tight and protected from water jets.",
             ["@ws100"], manual("4", "The enclosure is rated IP65.")),
        atom("@shield", "requirement", "Mount the TH-20 in a radiation shield at 2 m",
             "Sun and ground heat skew the readings otherwise; 2 m above the ground.", ["@th20"],
             manual("5", "Mount the TH-20 sensor in a radiation shield at 2 m above the ground.")),
        atom("@an5_top", "requirement", "Mount the AN-5 at the top of the 10 m mast",
             "Away from buildings and trees, at the top of the 10 m mast.", ["@an5", "@mast"],
             manual("5", "Mount the AN-5 anemometer at the top of the 10 m mast, away from buildings and trees.")),
        atom("@service", "requirement", "Clean the rain gauge and check guy wires every 6 months",
             "Maintenance every 6 months: RG-2 funnel and mast guy wires.", ["@rg2", "@mast"],
             manual("5", "Clean the RG-2 funnel and check the mast guy wires every 6 months.")),
        atom("@optemp", p, "WS-100 operating temperature: -40 to +60 °C", "The station works from -40 to +60 °C.",
             ["@ws100"], manual("5", "Operating temperature of the station: from -40 to +60 °C."),
             [value("operating_temperature", "Cel", low=-40, high=60)]),
        atom("@mast_h", p, "Mast height: 10 m", "The wind sensor sits on top of a 10 m mast.", ["@ws100", "@mast"],
             manual("5", "at the top of the 10 m mast"), [value("mast_height", "m", 10)]),
        # sensor datasheets
        atom("@th_trange", p, "TH-20 temperature range: -40 to +60 °C", "TH-20 measures from -40 to +60 °C.",
             ["@th20"], sheet("1", "Temperature range: -40 to +60 °C"),
             [value("temperature_range", "Cel", low=-40, high=60)]),
        atom("@th_tacc", p, "TH-20 temperature accuracy: ±0.2 °C", "TH-20 is accurate to 0.2 degrees.", ["@th20"],
             sheet("1", "accuracy ±0.2 °C"), [value("temperature_accuracy", "Cel", 0.2, value_text="±0.2")]),
        atom("@th_hrange", p, "TH-20 humidity range: 0 to 100 %RH", "TH-20 covers the whole humidity scale.",
             ["@th20"], sheet("1", "Humidity range: 0 to 100 %RH."), [value("humidity_range", "%", low=0, high=100)]),
        atom("@th_hacc", p, "TH-20 humidity accuracy: ±2 %RH",
             "TH-20 is accurate to ±2 %RH, but only between 10 and 90 %RH.", ["@th20"],
             sheet("1", "Humidity accuracy: ±2 %RH from 10 to 90 %RH."),
             [value("humidity_accuracy", "%", 2, value_text="±2",
                    qualifiers=[{"property": "humidity_range", "lower_bound": 10, "upper_bound": 90, "unit": "%"}])],
             tags=["metrology", "winter"], confidence=0.82,
             body=text("## What the source says\nThe accuracy is only specified in the middle of the scale. Near the "
                       "edges, in dry air and in fog, the vendor promises nothing.\n\n## Formula\nDew point by "
                       "Magnus:\n\n$$T_d = \\frac{b\\,\\gamma}{a - \\gamma}, \\qquad \\gamma = \\ln\\frac{RH}{100} + "
                       "\\frac{aT}{b+T}$$")),
        atom("@th_edges", "fact", "TH-20 humidity accuracy is not specified outside 10–90 %RH",
             "Near saturation, in fog and frost, the reading may be off by more than 2 %RH.", ["@th20"],
             sheet("1", "Outside 10 to 90 %RH the humidity accuracy is not specified.")),
        atom("@th_volt", p, "TH-20 supply voltage: 5 to 24 V DC", "TH-20 takes 5 to 24 volts DC.", ["@th20"],
             sheet("1", "Supply voltage: 5 to 24 V DC."), [value("supply_voltage", "V", low=5, high=24)]),
        atom("@pb_range", p, "PB-10 pressure range: 500 to 1100 hPa", "PB-10 measures from 500 to 1100 hPa.",
             ["@pb10"], sheet("2", "Pressure range: 500 to 1100 hPa."),
             [value("pressure_range", "hPa", low=500, high=1100)]),
        atom("@pb_acc", p, "PB-10 accuracy: ±0.3 hPa", "PB-10 is accurate to 0.3 hPa at 20 °C.", ["@pb10"],
             sheet("2", "Accuracy: ±0.3 hPa at 20 °C."), [value("pressure_accuracy", "hPa", 0.3, value_text="±0.3")]),
        atom("@pb_drift", "fact", "PB-10 drifts less than 0.1 hPa per year", "Long-term drift is below 0.1 hPa a year.",
             ["@pb10"], sheet("2", "Long-term drift: less than 0.1 hPa per year.")),
        atom("@an_range", p, "AN-5 wind speed range: 0.5 to 60 m/s", "AN-5 measures wind from 0.5 to 60 m/s.",
             ["@an5"], sheet("3", "Wind speed range: 0.5 to 60 m/s."),
             [value("wind_speed_range", "m/s", low=0.5, high=60)]),
        atom("@an_acc", p, "AN-5 accuracy: ±0.3 m/s up to 10 m/s", "AN-5 is accurate to 0.3 m/s below 10 m/s.",
             ["@an5"], sheet("3", "Accuracy: ±0.3 m/s up to 10 m/s."),
             [value("wind_speed_accuracy", "m/s", 0.3, value_text="±0.3")]),
        atom("@an_start", p, "AN-5 starting threshold: 0.5 m/s", "AN-5 starts turning at 0.5 m/s.", ["@an5"],
             sheet("3", "Starting threshold: 0.5 m/s."), [value("starting_threshold", "m/s", 0.5)]),
        atom("@an_heated", "fact", "A heated AN-5 exists for icing conditions",
             "Where cups ice up, order the heated version.", ["@an5"],
             sheet("3", "A heated version is available for icing conditions.")),
        atom("@rg_area", p, "RG-2 collecting area: 200 cm²", "The RG-2 funnel collects over 200 cm².", ["@rg2"],
             sheet("4", "Collecting area: 200 cm²"), [value("collecting_area", "cm2", 200)]),
        atom("@rg_res", p, "RG-2 resolution: 0.2 mm per tip", "Each tip of the bucket is 0.2 mm of rain.", ["@rg2"],
             sheet("4", "resolution 0.2 mm per tip"), [value("rain_resolution", "mm", 0.2)]),
        atom("@rg_acc", "fact", "RG-2 is accurate to ±2 % up to 50 mm/h", "Heavier rain than 50 mm/h is undercounted.",
             ["@rg2"], sheet("4", "Accuracy: ±2 % up to 50 mm/h.")),
        atom("@rg_snow", "fact", "RG-2 does not measure snow without the heated funnel",
             "Winter precipitation is lost unless the heated funnel kit is installed.", ["@rg2"],
             sheet("4", "Snow is not measured unless the heated funnel kit is installed.")),
        # calibration report
        atom("@cal_ws1_h", p, "WS-1 humidity reads 3.1 %RH high", "The TH-20 at WS-1 overstates humidity by 3.1 %RH.",
             ["@ws1", "@th20"], calib("the TH-20 reads humidity 3.1 %RH high against the reference"),
             [value("humidity_offset", "%", 3.1)], tags=["calibration"]),
        atom("@cal_ws1_t", "fact", "WS-1 temperature is within ±0.1 °C", "The TH-20 at WS-1 reads temperature well.",
             ["@ws1", "@th20"], calib("temperature is within ±0.1 °C of the reference"), tags=["calibration"]),
        atom("@cal_ws2", "fact", "WS-2 barometer read 0.4 hPa low and was adjusted",
             "The PB-10 at WS-2 was adjusted on site after reading 0.4 hPa low.", ["@ws2", "@pb10"],
             calib("the PB-10 reads 0.4 hPa low; adjusted on site"), tags=["calibration"]),
        atom("@cal_ws3", "fact", "WS-3 sensors are all within specification", "No adjustments at WS-3.", ["@ws3"],
             calib("WS-3 Valley Farm: all sensors are within specification."), tags=["calibration"]),
        atom("@cal_ws4", p, "WS-4 anemometer starts only at 1.2 m/s",
             "A worn bearing raised the AN-5 starting threshold at WS-4 to 1.2 m/s.", ["@ws4", "@an5"],
             calib("the AN-5 bearing is worn, the starting threshold is 1.2 m/s"),
             [value("starting_threshold", "m/s", 1.2)], tags=["calibration"]),
        # maintenance log
        atom("@frost", "fact", "Frost on the TH-20 shield overstated humidity at WS-1",
             "With frost on the shield WS-1 showed 99-100 %RH while a psychrometer gave 88 %RH.", ["@ws1", "@th20"],
             log("A2:D3"), tags=["winter"]),
        atom("@link", "fact", "WS-4 lost the LoRaWAN link for 3 days without losing data",
             "The logger buffered 3 days of data until the gateway came back.", ["@ws4", "@dl4"], log("A4:D4")),
        atom("@leaves", "lesson", "Leaves clog the WS-3 rain gauge every autumn",
             "Twice in October the funnel at WS-3 was clogged by leaves.", ["@ws3", "@rg2"], log("A6:D7")),
        atom("@fog", p, "WS-1 battery ran flat after 5 days of fog",
             "In December fog and short days drained the battery in 5 days, not 7.", ["@ws100", "@ws1"],
             log("A8:D8"), [value("battery_autonomy", "d", 5)], tags=["winter"]),
        atom("@icing", "fact", "AN-5 cups iced up twice at WS-1 in January",
             "Icing stopped the anemometer at Ridge Top.", ["@ws1", "@an5"],
             {"path": NOTES, "selectors": [{"type": "heading", "value": "WS-1 Ridge Top"}]}, tags=["winter"]),
    ]


def links() -> list[dict]:
    part = [("@ws1", "@net"), ("@ws2", "@net"), ("@ws3", "@net"), ("@ws4", "@net"), ("@th20", "@ws100"),
            ("@pb10", "@ws100"), ("@an5", "@ws100"), ("@rg2", "@ws100"), ("@dl4", "@ws100"), ("@mast", "@ws100")]
    return ([{"rel": "part_of", "src": s, "dst": d} for s, d in part]
            + [{"rel": "example_of", "src": s, "dst": "@ws100"} for s in ("@ws1", "@ws2", "@ws3", "@ws4")]
            + [{"rel": "contradicts", "src": "@cal_ws4", "dst": "@an_start", "note": text("worn bearing at WS-4")},
               {"rel": "contradicts", "src": "@fog", "dst": "@autonomy", "note": text("fog in December")},
               {"rel": "refines", "src": "@th_edges", "dst": "@th_hacc"},
               {"rel": "see_also", "src": "@frost", "dst": "@th_edges"}]
            # documents next to what they describe, so the sky has no loose stars
            + [{"rel": "see_also", "src": d, "dst": e} for d, ents in (
                ("@manual", ("@ws100", "@dl4", "@mast")), ("@sheets", ("@th20", "@pb10", "@an5", "@rg2")),
                ("@calib", ("@ws1", "@ws2", "@ws3", "@ws4"))) for e in ents])


def person_notes(refs: dict[str, str]) -> list[dict]:
    def note(ref, kind, label, body, about, **kw):
        return {"target": "atom", "payload": {"ref": ref, "kind": kind, "label": text(label),
                                              "summary_plain": text(label), "body": text(body),
                                              "about": [refs[a] for a in about], "basis": "author", **kw}}

    return [
        note("@q_heat", "question", "Do we need heated sensors at WS-1 in winter?",
             "Frost and icing at Ridge Top every January. Heated AN-5 and a heated shield, or a second visit a week?",
             ["@ws1"]),
        note("@d_heat", "decision", "Order a heated AN-5 for WS-1 Ridge Top",
             "Icing stopped the cups twice in January; the heated version exists.", ["@ws1", "@an5"]),
        note("@d_move", "decision", "Move the WS-3 rain gauge away from the oaks",
             "At least 10 m from the trees, so autumn leaves stay out of the funnel.", ["@ws3", "@rg2"]),
        note("@d_bearing", "decision", "Replace the AN-5 bearing at WS-4",
             "The calibration found a worn bearing; replace it before the spring storms.", ["@ws4", "@an5"]),
        note("@l_storm", "lesson", "Check guy wires after every storm",
             "WS-2 had a loose guy wire after a storm in March; do not wait for the 6-month visit.", ["@mast", "@ws2"]),
        note("@l_calib", "lesson", "Calibrate humidity before winter, not after",
             "Offsets show up in frost and fog; a March calibration is too late for the winter data.", ["@th20"]),
        note("@q_memory", "question", "Is 90 days of logger memory enough for the remote sites?",
             "WS-1 is cut off by snow for up to two months.", ["@dl4", "@ws1"]),
        note("@n_vendor", "note", "Ask the vendor about PB-10 drift in the cold",
             "The datasheet gives drift at 20 °C only.", ["@pb10"]),
        note("@t_dew", "term", "Dew point",
             "The temperature at which air becomes saturated and dew or frost forms.", ["@th20"]),
        note("@t_shield", "term", "Radiation shield",
             "A louvred housing that keeps sun and rain off a temperature sensor while letting air through.", ["@th20"]),
        note("@t_threshold", "term", "Starting threshold",
             "The lowest wind speed that makes the anemometer cups turn.", ["@an5"]),
        note("@m_magnus", "method", "Dew point with the Magnus formula",
             "From TH-20 temperature and humidity.", ["@th20"],
             content={"formula": {
                 "latex": "T_d = \\frac{b\\,\\gamma}{a - \\gamma}, \\quad "
                          "\\gamma = \\ln\\frac{RH}{100} + \\frac{aT}{b+T}",
                 "plain": "Td = b·γ / (a − γ), γ = ln(RH/100) + a·T / (b + T)",
                 "symbols": [{"symbol": "T_d", "label": text("dew point"), "unit": "Cel"},
                             {"symbol": "T", "label": text("air temperature"), "unit": "Cel"},
                             {"symbol": "RH", "label": text("relative humidity"), "unit": "%"}]}}),
        note("@offsets", "fact", "Calibration offsets by station, March 2026",
             "Summary of the 2026 calibration report.", ["@ws1", "@ws2", "@ws3", "@ws4"],
             derived_from=[refs[a] for a in ("@cal_ws1_h", "@cal_ws2", "@cal_ws3", "@cal_ws4")],
             content={"table": {
                 "columns": [{"code": "station", "label": text("Station")},
                             {"code": "sensor", "label": text("Sensor")},
                             {"code": "finding", "label": text("Finding")}],
                 "rows": [["WS-1", "TH-20", "humidity 3.1 %RH high"], ["WS-2", "PB-10", "0.4 hPa low, adjusted"],
                          ["WS-3", "all", "within specification"], ["WS-4", "AN-5", "threshold 1.2 m/s"]]}}),
    ]


FOLDERS = {
    "Projects/North Ridge network": ["@net", "@ws1", "@ws2", "@ws3", "@ws4", "@cal_ws1_h", "@cal_ws1_t", "@cal_ws2",
                                     "@cal_ws3", "@cal_ws4", "@frost", "@link", "@leaves", "@fog", "@icing",
                                     "@q_heat", "@d_heat", "@d_move", "@d_bearing", "@l_storm", "@q_memory",
                                     "@offsets"],
    "Areas/Instruments": ["@ws100", "@th20", "@pb10", "@an5", "@rg2", "@dl4", "@mast", "@kit", "@volt", "@solar",
                          "@battery", "@autonomy", "@sampling", "@transmit", "@retention", "@ip65", "@shield",
                          "@an5_top", "@service", "@optemp", "@mast_h", "@th_trange", "@th_tacc", "@th_hrange",
                          "@th_hacc", "@th_edges", "@th_volt", "@pb_range", "@pb_acc", "@pb_drift", "@an_range",
                          "@an_acc", "@an_start", "@an_heated", "@rg_area", "@rg_res", "@rg_acc", "@rg_snow",
                          "@l_calib", "@n_vendor"],
    "Resources/Sources": ["@manual", "@sheets", "@calib"],
    "Resources/Methods and terms": ["@t_dew", "@t_shield", "@t_threshold", "@m_magnus"],
}
RENAME = {"Проекты": "Projects", "Области": "Areas", "Ресурсы": "Resources", "Архив": "Archive"}
# open in the queue for the review screen; everything else is confirmed by the person
KEEP_OPEN = ("@th_hacc", "@cal_ws4", "@fog", "@frost", "@th_edges")


def seed(conn, store, docs: Path, person: str) -> dict:
    from amem import api

    write_docs(docs)
    first = api.submit(conn, store, docs, agent=MODEL, proposals=entities() + facts(), links=links(),
                       reason="manual, datasheets, calibration report and maintenance log of the WS-100 network")
    refs = {p["payload"]["ref"]: r["ref"] for p, r in zip(entities() + facts(), first["records"], strict=True)}
    notes = person_notes(refs)
    second = api.submit(conn, store, docs, agent=person, proposals=notes, reason="notes from site visits",
                        links=[{"rel": "answers", "src": "@d_heat", "dst": "@q_heat"}])
    refs |= {p["payload"]["ref"]: r["ref"] for p, r in zip(notes, second["records"], strict=True)}

    for old, new in RENAME.items():
        try:
            api.folder_rename(conn, old, new, agent=person)
        except Exception:   # noqa: BLE001 — a base without the default folders keeps what it has
            pass
    for folder, items in FOLDERS.items():
        api.folder_create(conn, folder, agent=person)
        for name in items:
            api.record_folder(conn, refs[name], folder, agent=person)

    keep = {refs[name] for name in KEEP_OPEN}
    for item in api.review_items(conn, state="queued"):
        if item["ref"] not in keep:
            api.review_resolve(conn, item["id"], agent=person, outcome="confirmed", note="checked against the source")
    return {"records": len(refs), "open": len(api.review_items(conn, state="queued"))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="write into a base that already has records")
    args = ap.parse_args(argv)
    packs = [p for p in os.environ.get("AMEM_PACKS", "").split(os.pathsep) if p]
    if PACK.resolve() not in {Path(p).resolve() for p in packs}:
        os.environ["AMEM_PACKS"] = os.pathsep.join([*packs, str(PACK)])

    from amem import api, db, settings
    from amem.ocfl_store import ObjectStore

    s = settings.load()
    if s.docs is None:
        print("amem: a documents folder is needed — AMEM_DOCS", file=sys.stderr)
        return 2
    with db.connect(s.dsn) as conn:
        db.prepare(conn)
        counts = api.base(conn)["counts"]
        if counts["atoms"] + counts["entities"] and not args.force:
            print("amem: the base already has records — the sample goes into an empty base (or --force)",
                  file=sys.stderr)
            return 2
        try:
            result = seed(conn, ObjectStore(s.data), s.docs, s.agent)
        except api.CheckRejected as e:
            print(f"amem: {e}", file=sys.stderr)
            for issue in e.issues:
                print(f"  {issue['severity']}: {issue['ref']} {issue['path'] or ''}: {issue['message']}", file=sys.stderr)
            return 1
    print(f"sample written: {result['records']} records, {result['open']} open review items")
    return 0


if __name__ == "__main__":
    sys.exit(main())
