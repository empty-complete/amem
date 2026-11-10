"""amemo setup и amemo pg (amemo/localpg.py, amemo/cli/commands/local.py).

Без PostgreSQL: свободный порт, amemo.toml (запись, права, чтение настройками), строка подключения, отказы до любых
изменений — агент с --embed/--ocr, переменные окружения, чужой amemo.toml, старый PostgreSQL, amemo pg без своего
кластера. Отказы проверяются на поддельных программах PostgreSQL (скрипты sh, поэтому не на Windows).

С PostgreSQL: AMEMO_TEST_PG_SERVER_BIN — каталог initdb, pg_ctl и postgres 18+ с pgvector (в CI —
/usr/lib/postgresql/18/bin из пакетов PGDG). Полный setup во временной папке, повторный запуск ничего не ломает,
amemo pg stop|status|start. Без переменной тест пропускается.
"""
import json
import os
import socket
import stat
import sys
from pathlib import Path

import pytest

from amemo import cli, localpg, settings
from amemo.cli.commands import local

AGENT_VARS = ("CLAUDECODE", "AMEMO_AS_MODEL", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED", "CODEX_HOME")
SERVER_BIN = os.environ.get("AMEMO_TEST_PG_SERVER_BIN", "").strip()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Чистое окружение человека: свой HOME, без AMEMO_* и без признаков агента."""
    monkeypatch.setenv("AMEMO_BACKEND", "none")
    home = tmp_path / "home"
    home.mkdir()
    environ = {k: v for k, v in os.environ.items() if not k.startswith("AMEMO_") and k not in AGENT_VARS}
    environ.update({"HOME": str(home), "USERPROFILE": str(home), "USER": "ann", "AMEMO_BACKEND": "none"})
    return environ


@pytest.fixture
def run(env, capsys):
    def call(*argv, extra=None):
        environ = dict(env)
        for key, value in (extra or {}).items():
            if value is None:
                environ.pop(key, None)
            else:
                environ[key] = value
        code = cli.main(list(argv), env=environ)
        out, err = capsys.readouterr()
        return code, out, err
    return call


def fake_bin(folder: Path, version: str = "18.1") -> Path:
    """Поддельные initdb, pg_ctl, postgres: pg_ctl --version печатает version, остальное — ошибка (не должно
    вызываться в тестах отказов)."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in localpg.TOOLS:
        body = (f'[ "$1" = --version ] && echo "pg_ctl (PostgreSQL) {version}" && exit 0\n' if name == "pg_ctl"
                else "")
        script = folder / name
        script.write_text(f"#!/bin/sh\n{body}echo 'не должен запускаться' >&2\nexit 9\n", encoding="utf-8")
        script.chmod(0o755)
    return folder


posix_only = pytest.mark.skipif(sys.platform == "win32", reason="поддельные программы — скрипты sh")


# --- без PostgreSQL ---

def test_free_port_skips_a_busy_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        assert localpg.free_port(taken, tries=4) != taken


def test_dsn_quotes_the_password():
    assert localpg.dsn("a/b@c:d", 5436) == "postgresql://amemo:a%2Fb%40c%3Ad@127.0.0.1:5436/amemo"


def test_conf_lines_listen_only_on_tcp_loopback():
    lines = localpg.conf_lines(5440)
    assert lines["listen_addresses"] == "'127.0.0.1'" and lines["port"] == "5440"
    assert lines["unix_socket_directories"] == "''"


def test_native_paths_for_postgresql_on_windows(monkeypatch, tmp_path):
    """Путь вне кодовой страницы ANSI — короткое имя 8.3; нет его — отказ с подсказкой; ANSI-путь — как есть."""
    assert localpg.native(tmp_path) == str(tmp_path)              # не Windows (или ANSI) — без изменений
    monkeypatch.setattr(localpg, "WINDOWS", True)
    monkeypatch.setattr(localpg, "_ansi", lambda text: text.isascii())
    assert localpg.native(Path("C:/amemo-data")) == str(Path("C:/amemo-data"))
    monkeypatch.setattr(localpg, "_short", lambda text: "C:\\Users\\ANNA~1\\AMEMO-~1")
    assert localpg.native(Path("C:/Users/Анна/amemo-data")) == "C:\\Users\\ANNA~1\\AMEMO-~1"
    monkeypatch.setattr(localpg, "_short", lambda text: None)
    with pytest.raises(localpg.LocalPgError, match="латинскими"):
        localpg.native(Path("C:/Users/Анна/amemo-data"))


def test_config_round_trips_through_settings(tmp_path):
    path = tmp_path / "cfg" / "amemo.toml"
    data = tmp_path / "данные \"с кавычками\""
    local.write_config(path, {"dsn": localpg.dsn("pw", 5436), "data": data / "objects", "docs": None,
                              "lang": "ru", "pg_bin": tmp_path / "bin", "pg_data": data / "pg", "auto_update": False})
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "docs" not in path.read_text(encoding="utf-8")
    loaded = settings.load({"AMEMO_CONFIG": str(path), "HOME": str(tmp_path)})
    assert loaded.dsn == localpg.dsn("pw", 5436)
    assert loaded.data == data / "objects" and loaded.pg_data == data / "pg" and loaded.pg_bin == tmp_path / "bin"
    assert loaded.auto_update is False


def test_agent_cannot_ask_for_embed_or_ocr(run, tmp_path):
    for flag in (["--embed"], ["--ocr", "rus"]):
        code, _, err = run("setup", "--pg-bin", str(tmp_path / "bin"), "--data", str(tmp_path / "d"), *flag,
                           extra={"CLAUDECODE": "1"})
        assert code == 2, err
        assert "только человек" in err
    assert not (tmp_path / "d").exists()


def test_env_overrides_are_refused(run, tmp_path):
    code, out, err = run("setup", "--pg-bin", str(tmp_path / "bin"), "--data", str(tmp_path / "d"), "--json",
                       extra={"AMEMO_DSN": "postgresql://x@127.0.0.1/x"})
    assert code == 2 and json.loads(out)["code"] == "env_overrides", err
    assert not (tmp_path / "d").exists()


def test_unknown_agent_is_refused(run, tmp_path):
    code, out, err = run("setup", "--pg-bin", str(tmp_path / "bin"), "--agents", "claude-code,cursor", "--json")
    assert code == 2 and json.loads(out)["code"] == "bad_agents", err


def test_missing_pg_programs(run, tmp_path):
    code, out, err = run("setup", "--pg-bin", str(tmp_path / "нет"), "--data", str(tmp_path / "d"), "--json")
    assert code == 1 and json.loads(out)["code"] == "pg_bin", err


@posix_only
def test_old_postgresql_is_refused(run, tmp_path):
    code, out, err = run("setup", "--pg-bin", str(fake_bin(tmp_path / "bin", "16.4")), "--data", str(tmp_path / "d"),
                       "--json")
    assert code == 1, err
    problem = json.loads(out)
    assert problem["code"] == "pg_bin" and "PostgreSQL 16" in problem["detail"] and "нужен 18" in problem["detail"]


@posix_only
def test_foreign_config_is_not_overwritten(run, env, tmp_path):
    config = Path(env["HOME"]) / ".config" / "amemo" / "amemo.toml"
    config.parent.mkdir(parents=True)
    config.write_text('dsn = "postgresql://someone@127.0.0.1:5432/kb"\n', encoding="utf-8")
    code, out, err = run("setup", "--pg-bin", str(fake_bin(tmp_path / "bin")), "--data", str(tmp_path / "d"), "--json")
    assert code == 2 and json.loads(out)["code"] == "config_exists", err
    assert config.read_text(encoding="utf-8") == 'dsn = "postgresql://someone@127.0.0.1:5432/kb"\n'


@posix_only
def test_orphan_cluster_is_not_reused(run, tmp_path):
    data = tmp_path / "d"
    (data / "pg").mkdir(parents=True)
    (data / "pg" / "PG_VERSION").write_text("18\n", encoding="utf-8")
    code, out, err = run("setup", "--pg-bin", str(fake_bin(tmp_path / "bin")), "--data", str(data), "--json")
    assert code == 1 and json.loads(out)["code"] == "cluster_orphan", err


def test_config_path_may_not_exist_yet(run, tmp_path):
    """AMEMO_CONFIG на ещё не созданный файл (его выбирает установщик): setup доходит до программ PostgreSQL."""
    code, out, err = run("setup", "--pg-bin", str(tmp_path / "нет"), "--json",
                         extra={"AMEMO_CONFIG": str(tmp_path / "cfg" / "amemo.toml")})
    assert code == 1 and json.loads(out)["code"] == "pg_bin", out + err


def test_pg_without_own_cluster(run):
    code, out, err = run("pg", "status", "--json")
    assert code == 1 and json.loads(out)["code"] == "no_local_pg", err


# --- с PostgreSQL ---

@pytest.mark.skipif(not SERVER_BIN, reason="нужен AMEMO_TEST_PG_SERVER_BIN — каталог initdb, pg_ctl, postgres 18+")
def test_setup_creates_cluster_base_and_config(run, env, tmp_path):
    data = tmp_path / "amemo-data"
    cluster = localpg.Cluster(Path(SERVER_BIN), data / "pg")
    try:
        code, out, err = run("setup", "--pg-bin", SERVER_BIN, "--data", str(data), "--lang", "ru",
                             "--no-auto-update", "--json")
        assert code == 0, err
        first = json.loads(out)
        assert first["base_id"] and first["migrations_applied"]
        assert first["pg_data"] == str(data / "pg") and first["store"] == str(data / "objects")
        assert first["port"] >= localpg.PORT_FROM
        config = Path(env["HOME"]) / ".config" / "amemo" / "amemo.toml"
        text = config.read_text(encoding="utf-8")
        assert "auto_update = false" in text and 'lang = "ru"' in text
        assert localpg.conf_lines(first["port"])["unix_socket_directories"] in (data / "pg" / "postgresql.conf"
                                                                                ).read_text(encoding="utf-8")

        # повторный запуск: тот же кластер, тот же пароль, база та же, миграций нет
        code, out, err = run("setup", "--pg-bin", SERVER_BIN, "--data", str(data), "--json")
        assert code == 0, err
        again = json.loads(out)
        assert again["base_id"] == first["base_id"] and again["migrations_applied"] == []
        assert config.read_text(encoding="utf-8") == text

        code, out, err = run("doctor", "--json")
        checks = {c["name"]: c["status"] for c in json.loads(out)["checks"]}
        for name in ("база", "миграции", "id базы", "хранилище"):
            assert checks.get(name) == "ok", (name, checks, err)

        code, out, err = run("pg", "stop", "--json")
        assert code == 0 and json.loads(out) | {"pg_data": None} == {
            "action": "stop", "changed": True, "running": False, "pg_data": None, "port": first["port"]}, err
        code, out, _ = run("pg", "status", "--json")
        assert json.loads(out)["running"] is False
        code, out, err = run("pg", "start", "--json")
        assert code == 0 and json.loads(out)["changed"] is True and json.loads(out)["running"] is True, err
        code, out, _ = run("pg", "start", "--json")
        assert json.loads(out)["changed"] is False
    finally:
        if cluster.exists:
            cluster.stop()
