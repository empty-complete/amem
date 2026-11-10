"""Образец PDF для моков части B: две страницы руководства МС-1 (подписи 11 и 12).

Запуск один раз из web/: <venv ядра amemo>/bin/python tools/make-sample-pdf.py [путь к шрифту TTF с кириллицей]
"""
import sys

import pymupdf

font = sys.argv[1] if len(sys.argv) > 1 else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
pages = {
    11: ["4.1 Комплект",
         "Метеостанция МС-1 поставляется с мачтой М-2, тремя датчиками и блоком питания 12 В.",
         "Данные передаются по линии RS-485 раз в минуту."],
    12: ["4.2 Датчики",
         "Датчик температуры Т-1 измеряет температуру воздуха в диапазоне от −40 до +60 °C с погрешностью не более ±0,3 °C.",
         "При температуре ниже −40 °C показания датчика Т-1 не нормируются.",
         "Датчик влажности В-2 измеряет относительную влажность от 0 до 100 %.",
         "Погрешность ±2 % в диапазоне от 10 до 90 %, вне его погрешность не нормируется."],
}
doc = pymupdf.open()
for n, lines in pages.items():
    p = doc.new_page(width=595, height=842)
    p.insert_font(fontname="dv", fontfile=font)
    y = 72
    for i, line in enumerate(lines):
        p.insert_textbox(pymupdf.Rect(72, y, 523, y + 60), line, fontname="dv", fontsize=14 if i == 0 else 11)
        y += 44 if i == 0 else 40
    p.insert_text((290, 800), str(n), fontname="dv", fontsize=9)
doc.set_metadata({"title": "Руководство по эксплуатации МС-1 (образец)", "author": "amemo sample"})
doc.subset_fonts()
doc.save("src/mocks/fixtures/manual.pdf", garbage=4, deflate=True)
