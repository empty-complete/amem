"""Пути записи HTTP v1 (подпроект 4, часть 4a, задача 7): очередь проверки, submit, папки. Каждый ответ сверяется
со схемой контракта docs/api/http-v1.openapi.yaml; агент — только из сессии (cookie человека, токен, иначе модель);
ошибки 400/403/404/409/413/415/422. starlette.testclient на настоящей базе (PostgreSQL 18 и 16), порт не слушается."""
import json
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import pytest

import contract
from amem import api, check, db, folders, objects, records, review
from amem.check import Proposal
from amem.records import Item
from amem.service import http_v1
from conftest import FakeProvider
from test_service_core import tokens_file

PERSON = "person:ann"           # человек службы в тестах (USER=ann)
MODEL = "model:local"           # клиент без cookie и токена
BOT = "model:bot"               # другая модель — автор пакетов, которые решает model:local
V1 = "/api/v1"
MD = "Заметки/узел.md"
QUOTE = "Кронштейн КБ-14 крепится к закладной анкером М10."
NOTE2 = "Заметки/закладная.md"          # своя заметка записи с пунктом source_changed: её меняет фикстура queue
NOTE2_MD = "# Закладная\n\n## Бетон\n\nЗакладная бетонируется заранее.\n"
NOTE2_SOURCES = [{"path": NOTE2, "selectors": [{"type": "heading", "value": "Бетон"}],
                  "quote": "Закладная бетонируется заранее."}]
ORIGIN = "http://127.0.0.1:8767"
SECRET = "пароль от щита"


def problem(response, status: int, code: str, path: str, method: str = "get") -> dict:
    """Ответ-ошибка по контракту: статус описан, тело — Problem с этим code."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = contract.check(response, path, method)
    assert body["code"] == code, body
    return body


def fact(ref="@a", label="Кронштейн крепится к закладной анкером", **fields) -> dict:
    """Факт, который проходит уровни 1–4 ядра: подпись, пояснение, источник — раздел заметки с дословной цитатой."""
    return {"ref": ref, "kind": "fact", "label": {"ru": label},
            "summary_plain": {"ru": "Кронштейн держится на одном анкере."},
            "sources": [{"path": MD, "selectors": [{"type": "heading", "value": "Кронштейн"}], "quote": QUOTE}],
            **fields}


def batch(*payloads, **extra) -> dict:
    return {"proposals": [{"target": "atom", "payload": p} for p in payloads], **extra}


@pytest.fixture
def kb(pg, monkeypatch):
    monkeypatch.setenv("AMEM_BACKEND", "none")          # уровень 4 — только текст; тест провайдера включает сам
    monkeypatch.setattr(review, "AUDIT_RATE", 0.0)      # выборка аудита случайна по id ревизии — здесь её нет
    db.prepare(pg)
    return pg


@pytest.fixture
def start(serve, kb, docs):
    """Служба с папкой документов: start() — модель (без cookie), start(person=True) — человек (cookie своей
    страницы, как у интерфейса)."""
    def run(env=None, *, person=False, **kw):
        client = serve({"AMEM_DOCS": str(docs), **(env or {})}, **kw)
        if person:
            response = client.get(f"{V1}/session", headers={"Sec-Fetch-Site": "same-origin"})
            assert response.json()["agent"] == PERSON
        return client
    return run


def written(conn, store, docs, *payloads, agent=BOT, record_id=None) -> check.Submitted:
    """Пакет мимо службы — от другого агента (у службы агент только из сессии)."""
    result = check.submit(conn, store, docs, [Proposal("atom", p, record_id) for p in payloads], agent=agent)
    assert result.state == "approved", result.report["issues"]
    return result


def ref_of(result: check.Submitted, i: int = 0) -> str:
    return f"atm:{result.records[i]['record_id']}"


def queued(result: check.Submitted, reason: str) -> str:
    return next(str(q["id"]) for q in result.queued if q["reason"] == reason)


# --- submit ---

def post_submit(client, body):
    """POST /submit с телом, которое само проходит схему тела запроса в контракте (строго)."""
    contract.check_request(body, "/submit", "post")
    return client.post(f"{V1}/submit", json=body)


def test_contract_example_of_the_submit_body_passes_the_schema_and_the_service(start, kb):
    example = contract.example("/submit", "post")
    contract.check_request(example, "/submit", "post")
    body = contract.check(start(person=True).post(f"{V1}/submit", json=example), "/submit", "post")
    assert [r["label"] for r in body["records"]] == ["@node", "@bracket", "@anchor"]
    assert all(r["status"] == "verified" for r in body["records"]) and body["warnings"] == []
    assert kb.execute("SELECT count(*) FROM link WHERE rel = 'depends_on'").fetchone()[0] == 1


def test_submit_body_schema_is_strict():
    """Схема тела /submit: Proposal и LinkProposal — без лишних полей, target — atom или entity, связь — rel, src,
    dst обязательны, note — LangString; payload открыт."""
    good = batch(fact())
    contract.check_request(good | {"links": [{"rel": "depends_on", "src": "@a", "dst": "atm:bracket",
                                              "note": {"ru": "по замеру"}, "confidence": 0.5,
                                              "qualifiers": [{"property": "load_case", "value_text": "ветер"}]}]},
                           "/submit", "post")
    contract.check_request({"proposals": [{"target": "entity", "payload": {"любое": "тело"}, "record_id": None}]},
                           "/submit", "post")
    for bad in ({"proposals": []}, {"proposals": [{"target": "link", "payload": {}}]},
                {"proposals": [{"target": "atom"}]}, {"proposals": [{"target": "atom", "payload": {}, "agent": PERSON}]},
                {"proposals": [{"target": "atom", "payload": {}, "record_id": "atm:bracket"}]},
                good | {"links": [{"rel": "depends_on", "src": "@a"}]},
                good | {"links": [{"rel": "depends_on", "src": "@a", "dst": "bracket"}]},
                good | {"links": [{"rel": "depends_on", "src": "@a", "dst": "@b", "note": "строкой"}]},
                good | {"links": [{"rel": "depends_on", "src": "@a", "dst": "@b", "id": "x"}]},
                good | {"agent": PERSON}):
        with pytest.raises(AssertionError, match="не по контракту"):
            contract.check_request(bad, "/submit", "post")


def test_submit_by_the_model_goes_through_the_check(start, kb):
    client = start()
    body = contract.check(post_submit(client, batch(fact())), "/submit", "post")
    [rec] = body["records"]
    assert (rec["label"], rec["status"], rec["created"], rec["review_state"]) == ("@a", "draft", True, "none")
    assert rec["ref"] == f"atm:{rec['record_id']}" and uuid.UUID(rec["revision_id"])
    [item] = body["queued"]
    assert (item["reason"], item["ref"], item["label"]) == ("semantic", rec["ref"], "@a")
    assert body["complete"] is False and body["warnings"] == []
    assert body["report"]["format"] == "amem.check/1"
    agent = kb.execute("SELECT agent FROM changeset WHERE id = %s", (body["changeset_id"],)).fetchone()[0]
    assert agent == MODEL


def test_submit_by_the_person_is_verified(start):
    body = contract.check(post_submit(start(person=True), batch(fact())), "/submit", "post")
    assert body["records"][0]["status"] == "verified" and body["queued"] == [] and body["complete"] is True


def test_submit_ignores_the_agent_in_the_body(start, kb):
    """Агент — только из сессии: поле agent в теле пакета и в предложении не читается."""
    body = batch(fact(), agent=PERSON)
    body["proposals"][0]["agent"] = PERSON
    result = contract.check(start().post(f"{V1}/submit", json=body), "/submit", "post")
    assert result["records"][0]["status"] == "draft"                  # человек дал бы verified
    agents = kb.execute("SELECT DISTINCT agent FROM changeset").fetchall()
    assert agents == [(MODEL,)]


def test_submit_edit_and_links(start, kb, store, docs):
    """Правка существующей записи (record_id) и связь пакета по @именам."""
    first = written(kb, store, docs, fact(), agent=PERSON)
    client = start(person=True)
    edit = {"target": "atom", "payload": fact(label="Кронштейн крепится к закладной одним анкером"),
            "record_id": str(first.records[0]["record_id"])}
    second = {"target": "atom", "payload": fact("@b", label="Анкер М10 держит кронштейн КБ-14")}
    body = contract.check(post_submit(client, {
        "proposals": [edit, second], "links": [{"rel": "depends_on", "src": "@b", "dst": "@a"}],
        "reason": "уточнение"}), "/submit", "post")
    assert [r["created"] for r in body["records"]] == [True, True]
    assert body["records"][0]["ref"] == ref_of(first)
    assert kb.execute("SELECT count(*) FROM atom_revision WHERE atom_id = %s",
                      (first.records[0]["record_id"],)).fetchone()[0] == 2
    assert kb.execute("SELECT count(*) FROM link WHERE rel = 'depends_on'").fetchone()[0] == 1
    assert kb.execute("SELECT reason FROM changeset WHERE id = %s", (body["changeset_id"],)).fetchone()[0] == \
        "уточнение"


def test_submit_rejected_is_422_with_issues_that_have_ref_and_path(start, kb):
    response = post_submit(start(), batch(fact(sources=None) | {"sources": []}, {"ref": "@b", "kind": "fact"},
                                          {"kind": "fact", "label": {"ru": "Без имени"}}))
    body = problem(response, 422, "check_rejected", "/submit", "post")
    assert body["issues"] and all({"ref", "path", "code", "severity", "message"} == set(i) for i in body["issues"])
    assert {i["ref"] for i in body["issues"]} == {"@a", "@b", "proposals[2]"}      # без @имени — номер в теле
    label = next(i for i in body["issues"] if i["ref"] == "@b" and i["code"] == "schema")
    assert label["path"] == "label" and label["severity"] == "violation"
    assert "ошибок" in body["detail"] and body["warnings"] == []
    state = kb.execute("SELECT state FROM changeset WHERE id = %s", (body["changeset_id"],)).fetchone()[0]
    assert state == "rejected"
    assert kb.execute("SELECT count(*) FROM atom").fetchone()[0] == 0


def test_issue_of_the_whole_record_has_an_empty_path():
    assert api._issue({"code": "retired_record", "severity": "violation", "message": "m", "where": "@a",
                       "level": 1, "details": {}}) == {"code": "retired_record", "severity": "violation",
                                                       "message": "m", "ref": "@a", "path": ""}
    assert api._issue({"code": "schema", "severity": "violation", "message": "m", "level": 1, "details": {},
                       "where": "links[0]: rel"})["path"] == "rel"
    assert api._issue({"code": "schema", "severity": "violation", "message": "m", "level": 1, "details": {},
                       "where": "items[12]: label.ru"})["ref"] == "proposals[12]"


def test_submit_cuts_private_before_the_check_and_warns(start, kb):
    payload = fact(label=f"Кронштейн крепится анкером<private>{SECRET}</private>")
    payload["summary_plain"] = {"ru": f"Кронштейн держится на одном анкере. < Private >{SECRET}"}   # незакрытая
    second = fact("@b", label="Анкер М10 держит кронштейн КБ-14")
    third = fact(None, label="Анкер ставят в бетон", summary_plain={"ru": f"<private>{SECRET}</private>Бетон B25."})
    del third["ref"]
    body = contract.check(post_submit(start(), {
        "proposals": [{"target": "atom", "payload": p} for p in (payload, second, third)],
        "links": [{"rel": "depends_on", "src": "@b", "dst": "@a",
                   "note": {"ru": f"по <private>{SECRET}</private>замеру"}}],
        "reason": f"разбор <private>{SECRET}</private>"}), "/submit", "post")
    places = sorted((w["code"], w["ref"], w["path"]) for w in body["warnings"])
    assert places == [("private_removed", "", "reason"), ("private_removed", "@a", "label.ru"),
                      ("private_removed", "@a", "summary_plain.ru"), ("private_removed", "links[0]", "note.ru"),
                      ("private_removed", "proposals[2]", "summary_plain.ru")]
    assert [r["label"] for r in body["records"]] == ["@a", "@b", "proposals[2]"]
    assert all(w["severity"] == "warning" for w in body["warnings"])
    stored = json.dumps([row for row in kb.execute(
        "SELECT r.payload, cs.reason, cs.check_report FROM atom_revision r JOIN changeset cs ON cs.id = r.changeset_id"
    ).fetchall()], ensure_ascii=False, default=str)
    stored += json.dumps(kb.execute("SELECT note FROM link").fetchall(), ensure_ascii=False)
    assert SECRET not in stored and "Кронштейн крепится анкером" in stored


def test_rejected_batch_keeps_the_private_warning(start, kb):
    body = problem(start().post(f"{V1}/submit", json=batch({"ref": "@a", "kind": "fact",
                                                           "summary_plain": {"ru": f"<private>{SECRET}</private>"}})),
                   422, "check_rejected", "/submit", "post")
    assert [(w["code"], w["ref"], w["path"]) for w in body["warnings"]] == [("private_removed", "@a",
                                                                             "summary_plain.ru")]
    reports = json.dumps(kb.execute("SELECT check_report FROM changeset").fetchall(), ensure_ascii=False)
    assert SECRET not in reports


@pytest.mark.parametrize("body, word", [
    ({}, "proposals"),
    ({"proposals": []}, "proposals"),
    ({"proposals": {"target": "atom"}}, "proposals"),
    ({"proposals": ["atom"]}, "proposals[0]"),
    ({"proposals": [{"target": ["atom"], "payload": {}}]}, "target"),
    ({"proposals": [{"target": "atom", "payload": fact()}], "links": {}}, "links"),
    ({"proposals": [{"target": "atom", "payload": fact()}], "reason": 1}, "reason"),
    ({"proposals": [{"target": "atom", "payload": fact(label="а\x00б")}]}, "NUL"),
    ({"proposals": [{"target": "atom", "payload": {**fact(), "x\x00": 1}}]}, "NUL"),
    ({"proposals": [{"target": "atom", "payload": fact()}], "reason": "a\x00"}, "NUL"),
    ({"proposals": [{"target": "atom", "payload": {"deep": json.loads("[" * 70 + "]" * 70)}}]}, "вложенность"),
])
def test_submit_bad_bodies_are_400(start, kb, body, word):
    response = start().post(f"{V1}/submit", json=body)
    assert word in problem(response, 400, "bad_request", "/submit", "post")["detail"]
    assert kb.execute("SELECT count(*) FROM changeset").fetchone()[0] == 0          # до проверки и базы


@pytest.mark.parametrize("raw, word", [
    (b"", "тело"), (b"   ", "тело"), (b"[]", "объект"), (b"{", "не JSON"), (b'{"a": NaN}', "NaN"),
    (b'{"a": Infinity}', "Infinity"), (b"\xff\xfe{", "не JSON"), (b"[" * 100_000, "вложенность"),
])
def test_submit_body_that_is_not_a_json_object_is_400(start, raw, word):
    response = start().post(f"{V1}/submit", content=raw, headers={"Content-Type": "application/json"})
    assert word in problem(response, 400, "bad_request", "/submit", "post")["detail"]


def test_body_over_the_limit_is_413_without_trusting_content_length(start, kb):
    client = start()
    big = json.dumps(batch(fact(), pad="x" * http_v1.BODY_LIMIT)).encode()
    problem(client.post(f"{V1}/submit", content=big, headers={"Content-Type": "application/json"}), 413,
            "too_large", "/submit", "post")

    def chunks():                                      # без Content-Length: Transfer-Encoding: chunked
        for i in range(0, len(big), 65536):
            yield big[i:i + 65536]

    response = client.post(f"{V1}/submit", content=chunks(), headers={"Content-Type": "application/json"})
    assert "content-length" not in response.request.headers
    problem(response, 413, "too_large", "/submit", "post")
    assert kb.execute("SELECT count(*) FROM changeset").fetchone()[0] == 0
    # тело чуть меньше предела проходит предел: дальше — разбор (нет proposals)
    near = json.dumps({"pad": "x" * (http_v1.BODY_LIMIT - 100)}).encode()
    problem(client.post(f"{V1}/submit", content=near, headers={"Content-Type": "application/json"}), 400,
            "bad_request", "/submit", "post")


def test_body_limit_counts_the_bytes_not_the_header(start):
    """Content-Length меньше тела: служба считает пришедшие байты сама (ASGI отдаёт тело кусками), а не заголовок."""
    import anyio

    app = start().app
    big = b'{"pad": "' + b"x" * (2 * http_v1.BODY_LIMIT) + b'"}'
    step = 65536
    messages = [{"type": "http.request", "body": big[i:i + step], "more_body": i + step < len(big)}
                for i in range(0, len(big), step)]
    sent = []

    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
             "path": f"{V1}/submit", "raw_path": f"{V1}/submit".encode(), "query_string": b"", "root_path": "",
             "headers": [(b"host", b"127.0.0.1:8767"), (b"content-type", b"application/json"),
                         (b"content-length", b"10")], "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 8767),
             "state": {}}
    anyio.run(app, scope, receive, send)
    assert next(m for m in sent if m["type"] == "http.response.start")["status"] == 413
    assert messages, "тело дочитано до конца, хотя предел уже превышен"


def test_submit_without_documents_folder_gives_source_unresolved(serve, kb):
    client = serve()                                    # AMEM_DOCS не задан
    body = problem(client.post(f"{V1}/submit", json=batch(fact())), 422, "check_rejected", "/submit", "post")
    issue = next(i for i in body["issues"] if i["code"] == "source_unresolved")
    assert (issue["ref"], issue["path"]) == ("@a", "sources[0]") and "AMEM_DOCS" in issue["message"]


def test_submit_with_a_provider_of_another_model_degrades_level_4(start, kb, monkeypatch):
    """Активная модель базы — одна, provider службы — другой: дубли ищутся только текстом, запись идёт (не 503)."""
    monkeypatch.delenv("AMEM_BACKEND")
    from amem import embed
    fake = FakeProvider()
    model = embed.register_model(kb, fake)
    embed.activate_model(kb, model["id"])

    class Other(FakeProvider):
        name = "other-text"

    body = contract.check(start(provider=Other()).post(f"{V1}/submit", json=batch(fact())), "/submit", "post")
    assert body["report"]["degraded"] == [{"level": 4, "channel": "vector", "reason": "provider_error"}]


# --- папки ---

def test_create_folder(start, kb):
    client = start(person=True)
    response = client.post(f"{V1}/folders", json={"path": " Проекты / Ветер и снег "})
    assert response.status_code == 201
    body = contract.check(response, "/folders", "post")
    assert body == {"path": "Проекты/Ветер и снег", "name": "Ветер и снег", "count": 0, "children": []}
    tree = contract.check(client.get(f"{V1}/folders"), "/folders")
    projects = next(f for f in tree["folders"] if f["path"] == "Проекты")
    assert [c["path"] for c in projects["children"]] == ["Проекты/Ветер и снег"]
    created_by = kb.execute("SELECT created_by FROM folder WHERE path = 'Проекты/Ветер и снег'").fetchone()[0]
    assert created_by == PERSON
    problem(client.post(f"{V1}/folders", json={"path": "Проекты/Ветер и снег"}), 409, "folder_exists", "/folders",
            "post")
    problem(client.post(f"{V1}/folders", json={"path": "Проекты"}), 409, "folder_exists", "/folders", "post")
    for bad in ("a/../b", "-", "a//b", "", "a/" * 9 + "b", "a​b"):
        problem(client.post(f"{V1}/folders", json={"path": bad}), 422, "folder_invalid", "/folders", "post")
    for body in ({}, {"path": None}, {"path": 1}, {"path": ["a"]}, {"path": "a\x00b"}):
        problem(client.post(f"{V1}/folders", json=body), 400, "bad_request", "/folders", "post")


def test_folder_structure_is_changed_only_by_the_person(start, kb):
    """Модель раскладывает записи, но папки не создаёт, не удаляет и не переименовывает: 403 forbidden."""
    folders.create(kb, "Ресурсы/Каталоги", agent=PERSON)
    client = start()
    for response, path, method in (
            (client.post(f"{V1}/folders", json={"path": "Модель"}), "/folders", "post"),
            (client.delete(f"{V1}/folders/{quote('Ресурсы/Каталоги', safe='')}"), "/folders/{path}", "delete"),
            (client.patch(f"{V1}/folders/Ресурсы", json={"path": "Ресурсы2"}), "/folders/{path}", "patch")):
        assert "только человек" in problem(response, 403, "forbidden", path, method)["detail"]
    assert kb.execute("SELECT count(*) FROM folder WHERE path IN ('Модель', 'Ресурсы2')").fetchone()[0] == 0
    assert kb.execute("SELECT count(*) FROM folder WHERE path = 'Ресурсы/Каталоги'").fetchone()[0] == 1
    with pytest.raises(api.Forbidden):                  # операция напрямую — тот же отказ (MCP, CLI)
        api.folder_create(kb, "Модель", agent=BOT)


@pytest.mark.parametrize("path", ["Ресурсы/Каталоги", "Проекты/Ветер и снег", "Архив/2026 год/Отчёты № 1",
                                  "Области/Ёлки + палки #1?", "Проекты/日本語", "Проекты/Ёлка"])
def test_delete_folder_by_its_encoded_path(start, kb, path):
    """{path} — путь целиком в encodeURIComponent: «/» внутри — %2F, пробелы, «+», «#», «?» и юникод (и не в NFC)
    после раскодирования — как в реестре. Знак «%» в имени здесь не проверить: TestClient раскодирует путь дважды
    (uvicorn — один раз, как и положено)."""
    folders.create(kb, path, agent=PERSON)
    client = start(person=True)
    response = client.delete(f"{V1}/folders/{quote(path, safe='')}")
    assert response.status_code == 204 and response.content == b""
    contract.check(response, "/folders/{path}", "delete")
    assert kb.execute("SELECT count(*) FROM folder WHERE path = %s", (folders.check(path),)).fetchone()[0] == 0
    parent = path.rsplit("/", 1)[0]
    assert kb.execute("SELECT count(*) FROM folder WHERE path = %s", (parent,)).fetchone()[0] == 1


def test_delete_folder_errors(start, kb, store, docs):
    folders.create(kb, "Ресурсы/Каталоги", agent=PERSON)
    result = written(kb, store, docs, fact(), agent=PERSON)
    folders.move(kb, ref_of(result), "Проекты/Ветер", agent=PERSON)
    client = start(person=True)
    problem(client.delete(f"{V1}/folders/{quote('Ресурсы', safe='')}"), 409, "folder_not_empty", "/folders/{path}",
            "delete")                                                       # вложенная папка
    problem(client.delete(f"{V1}/folders/{quote('Проекты/Ветер', safe='')}"), 409, "folder_not_empty",
            "/folders/{path}", "delete")                                    # запись
    problem(client.delete(f"{V1}/folders/{quote('Нет такой', safe='')}"), 404, "folder_not_found",
            "/folders/{path}", "delete")
    problem(client.delete(f"{V1}/folders/a%2F..%2Fb"), 422, "folder_invalid", "/folders/{path}", "delete")
    problem(client.delete(f"{V1}/folders/a%00b"), 400, "bad_request", "/folders/{path}", "delete")
    # без кодирования «/» путь тот же: маршрут {path:path} берёт хвост пути целиком
    assert client.delete(f"{V1}/folders/Ресурсы/Каталоги").status_code == 204


def test_rename_folder(start, kb, store, docs):
    folders.create(kb, "Проекты/Ветер/Замеры", agent=PERSON)
    result = written(kb, store, docs, fact(), agent=PERSON)
    folders.move(kb, ref_of(result), "Проекты/Ветер", agent=PERSON)
    client = start(person=True)
    response = client.patch(f"{V1}/folders/{quote('Проекты/Ветер', safe='')}", json={"path": "Архив/Ветер 2026"})
    body = contract.check(response, "/folders/{path}", "patch")
    assert body == {"from": "Проекты/Ветер", "to": "Архив/Ветер 2026", "folders": 2, "records": 1}
    record_id = result.records[0]["record_id"]
    assert kb.execute("SELECT folder FROM atom WHERE id = %s", (record_id,)).fetchone()[0] == "Архив/Ветер 2026"
    log = kb.execute("SELECT folder_from, folder_to, agent FROM folder_log WHERE record_id = %s ORDER BY changed_at",
                     (record_id,)).fetchall()
    assert log[-1] == ("Проекты/Ветер", "Архив/Ветер 2026", PERSON)
    assert kb.execute("SELECT count(*) FROM atom_revision WHERE atom_id = %s", (record_id,)).fetchone()[0] == 1
    paths = {row[0] for row in kb.execute("SELECT path FROM folder")}
    assert "Архив/Ветер 2026/Замеры" in paths and "Проекты/Ветер" not in paths

    problem(client.patch(f"{V1}/folders/{quote('Архив/Ветер 2026', safe='')}", json={"path": "Проекты"}), 409,
            "folder_exists", "/folders/{path}", "patch")
    problem(client.patch(f"{V1}/folders/{quote('Нет такой', safe='')}", json={"path": "Другая"}), 404,
            "folder_not_found", "/folders/{path}", "patch")
    problem(client.patch(f"{V1}/folders/Архив", json={"path": "Архив/Внутри"}), 422, "folder_invalid",
            "/folders/{path}", "patch")
    problem(client.patch(f"{V1}/folders/Архив", json={"path": "a/../b"}), 422, "folder_invalid", "/folders/{path}",
            "patch")
    for body in ({}, {"path": None}, {"path": 2}, {"folder": "Другая"}):
        problem(client.patch(f"{V1}/folders/Архив", json=body), 400, "bad_request", "/folders/{path}", "patch")


def test_move_record_to_a_folder(start, kb, store, docs):
    """Переносить вправе и модель; ответ — RecordSummary, ревизии нет; null — без папки."""
    result = written(kb, store, docs, fact(key="bracket"), agent=PERSON)
    ref, record_id = ref_of(result), result.records[0]["record_id"]
    folders.create(kb, "Проекты/Кронштейны", agent=PERSON)            # модель переносит только в существующую
    model = start()
    body = contract.check(model.patch(f"{V1}/records/{ref}/folder", json={"folder": "Проекты/Кронштейны"}),
                          "/records/{ref}/folder", "patch")
    assert (body["ref"], body["folder"], body["status"], body["kind_or_class"]) == (ref, "Проекты/Кронштейны",
                                                                                     "verified", "fact")
    assert (body["label"], body["agent"]) == ("Кронштейн крепится к закладной анкером", PERSON)
    log = kb.execute("SELECT folder_from, folder_to, agent FROM folder_log WHERE record_id = %s",
                     (record_id,)).fetchall()
    assert log == [(None, "Проекты/Кронштейны", MODEL)]
    assert kb.execute("SELECT count(*) FROM atom_revision WHERE atom_id = %s", (record_id,)).fetchone()[0] == 1
    person = start(person=True)
    by_key = contract.check(person.patch(f"{V1}/records/atm:bracket/folder", json={"folder": None}),
                            "/records/{ref}/folder", "patch")
    assert by_key["ref"] == ref and by_key["folder"] is None
    assert contract.check(person.get(f"{V1}/folders"), "/folders")["unfiled"] == 1

    problem(person.patch(f"{V1}/records/{ref}/folder", json={}), 400, "bad_request", "/records/{ref}/folder", "patch")
    problem(person.patch(f"{V1}/records/{ref}/folder", json={"folder": 1}), 400, "bad_request",
            "/records/{ref}/folder", "patch")
    problem(person.patch(f"{V1}/records/{ref}/folder", json={"folder": "-"}), 422, "folder_invalid",
            "/records/{ref}/folder", "patch")
    problem(person.patch(f"{V1}/records/{ref}/folder", json={"folder": "a/../b"}), 422, "folder_invalid",
            "/records/{ref}/folder", "patch")
    problem(person.patch(f"{V1}/records/atm:no_such/folder", json={"folder": "a"}), 404, "not_found",
            "/records/{ref}/folder", "patch")
    problem(person.patch(f"{V1}/records/bracket/folder", json={"folder": "a"}), 400, "bad_request",
            "/records/{ref}/folder", "patch")


# --- очередь: список, пункт, статистика ---

@pytest.fixture
def queue(kb, store, docs):
    """Пункты разных причин: semantic (пакет модели bot), edit (правка моделью записи человека), imported
    (расхождение с подборкой; у той же записи — source_changed: новая версия её заметки), audit (вручную)."""
    by_bot = written(kb, store, docs, fact("@s", label="Анкер ставят в бетон класса B25"), agent=BOT)
    by_person = written(kb, store, docs, fact(key="bracket"), agent=PERSON)
    edit = written(kb, store, docs, fact(label="Кронштейн крепится к закладной двумя анкерами"), agent=BOT,
                   record_id=by_person.records[0]["record_id"])
    (docs / NOTE2).write_text(NOTE2_MD, encoding="utf-8")
    other = written(kb, store, docs, fact("@i", label="Закладная бетонируется заранее", sources=NOTE2_SOURCES),
                    agent=PERSON)
    other_id = other.records[0]["record_id"]
    body = objects.resolve_sources(kb, store, docs, fact("@i", label="Закладная бетонируется до монтажа",
                                                         sources=NOTE2_SOURCES), agent=BOT)
    pending = records.commit(kb, [Item("atom", body, other_id, review_state="pending")], agent=BOT).revisions[0]
    with kb.transaction():
        imported = review.insert_item(kb, "atom", other_id, pending.revision_id, "imported", changeset_id=None,
                                      details={"bundle": "подборка 1"}, agent=PERSON,
                                      at=datetime.now(timezone.utc))["id"]
    (docs / NOTE2).write_text(NOTE2_MD + "\nДобавлено: бетон класса B25.\n", encoding="utf-8")
    note = objects.ingest(kb, store, docs, NOTE2, agent=PERSON)
    changed = kb.execute("SELECT id FROM review_item WHERE reason = 'source_changed' AND record_id = %s",
                         (other_id,)).fetchone()[0]
    audit = review.enqueue(kb, ref_of(by_bot), "audit", agent=PERSON, note="выборочно")
    return {"semantic": queued(by_bot, "semantic"), "edit": queued(edit, "edit"), "imported": str(imported),
            "source_changed": str(changed), "audit": str(audit), "semantic_ref": ref_of(by_bot),
            "edited": ref_of(by_person), "other": ref_of(other), "note": note,
            "proposed": edit.records[0]["revision_id"]}


def test_review_items(start, queue):
    client = start()

    def listed(**params):
        return contract.check(client.get(f"{V1}/review/items", params=params), "/review/items")

    every = listed()
    assert {queue[r] for r in ("semantic", "edit", "imported", "source_changed", "audit")} <= {i["id"] for i in every}
    semantic = next(i for i in every if i["id"] == queue["semantic"])
    assert (semantic["ref"], semantic["label"], semantic["kind_or_class"], semantic["author"]) == \
        (queue["semantic_ref"], "Анкер ставят в бетон класса B25", "fact", BOT)
    assert [i["id"] for i in listed(reason="edit")] == [queue["edit"]]
    assert {i["reason"] for i in listed(record=queue["semantic_ref"])} == {"semantic", "audit"}
    assert [i["reason"] for i in listed(record="atm:bracket")] == ["edit"]
    assert [i["reason"] for i in listed(record=queue["semantic_ref"].removeprefix("atm:"), reason="audit")] == \
        ["audit"]
    assert all(i["state"] == "queued" for i in listed(state="queued"))
    assert listed(state="done") == []
    assert len(listed(limit=2)) == 2
    for params in ({"state": "open"}, {"reason": "любая"}, {"limit": "0"}, {"limit": "501"}, {"record": "bracket"},
                   {"record": "a\x00"}):
        problem(client.get(f"{V1}/review/items", params=params), 400, "bad_request", "/review/items")
    problem(client.get(f"{V1}/review/items", params={"record": "atm:no_such"}), 404, "not_found", "/review/items")


def test_review_items_know_document_and_about(start, queue, kb):
    """Список очереди сразу знает документ пункта (первый источник ревизии) и о ком запись — для группировки
    очереди по документам в веб-UI; без запроса на каждый пункт."""
    every = contract.check(start().get(f"{V1}/review/items"), "/review/items")
    assert all("source" in i and "about" in i for i in every)
    semantic = next(i for i in every if i["id"] == queue["semantic"])
    obj = kb.execute("SELECT o.id, o.original_name FROM source s JOIN object o ON o.id = s.object_id "
                     "JOIN atom_current a ON a.id = s.atom_revision_id WHERE a.atom_id = %s ORDER BY s.position LIMIT 1",
                     (queue["semantic_ref"].removeprefix("atm:"),)).fetchone()
    assert semantic["source"] == {"object": str(obj[0]), "object_name": obj[1] or str(obj[0])}
    assert semantic["about"] == []
    # один пункт по ссылке — без полей списка: их несёт только список очереди
    single = contract.check(start().get(f"{V1}/review/items/{queue['semantic']}"), "/review/items/{id}")
    assert "source" not in single["item"]


def test_review_item_edit_has_current_and_proposed(start, queue):
    body = contract.check(start().get(f"{V1}/review/items/{queue['edit']}"), "/review/items/{id}")
    assert (body["item"]["id"], body["item"]["reason"]) == (queue["edit"], "edit")
    assert body["record"]["ref"] == queue["edited"] and body["record"]["revision"] == 1      # текущая — первая
    contract.component("RecordView", body["record"])
    current, proposed = body["current"], body["proposed"]
    assert (current["revision"], current["review_state"], current["agent"]) == (1, "none", PERSON)
    assert (proposed["revision"], proposed["review_state"], proposed["agent"]) == (2, "pending", BOT)
    assert proposed["payload"]["label"] == {"ru": "Кронштейн крепится к закладной двумя анкерами"}
    assert {"path": "/label/ru", "before": "Кронштейн крепится к закладной анкером",
            "after": "Кронштейн крепится к закладной двумя анкерами"} in proposed["changes"]
    assert body["versions"] is None


def test_review_item_imported_and_source_changed(start, queue):
    client = start()
    imported = contract.check(client.get(f"{V1}/review/items/{queue['imported']}"), "/review/items/{id}")
    assert imported["current"]["revision"] == 1 and imported["proposed"]["revision"] == 2
    assert "/label/ru" in [change["path"] for change in imported["proposed"]["changes"]]
    assert imported["item"]["details"] == {"bundle": "подборка 1"}
    changed = contract.check(client.get(f"{V1}/review/items/{queue['source_changed']}"), "/review/items/{id}")
    assert changed["current"] is None and changed["proposed"] is None
    assert changed["versions"] == {"objects": [{"object": str(queue["note"].object_id),
                                                "object_name": "закладная.md", "from": [1], "to": 2}]}
    audit = contract.check(client.get(f"{V1}/review/items/{queue['audit']}"), "/review/items/{id}")
    assert (audit["current"], audit["proposed"], audit["versions"]) == (None, None, None)


def test_review_item_errors(start, queue):
    client = start()
    problem(client.get(f"{V1}/review/items/{uuid.uuid4()}"), 404, "not_found", "/review/items/{id}")
    problem(client.get(f"{V1}/review/items/не-uuid"), 400, "bad_request", "/review/items/{id}")
    problem(client.get(f"{V1}/review/items/%00"), 400, "bad_request", "/review/items/{id}")


def test_review_stats(start, queue):
    client = start()
    body = contract.check(client.get(f"{V1}/review/stats"), "/review/stats")
    assert body["days"] == 7 and body["queue"]["semantic"]["queued"] >= 1
    assert body["records"]["atoms"]["verified"] >= 1 and "unchecked" in body["verdicts"]
    assert body["changesets"]["approved"] >= 1 and set(body) == {"now", "days", "queue", "done", "changesets",
                                                                 "records", "verdicts", "audit"}
    assert contract.check(client.get(f"{V1}/review/stats", params={"days": "1"}), "/review/stats")["days"] == 1
    for days in ("0", "36501", "неделя", "1.5"):
        problem(client.get(f"{V1}/review/stats", params={"days": days}), 400, "bad_request", "/review/stats")


# --- очередь: решение и ручная постановка ---

def resolve(client, item, **body):
    return client.post(f"{V1}/review/items/{item}/resolve", json=body)


def test_person_resolves_and_the_second_answer_is_409(start, queue, kb):
    client = start(person=True)
    body = contract.check(resolve(client, queue["semantic"], outcome="confirmed", note="сверено"),
                          "/review/items/{id}/resolve", "post")
    assert body["status"] == "verified" and body["queued"] == [] and uuid.UUID(body["verification_id"])
    agent = kb.execute("SELECT agent, note FROM verification WHERE id = %s", (body["verification_id"],)).fetchone()
    assert agent == (PERSON, "сверено")
    again = problem(resolve(client, queue["semantic"], outcome="refuted"), 409, "review_closed",
                    "/review/items/{id}/resolve", "post")
    assert again["by"] == PERSON and datetime.fromisoformat(again["at"]) and PERSON in again["detail"]


def test_person_decides_the_edit(start, queue, kb):
    body = contract.check(resolve(start(person=True), queue["edit"], outcome="confirmed"),
                          "/review/items/{id}/resolve", "post")
    assert body["status"] == "verified"
    current = kb.execute("SELECT n FROM atom_current WHERE atom_id = %s",
                         (queue["edited"].removeprefix("atm:"),)).fetchone()[0]
    assert current == 2


def test_model_resolves_only_semantic_with_confidence(start, queue, kb):
    """Модель решает только semantic, не свой пакет и с уверенностью; остальное — 403 или 400 (библиотека)."""
    model = start()
    problem(resolve(model, queue["semantic"], outcome="confirmed"), 400, "review_bad", "/review/items/{id}/resolve",
            "post")                                                       # без confidence
    problem(resolve(model, queue["audit"], outcome="confirmed", confidence=0.9), 403, "review_forbidden",
            "/review/items/{id}/resolve", "post")
    problem(resolve(model, queue["edit"], outcome="confirmed", confidence=0.9), 403, "review_forbidden",
            "/review/items/{id}/resolve", "post")
    body = contract.check(resolve(model, queue["semantic"], outcome="confirmed", confidence=0.95),
                          "/review/items/{id}/resolve", "post")
    assert body["status"] == "auto_verified"
    method = kb.execute("SELECT method, agent, confidence FROM verification WHERE id = %s",
                        (body["verification_id"],)).fetchone()
    assert method == ("llm_judge", MODEL, 0.95)
    # свой пакет модель не подтверждает
    own = contract.check(model.post(f"{V1}/submit", json=batch(fact("@o", label="Шаг анкеров 200 мм"))), "/submit",
                         "post")
    item = next(q["id"] for q in own["queued"] if q["reason"] == "semantic")
    problem(resolve(model, item, outcome="confirmed", confidence=0.95), 403, "review_forbidden",
            "/review/items/{id}/resolve", "post")


def test_model_doubt_goes_to_the_person(start, queue):
    body = contract.check(resolve(start(), queue["semantic"], outcome="uncertain", confidence=0.4),
                          "/review/items/{id}/resolve", "post")
    assert body["status"] == "needs_review" and len(body["queued"]) == 1


def test_item_claimed_by_another_is_403(start, queue, kb):
    [claimed] = review.claim(kb, agent="model:judge", reasons=["semantic"])
    assert str(claimed["id"]) == queue["semantic"]
    problem(resolve(start(person=True), queue["semantic"], outcome="confirmed"), 403, "review_forbidden",
            "/review/items/{id}/resolve", "post")


@pytest.mark.parametrize("body, status, code", [
    ({}, 400, "bad_request"),
    ({"outcome": ""}, 400, "bad_request"),
    ({"outcome": "maybe"}, 400, "bad_request"),
    ({"outcome": 1}, 400, "bad_request"),
    ({"outcome": "partial"}, 400, "review_bad"),                 # человеку недоступен
    ({"outcome": "confirmed", "confidence": 2}, 400, "bad_request"),
    ({"outcome": "confirmed", "confidence": "высокая"}, 400, "bad_request"),
    ({"outcome": "confirmed", "confidence": True}, 400, "bad_request"),
    ({"outcome": "confirmed", "note": 5}, 400, "bad_request"),
    ({"outcome": "confirmed", "note": "a\x00"}, 400, "bad_request"),
])
def test_resolve_bad_bodies(start, queue, body, status, code):
    problem(resolve(start(person=True), queue["semantic"], **body), status, code, "/review/items/{id}/resolve",
            "post")


def test_resolve_unknown_or_bad_item(start, queue):
    client = start(person=True)
    problem(resolve(client, uuid.uuid4(), outcome="confirmed"), 404, "not_found", "/review/items/{id}/resolve", "post")
    problem(resolve(client, "не-uuid", outcome="confirmed"), 400, "bad_request", "/review/items/{id}/resolve", "post")


def test_enqueue(start, queue, kb):
    client = start(person=True)
    body = contract.check(client.post(f"{V1}/review/enqueue", json={"ref": queue["edited"], "reason": "calibration",
                                                                    "note": "эталон"}), "/review/enqueue", "post")
    item = kb.execute("SELECT reason, created_by, details FROM review_item WHERE id = %s",
                      (body["item_id"],)).fetchone()
    assert item == ("calibration", PERSON, {"note": "эталон"})
    again = contract.check(client.post(f"{V1}/review/enqueue", json={"ref": "atm:bracket", "reason": "calibration"}),
                           "/review/enqueue", "post")
    assert again == body                                         # открытый пункт той же причины не дублируется
    problem(start().post(f"{V1}/review/enqueue", json={"ref": queue["edited"], "reason": "audit"}), 403,
            "review_forbidden", "/review/enqueue", "post")      # ставит только человек
    for bad in ({"ref": queue["edited"]}, {"ref": queue["edited"], "reason": "semantic"},
                {"ref": "bracket", "reason": "audit"}, {"reason": "audit"},
                {"ref": queue["edited"], "reason": "audit", "note": ["x"]}):
        problem(client.post(f"{V1}/review/enqueue", json=bad), 400, "bad_request", "/review/enqueue", "post")
    problem(client.post(f"{V1}/review/enqueue", json={"ref": "atm:no_such", "reason": "audit"}), 404, "not_found",
            "/review/enqueue", "post")


# --- защита и права на всех путях записи ---

def write_requests(client, queue):
    """Каждый путь записи с годным телом: (ответ, путь контракта, метод)."""
    return [
        (client.post(f"{V1}/submit", json=batch(fact("@w", label="Шаг анкеров 250 мм"))), "/submit", "post"),
        (client.post(f"{V1}/folders", json={"path": "Новая"}), "/folders", "post"),
        (client.patch(f"{V1}/folders/{quote('Новая', safe='')}", json={"path": "Новая 2"}), "/folders/{path}",
         "patch"),
        (client.delete(f"{V1}/folders/{quote('Новая 2', safe='')}"), "/folders/{path}", "delete"),
        (client.patch(f"{V1}/records/{queue['edited']}/folder", json={"folder": "Проекты"}), "/records/{ref}/folder",
         "patch"),
        (client.post(f"{V1}/review/enqueue", json={"ref": queue["other"], "reason": "audit"}), "/review/enqueue",
         "post"),
        (resolve(client, queue["semantic"], outcome="confirmed"), "/review/items/{id}/resolve", "post"),
    ]


def test_read_only_token_cannot_write(start, queue, tmp_path, kb):
    path = tokens_file(tmp_path, ("t-read", "person:anna", False), ("t-write", "person:anna", True))
    client = start({"AMEM_TOKENS": path})
    client.headers["Authorization"] = "Bearer t-read"
    for response, route, method in write_requests(client, queue):
        problem(response, 403, "read_only", route, method)
    assert contract.check(client.get(f"{V1}/review/items"), "/review/items")         # читать можно
    client.headers["Authorization"] = "Bearer t-write"
    for response, route, method in write_requests(client, queue):
        assert response.status_code in (200, 201, 204), (route, response.text)
        contract.check(response, route, method)
    assert kb.execute("SELECT agent FROM verification WHERE review_item_id = %s",
                      (queue["semantic"],)).fetchone()[0] == "person:anna"
    del client.headers["Authorization"]
    problem(client.post(f"{V1}/folders", json={"path": "Без входа"}), 401, "auth_required", "/folders", "post")


def test_model_token_writes_through_the_check(start, queue, tmp_path):
    path = tokens_file(tmp_path, ("t-bot", "model:helper", True))
    client = start({"AMEM_TOKENS": path})
    client.headers["Authorization"] = "Bearer t-bot"
    body = contract.check(client.post(f"{V1}/submit", json=batch(fact("@h", label="Шаг анкеров 300 мм"))),
                          "/submit", "post")
    assert body["records"][0]["status"] == "draft"
    problem(client.post(f"{V1}/folders", json={"path": "Бот"}), 403, "forbidden", "/folders", "post")


def test_writes_take_only_json_from_own_origin(start, queue):
    client = start(person=True)
    for route, method, url in (("/submit", "post", f"{V1}/submit"), ("/folders", "post", f"{V1}/folders"),
                               ("/folders/{path}", "patch", f"{V1}/folders/a"),
                               ("/records/{ref}/folder", "patch", f"{V1}/records/{queue['edited']}/folder"),
                               ("/review/enqueue", "post", f"{V1}/review/enqueue"),
                               ("/review/items/{id}/resolve", "post", f"{V1}/review/items/{queue['audit']}/resolve")):
        problem(client.request(method.upper(), url, content=b'{"path": "a"}', headers={"Content-Type": "text/plain"}),
                415, "unsupported_media_type", route, method)
        problem(client.request(method.upper(), url, json={"path": "a"}, headers={"Origin": "http://evil.example"}),
                403, "bad_origin", route, method)
    problem(client.delete(f"{V1}/folders/a", headers={"Origin": "http://evil.example"}), 403, "bad_origin",
            "/folders/{path}", "delete")
    # своя страница с Origin службы проходит защиту
    response = client.post(f"{V1}/folders", json={"path": "Своя"}, headers={"Origin": ORIGIN})
    assert response.status_code == 201
    response = client.delete(f"{V1}/folders/{quote('Своя', safe='')}", headers={"Origin": ORIGIN})
    assert response.status_code == 204


def test_other_methods_on_write_paths_are_405(start):
    client = start(person=True)
    for method, url in (("GET", f"{V1}/submit"), ("GET", f"{V1}/folders/a"), ("PUT", f"{V1}/folders/a"),
                        ("GET", f"{V1}/review/items/{uuid.uuid4()}/resolve"), ("GET", f"{V1}/review/enqueue"),
                        ("POST", f"{V1}/review/stats")):
        response = client.request(method, url, json={} if method != "GET" else None)
        assert response.status_code == 405, (method, url, response.text)


# --- библиотека для путей записи ---

def test_lookup_summary_is_a_row_of_the_record_list(kb, store, docs):
    from amem import lookup
    result = written(kb, store, docs, fact(key="bracket"), agent=PERSON)
    ref = ref_of(result)
    folders.move(kb, ref, "Проекты", agent=PERSON)
    [row] = lookup.list_records(kb)["items"]
    assert lookup.summary(kb, ref) == row == lookup.summary(kb, "atm:bracket")
    with pytest.raises(records.RecordNotFound):
        lookup.summary(kb, "atm:no_such")


def test_review_item_by_id(kb, queue):
    row = review.item(kb, queue["edit"])
    assert row == next(r for r in review.items(kb, reason="edit"))
    assert str(row["revision_id"]) == str(queue["proposed"])
    with pytest.raises(review.ReviewError) as e:
        review.item(kb, uuid.uuid4())
    assert e.value.code == "not_found"
    with pytest.raises(review.ReviewError) as e:
        review.item(kb, "не-uuid")
    assert e.value.code == "invalid"


def test_submit_on_semantic_error(kb, store, docs, monkeypatch):
    """check.submit: при skip отказ явного провайдера ослабляет уровень 4; при raise (по умолчанию) — наружу."""
    from amem import embed
    monkeypatch.delenv("AMEM_BACKEND")
    model = embed.register_model(kb, FakeProvider())
    embed.activate_model(kb, model["id"])

    class Other(FakeProvider):
        name = "other-text"

    with pytest.raises(embed.EmbeddingError):
        check.submit(kb, store, docs, [Proposal("atom", fact())], agent=BOT, provider=Other())
    result = check.submit(kb, store, docs, [Proposal("atom", fact())], agent=BOT, provider=Other(),
                          on_semantic_error="skip")
    assert result.state == "approved" and result.report["degraded"][0]["reason"] == "provider_error"
    with pytest.raises(ValueError, match="on_semantic_error"):
        check.submit(kb, store, docs, [Proposal("atom", {})], agent=BOT, on_semantic_error="ignore")


def test_submit_without_documents_folder(kb, store):
    result = check.submit(kb, store, None, [Proposal("atom", fact())], agent=BOT)
    assert result.state == "rejected"
    [issue] = [i for i in result.report["issues"] if i["code"] == "source_unresolved"]
    assert issue["where"] == "@a: sources[0]" and "AMEM_DOCS" in issue["message"]


# --- по ревью задачи 7 ---

@pytest.mark.parametrize("key", ["<private>X</private>", "a < PRIVATE >b", "</private>", "<\nprivate\n>"])
def test_private_tag_in_a_key_is_400_without_the_key(start, kb, key):
    """Скрытое в имени поля не вырезать, не сломав тело: ключ с меткой <private> — 400 до проверки; в ответе
    только путь до родителя, самого ключа нет."""
    table = fact()
    table["content"] = {"table": {"rows": [[{key: 1}]]}}
    extra = {**fact("@b", label="Анкер М10 держит кронштейн КБ-14"), key: SECRET}
    client = start()
    for payload, place in ((table, "proposals[0].payload.content.table.rows[0][0]"), (extra, "proposals[0].payload")):
        body = problem(client.post(f"{V1}/submit", json=batch(payload)), 400, "bad_request", "/submit", "post")
        assert place in body["detail"] and "X" not in body["detail"] and SECRET not in body["detail"]
        assert "private" not in body["detail"].replace("<private>", "")
    link = batch(fact()) | {"links": [{"rel": "depends_on", "src": "@a", "dst": "@a", key: 1}]}
    problem(client.post(f"{V1}/submit", json=link), 400, "bad_request", "/submit", "post")
    assert kb.execute("SELECT count(*) FROM changeset").fetchone()[0] == 0
    assert kb.execute("SELECT count(*) FROM atom_revision").fetchone()[0] == 0


def test_model_moves_records_only_into_existing_folders(start, kb, store, docs):
    """Перенос записи моделью не создаёт папок: нет такой — 404 folder_not_found, реестр прежний; человек — создаёт."""
    result = written(kb, store, docs, fact(), agent=PERSON)
    ref = ref_of(result)
    before = kb.execute("SELECT count(*) FROM folder").fetchone()[0]
    model = start()
    body = problem(model.patch(f"{V1}/records/{ref}/folder", json={"folder": "model/made/this"}), 404,
                   "folder_not_found", "/records/{ref}/folder", "patch")
    assert "человек" in body["detail"]
    assert kb.execute("SELECT count(*) FROM folder").fetchone()[0] == before
    assert kb.execute("SELECT folder FROM atom WHERE id = %s", (result.records[0]["record_id"],)).fetchone()[0] is None
    problem(model.patch(f"{V1}/records/{ref}/folder", json={"folder": "a/../b"}), 422, "folder_invalid",
            "/records/{ref}/folder", "patch")
    # папка, которая видна только по записям в ней (не в реестре), — тоже существующая
    other = written(kb, store, docs, fact("@b", label="Анкер М10 держит кронштейн КБ-14"), agent=PERSON)
    kb.execute("UPDATE atom SET folder = 'Склад' WHERE id = %s", (other.records[0]["record_id"],))
    assert contract.check(model.patch(f"{V1}/records/{ref}/folder", json={"folder": "Склад"}),
                          "/records/{ref}/folder", "patch")["folder"] == "Склад"
    assert contract.check(model.patch(f"{V1}/records/{ref}/folder", json={"folder": "Проекты"}),
                          "/records/{ref}/folder", "patch")["folder"] == "Проекты"
    assert contract.check(model.patch(f"{V1}/records/{ref}/folder", json={"folder": None}),
                          "/records/{ref}/folder", "patch")["folder"] is None
    person = start(person=True)
    assert contract.check(person.patch(f"{V1}/records/{ref}/folder", json={"folder": "Новая/Вложенная"}),
                          "/records/{ref}/folder", "patch")["folder"] == "Новая/Вложенная"
    with pytest.raises(folders.FolderError) as e:          # операция напрямую — тот же отказ (MCP, CLI)
        api.record_folder(kb, ref, "model/made/this", agent=BOT)
    assert e.value.code == "not_found"


def test_report_of_the_answer_names_proposals_like_records(start):
    """report ответа 200: where замечаний и label записей — proposals[i]/links[i], как в records и 422."""
    unnamed = fact(None)
    del unnamed["ref"]
    twin = dict(unnamed)
    body = contract.check(start().post(f"{V1}/submit", json=batch(unnamed, twin)), "/submit", "post")
    assert [r["label"] for r in body["report"]["records"]] == ["proposals[0]", "proposals[1]"]
    assert body["report"]["issues"], "у двойника пачки — замечание дубля"
    assert all(not i["where"].startswith("items[") for i in body["report"]["issues"])
    assert any(i["where"].startswith("proposals[1]") for i in body["report"]["issues"])


def test_private_is_cut_from_review_notes(start, queue, kb):
    client = start(person=True)
    item = contract.check(client.post(f"{V1}/review/enqueue", json={
        "ref": queue["edited"], "reason": "calibration", "note": f"эталон<private>{SECRET}</private>"}),
        "/review/enqueue", "post")["item_id"]
    assert kb.execute("SELECT details FROM review_item WHERE id = %s", (item,)).fetchone()[0] == {"note": "эталон"}
    done = contract.check(resolve(client, queue["semantic"], outcome="confirmed", note=f"<private>{SECRET}"),
                          "/review/items/{id}/resolve", "post")
    assert kb.execute("SELECT note FROM verification WHERE id = %s", (done["verification_id"],)).fetchone()[0] is None
    stored = json.dumps(kb.execute("SELECT details FROM review_item").fetchall(), ensure_ascii=False)
    assert SECRET not in stored


def test_private_marked():
    from amem import private
    assert private.marked("a <Private> b") and private.marked("</ private >") and not private.marked("privat")
    assert not private.marked(1)
