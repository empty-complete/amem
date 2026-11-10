"""MCP (подпроект 4, часть 4b, задача 11): инструменты amem_* через клиент SDK на настоящей базе (PostgreSQL 18 и 16).

Клиент SDK в памяти процесса (Client(server): протокол 2026-07-28 и, mode="legacy", рукопожатие initialize) — над
StdioRuntime, как у `amem mcp`; /mcp службы — сырым JSON-RPC через starlette.testclient (Host, Origin, токены, агент)
и клиентом SDK поверх ASGI (две сессии — две задачи); `python -m amem.cli mcp` — подпроцессом.
"""
import contextlib
import json
import logging
import os
import re
import sys
from pathlib import Path

import anyio
import httpx2
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.client.streamable_http import streamable_http_client

from amem import folders, service, settings
from amem.service import mcp
from test_service_core import tokens_file
from test_service_write import fact, queued, written

pytest_plugins = ["test_service_write", "test_cli"]     # фикстуры kb, env, run, base

AGENT = "model:claude-code"
PERSON = "person:ann"
SECRET = "ghp_" + "a1B2" * 9                  # форма токена GitHub (private.secret_like)
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@contextlib.asynccontextmanager
async def connect(environ, agent=AGENT, mode="auto"):
    """Клиент SDK в памяти к серверу amem над своим пулом и своей задачей сессии (как отдельный amem mcp)."""
    with mcp.open_stdio(settings.load(environ), agent=agent) as runtime:
        async with Client(mcp.build(runtime), mode=mode) as client:
            yield client


async def call(client, name, **arguments):
    """Вызов инструмента: (ошибка?, structured_content)."""
    result = await client.call_tool(name, arguments)
    return result.is_error, result.structured_content


def sync(fn):
    """Тело теста — корутина без аргументов; anyio.run на asyncio."""
    anyio.run(fn)


# --- инструменты ---

@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_tools_list_matches_spec(env, kb, mode):
    async def main():
        async with connect(env, mode=mode) as client:
            tools = (await client.list_tools()).tools
        assert {t.name for t in tools} == set(mcp.TOOLS)
        assert len(mcp.TOOLS) == 18
        for tool in tools:
            assert tool.description and len(tool.description) < 400, tool.name
        hints = {t.name: t.annotations.read_only_hint for t in tools}
        assert hints["amem_search"] and hints["amem_get"] and not hints["amem_submit"] and not hints["amem_move"]
        idempotent = {t.name for t in tools if t.annotations.idempotent_hint}
        assert idempotent == {"amem_move", "amem_helpful", "amem_mark_object", "amem_task_release", "amem_task_done"}
        assert hints["amem_tasks"] and not hints["amem_task_claim"] and not hints["amem_task_done"]
        mark = next(t for t in tools if t.name == "amem_mark_object")
        assert "хранилище" in mark.description
        schema = {t.name: t.input_schema for t in tools}
        assert schema["amem_search"]["required"] == ["query"]
        assert schema["amem_review_resolve"]["required"] == ["item", "outcome", "confidence"]
    sync(main)


def test_search_in_three_steps_and_query_log(env, base, tmp_path):
    async def main():
        async with connect(env) as client:
            err, found = await call(client, "amem_search", query="кронштейн")
            assert not err, found
            assert found["retrieval_id"] and found["items"]
            assert set(found["items"][0]) == {"ref", "label", "kind", "status", "snippet"}
            ref = next(i["ref"] for i in found["items"] if i["ref"] == base["@bracket"])

            err, around = await call(client, "amem_timeline", ref=ref)
            assert not err and around["record"]["ref"] == ref and around["events"]
            assert [link["rel"] for link in around["links"]] == ["depends_on"]

            err, full = await call(client, "amem_get", refs=[ref, base["@node"]])
            assert not err
            first, node = full["records"]
            assert first["ref"] == ref and first["payload"]["kind"] == "fact" and first["sources"]
            assert node["target"] == "entity"

            err, card = await call(client, "amem_card", ref="Узел крепления")    # текст с явным лидером
            assert not err and card["entity"]["ref"] == base["@node"]

            err, similar = await call(client, "amem_similar", ref=ref)
            assert not err and "retrieval_id" in similar
            err, both = await call(client, "amem_similar", ref=ref, query="анкер")
            assert err and both["code"] == "bad_request"

            err, vocab = await call(client, "amem_vocab", scheme="kind")
            assert not err and "fact" in {e["code"] for e in vocab["entries"]}
            err, body = await call(client, "amem_vocab", scheme="нет_такой")
            assert err and body["code"] == "bad_request" and "kind" in body["detail"]
    sync(main)
    lines = [json.loads(line) for line in (tmp_path / "state" / "queries.jsonl").read_text().splitlines()]
    assert [(l["recipe"], l["agent"]) for l in lines] == [("exact_fact", AGENT), ("similar", AGENT)]
    assert lines[0]["query"] == "кронштейн" and lines[0]["retrieval_id"]


def test_query_log_strips_private_and_turns_off(env, base, tmp_path):
    """<private> не попадает в журнал MCP; AMEM_QUERY_LOG=off — журнала нет."""
    path = tmp_path / "state" / "queries.jsonl"

    async def search(environ):
        async with connect(environ) as client:
            err, found = await call(client, "amem_search", query="кронштейн <private>скрытое</private>")
            assert not err, found
            err, found = await call(client, "amem_similar", query="анкер <private>скрытое</private>")
            assert not err, found

    sync(lambda: search({**env, "AMEM_QUERY_LOG": "off"}))
    assert not path.exists()
    sync(lambda: search(env))
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [l["recipe"] for l in lines] == ["exact_fact", "similar"]
    assert "скрытое" not in path.read_text() and "private" not in path.read_text()


def test_helpful_only_for_own_session(env, base, kb):
    async def main():
        async with connect(env) as mine, connect(env, agent="model:other") as other:
            _, found = await call(mine, "amem_search", query="кронштейн")
            rid = found["retrieval_id"]
            atom = next(i["ref"] for i in found["items"] if i["ref"].startswith("atm:"))

            err, body = await call(other, "amem_helpful", retrieval_id=rid, refs=[atom])
            assert err and body["code"] == "forbidden" and body["status"] == 403
            assert "не из этой сессии" in body["detail"]
            err, body = await call(mine, "amem_helpful", retrieval_id=rid, refs=[atom])
            assert not err and body == {"retrieval_id": rid, "marked": [atom]}
            err, body = await call(mine, "amem_helpful", retrieval_id=rid, refs=["atm:019a0000-0000-7000-8000-0000"
                                                                                   "00000000"])
            assert err and "не входит в эту выдачу" in body["detail"]
            err, body = await call(mine, "amem_helpful", retrieval_id="не-uuid", refs=[atom])
            assert err and body["code"] == "bad_request"
    sync(main)
    agent, = kb.execute("SELECT agent FROM atom_use").fetchone()
    assert agent == AGENT
    labels = {r[0] for r in kb.execute("SELECT label FROM activity WHERE kind = 'session'")}
    assert len(labels) == 2 and all(label.startswith("mcp:stdio:") for label in labels)


def test_bad_arguments_and_unknown_tool_answer_problem(env, kb):
    """Отказы SDK до инструмента — в той же форме, что прочие ошибки: isError и problem+json bad_request."""
    async def main():
        async with connect(env) as client:
            for name, arguments, word in [("amem_search", {}, "query"),
                                          ("amem_search", {"query": "анкер", "limit": "много"}, "limit"),
                                          ("amem_review_resolve", {"item": "x", "outcome": "confirmed"}, "confidence"),
                                          ("amem_nope", {}, "amem_nope")]:
                result = await client.call_tool(name, arguments)
                assert result.is_error, (name, arguments)
                body = result.structured_content
                assert body["code"] == "bad_request" and body["status"] == 400, body
                assert word in body["detail"] and result.content[0].text.startswith("bad_request:")
    sync(main)


def test_building_server_leaves_root_logger_alone(dsn, tmp_path):
    """MCPServer зовёт logging.basicConfig — у службы корневой логгер после create_app без новых обработчиков."""
    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    root.handlers.clear()                    # у pytest свои обработчики: без них basicConfig сработал бы
    try:
        service.create_app(settings.load({"AMEM_DSN": dsn, "HOME": str(tmp_path / "home"), "USER": "ann"}))
        assert root.handlers == [] and root.level == level
    finally:
        root.handlers[:] = saved


def test_submit_as_model_with_private_and_secret_warnings(env, kb):
    payload = fact(label="Кронштейн крепится к закладной анкером <private>по договору</private>")
    payload["summary_plain"] = {"ru": f"Кронштейн держится на одном анкере; ключ {SECRET}"}

    async def main():
        async with connect(env) as client:
            err, done = await call(client, "amem_submit", proposals=[{"target": "atom", "payload": payload}],
                                   reason="разбор заметки")
            assert not err, done
            assert {w["code"] for w in done["warnings"]} == {"private_removed", "secret_like"}
            assert SECRET not in json.dumps(done["warnings"])
            assert done["records"][0]["ref"].startswith("atm:")
            return done
    done = anyio.run(main)
    agent, activity = kb.execute("SELECT agent, activity FROM changeset WHERE id = %s",
                                 (done["changeset_id"],)).fetchone()
    assert agent == AGENT and activity is not None
    assert "по договору" not in json.dumps(
        kb.execute("SELECT payload FROM atom_revision").fetchone()[0], ensure_ascii=False)

    async def rejected():                # отказ проверки — ошибка с отчётом
        async with connect(env) as client:
            result = await client.call_tool("amem_submit", {"proposals": [{"target": "atom",
                                                                           "payload": {"ref": "@x", "kind": "fact"}}]})
            assert result.is_error and result.structured_content["code"] == "check_rejected"
            assert result.structured_content["issues"] and "check_rejected:" in result.content[0].text
    sync(rejected)


def test_person_agent_is_refused(env, kb, run):
    with pytest.raises(ValueError, match="model:"):
        with mcp.open_stdio(settings.load(env), agent=PERSON):
            pass
    code, _, err = run("mcp", "--agent", PERSON)
    assert code == 2 and "model:" in err
    code, _, err = run("mcp", extra={"AMEM_DSN": None})
    assert code == 1 and "AMEM_DSN" in err


def test_move_to_existing_folder_only(env, base, kb):
    folders.create(kb, "Проекты/Альфа", agent=PERSON)

    async def main():
        async with connect(env) as client:
            err, moved = await call(client, "amem_move", ref=base["@bracket"], folder="Проекты/Альфа")
            assert not err and moved["folder"] == "Проекты/Альфа" and moved["ref"] == base["@bracket"]
            err, body = await call(client, "amem_move", ref=base["@bracket"], folder="Проекты/Новая")
            assert err and body["code"] == "folder_not_found"
            err, moved = await call(client, "amem_move", ref=base["@bracket"], folder=None)
            assert not err and moved.get("folder") is None
    sync(main)
    assert kb.execute("SELECT count(*) FROM folder WHERE path = 'Проекты/Новая'").fetchone()[0] == 0


def test_review_claim_release_resolve_semantic(env, kb, store, docs):
    by_bot = written(kb, store, docs, fact(label="Анкер ставят в бетон класса B25"))
    item = queued(by_bot, "semantic")

    async def main():
        async with connect(env, agent="model:judge") as judge, connect(env, agent="model:other") as other:
            err, got = await call(judge, "amem_review_claim", reasons=["semantic"])
            assert not err and [i["id"] for i in got["items"]] == [item]
            assert got["items"][0]["claimed_by"] == "model:judge" and got["items"][0]["sources"]
            err, body = await call(other, "amem_review_release", item=item)
            assert err and body["code"] == "review_forbidden"
            err, body = await call(judge, "amem_review_release", item=item)
            assert not err and body == {"id": item, "state": "queued"}

            err, got = await call(judge, "amem_review_claim")
            assert not err and [i["id"] for i in got["items"]] == [item]
            err, body = await call(judge, "amem_review_resolve", item=item, outcome="confirmed", confidence=0.95,
                                   note="цитата подтверждает")
            assert not err and body["status"] and body["verification_id"]
            err, body = await call(judge, "amem_review_resolve", item=item, outcome="refuted", confidence=0.9)
            assert err and body["code"] == "review_closed"
    sync(main)
    assert kb.execute("SELECT state FROM review_item WHERE id = %s", (item,)).fetchone()[0] == "done"


def test_ambiguous_text_answers_candidates_not_error(env, base):
    async def main():
        async with connect(env) as client:
            result = await client.call_tool("amem_get", {"refs": [base["@node"], "кронштейн"]})
            assert not result.is_error
            body = result.structured_content
            assert body["ambiguous"] is True and body["ref"] == "кронштейн"
            assert {c["ref"] for c in body["candidates"]} >= {base["@bracket"], base["@anchor"]}
            err, body = await call(client, "amem_timeline", ref="кронштейн")
            assert not err and body["ambiguous"] is True
            result = await client.call_tool("amem_timeline", {"ref": "atm:019a0000-0000-7000-8000-000000000000"})
            assert result.is_error and result.structured_content["code"] == "not_found"
            assert "amem_search" in result.content[0].text
    sync(main)


def test_object_status_and_mark(env, base, kb):
    async def main():
        async with connect(env) as client:
            err, status = await call(client, "amem_object_status", path="Заметки/узел.md")
            assert not err and status["object"].startswith("obj:") and status["status"] is None
            assert status["cited_by"] >= 1
            err, marked = await call(client, "amem_mark_object", path="Заметки/узел.md", status="parsed",
                                     note="всё <private>лишнее</private>")
            assert not err and marked["status"] == "parsed" and marked["agent"] == AGENT
            assert marked["note"].strip() == "всё" and "лишнее" not in marked["note"]
            err, status = await call(client, "amem_object_status", path="заметка.md")
            assert not err and status["object"] is None and status["status"] is None
            err, marked = await call(client, "amem_mark_object", path="заметка.md", status="skipped")
            assert not err and marked["status"] == "skipped" and marked["object"].startswith("obj:")
            err, body = await call(client, "amem_mark_object", path="заметка.md", status="done")
            assert err and body["code"] == "bad_request"
            err, body = await call(client, "amem_mark_object", path="нет/такого.md", status="parsed")
            assert err
    sync(main)


def test_task_from_http_claimed_and_done_through_mcp(http, env, kb, store, docs):
    """Задачу ставят по HTTP, модель берёт и закрывает её через MCP, GET /tasks видит done."""
    from amem import objects

    client = http()
    version = objects.ingest(kb, store, docs, "Заметки/узел.md", agent=PERSON)
    made = client.post("/api/v1/tasks", json={"kind": "parse", "object": str(version.object_id),
                                              "version": version.n, "note": "разобрать узел"})
    assert made.status_code == 202, made.text
    task_id = made.json()["task_id"]

    async def main():
        async with connect(env) as agent, connect(env, agent="model:other") as other:
            err, listed = await call(agent, "amem_tasks")
            assert not err and [t["id"] for t in listed["tasks"]] == [task_id]
            assert listed["tasks"][0]["state"] == "open" and listed["tasks"][0]["note"] == "разобрать узел"
            err, taken = await call(agent, "amem_task_claim", task=task_id)
            assert not err and taken["task"]["state"] == "claimed" and taken["task"]["claimed_by"] == AGENT
            err, body = await call(other, "amem_task_claim", task=task_id)
            assert err and body["code"] == "task_claimed" and body["status"] == 409
            err, none = await call(other, "amem_task_claim")
            assert not err and none == {"task": None}                            # свободных нет
            err, mine = await call(agent, "amem_tasks")
            assert not err and [t["id"] for t in mine["tasks"]] == [task_id]     # своя взятая — в списке
            err, foreign = await call(other, "amem_tasks")
            assert not err and foreign["tasks"] == []
            err, body = await call(other, "amem_task_release", task=task_id)
            assert err and body["code"] == "task_claimed"
            result = {"refs": ["atm:019a0000-0000-7000-8000-000000000001"], "note": "один атом"}
            err, closed = await call(agent, "amem_task_done", task=task_id, result=result)
            assert not err and closed["task"]["state"] == "done" and closed["task"]["result"] == result
            err, body = await call(agent, "amem_task_done", task=task_id)
            assert err and body["code"] == "task_closed"
            err, body = await call(agent, "amem_task_claim", task="не-uuid")
            assert err and body["code"] == "bad_request"
    sync(main)
    [view] = client.get("/api/v1/tasks").json()
    assert (view["id"], view["state"], view["claimed_by"]) == (task_id, "done", AGENT)


# --- /mcp службы ---

@pytest.fixture
def http(serve, kb, docs, tmp_path):
    """Служба с /mcp; post(body, session=None, **headers) — запрос JSON-RPC."""
    def start(env=None, **kw):
        client = serve({"AMEM_DOCS": str(docs), "AMEM_STATE": str(tmp_path / "state"), **(env or {})}, **kw)

        def post(body, session=None, **headers):
            extra = {**MCP_HEADERS, **({"Mcp-Session-Id": session} if session else {}), **headers}
            return client.post("/mcp", content=json.dumps(body), headers=extra)
        client.mcp = post
        return client
    return start


def _open(client, **headers) -> str:
    """initialize и initialized: id сессии SDK."""
    response = client.mcp(INIT, **headers)
    assert response.status_code == 200, response.text
    sid = response.headers["mcp-session-id"]
    note = client.mcp({"jsonrpc": "2.0", "method": "notifications/initialized"}, session=sid, **headers)
    assert note.status_code == 202, note.text
    return sid


def _tool(client, sid, name, arguments, **headers) -> dict:
    response = client.mcp({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                           "params": {"name": name, "arguments": arguments}}, session=sid, **headers)
    assert response.status_code == 200, response.text
    return response.json()["result"]


def test_http_mcp_is_guarded_by_host_origin_and_fetch_site(http):
    client = http()
    refused = client.mcp(INIT, Host="evil.example:8767")         # Host проверяет Guard, не SDK
    assert refused.status_code == 421 and refused.headers["content-type"].startswith("application/problem+json")
    assert refused.json()["code"] == "bad_host"
    assert client.mcp(INIT, Host="Localhost:8767").status_code == 200       # имя — без учёта регистра
    refused = client.mcp(INIT, Origin="http://evil.example")
    assert refused.status_code == 403 and refused.json()["code"] == "bad_origin"
    assert client.mcp(INIT, **{"Sec-Fetch-Site": "cross-site"}).status_code == 403
    stream = client.get("/mcp", headers={"Accept": "text/event-stream", "Sec-Fetch-Site": "cross-site"})
    assert stream.status_code == 403
    assert client.mcp(INIT, Origin="http://127.0.0.1:8767").status_code == 200       # свой источник
    sid = _open(client)
    tools = client.mcp({"jsonrpc": "2.0", "id": 3, "method": "tools/list"}, session=sid).json()["result"]["tools"]
    assert {t["name"] for t in tools} == set(mcp.TOOLS)


def test_http_mcp_agent_header_is_model_only(http, kb, docs):
    client = http()
    refused = client.mcp(INIT, **{"X-Amem-Agent": PERSON})
    assert refused.status_code == 400 and refused.json()["code"] == "bad_agent"
    sid = _open(client, **{"X-Amem-Agent": "model:installer"})
    body = {"proposals": [{"target": "atom", "payload": fact()}]}
    done = _tool(client, sid, "amem_submit", body, **{"X-Amem-Agent": "model:installer"})
    assert not done.get("isError"), done
    changeset = done["structuredContent"]["changeset_id"]
    assert kb.execute("SELECT agent FROM changeset WHERE id = %s", (changeset,)).fetchone()[0] == "model:installer"
    # cookie человека /mcp не делает человеком: без заголовка — AMEM_MODEL_AGENT
    client.get("/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"})
    sid = _open(client)
    done = _tool(client, sid, "amem_submit", {"proposals": [{"target": "atom", "payload": fact(
        label="Анкер ставят в бетон класса B25")}]})
    assert kb.execute("SELECT agent FROM changeset WHERE id = %s",
                      (done["structuredContent"]["changeset_id"],)).fetchone()[0] == "model:local"
    # сессия привязана к агенту, который её открыл: чужому SDK отвечает «сессии нет»
    taken = client.mcp({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "amem_search", "arguments": {"query": "анкер"}}}, session=sid, **{"X-Amem-Agent": "model:intruder"})
    assert taken.status_code == 404
    assert not _tool(client, sid, "amem_search", {"query": "анкер"}).get("isError")


def test_http_mcp_tokens_bearer_and_read_only(http, tmp_path):
    path = tokens_file(tmp_path, ("tok-write", "model:writer", True), ("tok-read", "person:vera", False))
    client = http({"AMEM_TOKENS": str(path)})
    assert client.mcp(INIT).status_code == 401
    assert client.mcp(INIT, Authorization="Bearer wrong").status_code == 401
    auth = {"Authorization": "Bearer tok-read"}
    sid = _open(client, **auth)
    found = _tool(client, sid, "amem_search", {"query": "анкер"}, **auth)
    assert not found.get("isError"), found
    refused = _tool(client, sid, "amem_submit", {"proposals": [{"target": "atom", "payload": fact()}]}, **auth)
    assert refused["isError"] and refused["structuredContent"]["code"] == "read_only"
    writer = {"Authorization": "Bearer tok-write"}
    # чужая сессия: другой токен с её id — 404 на любой метод, и DELETE её не закрывает
    other = client.mcp({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "amem_search", "arguments": {"query": "анкер"}}}, session=sid, **writer)
    assert other.status_code == 404
    assert client.mcp({"jsonrpc": "2.0", "id": 3, "method": "tools/list"}, session=sid, **writer).status_code == 404
    assert client.delete("/mcp", headers={"Mcp-Session-Id": sid, **writer}).status_code == 404
    listed = client.mcp({"jsonrpc": "2.0", "id": 4, "method": "tools/list"}, session=sid, **auth)
    assert listed.status_code == 200 and {t["name"] for t in listed.json()["result"]["tools"]} == set(mcp.TOOLS)
    assert client.delete("/mcp", headers={"Mcp-Session-Id": sid, **auth}).status_code == 200    # свой — закрывает
    assert client.mcp({"jsonrpc": "2.0", "id": 5, "method": "tools/list"}, session=sid, **auth).status_code == 404
    sid = _open(client, **writer)
    refused = client.mcp(INIT, **writer, **{"X-Amem-Agent": "model:someone"})
    assert refused.status_code == 403                                                  # токен выдан model:writer
    done = _tool(client, sid, "amem_submit", {"proposals": [{"target": "atom", "payload": fact()}]}, **writer)
    assert not done.get("isError"), done


def test_http_mcp_sessions_with_sdk_client(dsn, kb, store, docs, tmp_path):
    """Клиент SDK через ASGI: у двух сессий /mcp — свои задачи; выдачу чужой сессии helpful не отмечает. Клиент без
    сессии (2026-07-28): выдачу сверяют по агенту и входу, задача режется по простою."""
    environ = {"AMEM_DSN": dsn, "HOME": str(tmp_path / "home"), "USER": "ann", "AMEM_DATA": str(tmp_path / "objects"),
               "AMEM_STATE": str(tmp_path / "state"), "AMEM_DOCS": str(docs)}
    app = service.create_app(settings.load(environ))
    written(kb, store, docs, fact())
    seen = {}

    async def main():
        async with app.router.lifespan_context(app):
            def http_client(agent):
                return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:8767",
                                          headers={"X-Amem-Agent": agent})

            async with http_client("model:one") as h1, http_client("model:two") as h2:
                async with Client(streamable_http_client("http://127.0.0.1:8767/mcp", http_client=h1),
                                  mode="legacy") as one, \
                        Client(streamable_http_client("http://127.0.0.1:8767/mcp", http_client=h2),
                               mode="legacy") as two:
                    _, found = await call(one, "amem_search", query="кронштейн")
                    atom = found["items"][0]["ref"]
                    err, body = await call(two, "amem_helpful", retrieval_id=found["retrieval_id"], refs=[atom])
                    assert err and body["code"] == "forbidden" and "не из этой сессии" in body["detail"]
                    err, body = await call(one, "amem_helpful", retrieval_id=found["retrieval_id"], refs=[atom])
                    assert not err, body
                async with Client(streamable_http_client("http://127.0.0.1:8767/mcp", http_client=h1)) as modern, \
                        Client(streamable_http_client("http://127.0.0.1:8767/mcp", http_client=h2)) as stranger:
                    err, found = await call(modern, "amem_search", query="кронштейн")
                    assert not err and found["retrieval_id"]
                    rid, atom = found["retrieval_id"], found["items"][0]["ref"]
                    err, body = await call(stranger, "amem_helpful", retrieval_id=rid, refs=[atom])
                    assert err and body["code"] == "forbidden"                   # другой агент
                    runtime = app.state.mcp.runtime
                    started = runtime.clock()
                    runtime.clock = lambda: started + mcp.IDLE_CUT + 1           # полчаса тишины: задача разрезана
                    err, body = await call(modern, "amem_helpful", retrieval_id=rid, refs=[atom])
                    assert not err, body                                         # выдача своя — отметка проходит
                    err, again = await call(modern, "amem_search", query="кронштейн")
                    assert not err
                    seen.update(first=rid, again=again["retrieval_id"])
    sync(main)
    labels = sorted(r[0] for r in kb.execute("SELECT label FROM activity WHERE kind = 'session'"))
    assert len(labels) == 4 and all(label.startswith("mcp:http:") for label in labels)
    rows = kb.execute("SELECT a.label FROM retrieval r JOIN activity a ON a.id = r.activity "
                      "WHERE r.id::text = ANY(%s)", ([seen["first"], seen["again"]],)).fetchall()
    open_labels = {label for label, in rows}
    assert len(open_labels) == 2                                                 # после простоя — новая задача
    assert all(re.fullmatch(r"mcp:http:[0-9a-f]{24}:[0-9a-f]{32}", label) for label in open_labels)
    assert {r[0] for r in kb.execute("SELECT agent FROM atom_use")} == {"model:one"}
    used, = kb.execute("SELECT u.activity = r.activity FROM atom_use u JOIN retrieval r ON r.id = u.retrieval_id "
                       "WHERE r.id = %s", (seen["first"],)).fetchone()
    assert used                                                                  # отметка — в задаче выдачи


def test_open_client_task_is_cut_by_idle(dsn, tmp_path):
    """Клиент без сессии: та же метка задачи, пока он не молчит IDLE_CUT; другие вход или агент — свои метки."""
    runtime = mcp.ServiceRuntime(settings.load({"AMEM_DSN": dsn, "HOME": str(tmp_path / "home"), "USER": "ann"}))
    now = [1000.0]
    runtime.clock = lambda: now[0]
    first = runtime.open_label("p1")
    now[0] += mcp.IDLE_CUT - 1
    assert runtime.open_label("p1") == first                                    # тишина короче — та же задача
    now[0] += mcp.IDLE_CUT - 1
    assert runtime.open_label("p1") == first                                    # отсчёт — от последнего вызова
    now[0] += mcp.IDLE_CUT + 1
    second = runtime.open_label("p1")
    assert second != first and second.startswith(runtime.issued_to("p1")) and first.startswith(runtime.issued_to("p1"))
    assert not runtime.open_label("p2").startswith(runtime.issued_to("p1"))


# --- stdio ---

def test_stdio_subprocess_initialize_and_list_tools(env, base):
    environ = {**{k: v for k, v in os.environ.items() if not k.startswith(("AMEM_", "CLAUDECODE", "CODEX_"))},
               **env, "AMEM_BACKEND": "none",
               "PYTHONPATH": str(Path(mcp.__file__).resolve().parents[2])}     # код этого дерева, а не установленный
    params = StdioServerParameters(command=sys.executable, args=["-m", "amem.cli", "mcp", "--agent", "model:stdio"],
                                   env=environ)

    async def main():
        with anyio.fail_after(60):
            async with Client(params, mode="legacy") as client:
                tools = (await client.list_tools()).tools
                assert {t.name for t in tools} == set(mcp.TOOLS)
                err, found = await call(client, "amem_search", query="анкер М10")
                assert not err and found["items"]
    sync(main)
