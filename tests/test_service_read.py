"""Пути чтения HTTP v1 (подпроект 4, часть 4a, задача 6): каждый ответ сверяется со схемой контракта
docs/api/http-v1.openapi.yaml; операции amem/api.py — нормализация пустых фильтров и проверка параметров.
starlette.testclient на настоящей базе (PostgreSQL 18 и 16), порт не слушается."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import contract
from amem import api, db, embed, folders, objects, records, review
from amem.ocfl_store import ObjectStore
from amem.records import Item
from conftest import FakeProvider
from samples import make_xlsx

PERSON = "person:ann"          # человек службы в тестах (USER=ann)
PDF = "НД/СП 99.pdf"
NOTE = "Заметки/узел.md"
XLSX = "Таблицы/нагрузки.xlsx"
QUOTE = "Ветровой район II: w0 = 0,30 кПа"
V1 = "/api/v1"
PACKS = Path(__file__).with_name("packs")


def problem(response, status: int, code: str, path: str, method: str = "get") -> dict:
    """Ответ-ошибка по контракту: статус описан, тело — Problem с этим code."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = contract.check(response, path, method)
    assert body["code"] == code
    return body


@pytest.fixture
def world(pg, docs, tmp_path):
    """Небольшая база: площадка ← станция ← датчик (part_of), факт о датчике с источником в PDF, урок, связь,
    папка, статус, пункт аудита; объекты — PDF, заметка .md, книга xlsx, переписка и страница сайта."""
    db.prepare(pg)
    store = ObjectStore(tmp_path / "objects")              # то же хранилище, что у службы (AMEM_DATA фикстуры serve)
    make_xlsx(docs / XLSX, {"Нагрузки": [["Район", "w0, кПа"], ["II", 0.3], ["III", 0.38]]})
    pdf = objects.ingest(pg, store, docs, PDF, agent=PERSON)
    note = objects.ingest(pg, store, docs, NOTE, agent=PERSON)
    book = objects.ingest(pg, store, docs, XLSX, agent=PERSON)
    letter = objects.message(pg, "Письмо о ветровом районе")
    site = objects.web(pg, "https://example.org/wind")
    fact = objects.resolve_sources(pg, store, docs, {
        "ref": "@w0", "kind": "fact", "key": "w0_ii", "label": {"ru": "Давление ветра для района II"},
        "summary_plain": {"ru": "Нормативное давление ветра во II районе — 0,30 кПа."}, "codes": ["w0"],
        "about": ["@sensor"], "tags": ["ветер"],
        "sources": [{"path": PDF, "selectors": [{"type": "page", "value": "2"}], "quote": QUOTE, "role": "primary"}],
    }, agent=PERSON)
    committed = records.commit(pg, [
        Item("entity", {"ref": "@area", "entity_class": "project", "key": "area", "label": {"ru": "Площадка"}}),
        Item("entity", {"ref": "@station", "entity_class": "artifact", "key": "station",
                        "label": {"ru": "Метеостанция"}}),
        Item("entity", {"ref": "@sensor", "entity_class": "artifact", "key": "sensor",
                        "label": {"ru": "Датчик ветра"}}),
        Item("atom", fact),
        Item("atom", {"ref": "@gusts", "kind": "lesson", "key": "gusts", "label": {"ru": "Порывы сильнее среднего"},
                      "summary_plain": {"ru": "Порывы ветра бывают сильнее среднего давления."}, "about": ["@sensor"]}),
    ], links=[{"rel": "part_of", "src": "@station", "dst": "@area"},
              {"rel": "part_of", "src": "@sensor", "dst": "@station"},
              {"rel": "depends_on", "src": "@gusts", "dst": "@w0", "confidence": 0.8, "note": "по замерам"}],
        agent=PERSON)
    refs = committed.refs
    folders.move(pg, refs["@w0"], "Проекты/Ветер", agent=PERSON)
    records.set_status(pg, "atom", records.resolve(pg, refs["@w0"])[1], "verified", agent=PERSON, reason="сверено")
    item = review.enqueue(pg, refs["@w0"], "audit", agent=PERSON, note="выборочно")
    return SimpleNamespace(conn=pg, store=store, docs=docs, refs=refs, w0=refs["@w0"], gusts=refs["@gusts"],
                           sensor=refs["@sensor"], station=refs["@station"], area=refs["@area"], item=item,
                           pdf=pdf, note=note, book=book, letter=letter, site=site)


def oid(version) -> str:
    return str(version.object_id)


# --- контракт: файл, копия в пакете, /openapi.json ---

def test_contract_is_valid_openapi_3_1():
    from openapi_spec_validator import validate

    validate(contract.spec())
    assert contract.spec()["openapi"].startswith("3.1")


def test_package_copy_of_the_contract_is_byte_for_byte_the_same():
    package = Path(api.__file__).parent / "service" / "http-v1.openapi.yaml"
    assert package.read_bytes() == contract.PATH.read_bytes(), \
        "копия контракта в пакете отстала: cp docs/api/http-v1.openapi.yaml amem/service/"


def test_contract_copy_is_package_data():
    import tomllib

    data = tomllib.loads((contract.ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "service/*.yaml" in data["tool"]["setuptools"]["package-data"]["amem"]


def test_openapi_json_is_the_contract(serve):
    response = serve().get(f"{V1}/openapi.json")
    assert response.status_code == 200
    assert response.json() == yaml.safe_load(contract.PATH.read_text(encoding="utf-8"))


def test_contract_check_is_strict_but_problem_is_open():
    """Лишнее поле ответа — расхождение с контрактом; у Problem расширения RFC 9457 разрешены."""
    session = {"agent": "model:local", "base": "01900000-0000-7000-8000-000000000000", "base_name": None,
               "amem_version": "0.1.0", "semantic": "used", "can_write": True}
    contract.component("Session", session)
    with pytest.raises(AssertionError, match="secret"):
        contract.component("Session", {**session, "secret": 1})
    contract.component("Problem", {"type": "about:blank", "title": "Уже решено", "status": 409,
                                   "code": "review_closed", "by": "person:ann"})
    contract.component("RecordView", {"ref": "atm:x", "target": "atom", "revision": 1, "status": "draft",
                                      "review_state": "none", "recorded_at": "2026-11-07T09:00:00+00:00",
                                      "agent": "person:ann", "sources": [], "open_items": [],
                                      "payload": {"любое": "тело"}})                    # тело записи — открытое


# --- сессия ---

def test_session(serve, pg):
    client = serve()
    body = contract.check(client.get(f"{V1}/session"), "/session")
    assert (body["agent"], body["base_name"], body["semantic"]) == ("model:local", None, "unavailable")
    db.set_base_name(pg, "Метеоплощадка")
    assert contract.check(client.get(f"{V1}/session"), "/session")["base_name"] == "Метеоплощадка"


# --- поиск ---

def test_search(serve, world):
    client = serve()
    body = contract.check(client.get(f"{V1}/search", params={"q": "w0"}), "/search")
    hit = next(h for h in body["items"] if h["ref"] == world.w0)
    assert (hit["label"], hit["kind"], hit["status"]) == ("Давление ветра для района II", "fact", "verified")
    assert hit["about"] == [{"ref": world.sensor, "label": "Датчик ветра", "entity_class": "artifact"}]
    code = next(m for m in hit["matches"] if m["channel"] == "code_exact")
    assert code["source_rank"] is None                        # у каналов кода своего ранга нет
    assert body["retrieval_id"]                               # явный поиск пишется в журнал выдачи
    agent = world.conn.execute("SELECT agent FROM retrieval WHERE id = %s", (body["retrieval_id"],)).fetchone()[0]
    assert agent == "model:local"


def test_search_filters_and_empty_filter_is_no_filter(serve, world):
    client = serve()

    def refs(**params):
        return [h["ref"] for h in contract.check(client.get(f"{V1}/search", params=params), "/search")["items"]]

    everything = refs(q="ветра")
    assert world.w0 in everything and world.sensor in everything
    assert refs(q="ветра", kind="lesson") == [world.gusts]
    assert set(refs(q="ветра", kind=["fact", "lesson"])) == {world.w0, world.gusts}
    assert refs(q="ветра", entity_class="artifact") == [world.sensor]
    assert world.w0 not in refs(q="ветра", status="draft")
    assert refs(q="ветра", target="entity") == [world.sensor]
    assert refs(q="ветра", status="") == everything           # пустой фильтр — без фильтра
    assert len(refs(q="ветра", limit=1)) == 1
    # операция напрямую: пустой список статусов — без фильтра (у recipes.exact_fact он дал бы пустую выдачу)
    direct = api.search(world.conn, "ветра", agent=PERSON, status=[], kind=[], entity_class=[])
    assert [h["ref"] for h in direct["items"]] == everything


@pytest.mark.parametrize("params, word", [
    ({}, "q"),
    ({"q": "w0", "limit": "0"}, "limit"),
    ({"q": "w0", "limit": "101"}, "limit"),
    ({"q": "w0", "limit": "много"}, "limit"),
    ({"q": "w0", "status": "забыт"}, "status"),
    ({"q": "w0", "target": "object"}, "target"),
])
def test_search_bad_parameters(serve, world, params, word):
    body = problem(serve().get(f"{V1}/search", params=params), 400, "bad_request", "/search")
    assert word in body["detail"]


def test_search_private_text_is_removed_before_search_and_journal(serve, world):
    body = contract.check(serve().get(f"{V1}/search", params={"q": "w0 <private>тайна</private>"}), "/search")
    query = world.conn.execute("SELECT query FROM retrieval WHERE id = %s", (body["retrieval_id"],)).fetchone()[0]
    assert "тайна" not in query and world.w0 in [h["ref"] for h in body["items"]]


def test_similar(serve, world, pg):
    provider = FakeProvider()
    model = embed.register_model(pg, provider)
    embed.sync_embeddings(pg, model["id"], provider)
    embed.activate_model(pg, model["id"])
    client = serve(provider=provider)
    by_ref = contract.check(client.get(f"{V1}/similar", params={"ref": world.w0}), "/similar")
    assert by_ref["semantic"] == "used" and world.w0 not in [h["ref"] for h in by_ref["items"]]
    by_key = contract.check(client.get(f"{V1}/similar", params={"ref": "atm:w0_ii"}), "/similar")
    assert [h["ref"] for h in by_key["items"]] == [h["ref"] for h in by_ref["items"]]
    by_text = contract.check(client.get(f"{V1}/similar", params={"q": "давление ветра"}), "/similar")
    assert by_text["semantic"] == "used"
    for params in ({}, {"ref": world.w0, "q": "ветер"}, {"ref": "w0_ii"}, {"q": "atm:w0_ii"}):
        problem(client.get(f"{V1}/similar", params=params), 400, "bad_request", "/similar")
    problem(client.get(f"{V1}/similar", params={"ref": "atm:no_such"}), 404, "not_found", "/similar")


def activate_fake_model(pg) -> FakeProvider:
    provider = FakeProvider()
    model = embed.register_model(pg, provider)
    embed.sync_embeddings(pg, model["id"], provider)
    embed.activate_model(pg, model["id"])
    return provider


def test_search_and_similar_degrade_when_the_provider_does_not_fit(serve, world, pg):
    """Активная модель есть, а provider службы — не её (fastembed по умолчанию): поиск не падает 503, а отвечает
    лексическими каналами с причиной; similar по ссылке берёт вектор из базы — provider ему не нужен."""
    activate_fake_model(pg)
    client = serve()
    for path, params in (("/search", {"q": "w0"}), ("/similar", {"q": "давление ветра"})):
        body = contract.check(client.get(f"{V1}{path}", params=params), path)
        assert body["semantic"] == "unavailable"
        assert body["channels"]["reasons"] == {"vector": "provider_mismatch"}
        assert world.w0 in [h["ref"] for h in body["items"]]
    assert pg.execute("SELECT count(*) FROM retrieval").fetchone()[0] == 2     # по строке журнала на поиск
    assert contract.check(client.get(f"{V1}/session"), "/session")["semantic"] == "unavailable"
    assert contract.check(client.get(f"{V1}/similar", params={"ref": world.w0}), "/similar")["semantic"] == "used"


def test_default_provider_is_made_once_per_service(serve, world, pg, monkeypatch):
    """provider по AMEM_BACKEND создаётся при первом поиске один раз: модель fastembed не грузится на каждый запрос."""
    made = []

    class Fastembed(FakeProvider):
        name, version, backend = "fake-fastembed", "1", "fastembed"

        def __init__(self):
            super().__init__()
            made.append(self)

    model = embed.register_model(pg, Fastembed())
    embed.sync_embeddings(pg, model["id"], made[0])
    embed.activate_model(pg, model["id"])
    made.clear()
    monkeypatch.setattr(embed, "FastembedProvider", Fastembed)
    client = serve()
    for q in ("w0", "ветер", "давление"):
        assert contract.check(client.get(f"{V1}/search", params={"q": q}), "/search")["semantic"] == "used"
    assert contract.check(client.get(f"{V1}/similar", params={"q": "ветер"}), "/similar")["semantic"] == "used"
    contract.check(client.get(f"{V1}/session"), "/session")
    assert len(made) == 1 and len(made[0].calls) == 4


@pytest.mark.parametrize("path, params", [
    ("/search", {"q": "w0\x00"}), ("/search", {"q": "w0", "kind": "\x00"}), ("/search", {"q": "w0", "target": "\x00"}),
    ("/search", {"q": "w0", "limit": "1\x00"}), ("/similar", {"q": "\x00"}), ("/similar", {"ref": "atm:\x00"}),
    ("/records", {"tag": "\x00"}), ("/records", {"folder": "\x00"}), ("/records", {"about": "\x00"}),
    ("/records", {"cursor": "\x00"}), ("/records", {"status": "\x00"}), ("/changes", {"since": "\x00"}),
    ("/changes", {"who": "\x00"}), ("/graph", {"ref": "ent:sensor", "rels": "\x00"}), ("/graph", {"ref": "ent:\x00"}),
])
def test_nul_in_a_parameter_is_400(serve, world, path, params):
    """Знак NUL PostgreSQL не принимает: ответ — 400 о параметре, а не 500 из базы."""
    body = problem(serve().get(f"{V1}{path}", params=params), 400, "bad_request", path)
    assert "NUL" in body["detail"]


def test_nul_in_a_path_is_400(serve, world):
    client = serve()
    for url, path in ((f"{V1}/vocab/%00", "/vocab/{scheme}"), (f"{V1}/records/atm:%00", "/records/{ref}"),
                      (f"{V1}/entities/ent:%00/card", "/entities/{ref}/card"), (f"{V1}/objects/%00", "/objects/{id}"),
                      (f"{V1}/objects/{oid(world.book)}/versions/1/sheet?name=%00",
                       "/objects/{id}/versions/{n}/sheet")):
        problem(client.get(url), 400, "bad_request", path)
    # операция напрямую — так же: MCP и CLI получают тот же отказ
    with pytest.raises(api.BadRequest, match="NUL"):
        api.record_list(world.conn, tag="a\x00b")


# --- папки и список записей ---

def test_folders(serve, world):
    body = contract.check(serve().get(f"{V1}/folders"), "/folders")
    projects = next(f for f in body["folders"] if f["path"] == "Проекты")
    assert projects["count"] == 1 and projects["children"][0]["path"] == "Проекты/Ветер"
    assert (body["unfiled"], body["total"]) == (4, 5)


def test_records_list_filters_and_about(serve, world):
    client = serve()

    def listed(**params):
        return contract.check(client.get(f"{V1}/records", params=params), "/records")

    every = listed()
    assert every["total"] == 5 and every["next_cursor"] is None
    w0 = next(i for i in every["items"] if i["ref"] == world.w0)
    assert (w0["folder"], w0["status"], w0["kind_or_class"], w0["tags"]) == ("Проекты/Ветер", "verified", "fact",
                                                                             ["ветер"])
    assert w0["about"] == [{"ref": world.sensor, "label": "Датчик ветра", "entity_class": "artifact"}]
    assert [i["ref"] for i in listed(folder="Проекты")["items"]] == [world.w0]
    assert listed(folder="-")["total"] == 4
    assert {i["ref"] for i in listed(kind="artifact")["items"]} == {world.station, world.sensor}
    assert {i["ref"] for i in listed(kind=["fact", "lesson"])["items"]} == {world.w0, world.gusts}
    assert [i["ref"] for i in listed(status="verified")["items"]] == [world.w0]
    assert listed(status="", kind="")["total"] == 5            # пустые фильтры — без фильтра
    assert [i["ref"] for i in listed(tag="ветер")["items"]] == [world.w0]
    assert {i["ref"] for i in listed(about=world.sensor)["items"]} == {world.w0, world.gusts}
    assert {i["ref"] for i in listed(about="ent:sensor")["items"]} == {world.w0, world.gusts}
    assert [i["ref"] for i in listed(about=f"obj:{oid(world.pdf)}")["items"]] == [world.w0]   # цитирует объект
    assert [i["ref"] for i in listed(about=oid(world.pdf))["items"]] == [world.w0]
    assert listed(about="ent:no_such")["items"] == []


def test_records_list_pages_by_cursor(serve, world):
    client = serve()
    seen, cursor = [], None
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = contract.check(client.get(f"{V1}/records", params=params), "/records")
        seen += [i["ref"] for i in page["items"]]
        assert page["total"] == 5
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 5


@pytest.mark.parametrize("params", [{"limit": "0"}, {"limit": "201"}, {"status": "забыт"}, {"cursor": "не-курсор"},
                                    {"about": "atm:w0_ii"}])
def test_records_list_bad_parameters(serve, world, params):
    problem(serve().get(f"{V1}/records", params=params), 400, "bad_request", "/records")


def test_records_list_bad_folder_is_422(serve, world):
    problem(serve().get(f"{V1}/records", params={"folder": "a/../b"}), 422, "folder_invalid", "/records")


# --- запись ---

def test_record_view(serve, world):
    client = serve()
    body = contract.check(client.get(f"{V1}/records/{world.w0}"), "/records/{ref}")
    assert (body["ref"], body["target"], body["revision"], body["status"]) == (world.w0, "atom", 1, "verified")
    assert body["payload"]["label"] == {"ru": "Давление ветра для района II"} and "id" not in body["payload"]
    assert (body["folder"], body["agent"]) == ("Проекты/Ветер", PERSON)
    assert body["about"] == [{"ref": world.sensor, "label": "Датчик ветра", "entity_class": "artifact"}]
    # цепочка part_of первой сущности about — от корня, без неё самой
    assert [a["ref"] for a in body["ancestors"]] == [world.area, world.station]
    [source] = body["sources"]
    assert source["object"] == oid(world.pdf)                    # голый UUID, как id у ObjectView
    assert (source["object_name"], source["object_kind"], source["media_type"]) == ("СП 99.pdf", "file",
                                                                                     "application/pdf")
    assert (source["quote"], source["role"], source["verdict"]) == (QUOTE, "primary", None)   # ещё не сверялся
    [item] = body["open_items"]
    assert (item["id"], item["reason"], item["state"], item["label"]) == (str(world.item), "audit", "queued",
                                                                          "Давление ветра для района II")
    assert item["kind_or_class"] == "fact" and item["details"] == {"note": "выборочно"}
    assert body["usefulness"] == 0.0
    by_key = contract.check(client.get(f"{V1}/records/atm:w0_ii"), "/records/{ref}")
    assert by_key["ref"] == world.w0

    entity = contract.check(client.get(f"{V1}/records/{world.sensor}"), "/records/{ref}")
    assert (entity["target"], entity["about"], entity["usefulness"]) == ("entity", [], None)
    assert [a["ref"] for a in entity["ancestors"]] == [world.area, world.station]


def test_record_with_every_revision_declined_is_still_shown(serve, world, pg):
    """Список записей показывает такую запись по последней ревизии — и страница записи тоже, а не 404."""
    written = records.commit(pg, [Item("atom", {"kind": "note", "label": {"ru": "Черновик модели"}},
                                       review_state="pending")], agent="model:bot")
    revision = written.revisions[0]
    records.decide(pg, "atom", revision.revision_id, False, agent=PERSON)
    ref = f"atm:{revision.record_id}"
    client = serve()
    assert ref in [i["ref"] for i in contract.check(client.get(f"{V1}/records"), "/records")["items"]]
    body = contract.check(client.get(f"{V1}/records/{ref}"), "/records/{ref}")
    assert (body["revision"], body["review_state"], body["agent"]) == (1, "declined", "model:bot")


def test_record_errors(serve, world):
    client = serve()
    problem(client.get(f"{V1}/records/atm:01900000-0000-7000-8000-000000000000"), 404, "not_found", "/records/{ref}")
    problem(client.get(f"{V1}/records/atm:no_such"), 404, "not_found", "/records/{ref}")
    problem(client.get(f"{V1}/records/w0_ii"), 400, "bad_request", "/records/{ref}")
    problem(client.get(f"{V1}/records/atm:no_such/history"), 404, "not_found", "/records/{ref}/history")
    problem(client.get(f"{V1}/records/ent:no_such/links"), 404, "not_found", "/records/{ref}/links")


def test_record_history(serve, world):
    body = contract.check(serve().get(f"{V1}/records/{world.w0}/history"), "/records/{ref}/history")
    assert body["ref"] == world.w0
    types = [e["type"] for e in body["events"]]
    assert {"revision", "status", "folder", "link_created"} <= set(types)
    revision = next(e for e in body["events"] if e["type"] == "revision")
    assert isinstance(revision["changes"], list) and revision["label"] == "Давление ветра для района II"
    assert "content_hash" not in revision and "previous_content_hash" not in revision   # служебные хэши — не наружу
    assert revision["recorded_at"] and revision["valid_from"] is None
    move = next(e for e in body["events"] if e["type"] == "folder")
    assert (move["from"], move["to"], move["agent"]) == (None, "Проекты/Ветер", PERSON)
    link = next(e for e in body["events"] if e["type"] == "link_created")
    assert (link["ref"], link["src"], link["dst"]) == (world.w0, world.gusts, world.w0)   # событие этой записи


def test_record_links(serve, world):
    client = serve()
    [link] = contract.check(client.get(f"{V1}/records/{world.w0}/links"), "/records/{ref}/links")
    assert (link["rel"], link["direction"], link["note"], link["confidence"]) == ("depends_on", "in", "по замерам", 0.8)
    assert link["other"] == {"ref": world.gusts, "label": "Порывы сильнее среднего", "kind": "lesson"}
    [up] = contract.check(client.get(f"{V1}/records/{world.sensor}/links"), "/records/{ref}/links")
    assert (up["rel"], up["direction"], up["other"]["ref"]) == ("part_of", "out", world.station)
    assert up["note"] is None and up["confidence"] is None


# --- карточка и граф ---

def test_card(serve, world):
    client = serve()
    body = contract.check(client.get(f"{V1}/entities/{world.sensor}/card"), "/entities/{ref}/card")
    assert body["format"] == "amem.card/1"
    assert body["entity"] == {"ref": world.sensor, "label": "Датчик ветра", "entity_class": "artifact"}
    assert [a["ref"] for a in body["ancestors"]] == [world.area, world.station]   # от корня
    assert body["ancestors"][0] == {"ref": world.area, "label": "Площадка", "entity_class": "project"}
    flat = contract.check(client.get(f"{V1}/entities/ent:sensor/card", params={"ancestors": "false"}),
                          "/entities/{ref}/card")
    assert flat["ancestors"] == []
    problem(client.get(f"{V1}/entities/{world.w0}/card"), 400, "bad_request", "/entities/{ref}/card")
    problem(client.get(f"{V1}/entities/ent:no_such/card"), 404, "not_found", "/entities/{ref}/card")
    problem(client.get(f"{V1}/entities/{world.sensor}/card", params={"ancestors": "может"}), 400, "bad_request",
            "/entities/{ref}/card")


def test_card_fields_have_property_labels_and_text_prompts(serve, pg, monkeypatch):
    """Поле карточки — с подписью величины из словаря; ask, hint, when (LangString библиотеки) — строкой ru."""
    monkeypatch.setenv("AMEM_PACKS", os.pathsep.join([str(PACKS / "quantities"), str(PACKS / "ontology")]))
    db.prepare(pg)
    done = records.commit(pg, [Item("entity", {"entity_class": "device", "label": {"ru": "Насос"}})], agent=PERSON)
    ref = f"ent:{done.revisions[0].record_id}"
    body = contract.check(serve().get(f"{V1}/entities/{ref}/card"), "/entities/{ref}/card")
    fields = {f["property"]: f for f in body["fields"]}
    mass, temperature = fields["mass"], fields["temperature"]
    assert (mass["label"], mass["ask"], mass["hint"], mass["state"]) == ("масса", "изготовитель", "паспорт, табличка",
                                                                         "missing")
    assert (temperature["label"], temperature["when"]) == ("температура", "если не задано заданием")
    assert temperature["default"] == {"amount": 20, "unit": "Cel"}


def test_graph(serve, world):
    client = serve()
    body = contract.check(client.get(f"{V1}/graph", params={"ref": world.sensor, "depth": 2}), "/graph")
    nodes = {n["ref"]: n for n in body["nodes"]}
    assert body["ref"] == world.sensor and body["truncated"] is False and body["total"] == len(nodes)
    assert {world.sensor, world.station, world.w0, world.gusts, world.area} <= set(nodes)
    assert (nodes[world.w0]["family"], nodes[world.gusts]["family"], nodes[world.station]["family"]) == \
        ("source", "work", "object")
    assert nodes[world.w0]["label"] == "Давление ветра для района II" and nodes[world.sensor]["depth"] == 0
    assert all(e["src"] in nodes and e["dst"] in nodes for e in body["edges"])
    # степень — все текущие связи в базе: part_of к станции, about от факта и урока
    assert (nodes[world.sensor]["degree"], nodes[world.w0]["degree"], nodes[world.area]["degree"]) == (3, 2, 1)
    assert {ref for ref, n in nodes.items() if n["pending"]} == {world.w0}               # пункт аудита открыт
    only = contract.check(client.get(f"{V1}/graph", params={"ref": world.sensor, "rels": "part_of"}), "/graph")
    assert {n["ref"] for n in only["nodes"]} == {world.sensor, world.station}
    assert {n["ref"]: n["degree"] for n in only["nodes"]}[world.sensor] == 3          # степень — не по выдаче
    every = contract.check(client.get(f"{V1}/graph", params={"ref": world.sensor, "rels": "", "status": ""}),
                           "/graph")
    assert {n["ref"] for n in every["nodes"]} == {n["ref"] for n in contract.check(
        client.get(f"{V1}/graph", params={"ref": world.sensor}), "/graph")["nodes"]}       # пустой — без фильтра
    for params in ({"ref": world.sensor, "depth": "4"}, {"ref": world.sensor, "rels": "no_such"},
                   {"limit": "0"}, {"limit": "1001"}, {"limit": "много"}, {"ref": world.sensor, "limit": "-1"},
                   {"project": "проект"}, {"project": "ent:\x00"}, {"limit": "\x00"}, {"project": world.w0},
                   {"depth": "0"}):
        problem(client.get(f"{V1}/graph", params=params), 400, "bad_request", "/graph")
    problem(client.get(f"{V1}/graph", params={"ref": "ent:no_such"}), 404, "not_found", "/graph")
    problem(client.get(f"{V1}/graph", params={"project": "ent:no_such"}), 404, "not_found", "/graph")


def test_graph_without_ref_is_the_overview(serve, world):
    """Без ref — обзор базы: узлы по degree по убыванию, рёбра между вернувшимися, total без предела, ref — null."""
    client = serve()
    body = contract.check(client.get(f"{V1}/graph"), "/graph")
    assert body["ref"] is None and body["truncated"] is False
    degrees = [n["degree"] for n in body["nodes"]]
    assert degrees == sorted(degrees, reverse=True) and body["nodes"][0]["ref"] == world.sensor
    assert {n["ref"] for n in body["nodes"]} == {world.sensor, world.station, world.area, world.w0, world.gusts}
    assert body["total"] == 5 and all("depth" not in n for n in body["nodes"])
    assert {n["ref"] for n in body["nodes"] if n["pending"]} == {world.w0}
    assert len(body["edges"]) == 5 and contract.check(client.get(f"{V1}/graph", params={"ref": ""}), "/graph") == body
    cut = contract.check(client.get(f"{V1}/graph", params={"limit": "2", "depth": "3"}), "/graph")
    kept = {n["ref"] for n in cut["nodes"]}
    assert (len(kept), cut["total"], cut["truncated"]) == (2, 5, True)
    assert [n["ref"] for n in cut["nodes"]] == [n["ref"] for n in body["nodes"]][:2]
    assert all(e["src"] in kept and e["dst"] in kept for e in cut["edges"])
    verified = contract.check(client.get(f"{V1}/graph", params={"status": "verified"}), "/graph")
    assert [n["ref"] for n in verified["nodes"]] == [world.w0] and verified["edges"] == []
    assert contract.check(client.get(f"{V1}/graph", params={"rels": "part_of"}), "/graph")["total"] == 5


def test_graph_overview_of_a_project(serve, world):
    """project — атомы с scope.project и сущности, связанные с ними; с ref project окрестность не сужает."""
    records.commit(world.conn, [Item("atom", {
        "kind": "lesson", "key": "mast", "label": {"ru": "Мачта качается"}, "about": [world.station],
        "summary_plain": {"ru": "В сильный ветер мачта станции качается."}, "scope": {"project": world.area}})],
        agent=PERSON)
    mast = f"atm:{records.resolve(world.conn, 'atm:mast')[1]}"
    client = serve()
    body = contract.check(client.get(f"{V1}/graph", params={"project": "ent:area"}), "/graph")
    assert body["ref"] is None and body["total"] == 2
    assert {n["ref"] for n in body["nodes"]} == {mast, world.station}
    assert [(e["src"], e["dst"], e["rel"]) for e in body["edges"]] == [(mast, world.station, "about")]
    assert {n["ref"]: n["degree"] for n in body["nodes"]}[world.station] == 3            # part_of ×2 и about
    around = contract.check(client.get(f"{V1}/graph", params={"ref": world.sensor, "project": world.area}), "/graph")
    assert around["ref"] == world.sensor and world.w0 in {n["ref"] for n in around["nodes"]}


def test_graph_is_cut_to_the_node_limit(serve, world):
    client = serve()
    full = contract.check(client.get(f"{V1}/graph", params={"ref": world.sensor, "depth": 3}), "/graph")
    assert full["truncated"] is False and full["total"] == len(full["nodes"]) == 5
    body = contract.check(client.get(f"{V1}/graph", params={"ref": world.sensor, "depth": 3, "limit": 3}), "/graph")
    assert body["truncated"] is True and len(body["nodes"]) == 3 and body["total"] == 5
    kept = {n["ref"] for n in body["nodes"]}
    assert world.sensor in kept and max(n["depth"] for n in body["nodes"]) <= 1      # ближние остаются
    assert all(e["src"] in kept and e["dst"] in kept for e in body["edges"])
    assert api.graph(world.conn, world.sensor, limit="1000")["total"] == 4            # глубина 1 по умолчанию


# --- изменения ---

def test_changes(serve, world):
    client = serve()
    body = contract.check(client.get(f"{V1}/changes"), "/changes")
    assert body["ref"] is None and {"revision", "status", "folder", "link_created"} <= {e["type"] for e in
                                                                                        body["events"]}
    events = body["events"]
    assert [e["at"] for e in events] == sorted(e["at"] for e in events)
    assert len(contract.check(client.get(f"{V1}/changes", params={"limit": 2}), "/changes")["events"]) == 2
    assert contract.check(client.get(f"{V1}/changes", params={"who": "model"}), "/changes")["events"] == []
    after = events[-1]["at"]
    late = contract.check(client.get(f"{V1}/changes", params={"since": after}), "/changes")
    assert late["since"] is not None and all(e["at"] >= after for e in late["events"])
    early = contract.check(client.get(f"{V1}/changes", params={"until": events[0]["at"]}), "/changes")
    assert early["events"] == []
    # «+05:00» без %2B: «+» в строке запроса — пробел; время всё равно читается
    plus = client.get(f"{V1}/changes?since=2026-01-01T00:00:00+05:00")
    assert contract.check(plus, "/changes")["since"] == "2026-01-01T00:00:00+05:00"
    for params in ({"who": "robot"}, {"limit": "0"}, {"limit": "501"}, {"since": "вчера"},
                   {"since": "2026-11-07T09:00:00"}, {"since": after, "until": after}):
        problem(client.get(f"{V1}/changes", params=params), 400, "bad_request", "/changes")


# --- объекты ---

def test_object_view(serve, world, pg):
    client = serve()
    objects.text(pg, world.store, world.pdf.object_id, 1)
    body = contract.check(client.get(f"{V1}/objects/{oid(world.pdf)}"), "/objects/{id}")
    assert (body["id"], body["kind"], body["original_name"], body["media_type"]) == (oid(world.pdf), "file",
                                                                                     "СП 99.pdf", "application/pdf")
    assert body["logical_paths"] == [PDF] and body["pages"] == 3 and body["sheets"] is None
    [version] = body["versions"]
    assert (version["n"], version["cited_by"]) == (1, 1) and version["digest"].startswith("sha256:")
    [cited] = body["cited_by"]
    assert cited["record"] == {"ref": world.w0, "label": "Давление ветра для района II", "kind": "fact"}
    assert (cited["version"], cited["quote"]) == (1, QUOTE)
    assert contract.check(client.get(f"{V1}/objects/obj:{oid(world.pdf)}"), "/objects/{id}")["id"] == oid(world.pdf)

    site = contract.check(client.get(f"{V1}/objects/{oid(world.site)}"), "/objects/{id}")
    assert "original_name" not in site and site["url"] == "https://example.org/wind"
    assert (site["versions"][0]["digest"], site["versions"][0]["size"]) == (None, None)
    letter = contract.check(client.get(f"{V1}/objects/{oid(world.letter)}"), "/objects/{id}")
    assert (letter["original_name"], letter["versions"][0]["digest"], letter["url"]) == (
        "Письмо о ветровом районе", None, None)

    problem(client.get(f"{V1}/objects/01900000-0000-7000-8000-000000000000"), 404, "not_found", "/objects/{id}")
    problem(client.get(f"{V1}/objects/не-uuid"), 400, "bad_request", "/objects/{id}")


def test_object_content(serve, world, docs):
    client = serve()
    url = f"{V1}/objects/{oid(world.pdf)}/versions/1/content"
    whole = client.get(url)
    contract.check(whole, "/objects/{id}/versions/{n}/content")
    assert whole.status_code == 200 and whole.content == (docs / PDF).read_bytes()
    assert whole.headers["content-type"] == "application/pdf"
    assert whole.headers["x-content-type-options"] == "nosniff"
    assert whole.headers["content-security-policy"] == "sandbox"
    assert whole.headers["content-disposition"].startswith("inline")
    part = client.get(url, headers={"Range": "bytes=0-9"})
    contract.check(part, "/objects/{id}/versions/{n}/content")
    assert part.status_code == 206 and part.content == whole.content[:10]
    assert part.headers["content-range"] == f"bytes 0-9/{len(whole.content)}"
    # неверный и невыполнимый Range — problem+json с nosniff, а не text/plain
    for bad in ("bytes=5-2", "items=0-1", "bytes=abc"):
        refused = problem(client.get(url, headers={"Range": bad}), 400, "bad_request",
                          "/objects/{id}/versions/{n}/content")
        assert "Range" in refused["detail"]
    for response in [client.get(url, headers={"Range": bad}) for bad in ("bytes=5-2", "items=0-1")]:
        assert response.headers["x-content-type-options"] == "nosniff"
    beyond = client.get(url, headers={"Range": f"bytes={len(whole.content) + 10}-"})
    problem(beyond, 416, "range_not_satisfiable", "/objects/{id}/versions/{n}/content")
    assert beyond.headers["content-range"] == f"bytes */{len(whole.content)}"
    assert beyond.headers["x-content-type-options"] == "nosniff"

    md = client.get(f"{V1}/objects/{oid(world.note)}/versions/1/content")    # text/markdown — не из белого списка
    assert md.status_code == 200 and md.content == (docs / NOTE).read_bytes()
    assert md.headers["content-type"] == "application/octet-stream"
    assert md.headers["content-disposition"].startswith("attachment")
    assert "filename*=utf-8''%D1%83%D0%B7%D0%B5%D0%BB.md" in md.headers["content-disposition"]
    assert md.headers["x-content-type-options"] == "nosniff"

    path = "/objects/{id}/versions/{n}/content"
    problem(client.get(f"{V1}/objects/{oid(world.letter)}/versions/1/content"), 404, "not_found", path)  # без файла
    problem(client.get(f"{V1}/objects/{oid(world.pdf)}/versions/2/content"), 404, "not_found", path)
    problem(client.get(f"{V1}/objects/01900000-0000-7000-8000-000000000000/versions/1/content"), 404, "not_found",
            path)
    problem(client.get(f"{V1}/objects/{oid(world.pdf)}/versions/0/content"), 400, "bad_request", path)
    problem(client.get(f"{V1}/objects/{oid(world.pdf)}/versions/первая/content"), 400, "bad_request", path)
    problem(client.get(f"{V1}/objects/{oid(world.pdf)}/versions/2147483648/content"), 400, "bad_request", path)


def test_store_without_its_root_is_503(serve, world, tmp_path):
    """AMEM_DATA без корня OCFL — том данных не подключён: это недоступность службы, а не «нет файла»."""
    client = serve({"AMEM_DATA": str(tmp_path / "другое-хранилище")})
    url = f"{V1}/objects/{{}}/versions/1/{{}}"
    for tail, object_id, params in (("content", world.pdf, None), ("text", world.pdf, None),
                                    ("sheet", world.book, {"name": "Нагрузки"})):
        body = problem(client.get(url.format(oid(object_id), tail), params=params), 503, "store_unavailable",
                       f"/objects/{{id}}/versions/{{n}}/{tail}")
        assert "AMEM_DATA" in body["detail"] and str(tmp_path) not in body["detail"]   # путь — только в журнал


def test_copy_missing_from_the_store_is_404_and_logged(serve, world, caplog):
    """Корень хранилища есть, а копии нет (удалили вручную) или копия — ссылка за пределы папки объекта: 404
    с подсказкой и предупреждение в журнале службы, а не 500. Текст, уже извлечённый в кэш, отдаётся и без копии."""
    world.store.content(world.pdf.object_id, 1).unlink()
    world.store.content(world.book.object_id, 1).unlink()
    objects.text(world.conn, world.store, world.note.object_id, 1)
    note = world.store.content(world.note.object_id, 1)
    outside = world.store.root.parent / "чужой.md"
    note.rename(outside)
    note.symlink_to(outside)
    client = serve()
    url = f"{V1}/objects/{{}}/versions/1/{{}}"
    with caplog.at_level("WARNING", logger="amem.service"):
        for tail, object_id, params in (("content", world.pdf, None), ("text", world.pdf, None),
                                        ("content", world.book, None), ("sheet", world.book, {"name": "Нагрузки"}),
                                        ("content", world.note, None)):
            body = problem(client.get(url.format(oid(object_id), tail), params=params), 404, "not_found",
                           f"/objects/{{id}}/versions/{{n}}/{tail}")
            assert "восстановите" in body["detail"] and str(world.store.root) not in body["detail"]
    assert caplog.text.count("копии версии 1 нет в хранилище") == 5
    assert str(world.store.root) in caplog.text                          # где именно — в журнале службы
    assert contract.check(client.get(url.format(oid(world.note), "text")), "/objects/{id}/versions/{n}/text")["pages"]


def test_object_text(serve, world):
    client = serve()
    path = "/objects/{id}/versions/{n}/text"
    pages = contract.check(client.get(f"{V1}/objects/{oid(world.pdf)}/versions/1/text"), path)["pages"]
    assert len(pages) == 3 and "w0 = 0,30" in pages[1]
    one = contract.check(client.get(f"{V1}/objects/{oid(world.pdf)}/versions/1/text", params={"page": 2}), path)
    assert one["pages"] == [pages[1]]
    assert contract.check(client.get(f"{V1}/objects/{oid(world.letter)}/versions/1/text"), path)["pages"] == []
    problem(client.get(f"{V1}/objects/{oid(world.pdf)}/versions/1/text", params={"page": 4}), 404, "not_found", path)
    problem(client.get(f"{V1}/objects/{oid(world.pdf)}/versions/1/text", params={"page": 0}), 400, "bad_request",
            path)
    problem(client.get(f"{V1}/objects/{oid(world.pdf)}/versions/3/text"), 404, "not_found", path)


def test_object_sheet(serve, world):
    client = serve()
    path = "/objects/{id}/versions/{n}/sheet"
    url = f"{V1}/objects/{oid(world.book)}/versions/1/sheet"
    window = contract.check(client.get(url, params={"name": "Нагрузки"}), path)
    assert window == {"name": "Нагрузки", "range": "A1:B3", "rows": [["Район", "w0, кПа"], ["II", "0.3"],
                                                                     ["III", "0.38"]]}
    assert contract.check(client.get(url, params={"name": "Нагрузки", "range": ""}), path) == window
    cells = contract.check(client.get(url, params={"name": "Нагрузки", "range": "B2:B3"}), path)
    assert cells["rows"] == [["0.3"], ["0.38"]]
    problem(client.get(url, params={"name": "Нагрузки", "range": "A1:Z1000"}), 413, "too_large", path)
    problem(client.get(url, params={"name": "Нет такого"}), 404, "not_found", path)
    problem(client.get(url), 400, "bad_request", path)
    problem(client.get(url, params={"name": "Нагрузки", "range": "B2-D10"}), 400, "bad_request", path)
    problem(client.get(f"{V1}/objects/{oid(world.pdf)}/versions/1/sheet", params={"name": "Лист1"}), 400,
            "bad_request", path)


# --- словарь, база, бэкапы ---

def test_vocab(serve, world):
    client = serve()
    kinds = contract.check(client.get(f"{V1}/vocab/kind"), "/vocab/{scheme}")
    fact = next(k for k in kinds if k["code"] == "fact")
    assert (fact["family"], fact["pack"]) == ("source", "core") and fact["label"]["ru"]
    classes = contract.check(client.get(f"{V1}/vocab/entity_class"), "/vocab/{scheme}")
    assert "artifact" in [c["code"] for c in classes] and all("family" not in c for c in classes)
    assert contract.check(client.get(f"{V1}/vocab/no_such"), "/vocab/{scheme}") == []


def test_base(serve, world, pg):
    client = serve()
    body = contract.check(client.get(f"{V1}/base"), "/base")
    assert body["base_id"] == pg.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()[0]
    assert body["name"] is None and "core" in [p["name"] for p in body["packs"]]
    assert body["counts"] == {"atoms": 2, "entities": 3, "objects": 5, "links": 3} and body["review_open"] == 1
    db.set_base_name(pg, "Метеоплощадка")
    assert contract.check(client.get(f"{V1}/base"), "/base")["name"] == "Метеоплощадка"


def test_backups(serve, tmp_path):
    client = serve()
    assert contract.check(client.get(f"{V1}/backups"), "/backups") == []          # каталога ещё нет
    backups = tmp_path / "backups"
    backups.mkdir()
    for name, size in (("2026-11-05T08-00-00Z", 7), ("2026-11-06T08-00-00Z", 3)):
        (backups / f"{name}.dump").write_bytes(b"x" * size)
        (backups / f"{name}.json").write_text(json.dumps(
            {"kind": "amem.pg_dump", "format": 1, "file": f"{name}.dump", "size": size}), encoding="utf-8")
    body = contract.check(client.get(f"{V1}/backups"), "/backups")
    assert body == [{"name": "2026-11-05T08-00-00Z", "created_at": "2026-11-05T08:00:00+00:00", "size": 7},
                    {"name": "2026-11-06T08-00-00Z", "created_at": "2026-11-06T08:00:00+00:00", "size": 3}]
    assert str(tmp_path) not in json.dumps(body)                                  # пути наружу не отдаются
