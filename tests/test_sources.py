import random

import pytest

from amem.sources import (
    DocText, Verdict, as_page, clean_anchor, extract_pages, find_locator, find_quote, judge, looks_like_file,
    normalize, safe_join,
)
from samples import NOTE_MD, SP_PAGES, make_pdf


def test_looks_like_file():
    assert looks_like_file("Ресурсы/u/норматив · СП 131.2025.pdf")
    assert looks_like_file("узел.STEP")
    assert not looks_like_file("СП 131.2025 строительная климатология")
    assert not looks_like_file("СП 20.13330.2016")
    assert not looks_like_file("Спецификация кампус.pptx — итоговая презентация")
    assert not looks_like_file("Письмо производителя стеклопакетов")


def test_looks_like_file_suffixes():
    for name in ("Ресурсы/x/норматив · СП 131.2025.pdf", "узел.STEP", "деталь.SLDPRT",
                 "Архив/Козырьки/Доп информация.txt"):
        assert looks_like_file(name), name
    for name in ("alutech.by", "paroc.fi", "knauf.ru/docs/TS.pdf", "https://knauf.ru/x.pdf", "www.knauf.ru",
                 "info@x.ru", "СП 20.13330.2016", "Спецификация кампус.pptx — итоговая презентация",
                 "Письмо производителя стеклопакетов, 12.09.2026"):
        assert not looks_like_file(name), name


def test_looks_like_file_web():
    for name in ("https://knauf.ru", "knauf.ru", "info@x.ru", "www.rehau.com/catalog", "сайт rehau.com"):
        assert not looks_like_file(name), name


def test_as_page():
    assert as_page(27) == 27 and as_page("27") == 27
    assert as_page(0) is None and as_page("стр. 5") is None and as_page(None) is None


def test_as_page_overflow():
    assert as_page(float("inf")) is None


def test_safe_join(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b.pdf").write_bytes(b"x")
    assert safe_join(tmp_path, "a/b.pdf") == (tmp_path / "a" / "b.pdf").resolve()
    for bad in ("../x", "a/../../x", "/etc/passwd", ".", "", "a\x00b"):
        assert safe_join(tmp_path, bad) is None, bad


def test_safe_join_symlinks(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret.pdf").write_bytes(b"x")
    (root / "link.pdf").symlink_to(tmp_path / "secret.pdf")
    (root / "loop").symlink_to(root / "loop")
    assert safe_join(root, "link.pdf") is None          # ссылка ведёт за пределы папки
    p = safe_join(root, "loop")                        # зацикленная ссылка — не исключение
    assert p is None or not p.is_file()                 # Python 3.13 разрешает петлю без ошибки


def test_extract_pages(tmp_path, docs):
    pages = extract_pages(docs / "НД" / "СП 99.pdf")
    assert len(pages) == 3 and "Пермь" in pages[2]
    assert extract_pages(docs / "Заметки" / "узел.md") == [NOTE_MD]
    assert extract_pages(docs / "НД" / "скан.docx") is None
    assert extract_pages(make_pdf(tmp_path / "скан.pdf", ["", ""])) is None
    (tmp_path / "битый.pdf").write_bytes(b"%PDF-1.4 garbage")
    assert extract_pages(tmp_path / "битый.pdf") is None


def _cyclic_pdf(path):
    """PDF с зацикленным деревом страниц: PyMuPDF бросает FzErrorFormat, не RuntimeError."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Pages /Kids [2 0 R] /Count 1 /Parent 2 0 R >>"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offs:
        out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.write_bytes(bytes(out))
    return path


def test_extract_pages_cyclic_page_tree(tmp_path):
    assert extract_pages(_cyclic_pdf(tmp_path / "цикл.pdf")) is None


def test_normalize():
    raw = "Ёлка  «тест» — ветро-\nвое давление "
    text, pos = normalize(raw)
    assert text == 'елка "тест" - ветровое давление'
    assert len(pos) == len(text)
    assert raw[pos[text.index("вое")]] == "в"          # карта позиций ведёт в исходный текст после переноса


def test_normalize_soft_hyphen_and_invisible():
    assert normalize("ветро­\nвое​ давление")[0] == "ветровое давление"


def test_normalize_hyphens():
    assert normalize("культурно-\nдосуговой")[0] == normalize("культурно-досуговой")[0] == "культурнодосуговой"
    assert normalize("от 5-\n10 мм")[0] == "от 5-10 мм"
    assert normalize("РСК-14")[0] == "рск-14"
    assert normalize("район - II")[0] == "район - ii"


def test_normalize_control_chars_and_lookalikes():
    assert normalize("П р и м е ч а н и \x03е")[0] == "п р и м е ч а н и е"
    assert normalize("CЗ")[0] == normalize("СЗ")[0]       # латинская C и кириллическая С


def test_normalize_dash_variants_and_spaces_after_hyphen():
    for a, b in [("ноябрь–март", "ноябрь-март"), ("культурно‑досуговой", "культурно-досуговой"),
                 ("5–\n10", "5-10"), ("культурно- досуговой", "культурно-\nдосуговой"), ("5- 10", "5-\n10"),
                 ("a-\u200bb", "ab"), ("до 100 м -\nминус 5", "до 100 м - минус 5")]:
        assert normalize(a)[0] == normalize(b)[0], (a, b)


def test_normalize_latin_case():
    assert normalize("ALUTECH ALT F50")[0] == normalize("Alutech Alt f50")[0]


def test_normalize_position_map_invariant():
    for raw in ("İstanbul ветро-\nвое 5-\n10 \x08x", "  «а» — б  ", "ветро­\nвое​", "-\n-", "",
                "ab–\ncd", "a-\u200bb", "5- 10"):
        text, pos = normalize(raw)
        assert len(pos) == len(text)
        assert all(0 <= p < len(raw) for p in pos) and pos == sorted(pos)


def test_clean_anchor():
    assert clean_anchor("Расчётное значение ветро-\nвого  давления\n") == "Расчётное значение ветрового давления"


def test_clean_anchor_numbers_and_control_chars():
    assert clean_anchor("от 5-\n10 мм") == "от 5-10 мм"
    assert clean_anchor("П р и \x03м") == "П р и м"


def test_clean_anchor_keeps_spaced_dash():
    assert clean_anchor("до 100 м -\nминус 5") == "до 100 м - минус 5"
    assert clean_anchor("ветро- \nвое") == "ветровое"


_ALPHABET = "аб вгЕёİ AbcBHMT-–—‑\u00ad\u200b\x08\n \t\u00a05190.,«»"


def test_clean_anchor_round_trips_through_normalize():
    rnd = random.Random(7)
    for _ in range(20000):
        x = "".join(rnd.choice(_ALPHABET) for _ in range(rnd.randint(0, 14)))
        assert normalize(clean_anchor(x))[0] == normalize(x)[0], repr(x)


@pytest.fixture(scope="module")
def sp(tmp_path_factory):
    return DocText.of(extract_pages(make_pdf(tmp_path_factory.mktemp("sp") / "СП 99.pdf", SP_PAGES)))


def test_anchor_matches_back_on_sample_pdf(sp):
    rnd = random.Random(3)
    for _ in range(300):
        i = rnd.randrange(len(sp.pages))
        t = sp.norm[i][0]
        if len(t) < 25:
            continue
        a = rnd.randrange(len(t) - 20)
        q = t[a: a + rnd.randint(15, min(60, len(t) - a))]
        v = find_quote(sp, q, i + 1)
        assert v.verdict == "ok" and find_quote(sp, v.anchor, v.page).verdict == "ok", (q, v)


def test_anchor_starting_with_hyphen_matches_back():
    # СП 20, с. 76: «+/- 0,2» нормализуется в «+/-0,2»; подсветка с дефиса без «/» перед ним дала бы «- 0,2»
    doc = DocText.of(["Коэффициенты сi1 = сi2 = +/- 0,2. Для каждой стены здания знак «плюс» или «минус»"])
    for quote in ("-0,2. Для каждой стены здания знак", "-0,2. Для каждой стены зданя знак «плюс»"):
        v = find_quote(doc, quote)
        assert v.verdict in ("ok", "fuzzy") and find_quote(doc, v.anchor).verdict == "ok", (quote, v)


def test_find_quote_ok_across_hyphenation(sp):
    v = find_quote(sp, "расчетное значение ветрового давления", page=2)
    assert (v.verdict, v.page, v.anchor) == ("ok", 2, "Расчётное значение ветрового давления")


def test_find_quote_without_page(sp):
    v = find_quote(sp, "Пермь относится ко II ветровому району")
    assert (v.verdict, v.page) == ("ok", 3)


def test_find_quote_moved(sp):
    v = find_quote(sp, "Пермь относится ко II ветровому району", page=1)
    assert (v.verdict, v.page) == ("moved", 3)


def test_find_quote_moved_to_nearest():
    same = "Анкер М10 крепит закладную к бетону"
    doc = DocText.of([same, "x" * 60, "y" * 60, same])
    assert find_quote(doc, "анкер м10 крепит закладную", page=3).page == 4


def test_find_quote_fuzzy(sp):
    v = find_quote(sp, "Пермь относится ко II ветровому раону", page=3)
    assert (v.verdict, v.page) == ("fuzzy", 3)
    assert v.score >= 85 and v.anchor == "Пермь относится ко II ветровому району"


def test_find_quote_compound_word_across_line():
    doc = DocText.of(["Помещения культурно-\nдосуговой деятельности и залы ожидания вокзалов."])
    assert find_quote(doc, "культурно-досуговой деятельности").verdict == "ok"


def test_find_quote_across_pages_is_not_found():
    doc = DocText.of(["Первая часть длинной цитаты стоит в конце страницы", "продолжение цитаты на следующей странице документа"])
    assert find_quote(doc, "в конце страницы продолжение цитаты").verdict == "not_found"   # цитата — в пределах страницы


def test_find_quote_fuzzy_prefers_claimed_page():
    same = "Нормативное значение ветрового давления для района"
    doc = DocText.of([same, same])
    assert find_quote(doc, "нормативное значение ветрового давлени для района", page=2).page == 2


def test_find_quote_not_found(sp):
    assert find_quote(sp, "Снеговая нагрузка на покрытие складов").verdict == "not_found"
    assert find_quote(sp, "вет рай").verdict == "not_found"      # короткая — нечёткий поиск не включается


@pytest.mark.parametrize("locator, page, anchor", [
    ("табл. 1.1, п. 1.2.3", 2, "Т а б л и ц а 1 .1"),           # заголовок вразрядку; «по таблице 1.1» на стр. 1 — не заголовок
    ("п. 1.2.3", 2, "1.2.3"),
    ("формула (1.1)", 2, "(1.1)"),
    ("приложение А", 3, "ПРИЛОЖЕНИЕ А"),                          # строка оглавления на стр. 1 пропущена
    ("карта 2 приложения А; табл. 1.1", 3, "ПРИЛОЖЕНИЕ А"),       # первая ссылка в локаторе — приложение
    ("табл. 1.1, строка «Пермь»", 3, "Пермь"),                    # строка уточняет страницу внутри таблицы
    ("таблицу 1.1", 2, "Т а б л и ц а 1 .1"),
    ("приложение а", 3, "ПРИЛОЖЕНИЕ А"),                          # строчная буква в локаторе (кириллица)
    ("приложение A", 3, "ПРИЛОЖЕНИЕ А"),                          # латинская A в локаторе
    ("приложение к приказу, табл. 1.1", 2, "Т а б л и ц а 1 .1"),  # «к» — предлог, а не приложение К
    ("приложения и табл. 1.1", 2, "Т а б л и ц а 1 .1"),          # «и» — союз, а не приложение И
    ("таблицей 1.1", 2, "Т а б л и ц а 1 .1"),
])
def test_find_locator(sp, locator, page, anchor):
    assert find_locator(sp, locator) == Verdict("by_locator", page, anchor)


def test_find_locator_unresolved(sp):
    assert find_locator(sp, "п. 1.4").verdict == "unresolved"     # «1.4 соответственно» — не пункт
    assert find_locator(sp, "разд. 7, строки «Пермь»").verdict == "unresolved"


def test_find_locator_markdown_section():
    v = find_locator(DocText.of([NOTE_MD]), "раздел «Узел крепления / Кронштейн»")
    assert v == Verdict("by_locator", 1, "Кронштейн")


def test_find_locator_section_prefers_heading_and_whole_words():
    doc = DocText.of(["Снеговая нагрузка на кровлю: первая страница заметки, где слово стоит внутри другого.",
                      "## Снег\n\nНормативная снеговая нагрузка по карте районов."])
    assert find_locator(doc, "раздел «Нагрузки / Снег»") == Verdict("by_locator", 2, "Снег")
    assert find_locator(doc, "раздел « »").verdict == "unresolved"
    assert find_locator(doc, "раздел «Нагрузки/Снег»") == Verdict("by_locator", 2, "Снег")


def test_find_locator_row_stays_inside_table():
    doc = DocText.of(["Т а б л и ц а 1 .1 – Климат\nМосква 1\nКазань 2 и ещё немного текста строки",
                      "Т а б л и ц а 2 .1 – Ветер\nПермь 2\nи ещё немного текста таблицы два"])
    assert find_locator(doc, "табл. 1.1, строка «Пермь»") == Verdict("by_locator", 1, "Т а б л и ц а 1 .1")


def test_find_locator_row_after_caption_on_same_page():
    doc = DocText.of(["Т а б л и ц а 5 .1 – Холод\nПермь -35\nи ещё немного текста таблицы пять",
                      "Хвост таблицы 5.1\nПермь -30\nТ а б л и ц а 6 .1 – Тепло\nМосква 23",
                      "Продолжение таблицы 6.1\nПермь 24\nи ещё немного текста таблицы шесть"])
    assert find_locator(doc, "табл. 6.1, строка «Пермь»") == Verdict("by_locator", 3, "Пермь")
    # строка ниже следующего заголовка на той же странице — уже не наша таблица
    doc = DocText.of(["Т а б л и ц а 5 .1 – Холод\nМосква -25\nТ а б л и ц а 6 .1 – Тепло\nПермь 24",
                      "и ещё немного текста таблицы шесть, страница вторая документа"])
    assert find_locator(doc, "табл. 5.1, строка «Пермь»") == Verdict("by_locator", 1, "Т а б л и ц а 5 .1")
    # «Таблица В.3а» (СП 20, с. 70) — заголовок следующей таблицы, хоть после номера и буква
    doc = DocText.of(["Т а б л и ц а В.3 – Коэффициенты\nМосква 1\nТаблица В.3а\nПермь 2",
                      "и ещё немного текста таблицы, страница вторая документа"])
    assert find_locator(doc, "табл. В.3, строка «Пермь»") == Verdict("by_locator", 1, "Т а б л и ц а В.3")


def test_find_locator_row_ignores_table_reference_at_line_start():
    # «Таблица 6.1, графа 3» в начале строки — ссылка в тексте (СП 131, с. 230), а не заголовок следующей таблицы
    doc = DocText.of(["Т а б л и ц а 5 .1 – Холод\nМосква -25\nТаблица 6.1, графа 3 — для тёплого периода",
                      "Продолжение таблицы 5.1\nТаблица 6.1, графа 4\nПермь -35\nи ещё немного текста таблицы"])
    assert find_locator(doc, "табл. 5.1, строка «Пермь»") == Verdict("by_locator", 2, "Пермь")


def test_find_locator_appendix_letter_is_not_preposition():
    doc = DocText.of(["ПРИЛОЖЕНИЕ К\nФорма приказа и прочие сведения для заполнения",
                      "ПРИЛОЖЕНИЕ И\nПеречень документов и прочие сведения для заполнения",
                      "Т а б л и ц а 11 .1 – Коэффициенты\nи ещё немного текста таблицы одиннадцать"])
    for locator in ("приложение к приказу, табл. 11.1", "приложения и табл. 11.1"):
        assert find_locator(doc, locator) == Verdict("by_locator", 3, "Т а б л и ц а 11 .1"), locator
    assert find_locator(doc, "приложение К, табл. 11.1") == Verdict("by_locator", 1, "ПРИЛОЖЕНИЕ К")
    assert find_locator(doc, "прил. И") == Verdict("by_locator", 2, "ПРИЛОЖЕНИЕ И")
    assert find_locator(doc, "приложение и") == Verdict("by_locator", 2, "ПРИЛОЖЕНИЕ И")


def test_find_locator_uppercase_appendix_letter_before_lowercase_word():
    # заглавная буква — всегда приложение, даже перед строчным словом; предлогом может быть только строчная
    doc = DocText.of(["1 Общие положения\nНастоящий свод правил распространяется на здания и сооружения.",
                      "ПРИЛОЖЕНИЕ Б\nТ а б л и ц а Б.1 – Коэффициенты\nи ещё немного текста приложения"])
    for locator in ("Приложение Б таблица Б.1", "прил. Б п. Б.2", "приложение Б к СП 50"):
        assert find_locator(doc, locator) == Verdict("by_locator", 2, "ПРИЛОЖЕНИЕ Б"), locator


def test_find_locator_appendix_case_ending_is_not_a_letter():
    # окончание падежа — не буква приложения: «приложением Д» — не «приложение М»
    doc = DocText.of(["1 Общие положения\nНастоящий свод правил распространяется на здания и сооружения.",
                      "ПРИЛОЖЕНИЕ Д\nПеречень документов и прочие сведения для заполнения",
                      "ПРИЛОЖЕНИЕ М\nФорма приказа и прочие сведения для заполнения"])
    for locator in ("приложением Д", "по приложениям Д и Е", "в приложении Д", "в приложениях Д", "приложению Д",
                    "приложение Д", "прил. Д"):
        assert find_locator(doc, locator) == Verdict("by_locator", 2, "ПРИЛОЖЕНИЕ Д"), locator
    assert find_locator(doc, "приложением М") == Verdict("by_locator", 3, "ПРИЛОЖЕНИЕ М")
    assert find_locator(doc, "приложением").verdict == "unresolved"       # без буквы окончание не становится буквой


def test_find_locator_skips_table_of_contents_page():
    doc = DocText.of(["Содержание\nПриложение Б Методика расчёта\nудельной характеристики ........ 40\n"
                      "Приложение В ........ 41\nПриложение Г ........ 42",
                      "1 Область применения\nНастоящий свод правил распространяется на здания.",
                      "Приложение Б\nМетодика расчёта удельной характеристики расхода тепловой энергии"])
    assert find_locator(doc, "приложение Б") == Verdict("by_locator", 3, "Приложение Б")
    # одиночное «…» в формулах и таблицах (СП 50, с. 26, 40) — не отточие: страница не оглавление
    doc = DocText.of(["Приложение Б\nD1 = R1s1; D2 = R2s2; …; Dn = Rnsn\nR1, R2, … , Rn — сопротивления\n…\n…",
                      "Продолжение приложения Б и ещё немного текста для второй страницы"])
    assert find_locator(doc, "приложение Б") == Verdict("by_locator", 1, "Приложение Б")


def test_judge(sp):
    assert judge(None, "что угодно").verdict == "no_text"
    assert judge(sp, "Пермь относится ко II ветровому району").verdict == "ok"
    assert judge(sp, "", None, "табл. 1.1").verdict == "by_locator"
    assert judge(sp, "", None, "").verdict == "unresolved"
    assert judge(DocText.of([NOTE_MD]), "", None, "заметка") == Verdict("ok", 1)
