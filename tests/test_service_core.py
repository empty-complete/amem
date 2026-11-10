"""Служба (подпроект 4, часть 4a, задача 5): настройки, private.strip, защита Host/Origin/415, сессия и cookie
человека, общая служба по токенам, перевод исключений в problem+json — starlette.testclient на настоящей базе
(PostgreSQL 18 и 16), порт не слушается."""
import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest
from starlette.routing import Route

from amemo import __version__, bundle, db, embed, objects, private, records, review, service, settings, vocab
from amemo.canon import CanonError
from amemo.check import CheckError
from amemo.folders import FolderError
from amemo.packs import PackError
from amemo.service import problems
from conftest import SERVICE_URL, FakeProvider

BASE_URL = SERVICE_URL
ORIGIN = BASE_URL
DEV_UI = "http://127.0.0.1:5173"


# --- настройки ---

def test_settings_explicit_argument_beats_environment_and_environment_beats_toml(tmp_path):
    config = tmp_path / "amemo.toml"
    config.write_text('dsn = "postgresql://toml/db"\nport = 9001\nhost = "127.0.0.2"\n', encoding="utf-8")
    env = {"AMEMO_CONFIG": str(config), "AMEMO_DSN": "postgresql://env/db", "AMEMO_PORT": "9002", "USER": "ann"}

    explicit = settings.load(env, dsn="postgresql://arg/db")
    assert (explicit.dsn, explicit.port, explicit.host) == ("postgresql://arg/db", 9002, "127.0.0.2")
    assert explicit.config == config

    from_env = settings.load(env)
    assert (from_env.dsn, from_env.port) == ("postgresql://env/db", 9002)

    del env["AMEMO_DSN"], env["AMEMO_PORT"]
    from_toml = settings.load(env)
    assert (from_toml.dsn, from_toml.port) == ("postgresql://toml/db", 9001)


def test_settings_toml_from_home_config_and_defaults(tmp_path):
    home = tmp_path / "home"
    (home / ".config" / "amemo").mkdir(parents=True)
    (home / ".config" / "amemo" / "amemo.toml").write_text(
        'dsn = "postgresql://home/db"\ndocs = "~/Документы"\ndata = "objects"\n', encoding="utf-8")
    s = settings.load({"HOME": str(home), "USER": "ann"})
    assert s.dsn == "postgresql://home/db"
    assert s.config == home / ".config" / "amemo" / "amemo.toml"
    assert s.docs == home / "Документы"                              # ~ раскрывается
    assert s.data == home / ".config" / "amemo" / "objects"            # относительный путь — от файла настроек
    assert s.state == home / ".local" / "state" / "amemo"
    assert s.backups == s.state / "backups"
    assert s.query_log == s.state / "queries.jsonl"
    assert (s.host, s.port) == ("127.0.0.1", 8767)
    assert (s.agent, s.model_agent) == ("person:ann", "model:local")
    assert s.ui_origins == ()
    assert s.tokens is None


def test_settings_defaults_without_toml(tmp_path):
    home = tmp_path / "home"
    s = settings.load({"HOME": str(home), "USER": "ann", "AMEMO_DSN": "postgresql://x/db"})
    assert s.config is None
    assert s.data == home / ".local" / "share" / "amemo" / "objects"
    assert s.docs is None
    state = tmp_path / "state"
    s = settings.load({"HOME": str(home), "USER": "ann", "AMEMO_STATE": str(state)})
    assert s.dsn is None                     # обязательность DSN проверяет тот, кому нужна база (create_app)
    assert (s.backups, s.query_log) == (state / "backups", state / "queries.jsonl")


@pytest.mark.parametrize("user, agent", [
    ("ann", "person:ann"),
    ("Ann.Smith", "person:ann.smith"),
    ("José Núñez", "person:jose-nunez"),
    ("DOMAIN\\ann_b", "person:domain-ann_b"),
    ("Анна", "person:local"),            # от имени ничего не осталось — общее имя, а не пустой агент
])
def test_settings_default_agent_from_os_user_name(tmp_path, user, agent):
    assert settings.load({"HOME": str(tmp_path), "USER": user}).agent == agent


def test_settings_agents_ui_origins_tokens_and_query_log_from_environment(tmp_path):
    s = settings.load({"HOME": str(tmp_path), "USER": "ann", "AMEMO_AGENT": "person:anna",
                       "AMEMO_MODEL_AGENT": "model:bot", "AMEMO_UI_ORIGINS": f"{DEV_UI}/, HTTP://LOCALHOST:5173",
                       "AMEMO_TOKENS": str(tmp_path / "amemo-tokens.toml"), "AMEMO_QUERY_LOG": "off"})
    assert (s.agent, s.model_agent) == ("person:anna", "model:bot")
    assert s.ui_origins == (DEV_UI, "http://localhost:5173")
    assert s.tokens == tmp_path / "amemo-tokens.toml"
    assert s.query_log is None


@pytest.mark.parametrize("env, where", [
    ({"AMEMO_PORT": "восемь"}, "AMEMO_PORT"),
    ({"AMEMO_PORT": "70000"}, "AMEMO_PORT"),
    ({"AMEMO_AGENT": "model:x"}, "AMEMO_AGENT"),          # человек локальной службы — только person:
    ({"AMEMO_AGENT": "person:Анна"}, "AMEMO_AGENT"),
    ({"AMEMO_MODEL_AGENT": "person:x"}, "AMEMO_MODEL_AGENT"),
    ({"AMEMO_UI_ORIGINS": "127.0.0.1:5173"}, "AMEMO_UI_ORIGINS"),
    ({"AMEMO_UI_ORIGINS": "http://127.0.0.1:5173/ui"}, "AMEMO_UI_ORIGINS"),
    ({"AMEMO_CONFIG": "нет-такого.toml"}, "нет-такого.toml"),
])
def test_settings_errors_name_the_source(tmp_path, env, where):
    with pytest.raises(settings.SettingsError, match=where):
        settings.load({"HOME": str(tmp_path), "USER": "ann", **env})


@pytest.mark.parametrize("text, where", [
    ("dsn = ", "amemo.toml"),                        # не TOML
    ('dns = "postgresql://x/db"', "dns"),           # опечатка в ключе — ошибка, а не тихий пропуск
    ("port = true", "port"),
    ("ui_origins = 5", "ui_origins"),
])
def test_settings_bad_toml(tmp_path, text, where):
    config = tmp_path / "amemo.toml"
    config.write_text(text, encoding="utf-8")
    with pytest.raises(settings.SettingsError, match=where):
        settings.load({"HOME": str(tmp_path), "USER": "ann", "AMEMO_CONFIG": str(config)})


def test_settings_ui_origins_list_in_toml(tmp_path):
    config = tmp_path / "amemo.toml"
    config.write_text(f'ui_origins = ["{DEV_UI}"]\nquery_log = "журнал.jsonl"\n', encoding="utf-8")
    s = settings.load({"HOME": str(tmp_path), "USER": "ann", "AMEMO_CONFIG": str(config)})
    assert s.ui_origins == (DEV_UI,)
    assert s.query_log == tmp_path / "журнал.jsonl"


# --- токены общей службы ---

def tokens_file(tmp_path, *entries) -> str:
    path = tmp_path / "amemo-tokens.toml"
    path.write_text("".join(f'[[token]]\nhash = "{settings.token_hash(token)}"\nagent = "{agent}"\n'
                            f'write = {str(write).lower()}\n\n' for token, agent, write in entries), encoding="utf-8")
    path.chmod(0o600)
    return str(path)


def test_token_hash_and_tokens_file(tmp_path):
    assert settings.token_hash("abc") == "sha256:" + hashlib.sha256(b"abc").hexdigest()
    path = tokens_file(tmp_path, ("t-write", "person:anna", True), ("t-read", "model:bot", False))
    tokens = settings.load_tokens(path)
    assert settings.match_token(tokens, "t-write") == \
        settings.Token(settings.token_hash("t-write"), "person:anna", True)
    assert settings.match_token(tokens, "t-read").write is False
    assert settings.match_token(tokens, "чужой") is None


@pytest.mark.parametrize("text, where", [
    ('[[token]]\nagent = "person:anna"\n', "hash"),
    ('[[token]]\nhash = "md5:00"\nagent = "person:anna"\n', "hash"),
    (f'[[token]]\nhash = "{settings.token_hash("x")}"\nagent = "anna"\n', "agent"),
    (f'[[token]]\nhash = "{settings.token_hash("x")}"\nagent = "person:anna"\nwrite = "yes"\n', "write"),
    ("token = 1", "token"),
])
def test_bad_tokens_file(tmp_path, text, where):
    path = tmp_path / "amemo-tokens.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(settings.SettingsError, match=where):
        settings.load_tokens(path)


@pytest.mark.skipif(os.name != "posix", reason="права файла — POSIX")
def test_tokens_file_permissions(tmp_path, caplog):
    path = tokens_file(tmp_path, ("t", "person:anna", True))
    Path(path).chmod(0o620)                  # другой может вписать свой токен — служба не стартует
    with pytest.raises(settings.SettingsError, match="chmod 600"):
        settings.load_tokens(path)
    Path(path).chmod(0o644)                  # только чтение другими — предупреждение
    with caplog.at_level(logging.WARNING, logger="amemo.settings"):
        assert len(settings.load_tokens(path)) == 1
    assert "chmod 600" in caplog.text


@pytest.mark.parametrize("field", ["hash", "agent"])
def test_tokens_file_value_with_trailing_newline_is_rejected(tmp_path, field):
    """Шаблон — целиком: у re.match с «$» значение с переводом строки на конце проходило."""
    values = {"hash": settings.token_hash("x"), "agent": "person:anna"}
    values[field] += "\n"
    path = tmp_path / "amemo-tokens.toml"
    path.write_text(f'[[token]]\nhash = """{values["hash"]}"""\nagent = """{values["agent"]}"""\n', encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(settings.SettingsError, match=field):
        settings.load_tokens(path)


@pytest.mark.skipif(os.name != "posix", reason="владелец файла — POSIX")
def test_tokens_file_of_another_user_is_rejected(tmp_path, monkeypatch):
    path = tokens_file(tmp_path, ("t", "person:anna", True))
    owner = Path(path).stat().st_uid
    if owner == 0:
        pytest.skip("файл root принимается всегда: от root другого владельца не подменить")
    monkeypatch.setattr(settings.os, "getuid", lambda: owner + 1)       # служба — другой пользователь
    with pytest.raises(settings.SettingsError, match="другому пользователю"):
        settings.load_tokens(path)


@pytest.mark.skipif(os.name != "posix", reason="права файла — POSIX")
def test_tokens_file_permissions_are_checked_on_the_opened_file(tmp_path, monkeypatch):
    """Права — по fstat уже открытого файла: подмена между проверкой и чтением ничего не даёт."""
    path = tokens_file(tmp_path, ("t", "person:anna", True))
    Path(path).chmod(0o620)
    monkeypatch.setattr(Path, "stat", lambda self, **kw: (_ for _ in ()).throw(AssertionError("stat по имени")))
    with pytest.raises(settings.SettingsError, match="chmod 600"):
        settings.load_tokens(path)


def test_tokens_file_must_be_a_regular_file(tmp_path):
    with pytest.raises(settings.SettingsError, match=str(tmp_path)):
        settings.load_tokens(tmp_path)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="каналы FIFO — POSIX")
def test_fifo_in_place_of_the_tokens_file_does_not_hang_the_start(tmp_path):
    """Канал без пишущего на месте файла: открытие с O_NONBLOCK не ждёт, fstat отвергает его до чтения."""
    import time

    path = tmp_path / "amemo-tokens.toml"
    os.mkfifo(path)
    started = time.perf_counter()
    with pytest.raises(settings.SettingsError, match="не обычный файл"):
        settings.load_tokens(path)
    assert time.perf_counter() - started < 1


def test_missing_tokens_file(tmp_path):
    with pytest.raises(settings.SettingsError, match="amemo-tokens.toml"):
        settings.load_tokens(tmp_path / "нет" / "amemo-tokens.toml")


# --- <private> ---

@pytest.mark.parametrize("text, expected", [
    ("до <private>секрет</private> после", "до  после"),
    ("текст <private>секрет до конца\nи дальше", "текст "),            # незакрытая метка — до конца текста
    ("a<private>1</private>b<private>2</private>c", "abc"),
    ("a<PRIVATE>1</Private>b", "ab"),
    ("a<private>1<private>2</private>3</private>b", "ab"),             # вложенная метка не открывает остаток
    ("a<private>\nстроки\n</private>b", "ab"),
    ("без меток", "без меток"),
    ("a</private>b", "a</private>b"),                                    # закрывающая без открывающей — просто текст
    ("", ""),
    ("a<private >1</private>b", "ab"),                                    # пробелы и переводы строк внутри метки
    ("a< private>1</ private >b", "ab"),
    ("a<private\n>1</private\n>b", "ab"),
    ("a<\tPRIVATE\t>1< / Private >b", "ab"),
    ("a< private >хвост", "a"),
    ("a<privat>b", "a<privat>b"),                                         # не метка
])
def test_private_strip(text, expected):
    assert private.strip(text) == expected


@pytest.mark.parametrize("tail", [" ", "\n", "\t ", "< "])
def test_private_strip_is_linear_on_long_whitespace(tail):
    """«<» с длинным хвостом пробелов или переводов строк разбирается без перебора (захватывающие квантификаторы)."""
    import time

    text = "<" + tail * (100_000 // len(tail))
    started = time.perf_counter()
    assert private.strip(text) == text
    assert time.perf_counter() - started < 0.1


# --- служба: фикстуры dsn и serve — в conftest.py ---

def is_problem(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert (body["status"], body["code"]) == (status, code)
    assert body["type"] and body["title"]
    return body


def base_id(pg) -> str:
    return pg.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()[0]


# --- служба: запуск, /health, защита ---

def test_create_app_needs_dsn(tmp_path):
    with pytest.raises(settings.SettingsError, match="AMEMO_DSN"):
        service.create_app(settings.load({"HOME": str(tmp_path), "USER": "ann"}))


def test_health_and_lifespan_prepares_the_base(serve, pg):
    client = serve()
    response = client.get("/health")
    assert (response.status_code, response.text) == (200, "ok")
    assert base_id(pg)                       # служба при старте подготовила базу (db.prepare)
    pool = client.app.state.pool
    client.__exit__(None, None, None)
    assert pool.closed                       # lifespan закрыл пул


@pytest.mark.parametrize("host", ["127.0.0.1:8767", "localhost:8767", "[::1]:8767", "LOCALHOST", "127.0.0.1"])
def test_local_hosts_are_allowed(serve, host):
    assert serve().get("/health", headers={"Host": host}).status_code == 200


def test_foreign_host_is_421(serve):
    client = serve()
    body = is_problem(client.get("/health", headers={"Host": "evil.example"}), 421, "bad_host")
    assert "evil.example" in body["detail"]
    is_problem(client.get("/api/v1/session", headers={"Host": "evil.example:8767"}), 421, "bad_host")
    is_problem(client.get("/health", headers={"Host": "127.0.0.1.evil.example"}), 421, "bad_host")


def test_host_from_settings_is_allowed(serve):
    client = serve(host="192.0.2.10")
    assert client.get("/health", headers={"Host": "192.0.2.10:8767"}).status_code == 200
    is_problem(client.get("/health", headers={"Host": "192.0.2.11:8767"}), 421, "bad_host")
    # адрес «на всех интерфейсах» не делает любой Host своим
    wildcard = serve(host="0.0.0.0")
    is_problem(wildcard.get("/health", headers={"Host": "evil.example"}), 421, "bad_host")
    assert wildcard.get("/health", headers={"Host": "localhost:8767"}).status_code == 200


def test_foreign_origin_is_403(serve):
    client = serve()
    is_problem(client.post("/api/v1/submit", json={}, headers={"Origin": "http://evil.example"}), 403, "bad_origin")
    is_problem(client.get("/api/v1/session", headers={"Origin": "http://evil.example"}), 403, "bad_origin")
    is_problem(client.post("/api/v1/submit", json={}, headers={"Origin": "null"}), 403, "bad_origin")
    # свой источник и dev-сервер из AMEMO_UI_ORIGINS проходят защиту: дальше — разбор тела (нет proposals) — 400
    is_problem(client.post("/api/v1/submit", json={}, headers={"Origin": ORIGIN}), 400, "bad_request")
    is_problem(client.post("/api/v1/submit", json={}, headers={"Origin": DEV_UI}), 403, "bad_origin")
    dev = serve({"AMEMO_UI_ORIGINS": DEV_UI})
    is_problem(dev.post("/api/v1/submit", json={}, headers={"Origin": DEV_UI}), 400, "bad_request")


def test_request_from_foreign_site_without_origin_is_403(serve, pg):
    """Запасная проверка: запрос без Origin, но с Sec-Fetch-Site чужой страницы — 403 у записи и у любого /api/v1
    (картинка с чужой страницы не пишет поиск в журнал выдачи); /health отвечает."""
    client = serve()
    for site in ("cross-site", "same-site", "Cross-Site"):
        body = is_problem(client.post("/api/v1/submit", json={}, headers={"Sec-Fetch-Site": site}), 403, "bad_origin")
        assert "Sec-Fetch-Site" in body["detail"]
        is_problem(client.delete("/api/v1/folders/a", headers={"Sec-Fetch-Site": site}), 403, "bad_origin")
        is_problem(client.get("/api/v1/session", headers={"Sec-Fetch-Site": site}), 403, "bad_origin")
        is_problem(client.get("/api/v1/search", params={"q": "x"}, headers={"Sec-Fetch-Site": site,
                                                                           "Sec-Fetch-Dest": "image"}),
                   403, "bad_origin")
        assert client.get("/health", headers={"Sec-Fetch-Site": site}).status_code == 200
    assert pg.execute("SELECT count(*) FROM retrieval").fetchone()[0] == 0
    # своя страница, ввод адреса и клиенты без заголовка проходят защиту — дальше разбор тела (нет proposals)
    for headers in ({"Sec-Fetch-Site": "same-origin"}, {"Sec-Fetch-Site": "none"}, {}):
        is_problem(client.post("/api/v1/submit", json={}, headers=headers), 400, "bad_request")
        assert client.get("/api/v1/session", headers=headers).status_code == 200


def test_write_accepts_only_json(serve):
    client = serve()
    for method in ("POST", "PATCH", "DELETE", "PUT"):
        response = client.request(method, "/api/v1/submit", content=b"{}", headers={"Content-Type": "text/plain"})
        is_problem(response, 415, "unsupported_media_type")
    form = {"Content-Type": "application/x-www-form-urlencoded"}
    is_problem(client.post("/api/v1/submit", content=b"x=1", headers=form), 415, "unsupported_media_type")
    is_problem(client.post("/api/v1/submit", content=b"{}"), 415, "unsupported_media_type")   # тело без типа
    # JSON (с charset) проходит защиту — дальше разбор тела: нет proposals — 400
    is_problem(client.post("/api/v1/submit", content=b"{}",
                           headers={"Content-Type": "application/json; charset=utf-8"}), 400, "bad_request")
    # запись без тела (DELETE папки) — проверять нечего: дальше право агента (папки удаляет только человек)
    is_problem(client.delete("/api/v1/folders/a"), 403, "forbidden")
    # чтение тип тела не проверяет
    assert client.get("/health", headers={"Content-Type": "text/plain"}).status_code == 200


def test_bundle_inspect_takes_multipart_and_requires_origin(serve):
    client = serve()
    files = {"file": ("подборка.zip", b"PK", "application/zip")}
    body = is_problem(client.post("/api/v1/bundles/inspect", files=files), 403, "bad_origin")
    assert "Origin" in body["detail"]
    is_problem(client.post("/api/v1/bundles/inspect", files=files, headers={"Origin": ORIGIN}), 422,
               "bundle_invalid")                      # с Origin загрузка принята; «PK» — не zip подборки
    is_problem(client.post("/api/v1/bundles/inspect", json={}, headers={"Origin": ORIGIN}), 415,
               "unsupported_media_type")


# --- локальная служба: сессия и cookie человека ---

def test_session_without_cookie_is_the_model(serve, pg):
    client = serve()
    response = client.get("/api/v1/session")
    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    assert response.json() == {"agent": "model:local", "base": base_id(pg), "base_name": None,
                               "amem_version": __version__, "semantic": "unavailable", "can_write": True}


def test_session_cookie_from_own_page_makes_the_person(serve):
    client = serve()
    response = client.get("/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"})
    assert response.status_code == 200
    assert response.json()["agent"] == "person:ann"           # выдача cookie — уже запрос человека
    cookie = response.headers["set-cookie"]
    attributes = {part.strip().lower() for part in cookie.split(";")[1:]}
    assert {"httponly", "samesite=strict", "path=/"} <= attributes
    name, value = cookie.split(";")[0].split("=", 1)
    assert name == "amemo_session" and len(value) >= 32

    # клиент хранит cookie: следующий запрос без заголовков браузера — тоже человек
    again = client.get("/api/v1/session")
    assert (again.json()["agent"], again.json()["can_write"]) == ("person:ann", True)
    assert client.app.state.settings.agent == "person:ann"

    # без cookie — снова модель; поддельная cookie — модель
    client.cookies.clear()
    assert client.get("/api/v1/session").json()["agent"] == "model:local"
    client.cookies.set("amemo_session", "x" * len(value))
    assert client.get("/api/v1/session").json()["agent"] == "model:local"


def test_session_cookie_for_ui_origin_but_not_for_others(serve):
    client = serve({"AMEMO_UI_ORIGINS": DEV_UI, "AMEMO_AGENT": "person:anna"})
    response = client.get("/api/v1/session", headers={"Origin": DEV_UI})
    assert response.json()["agent"] == "person:anna"
    assert response.headers["set-cookie"].startswith("amemo_session=")
    client.cookies.clear()

    for headers in ({"Sec-Fetch-Site": "none"}, {}):
        response = client.get("/api/v1/session", headers=headers)
        assert response.json()["agent"] == "model:local", headers
        assert "set-cookie" not in response.headers
    for headers in ({"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"}):    # чужая страница — отказ
        response = client.get("/api/v1/session", headers=headers)
        is_problem(response, 403, "bad_origin")
        assert "set-cookie" not in response.headers
    foreign = client.get("/api/v1/session", headers={"Origin": "http://evil.example", "Sec-Fetch-Site": "same-origin"})
    is_problem(foreign, 403, "bad_origin")
    assert "set-cookie" not in foreign.headers


def test_session_cookie_is_new_on_every_start(serve):
    first, second = serve(), serve()
    a = first.get("/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"}).cookies["amemo_session"]
    b = second.get("/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"}).cookies["amemo_session"]
    assert a != b
    second.cookies.clear()
    second.cookies.set("amemo_session", a)
    assert second.get("/api/v1/session").json()["agent"] == "model:local"


def test_session_base_name_and_semantic(serve, pg):
    db.prepare(pg)
    db.set_base_name(pg, "Тестовая база")
    provider = FakeProvider()
    model = embed.register_model(pg, provider)
    embed.activate_model(pg, model["id"])
    view = serve(provider=provider).get("/api/v1/session").json()
    assert (view["base_name"], view["semantic"]) == ("Тестовая база", "used")
    assert serve({"AMEMO_MODEL_AGENT": "model:bot"}).get("/api/v1/session").json()["agent"] == "model:bot"


def test_session_semantic_off_with_backend_none(serve, pg, monkeypatch):
    """AMEMO_BACKEND=none выключает смысловой канал и при активной модели."""
    db.prepare(pg)
    provider = FakeProvider()
    embed.activate_model(pg, embed.register_model(pg, provider)["id"])
    monkeypatch.setenv("AMEMO_BACKEND", "none")
    assert serve(provider=provider).get("/api/v1/session").json()["semantic"] == "unavailable"


# --- общая служба: токены ---

def test_shared_service_requires_token(serve, tmp_path):
    path = tokens_file(tmp_path, ("t-write", "person:anna", True), ("t-read", "model:bot", False))
    client = serve({"AMEMO_TOKENS": path})

    response = client.get("/api/v1/session")
    is_problem(response, 401, "auth_required")
    assert response.headers["www-authenticate"].lower().startswith("bearer")
    is_problem(client.get("/api/v1/session", headers={"Authorization": "Bearer wrong"}), 401, "auth_required")
    is_problem(client.get("/api/v1/session", headers={"Authorization": "Basic dC13cml0ZQ=="}), 401, "auth_required")
    assert client.get("/health").status_code == 200           # проверка живости — без входа

    read = {"Authorization": "Bearer t-read"}
    view = client.get("/api/v1/session", headers=read).json()
    assert (view["agent"], view["can_write"]) == ("model:bot", False)
    is_problem(client.post("/api/v1/submit", json={}, headers=read), 403, "read_only")

    write = {"Authorization": "bearer t-write"}
    response = client.get("/api/v1/session", headers={**write, "Sec-Fetch-Site": "same-origin"})
    assert response.status_code == 200
    assert (response.json()["agent"], response.json()["can_write"]) == ("person:anna", True)
    assert "set-cookie" not in response.headers               # в общей службе cookie не выдаётся
    is_problem(client.post("/api/v1/submit", json={}, headers=write), 400, "bad_request")  # защиту прошёл


def test_shared_service_with_missing_tokens_file_does_not_start(dsn, tmp_path):
    s = settings.load({"AMEMO_DSN": dsn, "HOME": str(tmp_path), "USER": "ann",
                       "AMEMO_TOKENS": str(tmp_path / "amemo-tokens.toml")})
    with pytest.raises(settings.SettingsError, match="amemo-tokens.toml"):
        service.create_app(s)


# --- problem+json ---

CLOSED_AT = datetime(2026, 11, 7, 12, 30, tzinfo=timezone.utc)

PROBLEMS = [
    (records.RecordNotFound("atm:x: записи нет"), 404, "not_found"),
    (records.RecordError("ссылка: нужен atm:"), 400, "bad_request"),
    (CheckError("пустая пачка"), 400, "bad_request"),
    (objects.ObjectError("объект: неверный путь"), 400, "bad_request"),
    (objects.ObjectError("неверный диапазон", code="invalid"), 400, "bad_request"),
    (objects.ObjectError("объекта нет", code="not_found"), 404, "not_found"),
    (objects.ObjectError("лист больше 10 000 ячеек", code="too_large"), 413, "too_large"),
    (review.ReviewError("пункт закрыт", code="closed", by="person:anna", at=CLOSED_AT), 409, "review_closed"),
    (review.ReviewError("нет права", code="forbidden"), 403, "review_forbidden"),
    (review.ReviewError("захвачен", code="claimed"), 403, "review_forbidden"),
    (review.ReviewError("устарел", code="stale"), 400, "review_bad"),
    (review.ReviewError("исход недоступен", code="bad_outcome"), 400, "review_bad"),
    (review.ReviewError("неверный аргумент", code="invalid"), 400, "review_bad"),
    (review.ReviewError("пункта нет", code="not_found"), 404, "not_found"),
    (FolderError("папка есть", code="exists"), 409, "folder_exists"),
    (FolderError("папка не пуста", code="not_empty"), 409, "folder_not_empty"),
    (FolderError("папки нет", code="not_found"), 404, "folder_not_found"),
    (FolderError("неверный путь", code="invalid"), 422, "folder_invalid"),
    (bundle.BundleError("не загружены пакеты", code="bundle_pack_missing", missing=["example 1.0.0"]), 422,
     "bundle_pack_missing"),
    (bundle.BundleError("подборка повреждена"), 422, "bundle_invalid"),
    (db.BaseNameError("имя базы: пустое"), 400, "bad_request"),
    (vocab.VocabError("нет такого кода"), 400, "bad_request"),
    (problems.Problem(501, "not_implemented", "антологии ещё нет"), 501, "not_implemented"),
    (embed.EmbeddingError("provider не соответствует активной модели"), 503, "semantic_unavailable"),
    (CanonError("число не переводится в JSON"), 400, "bad_request"),
    (PackError("пакет example: нет pack.yaml"), 400, "bad_request"),
    (ValueError("limit должен быть целым числом от 1 до 100"), 400, "bad_request"),   # прочий — последняя ступень
]


def raising(exc):
    def boom(request):
        raise exc
    return Route("/api/v1/boom", boom)


@pytest.mark.parametrize("exc, status, code", PROBLEMS, ids=lambda v: v if isinstance(v, str) else None)
def test_library_errors_become_problems(serve, exc, status, code):
    body = is_problem(serve(routes=[raising(exc)]).get("/api/v1/boom"), status, code)
    assert str(exc) in body["detail"]


def test_problem_details(serve):
    closed = review.ReviewError("пункт закрыт", code="closed", by="person:anna", at=CLOSED_AT)
    body = is_problem(serve(routes=[raising(closed)]).get("/api/v1/boom"), 409, "review_closed")
    assert "person:anna" in body["detail"] and "2026-11-07" in body["detail"]          # кто и когда решил
    assert (body["by"], body["at"]) == ("person:anna", CLOSED_AT.isoformat())

    missing = bundle.BundleError("не загружены пакеты", code="bundle_pack_missing", missing=["example 1.0.0"])
    assert is_problem(serve(routes=[raising(missing)]).get("/api/v1/boom"), 422,
                      "bundle_pack_missing")["missing"] == ["example 1.0.0"]

    issue = {"code": "x", "severity": "violation", "message": "m", "ref": "@a", "path": "label"}
    check = problems.Problem(422, "check_rejected", "пакет отклонён", issues=[issue])
    assert is_problem(serve(routes=[raising(check)]).get("/api/v1/boom"), 422, "check_rejected")["issues"] == [issue]


def test_problem_extensions_do_not_replace_main_fields(serve):
    """Детали BundleError с ключами detail, headers, status, type, title не ломают ответ и не заменяют поля."""
    exc = bundle.BundleError("подборка не принята", code="bundle_key_collision", detail="чужое", headers={"x": 1},
                             status=200, type="https://evil.example", title="чужое", collisions=["k"])
    body = is_problem(serve(routes=[raising(exc)]).get("/api/v1/boom"), 422, "bundle_key_collision")
    assert (body["type"], body["detail"]) == ("about:blank", "подборка не принята")
    assert body["title"] != "чужое" and body["collisions"] == ["k"]
    problem = problems.Problem(400, "bad_request", "неверно", type="https://evil.example", code2="x")
    body = is_problem(serve(routes=[raising(problem)]).get("/api/v1/boom"), 400, "bad_request")
    assert (body["type"], body["code2"]) == ("about:blank", "x")


def test_value_the_database_refuses_is_400_without_its_text(serve):
    """psycopg.DataError (знак NUL, число вне integer…) — неверный ввод: 400 без текста ошибки базы."""
    error = psycopg.DataError("PostgreSQL text fields cannot contain NUL (0x00) bytes")
    body = is_problem(serve(routes=[raising(error)]).get("/api/v1/boom"), 400, "bad_request")
    assert "PostgreSQL" not in body["detail"]


def test_every_problem_has_nosniff(serve):
    client = serve()
    for response in (client.get("/api/v1/нет-такого"), client.get("/health", headers={"Host": "evil.example"}),
                     client.post("/api/v1/submit", content=b"x", headers={"Content-Type": "text/plain"})):
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.headers["x-content-type-options"] == "nosniff"


def test_database_unavailable_is_503_without_connection_details(serve):
    error = psycopg.OperationalError('connection to server at "127.0.0.1", port 5446 failed: Connection refused')
    body = is_problem(serve(routes=[raising(error)]).get("/api/v1/boom"), 503, "db_unavailable")
    assert "5446" not in str(body)
    # настоящий отказ пула: закрытый пул — тоже 503
    client = serve()
    client.app.state.pool.close()
    is_problem(client.get("/api/v1/session"), 503, "db_unavailable")


def test_unexpected_error_is_500_without_details(serve, caplog):
    client = serve(routes=[raising(RuntimeError("секрет: путь /srv/amemo/x"))], raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="amemo.service"):
        response = client.get("/api/v1/boom")
    body = is_problem(response, 500, "internal")
    assert "секрет" not in response.text and "/srv" not in response.text
    assert "секрет" in caplog.text                    # подробности — в журнал службы
    assert body["title"]


def test_unknown_path_and_method_are_problems(serve):
    client = serve()
    is_problem(client.get("/api/v1/нет-такого"), 404, "not_found")
    response = client.post("/api/v1/session", json={})
    is_problem(response, 405, "method_not_allowed")
    assert "GET" in response.headers["allow"]
