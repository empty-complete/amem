"""Служба (подпроект 4, часть 4a, задача 9): полнота контракта (каждый путь docs/api/http-v1.openapi.yaml — маршрут
службы, лишних нет), запуск (python -m amemo.service, проверка открытости, --no-auth), адрес и AMEMO_ALLOWED_HOSTS,
таймауты (медленное тело — 408, statement_timeout у /graph — 503 timeout), предел места подборок владельца
(AMEMO_STATE_QUOTA — 507). starlette.testclient и настоящий uvicorn в подпроцессе — на настоящей базе (PostgreSQL 18
и 16)."""
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

import anyio
import pytest
from starlette.applications import Starlette
from starlette.routing import Route

import contract
from amemo import api, check, db, recipes, review, settings
from amemo.check import Proposal
from amemo.service import create_app, http_v1, server
from check_support import atom
from test_service_core import tokens_file

V1 = "/api/v1"
ORIGIN = "http://127.0.0.1:8767"
PERSON = "person:ann"
METHODS = ("get", "post", "put", "patch", "delete")
# пути контракта, которых в 4a ещё нет: часть D веба (шаблоны, «Мои виды», загрузка объектов, задачи агентам) —
# служба сделает их в 4d; сделанный путь убирается отсюда (тест ниже не даст забыть)
LATER_4D = frozenset({
    ("/objects", "get"), ("/objects", "post"),
    ("/templates", "get"),
    ("/packs/mine/templates/{code}", "put"), ("/packs/mine/templates/{code}", "delete"),
    ("/tasks", "get"), ("/tasks", "post"),
})
# маршруты службы вне контракта: сам контракт, живость, интерфейс (и /mcp — с частью 4b)
OUTSIDE = frozenset({
    ("/api/v1/openapi.json", "get"), ("/health", "get"), ("/mcp", "post"), ("/mcp", "get"), ("/mcp", "delete"),
    ("/", "get"), ("/ui", "get"), ("/ui/{path}", "get"),
})


def _app(tmp_path) -> Starlette:
    """Приложение без запуска (lifespan не идёт, база не нужна): только список маршрутов."""
    return create_app(settings.load({"AMEMO_DSN": "postgresql://unused/db", "HOME": str(tmp_path), "USER": "ann"}))


def _service_ops(app: Starlette) -> set[tuple[str, str]]:
    ops = set()
    for route in app.routes:
        assert isinstance(route, Route), route
        path = re.sub(r"\{(\w+)(:\w+)?\}", r"{\1}", route.path)      # {path:path} — как {path} в контракте
        ops |= {(path, method.lower()) for method in route.methods if method != "HEAD"}
    return ops


def _contract_ops() -> set[tuple[str, str]]:
    return {(path, method) for path, item in contract.spec()["paths"].items() for method in METHODS if method in item}


# --- полнота контракта ---

def test_every_contract_path_is_served(tmp_path):
    served = _service_ops(_app(tmp_path))
    missing = sorted(op for op in _contract_ops() - LATER_4D if (V1 + op[0], op[1]) not in served)
    assert missing == [], f"пути контракта без маршрута службы: {missing}"


def test_later_paths_are_in_contract_and_not_yet_served(tmp_path):
    """Список «будет в 4d» честный: каждый путь из него есть в контракте и ещё не сделан."""
    served = _service_ops(_app(tmp_path))
    assert LATER_4D <= _contract_ops(), sorted(LATER_4D - _contract_ops())
    done = sorted(op for op in LATER_4D if (V1 + op[0], op[1]) in served)
    assert done == [], f"уже сделаны — уберите из LATER_4D: {done}"


def test_no_routes_outside_contract(tmp_path):
    contract_ops = {(V1 + path, method) for path, method in _contract_ops()}
    extra = sorted(_service_ops(_app(tmp_path)) - contract_ops - OUTSIDE)
    assert extra == [], f"маршруты вне контракта: {extra}"


def test_service_does_not_answer_outside_contract(serve, pg):
    db.prepare(pg)
    client = serve()
    for path in (f"{V1}/unknown", f"{V1}/records/x/unknown", f"{V1}", "/api/v2/session", f"{V1}/objects"):
        response = client.get(path)
        assert response.status_code == 404, (path, response.text)
        assert response.headers["content-type"].startswith("application/problem+json")
        contract.component("Problem", response.json())
    wrong = client.delete(f"{V1}/records")
    assert wrong.status_code == 405 and wrong.json()["code"] == "method_not_allowed"
    assert client.get(f"{V1}/openapi.json").json()["paths"].keys() == contract.spec()["paths"].keys()


# --- запуск ---

class Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, app, **kw):
        self.calls.append((app, kw))


def _env(tmp_path, **extra) -> dict:
    return {"AMEMO_DSN": "postgresql://unused/db", "HOME": str(tmp_path / "home"), "USER": "ann", **extra}


def test_main_defaults_to_loopback_8767(tmp_path, capsys):
    runner = Runner()
    assert server.main([], env=_env(tmp_path), runner=runner) == 0
    (app, kw), = runner.calls
    assert isinstance(app, Starlette)
    assert (kw["host"], kw["port"]) == ("127.0.0.1", 8767)
    assert capsys.readouterr().err == ""


def test_main_arguments_beat_environment(tmp_path):
    runner = Runner()
    env = _env(tmp_path, AMEMO_HOST="127.0.0.2", AMEMO_PORT="9000")
    assert server.main(["--port", "9100"], env=env, runner=runner) == 0
    assert (runner.calls[0][1]["host"], runner.calls[0][1]["port"]) == ("127.0.0.2", 9100)
    assert server.main(["--host", "::1"], env=env, runner=runner) == 0
    assert runner.calls[1][1]["host"] == "::1"
    assert server.main(["--host", "localhost"], env=env, runner=runner) == 0


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "amemo"])
def test_main_refuses_open_host_without_tokens(tmp_path, capsys, host):
    runner = Runner()
    assert server.main(["--host", host], env=_env(tmp_path), runner=runner) == 2
    assert runner.calls == []
    err = capsys.readouterr().err
    assert "без входа" in err and "AMEMO_TOKENS" in err and "--no-auth" in err


def test_main_no_auth_warns_loudly(tmp_path, capsys):
    runner = Runner()
    assert server.main(["--host", "0.0.0.0", "--no-auth"], env=_env(tmp_path), runner=runner) == 0
    assert runner.calls[0][1]["host"] == "0.0.0.0"
    err = capsys.readouterr().err
    assert "ВНИМАНИЕ" in err and "БЕЗ ВХОДА" in err and "!" * 72 in err


def test_main_open_host_with_tokens(tmp_path, capsys):
    runner = Runner()
    env = _env(tmp_path, AMEMO_TOKENS=tokens_file(tmp_path, ("t", "person:anna", True)))
    assert server.main(["--host", "0.0.0.0"], env=env, runner=runner) == 0
    assert capsys.readouterr().err == ""
    assert server.main(["--host", "0.0.0.0", "--no-auth"], env=env, runner=runner) == 0
    assert "не действует" in capsys.readouterr().err


@pytest.mark.parametrize("argv, env, words", [
    (["--host", "amemo:8767"], {}, "без порта"),
    (["--host", "http://amemo"], {}, "без порта"),
    (["--port", "0"], {}, "от 1 до 65535"),
    ([], {"AMEMO_DSN": ""}, "AMEMO_DSN"),
    ([], {"AMEMO_ALLOWED_HOSTS": "amemo:8767"}, "без порта"),
    ([], {"AMEMO_STATE_QUOTA": "много"}, "AMEMO_STATE_QUOTA"),
])
def test_main_bad_settings_exit_2(tmp_path, capsys, argv, env, words):
    runner = Runner()
    assert server.main(argv, env={**_env(tmp_path), **env}, runner=runner) == 2
    assert runner.calls == []
    assert words in capsys.readouterr().err


def test_loopback():
    for host in ("127.0.0.1", "127.0.0.2", "::1", "[::1]", "localhost", "LOCALHOST"):
        assert server.loopback(host), host
    for host in ("0.0.0.0", "::", "10.0.0.1", "amemo", "localhost.example"):
        assert not server.loopback(host), host


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _child_env(tmp_path, **extra) -> dict:
    env = {key: value for key, value in os.environ.items() if not key.startswith("AMEMO_") and key != "PYTHONPATH"}
    return {**env, "HOME": str(tmp_path / "home"), "AMEMO_STATE": str(tmp_path / "state"),
            "AMEMO_DATA": str(tmp_path / "objects"), "AMEMO_BACKEND": "none", **extra}


def test_python_m_amemo_service_serves(dsn, tmp_path):
    """Настоящий uvicorn в подпроцессе: /health и /session по 127.0.0.1, затем остановка."""
    port = _free_port()
    child = subprocess.Popen([sys.executable, "-m", "amemo.service", "--port", str(port)],
                             env=_child_env(tmp_path, AMEMO_DSN=dsn), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        deadline, answer = time.monotonic() + 60, None
        while time.monotonic() < deadline and child.poll() is None:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                    answer = response.read()
                    break
            except OSError:
                time.sleep(0.2)
        assert answer == b"ok", child.stdout.read().decode() if child.poll() is not None else "служба не ответила"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{V1}/session", timeout=5) as response:
            body = json.loads(response.read())
        contract.component("Session", body)
        assert body["agent"] == "model:local" and body["can_write"] is True
    finally:
        child.terminate()
        child.wait(timeout=30)


def test_python_m_amemo_service_refuses_open_host(tmp_path):
    done = subprocess.run([sys.executable, "-m", "amemo.service", "--host", "0.0.0.0"], capture_output=True, text=True,
                          env=_child_env(tmp_path, AMEMO_DSN="postgresql://unused/db"), timeout=60)
    assert done.returncode == 2
    assert "AMEMO_TOKENS" in done.stderr and "--no-auth" in done.stderr


# --- адрес и AMEMO_ALLOWED_HOSTS ---

@pytest.mark.parametrize("value, host", [
    ("127.0.0.1", "127.0.0.1"), ("0.0.0.0", "0.0.0.0"), ("::1", "::1"), ("[::1]", "::1"), ("::", "::"),
    ("Localhost", "localhost"), ("amemo", "amemo"), ("amemo.internal", "amemo.internal"), (" 10.0.0.5 ", "10.0.0.5"),
])
def test_host_setting_accepts_address_or_name(tmp_path, value, host):
    assert settings.load({"HOME": str(tmp_path), "AMEMO_HOST": value}).host == host


@pytest.mark.parametrize("value", ["amemo:8767", "127.0.0.1:8767", "[::1]:8767", "http://amemo", "amemo/ui", "a b",
                                   "1.2.3", "-amemo", "amemo_db", "fe80::1%eth0", "[amemo]"])
def test_host_setting_rejects_port_scheme_and_garbage(tmp_path, value):
    with pytest.raises(settings.SettingsError, match="AMEMO_HOST"):
        settings.load({"HOME": str(tmp_path), "AMEMO_HOST": value})


def test_allowed_hosts_setting(tmp_path):
    base = {"HOME": str(tmp_path)}
    assert settings.load(base).allowed_hosts == ()
    assert settings.load({**base, "AMEMO_ALLOWED_HOSTS": "amemo, Amemo.Internal,,amemo"}).allowed_hosts == \
        ("amemo", "amemo.internal")
    config = tmp_path / "amemo.toml"
    config.write_text('allowed_hosts = ["amemo", "::1"]\nstate_quota = "2G"\n', encoding="utf-8")
    loaded = settings.load({**base, "AMEMO_CONFIG": str(config)})
    assert loaded.allowed_hosts == ("amemo", "::1") and loaded.state_quota == 2 << 30
    for bad in ("amemo:8767", "http://amemo", "a b"):
        with pytest.raises(settings.SettingsError, match="AMEMO_ALLOWED_HOSTS"):
            settings.load({**base, "AMEMO_ALLOWED_HOSTS": bad})


def test_guard_accepts_allowed_host_names(serve, pg):
    """compose: служба на 0.0.0.0, Host — имя службы в сети (amemo:8767); прочие имена — 421."""
    db.prepare(pg)
    client = serve({"AMEMO_ALLOWED_HOSTS": "amemo"}, host="0.0.0.0")
    for host in ("amemo:8767", "AMEMO", "amemo:80", "127.0.0.1:8767", "localhost"):
        assert client.get("/health", headers={"Host": host}).status_code == 200, host
    for host in ("evil:8767", "0.0.0.0:8767", "amemo.evil", "[::]:8767"):
        response = client.get("/health", headers={"Host": host})
        assert response.status_code == 421 and response.json()["code"] == "bad_host", host
    own = client.post(f"{V1}/folders", json={"path": "Проекты/Север"},
                      headers={"Host": "amemo:8767", "Origin": "http://amemo:8767"})
    # свой источник по имени службы: защита пропустила, отказ — уже по праву (папки создаёт человек)
    assert own.status_code == 403 and own.json()["code"] == "forbidden", own.text
    foreign = client.post(f"{V1}/folders", json={"path": "Проекты/Юг"},
                          headers={"Host": "amemo:8767", "Origin": "http://evil:8767"})
    assert foreign.status_code == 403 and foreign.json()["code"] == "bad_origin"
    plain = serve()                                              # без AMEMO_ALLOWED_HOSTS имя службы — чужое
    assert plain.get("/health", headers={"Host": "amemo:8767"}).status_code == 421


# --- таймауты ---

def _raw(client, method: str, path: str, headers: dict, receive) -> list[dict]:
    """Запрос прямо в ASGI-приложение в цикле событий клиента: тело отдаёт receive (медленный клиент)."""
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
             "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
             "headers": [(k.lower().encode(), v.encode()) for k, v in {"host": "127.0.0.1:8767", **headers}.items()],
             "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8767)}
    sent = []

    async def send(message):
        sent.append(message)

    async def call():
        with anyio.fail_after(20):
            await client.app(scope, receive, send)

    client.portal.call(call)
    return sent


def _answer(sent: list[dict]) -> tuple[int, dict, dict]:
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    headers = {k.decode(): v.decode() for k, v in start["headers"]}
    return start["status"], headers, json.loads(body)


def _stalls_after(first: bytes):
    """Тело: первый кусок, потом клиент молчит."""
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": first, "more_body": True}
        await anyio.sleep(60)
        return {"type": "http.disconnect"}
    return receive


def _trickles(piece: bytes):
    """Тело: по куску каждые 50 мс без конца — ни одной долгой паузы."""
    async def receive():
        await anyio.sleep(0.05)
        return {"type": "http.request", "body": piece, "more_body": True}
    return receive


def test_slow_json_body_408(serve, pg, monkeypatch):
    db.prepare(pg)
    client = serve()
    monkeypatch.setattr(http_v1, "BODY_IDLE", 0.3)
    headers = {"content-type": "application/json", "content-length": "100"}
    started = time.monotonic()
    status, out_headers, body = _answer(_raw(client, "POST", f"{V1}/submit", headers, _stalls_after(b'{"propo')))
    assert status == 408 and body["code"] == "body_timeout", body
    assert time.monotonic() - started < 5
    assert out_headers["connection"] == "close" and out_headers["content-type"].startswith("application/problem+json")
    contract.component("Problem", body)
    assert "без новых данных" in body["detail"]

    monkeypatch.setattr(http_v1, "BODY_TOTAL", 0.5)              # капает без пауз, но дольше общего предела
    status, _, body = _answer(_raw(client, "POST", f"{V1}/folders", {"content-type": "application/json"},
                                   _trickles(b" ")))
    assert status == 408 and body["code"] == "body_timeout" and "целиком" in body["detail"], body


def test_slow_upload_408_and_part_removed(serve, pg, monkeypatch, tmp_path):
    db.prepare(pg)
    state = tmp_path / "state"
    client = serve({"AMEMO_STATE": str(state)})
    monkeypatch.setattr(http_v1, "BODY_IDLE", 0.3)
    head = (b'--b\r\nContent-Disposition: form-data; name="file"; filename="x.zip"\r\n'
            b"Content-Type: application/zip\r\n\r\nPK\x03\x04")
    headers = {"content-type": "multipart/form-data; boundary=b", "origin": ORIGIN}
    status, _, body = _answer(_raw(client, "POST", f"{V1}/bundles/inspect", headers, _stalls_after(head)))
    assert status == 408 and body["code"] == "body_timeout", body
    assert [p.name for p in (state / "uploads").iterdir()] == []          # недокачанное удалено
    # загрузка без общего предела: капающий файл идёт дальше BODY_TOTAL
    monkeypatch.setattr(http_v1, "BODY_TOTAL", 0.01)
    monkeypatch.setattr(http_v1, "UPLOAD_LIMIT", 40)
    status, _, body = _answer(_raw(client, "POST", f"{V1}/bundles/inspect", headers, _trickles(head)))
    assert status == 413 and body["code"] == "too_large", body


def test_graph_statement_timeout_503(serve, pg, monkeypatch):
    db.prepare(pg)
    client = serve()
    seen, slow = [], {"on": True}
    overview, around = recipes.overview, recipes.around_entity

    def sleepy(real):
        def run(conn, *args, **kw):
            seen.append(conn.execute("SHOW statement_timeout").fetchone()[0])
            if slow["on"]:
                conn.execute("SELECT pg_sleep(3)")
            return real(conn, *args, **kw)
        return run

    monkeypatch.setattr(recipes, "overview", sleepy(overview))
    monkeypatch.setattr(recipes, "around_entity", sleepy(around))
    monkeypatch.setattr(http_v1, "HEAVY_TIMEOUT_MS", 300)
    started = time.monotonic()
    response = client.get(f"{V1}/graph")
    assert response.status_code == 503, response.text
    body = contract.check(response, "/graph")
    assert body["code"] == "timeout" and "limit" in body["detail"]
    assert time.monotonic() - started < 2.5
    assert seen == ["300ms"]
    slow["on"] = False
    assert client.get(f"{V1}/graph").status_code == 200
    with client.app.state.pool.connection() as conn:              # SET LOCAL не остался на соединении пула
        assert conn.execute("SHOW statement_timeout").fetchone()[0] == "0"
    monkeypatch.setattr(http_v1, "HEAVY_TIMEOUT_MS", 15_000)
    client.get(f"{V1}/graph", params={"ref": "ent:нет-такого"})
    assert seen[-1] == "15s"                                       # окрестность — под тем же пределом


# --- предел места подборок ---

@pytest.mark.parametrize("value, size", [
    (None, 10 << 30), ("1024", 1024), ("500M", 500 << 20), ("10G", 10 << 30), ("2GiB", 2 << 30), ("1t", 1 << 40),
    (" 7 k ", 7 << 10),
])
def test_state_quota_setting(tmp_path, value, size):
    env = {"HOME": str(tmp_path)} if value is None else {"HOME": str(tmp_path), "AMEMO_STATE_QUOTA": value}
    assert settings.load(env).state_quota == size


@pytest.mark.parametrize("value", ["0", "-1", "10X", "1.5G", "много"])
def test_state_quota_setting_rejects(tmp_path, value):
    with pytest.raises(settings.SettingsError, match="AMEMO_STATE_QUOTA"):
        settings.load({"HOME": str(tmp_path), "AMEMO_STATE_QUOTA": value})


@pytest.fixture
def kb(pg, monkeypatch, store, docs):
    monkeypatch.setenv("AMEMO_BACKEND", "none")
    monkeypatch.setattr(review, "AUDIT_RATE", 0.0)
    db.prepare(pg)
    made = check.submit(pg, store, docs, [
        Proposal("atom", atom("@a", kind="note", basis="author", sources=None, body={"ru": "Своё о кронштейне."})),
    ], agent=PERSON)
    assert made.state == "approved", made.report
    return pg


def _quota_problem(response, path: str) -> dict:
    assert response.status_code == 507, response.text
    body = contract.check(response, path, "post")
    assert body["code"] == "quota_exceeded" and "AMEMO_STATE_QUOTA" in body["detail"], body
    return body


def test_export_over_quota_507_per_owner(serve, kb, docs, tmp_path):
    state = tmp_path / "state"
    big = serve({"AMEMO_STATE": str(state), "AMEMO_DOCS": str(docs)})
    made = big.post(f"{V1}/bundles/export", json={"selection": {}})
    assert made.status_code == 200, made.text
    size = api.state_usage(state, "agent:model:local")
    assert size > 0
    # предел — полторы подборки: первая модели проходит (уже есть одна — вторая не влезает)
    client = serve({"AMEMO_STATE": str(state), "AMEMO_DOCS": str(docs), "AMEMO_STATE_QUOTA": str(size * 3 // 2)})
    _quota_problem(client.post(f"{V1}/bundles/export", json={"selection": {}}), "/bundles/export")
    assert len(list((state / "bundles").iterdir())) == 1              # сверх предела — удалена
    # у человека свой счёт: его подборка влезает
    person = client.get(f"{V1}/session", headers={"Sec-Fetch-Site": "same-origin"})
    assert person.json()["agent"] == PERSON
    assert client.post(f"{V1}/bundles/export", json={"selection": {}}).status_code == 200
    # предел занят целиком — отказ сразу, до экспорта
    tiny = serve({"AMEMO_STATE": str(state), "AMEMO_DOCS": str(docs), "AMEMO_STATE_QUOTA": "1"})
    _quota_problem(tiny.post(f"{V1}/bundles/export", json={"selection": {}}), "/bundles/export")
    assert len(list((state / "bundles").iterdir())) == 2


def test_upload_over_quota_507(serve, kb, docs, tmp_path):
    state = tmp_path / "state"
    big = serve({"AMEMO_STATE": str(state), "AMEMO_DOCS": str(docs)})
    made = big.post(f"{V1}/bundles/export", json={"selection": {}}).json()
    data = big.get(made["download"]).content
    other = tmp_path / "other"                     # загрузки — в другой папке состояния: подборка выше не мешает
    files = {"file": ("bundle.zip", data, "application/zip")}
    small = serve({"AMEMO_STATE": str(other), "AMEMO_STATE_QUOTA": str(len(data) // 2)})
    _quota_problem(small.post(f"{V1}/bundles/inspect", files=files, headers={"Origin": ORIGIN}), "/bundles/inspect")
    assert list((other / "uploads").iterdir()) == []                 # оборвано при приёме, .part удалён
    roomy = serve({"AMEMO_STATE": str(other), "AMEMO_STATE_QUOTA": str(len(data) * 20)})
    first = roomy.post(f"{V1}/bundles/inspect", files=files, headers={"Origin": ORIGIN})
    assert first.status_code == 200, first.text
    used = api.state_usage(other, "agent:model:local")             # распакованная загрузка с meta.json
    full = serve({"AMEMO_STATE": str(other), "AMEMO_STATE_QUOTA": str(used)})
    _quota_problem(full.post(f"{V1}/bundles/inspect", files=files, headers={"Origin": ORIGIN}), "/bundles/inspect")
    # zip принят, распакованная подборка в предел не влезла — удаляется после распаковки (api.upload_finish)
    third = tmp_path / "third"
    upload_id, part = api.upload_begin(third)
    part.write_bytes(data)
    with pytest.raises(api.QuotaExceeded, match="AMEMO_STATE_QUOTA"):
        api.upload_finish(third, upload_id, part, owner="agent:model:local", quota=1)
    assert list((third / "uploads").iterdir()) == []


def test_state_usage_counts_own_live_folders(tmp_path, monkeypatch):
    state = tmp_path / "state"

    def folder(kind, owner, size, created):
        bid = str(uuid.uuid4())
        path = state / kind / bid
        path.mkdir(parents=True)
        (path / "data").write_bytes(b"x" * size)
        if owner is not None:
            (path / "meta.json").write_text(json.dumps({"owner": owner, "created_at": created}), encoding="utf-8")
        return path

    now = time.time()
    monkeypatch.setattr(api, "_now", lambda: now)
    folder("bundles", "agent:a", 100, now)
    folder("uploads", "agent:a", 50, now - 10)
    folder("bundles", "agent:b", 1000, now)
    folder("bundles", "agent:a", 7000, now - api.BUNDLE_TTL - 1)       # просрочена
    folder("bundles", None, 3000, now)                                # недописана — ничья
    (state / "bundles" / "чужое").mkdir()
    (state / "bundles" / "чужое" / "big").write_bytes(b"x" * 5000)
    link = state / "bundles" / str(uuid.uuid4())
    link.symlink_to(state / "bundles" / "чужое")
    used = api.state_usage(state, "agent:a")
    assert 150 <= used < 1000                                         # meta.json тоже занимает место
    assert api.upload_room(state, "agent:a", None) is None
    assert api.upload_room(state, "agent:a", used + 10) == 10
    with pytest.raises(api.QuotaExceeded, match="AMEMO_STATE_QUOTA"):
        api.upload_room(state, "agent:a", used)
    assert api.state_usage(tmp_path / "нет", "agent:a") == 0
