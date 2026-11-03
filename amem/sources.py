"""Источники атомов: файл в папке документов, его текст и место цитаты в нём.

Модуль не знает о базе: на вход — путь, текст страниц, цитата, локатор; на выход — Verdict.
Кэш текста и запись результатов — на стороне хранилища (objects.py).

verdict источника
-----------------
ok          цитата найдена на указанной странице (или страница не была указана);
            одностраничный документ (.md, .txt) без цитаты
moved       цитата найдена на другой странице — номер исправлен
fuzzy       цитата найдена нечётким поиском (опечатка, другие кавычки)
by_locator  цитаты нет, страница найдена по локатору («табл. 11.1»)
unresolved  цитаты нет, локатор не помог
not_found   цитата не найдена — новый атом не записывается
no_file     путь похож на файл, но файла нет — новый атом не записывается
no_text     у файла нет текста: скан, .docx, .pptx …
external    источник — название, а не файл (письмо, сайт)
error       сбой при чтении или сверке файла (ошибка PyMuPDF и т. п.) — фоновая сверка его больше не повторяет,
            заново — check-sources --all
''          не проверялось (папка документов не подключена)
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz

MIN_QUOTE = 15            # цитата короче не находится однозначно
FUZZY_MIN_LEN = 20        # нечёткий поиск — только для цитат не короче
FUZZY_SCORE = 85          # минимальная схожесть нечёткого совпадения, %
MIN_CHARS_PER_PAGE = 50   # меньше в среднем — у PDF нет текстового слоя

# значок сверки для kb_get и веб-интерфейса; verdict-ов без значка в словаре нет
MARKS = {"ok": "✓", "moved": "✓", "by_locator": "✓", "fuzzy": "≈",
         "not_found": "⚠", "unresolved": "⚠", "no_file": "⚠", "error": "⚠"}

# расширения документов; остальное после точки («.ru», «.by», «.2016») — часть названия
DOC_SUFFIXES = {
    "pdf", "md", "txt", "rtf", "doc", "docx", "odt", "xls", "xlsx", "xlsm", "ods", "csv", "ppt", "pptx", "odp",
    "dwg", "dxf", "step", "stp", "igs", "iges", "sldprt", "sldasm", "slddrw", "ifc", "rvt", "skp",
    "png", "jpg", "jpeg", "tif", "tiff", "bmp", "svg", "json", "yaml", "yml", "xml", "html", "htm",
    "zip", "rar", "7z", "msg", "eml",
}
# адрес в интернете: схема, www., почта или первый сегмент — домен латиницей («knauf.ru/docs/TS.pdf»)
_WEB = re.compile(r"://|^www\.|@|^[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+/", re.I)
# латинские двойники кириллических букв: в PDF встречается «CЗ» с латинской C
_LOOKALIKE = str.maketrans("abcehkmoptxy", "авсенкмортху")          # после lower(): латинские двойники → кириллица
_LOOKALIKE_UPPER = str.maketrans("ABCEHKMOPTXY", "АВСЕНКМОРТХУ")   # для буквы приложения
_TO_LATIN = str.maketrans("АВСЕНКМОРТХУ", "ABCEHKMOPTXY")

_QUOTE_CHARS = set("«»„“”‟\"'’‘`")
_DASH_CHARS = set("‐‑‒–—―−")


@dataclass
class Verdict:
    verdict: str
    page: int | None = None
    anchor: str = ""          # текст для подсветки — как он записан в документе
    score: float = 0.0        # схожесть нечёткого совпадения, %


def looks_like_file(path: str) -> bool:
    """«…/СП 131.2025.pdf», «узел.SLDPRT» — файлы; «СП 20.13330.2016», «knauf.ru», «alutech.by», адреса — названия.
    Существующий файл в папке документов — всегда файл: это проверяет вызывающий код до этой функции."""
    path = path.strip()
    suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return suffix in DOC_SUFFIXES and not _WEB.search(path)


def as_page(value) -> int | None:
    """Номер страницы из того, что прислала модель: 27, "27" → 27; мусор и 0 → None."""
    try:
        page = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return page if page > 0 else None


def safe_join(root: Path, rel: str) -> Path | None:
    """Путь внутри root или None, если rel выводит наружу (../, абсолютный путь, сам root, ссылка наружу).
    Может вернуть и папку — вызывающий проверяет is_file()."""
    root = root.resolve()
    try:
        p = (root / rel).resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    return p if root in p.parents else None


def extract_pages(file: Path) -> list[str] | None:
    """Текст по страницам; у .md и .txt — одна «страница». None — извлекаемого текста нет."""
    suffix = file.suffix.lower()
    if suffix in (".md", ".txt"):
        return [file.read_text(encoding="utf-8", errors="replace")]
    if suffix != ".pdf":
        return None
    import pymupdf

    try:
        with pymupdf.open(file) as doc:
            pages = [p.get_text() for p in doc]
    except pymupdf.FileNotFoundError as e:      # подкласс RuntimeError, но файл исчез — это не «нет текста»
        raise FileNotFoundError(str(file)) from e
    except (RuntimeError, ValueError, pymupdf.mupdf.FzErrorBase):  # битый, пустой или зашифрованный PDF
        return None                     # (FzErrorBase в PyMuPDF 1.28 — подкласс Exception, не RuntimeError)
    if not pages or sum(len(t.strip()) for t in pages) / len(pages) < MIN_CHARS_PER_PAGE:
        return None
    return pages


def _invisible(ch: str) -> bool:
    """Управляющий или невидимый символ (\\x08, мягкий перенос, нулевая ширина, BOM), но не пробельный."""
    return not ch.isspace() and unicodedata.category(ch) in ("Cc", "Cf")


def _after_hyphen(text: str, i: int) -> int:
    """Индекс первого значимого символа после дефиса в позиции i: пропускаются пробелы, переносы строк и невидимые."""
    j = i + 1
    while j < len(text) and (text[j].isspace() or _invisible(text[j])):
        j += 1
    return j


def normalize(text: str) -> tuple[str, list[int]]:
    """Текст для сравнения цитат и карта «позиция в результате → позиция в исходном тексте».
    Нижний регистр, ё → е, латинские двойники кириллицы → кириллица, один пробел, единые кавычки и тире.
    Дефис (любое тире) сразу после буквы перед буквой убирается, через пробел или перенос строки тоже:
    «культурно-\\nдосуговой» = «культурно- досуговой» = «культурно‑досуговой» = «культурнодосуговой».
    После другого знака пробелы за ним убираются: «5-\\n10» = «5- 10» = «5–10». Тире после пробела не трогается:
    «до 100 м -\\nминус 5» = «до 100 м - минус 5». Управляющие и невидимые символы выкидываются."""
    out: list[str] = []
    pos: list[int] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in _DASH_CHARS:
            c = "-"
        if c in "-\u00ad" and out and out[-1] != " ":
            j = _after_hyphen(text, i)
            # буква ли перед дефисом — по исходному символу, как в clean_anchor: у «İ».lower() последний знак не буква
            if j < n and text[pos[-1]].isalpha() and text[j].isalpha():
                i = j                       # дефис или перенос в слове: «культурно-досуговой» → «культурнодосуговой»
                continue
            if c == "-" and j > i + 1:
                out.append("-")
                pos.append(i)
                i = j                       # «5-\n10», «5- 10» → «5-10»
                continue
        if c.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                pos.append(i)
            i += 1
            continue
        if _invisible(c):
            i += 1
            continue
        if c in _QUOTE_CHARS:
            c = '"'
        for ch in c.lower().replace("ё", "е").translate(_LOOKALIKE):
            out.append(ch)
            pos.append(i)
        i += 1
    if out and out[-1] == " ":
        out.pop()
        pos.pop()
    return "".join(out), pos


def clean_anchor(raw: str) -> str:
    """Фрагмент исходного текста для подсветки: те же правила переносов и дефисов, что в normalize,
    но с исходными буквами, регистром и знаками. normalize(clean_anchor(x))[0] == normalize(x)[0]."""
    out: list[str] = []
    i, n = 0, len(raw)
    while i < n:
        c = raw[i]
        if (c in _DASH_CHARS or c in "-\u00ad") and out and out[-1] != " ":
            j = _after_hyphen(raw, i)
            if j > i + 1 and j < n and out[-1].isalpha() and raw[j].isalpha():
                i = j                       # перенос слова: «ветро-\nвое» → «ветровое»
                continue
            if c != "\u00ad" and j > i + 1:
                out.append(c)
                i = j                       # «5-\n10» → «5-10»
                continue
        if c.isspace():
            if out and out[-1] != " ":
                out.append(" ")
            i += 1
            continue
        if not _invisible(c):
            out.append(c)
        i += 1
    return "".join(out).strip()


@dataclass
class DocText:
    """Текст документа по страницам и его нормализованная форма (считается один раз на документ)."""
    pages: list[str]
    norm: list[tuple[str, list[int]]]

    @classmethod
    def of(cls, pages: list[str]) -> DocText:
        return cls(pages, [normalize(t) for t in pages])


def find_quote(doc: DocText, quote: str, page: int | None = None) -> Verdict:
    """Цитата: на указанной странице → ok; на другой (ближайшей к указанной) → moved;
    нечётко (для цитат от FUZZY_MIN_LEN символов) → fuzzy; иначе not_found.
    Цитата ищется в пределах одной страницы: цитата через разрыв страницы не находится."""
    q, _ = normalize(quote)
    if not q:
        return Verdict("not_found")
    want = page - 1 if page else None
    hits = [i for i, (t, _) in enumerate(doc.norm) if q in t]
    if hits:
        if want is None or want in hits:
            i, verdict = (hits[0] if want is None else want), "ok"
        else:
            i, verdict = min(hits, key=lambda h: abs(h - want)), "moved"
        start = doc.norm[i][0].index(q)
        return Verdict(verdict, i + 1, _anchor(doc, i, start, start + len(q)))
    if len(q) >= FUZZY_MIN_LEN:
        best_i, best = -1, None
        for i, (t, _) in enumerate(doc.norm):
            if len(t) < len(q):
                continue
            al = fuzz.partial_ratio_alignment(q, t, score_cutoff=FUZZY_SCORE)
            if al is not None and (best is None or (al.score, i == want) > (best.score, best_i == want)):
                best_i, best = i, al
        if best is not None:
            return Verdict("fuzzy", best_i + 1, _anchor(doc, best_i, best.dest_start, best.dest_end, whole_words=True),
                           best.score)
    return Verdict("not_found")


def _anchor(doc: DocText, i: int, start: int, end: int, whole_words: bool = False) -> str:
    """Исходный текст страницы i, соответствующий [start, end) нормализованного текста.
    whole_words — расширить до границ слов: окно нечёткого совпадения может начаться с середины слова.
    Фрагмент с дефиса, за которым пробел («+/- 0,2» → «+/-0,2»), берётся со знаком перед дефисом:
    без него normalize оставит пробел, и подсветка не найдётся как цитата."""
    raw, (text, pos) = doc.pages[i], doc.norm[i]
    while (start > 0 and text[start] == "-" and text[start - 1] != " "
           and _after_hyphen(raw, pos[start]) > pos[start] + 1):
        start -= 1
    a, b = pos[start], pos[end - 1] + 1
    if whole_words:
        while a > 0 and raw[a - 1].isalnum():
            a -= 1
        while b < len(raw) and raw[b].isalnum():
            b += 1
    return clean_anchor(raw[a:b])


_REF = r"[А-ЯA-Z]?\.?\d+(?:\.\d+)*"
_NOT_LETTER = r"(?![А-Яа-яЁёA-Za-z])"


def _spaced(word: str) -> str:
    """«Т а б л и ц а»: в нормативах заголовки набирают вразрядку."""
    return "[ \t]*".join(map(re.escape, word))


def _number(ref: str) -> str:
    """«6.1» совпадает и с «6 .1» — разрядка доходит до номера."""
    return r"[ \t]*\.[ \t]*".join(map(re.escape, ref.split(".")))


def _words(text: str) -> str:
    return r"\s+".join(map(re.escape, text.split()))


_TABLE = _spaced("Таблица")
_APPENDIX = f"(?:{_spaced('Приложение')}|{_spaced('ПРИЛОЖЕНИЕ')})"


def _letter(ref: str) -> str:
    """Буква приложения: «е», «Е» и латинская «E» — одно и то же."""
    cyr = ref.upper().translate(_LOOKALIKE_UPPER)
    lat = cyr.translate(_TO_LATIN)
    return f"[{re.escape(cyr)}{re.escape(lat)}]" if lat != cyr else re.escape(cyr)


def _section(ref: str) -> list[str]:
    """Раздел заметки «A / B»: сначала заголовок «# B», потом слова «B» целиком в тексте (не «Снег» внутри «Снеговая»)."""
    parts = [p for p in re.split(r"\s*/\s*", ref) if p.strip()]
    words = _words(parts[-1] if parts else ref.strip())
    return [rf"^#{{1,6}}[ \t]*(?P<a>{words})[ \t]*$", rf"(?<!\w)(?P<a>{words})(?!\w)"]


# (ссылка в локаторе, как это место выглядит в тексте документа: список шаблонов, пробуются по порядку);
# группа «a» — текст для подсветки.
# Проверено на СП 20.13330.2016 и СП 131.13330.2025: верные страницы для 19 из 20 локаторов базы.
_LOCATOR_RULES = [
    # заголовок таблицы: после номера тире или конец строки («Таблица 5.1, графа …» в ячейках — ссылка)
    (re.compile(rf"табл(?:ица|ицы|ице|ицу|ицей|\.)?\s*({_REF})", re.I),
     lambda r: [rf"^[ \t]*(?P<a>{_TABLE}\s+{_number(r)})(?![ \t]*\.?[ \t]*\d)(?=[ \t]*(?:[-–—]|$))"]),
    # номер формулы в конце строки
    (re.compile(r"(?:формул[аыеу]|ф\.)\s*\(([^)]+)\)", re.I),
     lambda r: [rf"(?P<a>\({_number(r)}\))[ \t]*$"]),
    # пункт в начале строки, дальше заглавная буква («11.4 соответственно» — не пункт)
    (re.compile(r"(?:п\.|пункт[а-я]*)\s*(\d+(?:\.\d+)+)", re.I),
     lambda r: [rf"^[ \t]*(?P<a>{_number(r)})\.?[ \t]+(?=[А-ЯЁA-Z])"]),
    # буква приложения: заглавная — всегда («Приложение Б таблица Б.1»); строчная — если за ней не слово
    # со строчной буквы, иначе это предлог или союз: «приложение к приказу», «приложения и табл. 11.1».
    # Окончание падежа — не буква: «приложением Д» — приложение Д, а не М
    (re.compile(rf"прил(?:ожени(?:ями|ях|ям|ем|[еяию])|\.)?\s*(?<![А-Яа-яЁёA-Za-z])"
                rf"((?-i:[А-ЯA-Z])|[а-яёa-z](?!\s+(?-i:[а-яёa-z]))){_NOT_LETTER}", re.I),
     lambda r: [rf"^[ \t]*(?P<a>{_APPENDIX}\s+{_letter(r)}){_NOT_LETTER}"]),
    # раздел заметки: «раздел «Нагрузки / Снег»» → заголовок «Снег»
    (re.compile(r"раздел[а-я]*\s*«([^»]*[^\s»][^»]*)»", re.I), _section),
]
_ROW = re.compile(r"строк[аи]\s*«([^»]+)»", re.I)
# заголовок любой таблицы — как в правиле таблицы: после номера (бывает с буквой: «В.3а») тире или конец строки
# («Таблица 6.1, графа 3» в начале строки — ссылка в тексте)
_ANY_TABLE = re.compile(rf"^[ \t]*{_TABLE}\s+[А-ЯA-Z]?[ \t]*\.?[ \t]*\d+(?:[ \t]*\.[ \t]*\d+)*[а-я]?"
                        r"[ \t]*(?:[-–—]|$)", re.M)
# строка оглавления: отточие — четыре и больше точек или «…»; найденное в такой строке — не само место в тексте
_TOC_LINE = re.compile(r"(?:\.\s*){4,}|…")
# строка с отточием при подсчёте строк страницы оглавления — четыре и больше точек или многоточий подряд:
# одиночное «…» бывает в формулах и таблицах («D1; D2; …; Dn»)
_TOC_PAGE = re.compile(r"(?:[.…]\s*){4,}")
TOC_MIN_LINES = 3         # строк с отточиями на странице оглавления


def find_locator(doc: DocText, locator: str) -> Verdict:
    """Страница по локатору: ссылки из него ищутся в тексте в порядке появления в локаторе;
    оглавление пропускается — и строки с отточиями, и страницы, где таких строк не меньше TOC_MIN_LINES
    (строка оглавления переносится, и отточия оказываются на следующей строке);
    «строка «Пермь»» уточняет страницу внутри многостраничной таблицы
    (поиск строки — от заголовка до заголовка следующей таблицы, а не до конца документа)."""
    refs = sorted(((m.start(), make(m.group(1))) for rx, make in _LOCATOR_RULES for m in rx.finditer(locator)),
                  key=lambda x: x[0])
    row = _ROW.search(locator)
    toc: dict[int, bool] = {}
    for _, patterns in refs:
        for pattern in patterns:
            rx = re.compile(pattern, re.M)
            for i, text in enumerate(doc.pages):
                for m in rx.finditer(text):
                    if _TOC_LINE.search(_line(text, m.start())):
                        continue
                    if i not in toc:
                        toc[i] = _is_toc(text)
                    if toc[i]:
                        break
                    if row:
                        j = _row_page(doc, i, m.end(), row.group(1))
                        if j is not None:
                            return Verdict("by_locator", j + 1, row.group(1))
                    return Verdict("by_locator", i + 1, clean_anchor(m.group("a")))
    return Verdict("unresolved")


def _is_toc(text: str) -> bool:
    """Страница оглавления: не меньше TOC_MIN_LINES строк с отточиями."""
    return sum(1 for line in text.splitlines() if _TOC_PAGE.search(line)) >= TOC_MIN_LINES


def _row_page(doc: DocText, i: int, at: int, row: str) -> int | None:
    """Индекс страницы со строкой таблицы, заголовок которой на странице i кончается в позиции at.
    Поиск идёт от заголовка до следующего заголовка таблицы: текст выше нашего заголовка — хвост предыдущей
    таблицы; на странице следующего заголовка смотрим только текст выше него (там может быть хвост нашей)."""
    for j in range(i, len(doc.pages)):
        text = doc.pages[j]
        start = at if j == i else 0
        nxt = _ANY_TABLE.search(text, start)
        if row in text[start: nxt.start() if nxt else len(text)]:
            return j
        if nxt:
            break
    return None


def _line(text: str, at: int) -> str:
    start = text.rfind("\n", 0, at) + 1
    end = text.find("\n", at)
    return text[start: end if end >= 0 else len(text)]


def judge(doc: DocText | None, quote: str = "", page: int | None = None, locator: str = "") -> Verdict:
    """Сверка источника с текстом файла (doc=None — у файла нет текста): по цитате, иначе по локатору.
    Одностраничный документ без цитаты — ok: ссылка и так ведёт в нужный документ."""
    if doc is None:
        return Verdict("no_text")
    if quote.strip():
        return find_quote(doc, quote, page)
    v = find_locator(doc, locator) if locator.strip() else Verdict("unresolved")
    if v.verdict == "unresolved" and len(doc.pages) == 1:
        return Verdict("ok", 1)
    return v
