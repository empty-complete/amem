"""Языки текста записей (docs/superpowers/specs/2026-11-09-amem-text-languages-design.md): amem.lang, подписи
и фрагменты на языке запроса с заменой на другой слот, полнотекстовый поиск по слотам en, перестройка проекции
поиска, язык у HTTP (Accept-Language), MCP (lang) и CLI (--lang, AMEM_LANG); база — PostgreSQL 18 и 16."""
import json

import pytest

from amem import db, lang, lookup, recipes, records, search, settings
from amem.records import Item, RecordError

pytest_plugins = ["test_service_write", "test_cli"]     # фикстуры kb, start, env, run

MODEL = "model:test"
V1 = "/api/v1"
BOTH = {"ru": "Погрешность влажности датчика", "en": "Sensor humidity accuracy"}
BOTH_SUMMARY = {"ru": "У верхнего края шкалы датчик завышает влажность.",
                "en": "Near saturation the sensor reads humidity high."}
ONLY_EN = {"en": "Humidity readings near saturation"}
ONLY_RU = {"ru": "Высота мачты станции"}


# --- amem.lang без базы ---

def test_check():
    assert [lang.check(v) for v in (None, "", "ru", "EN", " en ")] == [None, None, "ru", "en", "en"]
    for bad in ("de", "en-GB", 1, ["en"]):
        with pytest.raises(lang.LangError, match="допустимы ru, en"):
            lang.check(bad)


@pytest.mark.parametrize("header, expected", [
    ("en", "en"),
    ("en-GB,en;q=0.9,ru;q=0.8", "en"),
    ("ru-RU,ru;q=0.9,en-US;q=0.8", "ru"),
    ("de-DE,de;q=0.9,en;q=0.5,ru;q=0.4", "en"),         # первый поддерживаемый по весу, а не по месту
    ("ru;q=0.5, en", "en"),
    ("en;q=0, ru;q=0.1", "ru"),                          # q=0 — «не надо»
    ("de, fr;q=0.5", None),
    ("*", None),
    ("en;q=abc", None),
    ("", None),
    (None, None),
])
def test_from_header(header, expected):
    assert lang.from_header(header) == expected


def test_pick_order_and_fallback():
    assert lang.order() == ("ru", "en") and lang.order("en") == ("en", "ru")
    assert lang.pick(BOTH, "en") == BOTH["en"] and lang.pick(BOTH, "ru") == BOTH["ru"] and lang.pick(BOTH) == BOTH["ru"]
    assert lang.pick(ONLY_EN) == ONLY_EN["en"] and lang.pick(ONLY_RU, "en") == ONLY_RU["ru"]
    assert lang.pick({"ru": "  ", "en": "Mast"}, "ru") == "Mast"            # пустой слот — как отсутствие
    assert lang.pick({}) is None and lang.pick(None) is None and lang.pick("как есть") == "как есть"
    assert lang.texts({"ru": " ", "en": "Mast"}) == [("en", "Mast")] and lang.texts("строка") == []


def test_using_sets_and_restores_current():
    assert lang.current() is None
    with lang.using("en"):
        assert lang.current() == "en"
        with lang.using(None):
            assert lang.current() is None
        assert lang.current() == "en"
    assert lang.current() is None
    with pytest.raises(lang.LangError):
        with lang.using("de"):
            pass


def test_search_text_keeps_document_without_en():
    """У записи без en документ эмбеддинга прежний: веса A–D по ru и языконезависимому тексту."""
    payload = {"kind": "fact", "label": ONLY_RU, "summary_plain": {"ru": "Мачта 10 м."}, "codes": ["WS-100"]}
    text = search.search_text(payload, "atom")
    assert text.english == {weight: () for weight in "ABCD"}
    assert text.document == "Высота мачты станции Мачта 10 м. WS-100"


def test_search_text_english_parts():
    payload = {"kind": "fact", "label": BOTH, "summary_plain": {"en": "Reads high."}, "codes": ["TH-20"],
               "retrieval_context": {"en": "TH-20"}}
    text = search.search_text(payload, "atom")
    assert text.weighted["A"] == (BOTH["ru"],) and text.english["A"] == (BOTH["en"],)
    assert text.weighted["B"] == () and text.english["B"] == ("Reads high.",)
    assert text.english["D"] == ()                    # «TH-20» уже есть в D марками — второй раз не индексируется
    assert text.document == f"{BOTH['ru']} {BOTH['en']} Reads high. TH-20"
    assert search.shown_text(payload, "atom", "en") == f"{BOTH['en']} Reads high. TH-20"
    assert search.shown_text(payload, "atom", "ru") == f"{BOTH['ru']} Reads high. TH-20"     # пояснение — замена


def test_shown_text_picks_nested_lang_strings():
    payload = {"kind": "fact", "label": ONLY_EN,
               "content": {"values": [{"property": "x", "label": {"ru": "погрешность", "en": "accuracy"}}]}}
    assert search.shown_text(payload, "atom", "en") == f"{ONLY_EN['en']} accuracy x"
    assert "погрешность" in search.search_text(payload, "atom").document       # индекс — все слоты


def test_lang_setting(tmp_path):
    home = {"HOME": str(tmp_path)}
    assert settings.load(home).lang is None
    assert settings.load({**home, "AMEM_LANG": "EN"}).lang == "en"
    with pytest.raises(settings.SettingsError, match="AMEM_LANG"):
        settings.load({**home, "AMEM_LANG": "de"})


# --- база ---

def atom(label: dict, **payload) -> Item:
    return Item("atom", {"kind": "fact", "label": label, "sources": [], **payload})


def commit(kb, *items) -> list[str]:
    return [f"{records.PREFIX[r.target]}:{r.record_id}" for r in records.commit(kb, list(items), agent=MODEL).revisions]


def test_labels_follow_language(kb):
    both, only_en, only_ru = commit(kb, atom(BOTH), atom(ONLY_EN), atom(ONLY_RU))
    refs = [both, only_en, only_ru]

    def shown(**kw):
        found = lookup.labels(kb, refs, **kw)
        return [found[ref]["label"] for ref in refs]

    assert shown(lang="en") == [BOTH["en"], ONLY_EN["en"], ONLY_RU["ru"]]
    assert shown(lang="ru") == [BOTH["ru"], ONLY_EN["en"], ONLY_RU["ru"]]
    assert shown() == shown(lang="ru")                               # без языка — ru, затем en
    listed = {item["ref"]: item["label"] for item in lookup.list_records(kb, lang="en")["items"]}
    assert listed == {both: BOTH["en"], only_en: ONLY_EN["en"], only_ru: ONLY_RU["ru"]}
    assert lookup.summary(kb, both, lang="en")["label"] == BOTH["en"]
    with pytest.raises(RecordError, match="допустимы ru, en"):
        lookup.labels(kb, refs, lang="de")


def test_fts_finds_english_slots(kb):
    both, only_en, naive = commit(kb, atom(BOTH, summary_plain=BOTH_SUMMARY), atom(ONLY_EN),
                                  atom({"en": "Naïve calibration of the anemometer"}))

    def found(query):
        return {row["ref"] for row in search._fts(kb, query)}

    assert only_en in found("reading saturated")                     # английский стеммер: readings, saturation
    assert both in found("sensor reads high")                        # пояснение en, вес B
    assert both in found("погрешности влажности")                    # слот ru — русский стеммер
    # не-ASCII буква: russian оставил бы «naïve», english даёт «naïv» — запрос идёт на обеих конфигурациях
    assert naive in found("naïve")


def test_snippet_in_requested_language(kb):
    [both] = commit(kb, atom(BOTH, summary_plain=BOTH_SUMMARY))
    for language, text in (("en", BOTH_SUMMARY["en"]), ("ru", BOTH_SUMMARY["ru"])):
        hit = next(item for item in recipes.exact_fact(kb, "humidity", agent=MODEL, log=False, lang=language)["items"]
                   if item["ref"] == both)
        assert text in hit["snippet"] and hit["label"] == BOTH         # label — LangString целиком
        other = BOTH_SUMMARY["ru" if language == "en" else "en"]
        assert other not in hit["snippet"]


def test_projection_rebuilt_when_outdated(kb):
    [ref] = commit(kb, atom(ONLY_EN))
    assert kb.execute("SELECT value FROM meta WHERE key = 'search_projection'").fetchone()[0] == search.PROJECTION
    assert search.ensure_projection(kb) is False                     # версия та же — не перестраивается
    kb.execute("DELETE FROM search_document")
    kb.execute("UPDATE meta SET value = '1'::jsonb WHERE key = 'search_projection'")
    db.prepare(kb)
    assert kb.execute("SELECT value FROM meta WHERE key = 'search_projection'").fetchone()[0] == search.PROJECTION
    assert ref in {row["ref"] for row in search._fts(kb, "humidity reading")}


# --- HTTP, MCP, CLI ---

def test_http_accept_language(start, kb):
    client = start()
    both, only_ru = commit(kb, atom(BOTH, summary_plain=BOTH_SUMMARY), atom(ONLY_RU))

    def labels(**headers):
        items = client.get(f"{V1}/records", headers=headers).json()["items"]
        return {item["ref"]: item["label"] for item in items}

    assert labels(**{"Accept-Language": "en-US,en;q=0.9"}) == {both: BOTH["en"], only_ru: ONLY_RU["ru"]}
    assert labels(**{"Accept-Language": "ru"}) == {both: BOTH["ru"], only_ru: ONLY_RU["ru"]}
    assert labels() == labels(**{"Accept-Language": "de"}) == {both: BOTH["ru"], only_ru: ONLY_RU["ru"]}
    found = client.get(f"{V1}/search", params={"q": "humidity"}, headers={"Accept-Language": "en"}).json()
    hit = next(item for item in found["items"] if item["ref"] == both)
    assert hit["label"] == BOTH["en"] and BOTH_SUMMARY["en"] in hit["snippet"]


def test_mcp_lang_argument(env, kb):
    import contextlib

    import anyio
    from mcp import Client

    from amem.service import mcp

    @contextlib.asynccontextmanager
    async def connect(environ):
        with mcp.open_stdio(settings.load(environ), agent="model:claude-code") as runtime:
            async with Client(mcp.build(runtime)) as client:
                yield client

    async def call(client, name, **arguments):
        result = await client.call_tool(name, arguments)
        return result.is_error, result.structured_content

    [both] = commit(kb, atom(BOTH, summary_plain=BOTH_SUMMARY))

    async def main():
        async with connect(env) as client:
            for language, label in (("en", BOTH["en"]), ("ru", BOTH["ru"]), (None, BOTH["ru"])):
                arguments = {"query": "humidity", **({"lang": language} if language else {})}
                err, found = await call(client, "amem_search", **arguments)
                assert not err, found
                assert next(i["label"] for i in found["items"] if i["ref"] == both) == label
            err, refused = await call(client, "amem_search", query="humidity", lang="de")
            assert err and refused["code"] == "bad_request"
        async with connect({**env, "AMEM_LANG": "en"}) as client:
            err, found = await call(client, "amem_search", query="humidity")
            assert not err and next(i["label"] for i in found["items"] if i["ref"] == both) == BOTH["en"]
    anyio.run(main)


def test_cli_lang(run, kb):
    [both] = commit(kb, atom(BOTH, summary_plain=BOTH_SUMMARY))

    def label(*argv, extra=None):
        code, out, err = run("search", "humidity", "--json", *argv, extra=extra)
        assert code == 0, err
        return next(item["label"] for item in json.loads(out)["items"] if item["ref"] == both)

    assert label("--lang", "en") == BOTH["en"]
    assert label() == BOTH["ru"]
    assert label(extra={"AMEM_LANG": "en"}) == BOTH["en"]
    assert label("--lang", "ru", extra={"AMEM_LANG": "en"}) == BOTH["ru"]      # опция главнее окружения
    code, _, err = run("search", "humidity", "--lang", "de")
    assert code == 2 and "--lang" in err
