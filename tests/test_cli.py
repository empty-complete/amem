"""CLI (подпроект 4, часть 4b, задача 10): main(argv) с перехватом вывода на настоящей базе (PostgreSQL 18 и 16).

Каждая команда; коды выхода по разд. 5.1 на своих случаях; --json — тот же объект, что HTTP той же операции
(сверка с starlette.testclient); агент по окружению; токены — один показ, только хэш, права 0600; журнал запросов
пишет явный search; скрипт и python -m amem.cli запускаются.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

import contract
from amem import api, bundle, cli, db, folders, objects, records, review, settings
from amem.cli import errors
from amem.service import problems
from test_service_write import BOT, V1, fact, kb, queued, ref_of, start, written  # noqa: F401 — фикстуры

PERSON = "person:ann"
AGENT_VARS = ("CLAUDECODE", "AMEM_AS_MODEL", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED", "CODEX_HOME")


def _dsn_of(conn) -> str:
    params = conninfo_to_dict(conn.info.dsn)
    params["password"] = conn.info.password
    return make_conninfo(**params)


@pytest.fixture
def env(dsn, tmp_path, docs, monkeypatch):
    """Окружение команды: своя схема, папки во временной папке теста, обычный терминал человека ann."""
    monkeypatch.setenv("AMEM_BACKEND", "none")
    return {"AMEM_DSN": dsn, "HOME": str(tmp_path / "home"), "USER": "ann", "AMEM_DATA": str(tmp_path / "objects"),
            "AMEM_STATE": str(tmp_path / "state"), "AMEM_BACKUPS": str(tmp_path / "backups"),
            "AMEM_DOCS": str(docs), "PATH": os.environ.get("PATH", "")}


@pytest.fixture
def run(env, capsys):
    """run(*argv, env=…) → (код, stdout, stderr); extra окружения дополняет env фикстуры (None — убрать)."""
    def call(*argv, extra=None, runner=None):
        environ = dict(env)
        for key, value in (extra or {}).items():
            if value is None:
                environ.pop(key, None)
            else:
                environ[key] = value
        code = cli.main(list(argv), env=environ, runner=runner)
        out, err = capsys.readouterr()
        return code, out, err
    return call


def js(out: str):
    return json.loads(out)


@pytest.fixture
def base(kb, run, docs, tmp_path):
    """База с образцом тела /submit (сущность @node, атомы @bracket и @anchor, связь), записанным через CLI."""
    body = tmp_path / "batch.json"
    body.write_text(json.dumps(contract.example("/submit", "post"), ensure_ascii=False), encoding="utf-8")
    code, out, err = run("submit", str(body), "--json")
    assert code == 0, err
    refs = {r["label"]: r["ref"] for r in js(out)["records"]}
    return refs


# --- вход ---

def test_python_m_and_script_show_help():
    done = subprocess.run([sys.executable, "-m", "amem.cli", "--help"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert "search" in done.stdout and "Коды выхода" in done.stdout
    script = Path(sys.executable).with_name("amem")
    if script.exists():                        # скрипт [project.scripts] установленного пакета
        done = subprocess.run([str(script), "token", "--help"], capture_output=True, text=True, timeout=60)
        assert done.returncode == 0 and "create" in done.stdout


def test_usage_errors_exit_2(run):
    assert run()[0] == 2                                        # без команды — справка
    code, _, err = run("search")
    assert code == 2 and "подсказка: справка: amem search --help" in err
    assert run("nope")[0] == 2
    assert run("review")[0] == 2                                # группа без действия
    assert run("--help")[0] == 0
    assert run("search", "x", "--limit", "много")[0] == 2


def test_environment_errors_exit_1_with_hint(run, dsn):
    code, _, err = run("search", "x", extra={"AMEM_DSN": None})
    assert code == 1 and "задайте AMEM_DSN или выполните amem init" in err
    code, out, err = run("search", "x", "--json", extra={"AMEM_DSN": "postgresql://u:p@127.0.0.1:1/none"})
    assert code == 1 and js(out)["code"] == "db_unavailable" and "127.0.0.1:1" not in out
    code, _, err = run("folders", "tree")                       # схема пустая: amem init не выполнялся
    assert code == 1 and "выполните amem init" in err


def test_bad_settings_exit_2(run):
    code, _, err = run("search", "x", extra={"AMEM_PORT": "порт"})
    assert code == 2 and "AMEM_PORT" in err


# --- init, base, doctor ---

def test_init_prepares_base_and_store_and_is_repeatable(run, pg, tmp_path):
    code, out, _ = run("init", "--json")
    assert code == 0
    first = js(out)
    assert first["migrations_applied"] and first["base_id"]
    assert (tmp_path / "objects" / api.STORE_MARK).is_file()
    assert {r[0] for r in pg.execute("SELECT path FROM folder")} >= {"Проекты", "Архив"}
    code, out, _ = run("init")
    assert code == 0 and first["base_id"] in out and "миграций применено: 0" in out


def test_init_with_dsn_saves_config_0600(run, dsn, tmp_path):
    code, out, _ = run("init", "--dsn", dsn, "--json", extra={"AMEM_DSN": None})
    assert code == 0
    saved = Path(js(out)["config_saved"])
    assert saved == tmp_path / "home" / ".config" / "amem" / "amem.toml"
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    assert settings.load({"HOME": str(tmp_path / "home"), "USER": "ann"}).dsn == dsn
    assert run("folders", "tree", extra={"AMEM_DSN": None})[0] == 0     # DSN теперь из amem.toml


def test_init_refuses_empty_store_of_a_base_with_files(run, kb, store, docs, tmp_path):
    objects.ingest(kb, store, docs, "Заметки/узел.md", agent=PERSON)
    shutil.rmtree(tmp_path / "objects")
    (tmp_path / "objects").mkdir()                               # пустой том на месте хранилища
    code, _, err = run("init")
    assert code == 1 and "не подключено" in err
    assert not (tmp_path / "objects" / api.STORE_MARK).exists()


def test_base_summary_and_name(run, base, start):
    code, out, _ = run("base", "--json")
    assert code == 0
    assert js(out) == start().get(f"{V1}/base").json()
    code, out, _ = run("base", "name", "Рабочая база")
    assert code == 0 and "Рабочая база" in out
    assert js(run("base", "name", "--json")[1]) == {"name": "Рабочая база"}
    code, _, err = run("base", "name", "Чужое", extra={"CLAUDECODE": "1"})
    assert code == 2 and "только человек" in err
    assert run("base", "name", " ")[0] == 2                     # пустое имя — BaseNameError


def test_doctor(run, base, tmp_path):
    code, out, _ = run("doctor", "--json")
    report = js(out)
    assert code == 0 and report["ok"]
    assert {c["name"]: c["status"] for c in report["checks"]} == {
        "настройки": "ok", "база": "ok", "миграции": "ok", "хранилище": "ok", "смысловой поиск": "warn"}
    code, out, _ = run("doctor", extra={"AMEM_DSN": "postgresql://u:p@127.0.0.1:1/none"})
    assert code == 1 and "FAIL  база" in out


def test_doctor_reports_missing_store_of_a_base_with_files(run, kb, store, docs, tmp_path):
    code, out, _ = run("doctor", "--json")
    assert code == 0 and {c["name"]: c["status"] for c in js(out)["checks"]}["хранилище"] == "warn"   # ещё нет
    objects.ingest(kb, store, docs, "Заметки/узел.md", agent=PERSON)
    shutil.rmtree(tmp_path / "objects")
    code, out, _ = run("doctor")
    assert code == 1 and "FAIL  хранилище" in out


# --- serve ---

def test_serve_calls_service_and_refuses_open_address(run, kb):
    calls = []
    code, _, _ = run("serve", "--port", "9123", runner=lambda app, **kw: calls.append(kw))
    assert code == 0 and calls[0]["host"] == "127.0.0.1" and calls[0]["port"] == 9123
    code, _, err = run("serve", "--host", "0.0.0.0", runner=lambda app, **kw: calls.append(kw))
    assert code == 2 and "AMEM_TOKENS" in err and len(calls) == 1
    code, _, err = run("serve", "--host", "0.0.0.0", "--no-auth", runner=lambda app, **kw: calls.append(kw))
    assert code == 0 and "БЕЗ ВХОДА" in err and calls[-1]["host"] == "0.0.0.0"
    assert run("serve", extra={"AMEM_DSN": None}, runner=lambda app, **kw: None)[0] == 1
    assert run("serve", "--host", "a:1", runner=lambda app, **kw: None)[0] == 2


# --- чтение ---

def test_search_text_json_and_journal(run, base, start, tmp_path):
    code, out, _ = run("search", "анкер", "М10")
    assert code == 0 and "Анкер М10 держит кронштейн КБ-14" in out and base["@anchor"] in out
    code, out, _ = run("search", "анкер М10", "--json", "--limit", "5")
    mine = js(out)
    client = start({"AMEM_STATE": str(tmp_path / "state")})
    http = client.get(f"{V1}/search", params={"q": "анкер М10", "limit": 5}).json()
    for body in (mine, http):
        assert body.pop("retrieval_id")
        body["channels"].pop("durations_ms", None)
    assert mine == http
    lines = [json.loads(line) for line in (tmp_path / "state" / "queries.jsonl").read_text().splitlines()]
    assert [(l["query"], l["agent"]) for l in lines] == [("анкер М10", PERSON), ("анкер М10", PERSON),
                                                         ("анкер М10", "model:local")]
    assert run("search", "секрет <private>скрытое</private>")[0] == 0
    assert "скрытое" not in (tmp_path / "state" / "queries.jsonl").read_text()


def test_search_without_journal_when_off(run, base, tmp_path):
    assert run("search", "анкер", extra={"AMEM_QUERY_LOG": "off"})[0] == 0
    assert not (tmp_path / "state" / "queries.jsonl").exists()


def test_get_timeline_card(run, base, start):
    code, out, _ = run("get", base["@bracket"], "--json")
    assert code == 0
    http = start().get(f"{V1}/records/{base['@bracket']}").json()
    assert js(out) == [http]
    code, out, _ = run("get", base["@bracket"], base["@node"])
    assert code == 0 and "Кронштейн крепится к закладной анкером" in out and "Узел крепления" in out
    assert "источник: узел.md" in out

    code, out, _ = run("timeline", base["@bracket"], "--json")
    view = js(out)
    assert code == 0 and view["record"]["ref"] == base["@bracket"] and view["events"]
    assert [link["rel"] for link in view["links"]] == ["depends_on"]
    code, out, _ = run("timeline", base["@bracket"])
    assert "depends_on" in out and "Анкер М10" in out

    code, out, _ = run("card", base["@node"], "--json")
    assert code == 0 and js(out) == start().get(f"{V1}/entities/{base['@node']}/card").json()
    code, out, _ = run("card", "Узел крепления")                 # текст с явным лидером
    assert code == 0 and "Узел крепления  [artifact]" in out


def test_ambiguous_text_exits_3_with_candidates(run, base):
    code, out, err = run("get", "кронштейн")
    assert code == 3 and "явного лидера нет" in err
    assert base["@bracket"] in out and base["@anchor"] in out
    code, out, _ = run("timeline", "кронштейн", "--json")
    body = js(out)
    assert code == 3 and body["code"] == "ambiguous"
    assert {c["ref"] for c in body["candidates"]} >= {base["@bracket"], base["@anchor"]}


def test_not_found_exits_4(run, base):
    code, _, err = run("get", "atm:019a0000-0000-7000-8000-000000000000")
    assert code == 4 and "amem search" in err
    assert run("timeline", "несуществующее слово ъъъ")[0] == 4
    assert run("card", "ent:no.such.key")[0] == 4
    assert run("card", "ent:нет-такого")[0] == 2                # не ссылка: ключ — латиница


# --- submit ---

def test_submit_rejected_exits_5_with_report(run, kb, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"proposals": [{"target": "atom", "payload": {"ref": "@x", "kind": "fact"}}]}),
                   encoding="utf-8")
    code, out, err = run("submit", str(bad))
    assert code == 5 and "отклонён" in err and "violation" in out and "@x" in out
    code, out, _ = run("submit", str(bad), "--json")
    body = js(out)
    assert code == 5 and body["code"] == "check_rejected" and body["issues"] and body["changeset_id"]


def test_submit_bad_files_exit_2(run, kb, tmp_path):
    (tmp_path / "x.json").write_text("{не json", encoding="utf-8")
    assert run("submit", str(tmp_path / "x.json"))[0] == 2
    (tmp_path / "y.json").write_text('{"proposals": [], "agent": "person:x"}', encoding="utf-8")
    code, _, err = run("submit", str(tmp_path / "y.json"))
    assert code == 2 and "agent" in err
    assert run("submit", str(tmp_path / "нет.json"))[0] == 2
    (tmp_path / "z.json").write_text('{"proposals": []}', encoding="utf-8")
    assert run("submit", str(tmp_path / "z.json"))[0] == 2      # BadRequest api


def test_submit_text_and_secret_like_warning(run, kb, tmp_path):
    key = "AKIA" + "Q" * 16
    path = tmp_path / "b.json"
    path.write_text(json.dumps({"proposals": [{"target": "atom", "payload": fact(
        summary_plain={"ru": f"Доступ к щиту: ключ {key}"})}]}, ensure_ascii=False), encoding="utf-8")
    code, out, _ = run("submit", str(path))
    assert code == 0 and "@a → atm:" in out and "secret_like" in out and key not in out


# --- агент по окружению ---

@pytest.mark.parametrize("extra, agent", [
    ({}, PERSON),
    ({"AMEM_AGENT": "person:boris"}, "person:boris"),
    ({"CLAUDECODE": "1"}, "model:claude-code"),
    ({"CODEX_SANDBOX": "seatbelt"}, "model:codex"),
    ({"CODEX_HOME": "/tmp/codex"}, PERSON),                     # настройка, а не признак запуска из Codex
    ({"AMEM_AS_MODEL": "night-judge", "CLAUDECODE": "1"}, "model:night-judge"),
])
def test_agent_from_environment(run, kb, tmp_path, extra, agent):
    path = tmp_path / "b.json"
    path.write_text(json.dumps({"proposals": [{"target": "atom", "payload": fact()}]}, ensure_ascii=False),
                    encoding="utf-8")
    code, out, err = run("submit", str(path), "--json", extra=extra)
    assert code == 0, err
    changeset = js(out)["changeset_id"]
    assert kb.execute("SELECT agent FROM changeset WHERE id = %s", (changeset,)).fetchone()[0] == agent


def test_explicit_agent_and_person_in_agent_environment(run, kb, tmp_path):
    path = tmp_path / "b.json"
    path.write_text(json.dumps({"proposals": [{"target": "atom", "payload": fact()}]}, ensure_ascii=False),
                    encoding="utf-8")
    code, _, err = run("submit", str(path), "--agent", "person:x", extra={"CLAUDECODE": "1"})
    assert code == 2 and "CLAUDECODE=1" in err
    assert run("--agent", "person:x", "folders", "tree", extra={"CODEX_SANDBOX": "seatbelt"})[0] == 2
    assert run("folders", "tree", "--agent", "Кто-то")[0] == 2
    assert run("folders", "tree", extra={"AMEM_AS_MODEL": "Не Имя"})[0] == 2
    code, out, _ = run("submit", str(path), "--json", "--agent", "model:helper", extra={"CLAUDECODE": "1"})
    assert code == 0
    assert kb.execute("SELECT agent FROM changeset WHERE id = %s",
                      (js(out)["changeset_id"],)).fetchone()[0] == "model:helper"
    code, out, _ = run("--agent", "person:vera", "submit", str(path), "--json")
    assert code == 0
    assert kb.execute("SELECT agent FROM changeset WHERE id = %s",
                      (js(out)["changeset_id"],)).fetchone()[0] == "person:vera"


# --- очередь ---

def test_review_list_claim_release_resolve_stats(run, kb, store, docs, start):
    by_bot = written(kb, store, docs, fact(label="Анкер ставят в бетон класса B25"))
    item = queued(by_bot, "semantic")
    judge = {"AMEM_AS_MODEL": "judge"}
    code, out, _ = run("review", "list", "--json", "--reason", "semantic")
    assert code == 0 and js(out) == start().get(f"{V1}/review/items", params={"reason": "semantic"}).json()
    assert item in run("review", "list")[1]

    code, out, _ = run("review", "claim", "--json", extra=judge)
    [claimed] = js(out)
    assert code == 0 and claimed["id"] == item and claimed["claimed_by"] == "model:judge"
    assert claimed["payload"]["label"]["ru"] == "Анкер ставят в бетон класса B25" and claimed["sources"]
    assert "Решать нечего" in run("review", "claim", extra={"AMEM_AS_MODEL": "other"})[1]
    code, _, _ = run("review", "release", item, extra={"AMEM_AS_MODEL": "other"})
    assert code == 2                                            # держит другой — review_forbidden (403)
    assert run("review", "release", item, extra=judge)[0] == 0
    assert kb.execute("SELECT state FROM review_item WHERE id = %s", (item,)).fetchone()[0] == "queued"

    code, _, err = run("review", "resolve", item, "confirmed", extra=judge)
    assert code == 2 and "confidence" in err                    # модели нужна уверенность — review_bad
    code, out, _ = run("review", "resolve", item, "confirmed", "--confidence", "0.95", "--json", extra=judge)
    assert code == 0 and js(out)["status"]
    code, _, err = run("review", "resolve", item, "refuted")
    assert code == 6 and "решил model:judge" in err             # пункт уже решён
    assert run("review", "resolve", "019a0000-0000-7000-8000-000000000000", "confirmed")[0] == 4
    assert run("review", "resolve", "не-uuid", "confirmed")[0] == 2

    code, out, _ = run("review", "stats", "--json")
    mine, http = js(out), start().get(f"{V1}/review/stats").json()
    mine.pop("now"), http.pop("now")
    assert code == 0 and mine == http


# --- папки ---

def test_folders(run, base, start):
    code, out, _ = run("folders", "--json")
    assert code == 0 and js(out) == start().get(f"{V1}/folders").json()
    assert "Проекты  (0)" in run("folders", "tree")[1]
    assert run("folders", "create", "Проекты/Узлы")[0] == 0
    code, _, err = run("folders", "create", "Проекты/Узлы")
    assert code == 6 and "уже есть" in err
    code, _, err = run("folders", "create", "Проекты/Модель", extra={"CLAUDECODE": "1"})
    assert code == 2 and "только человек" in err
    code, out, _ = run("folders", "move", base["@bracket"], "Проекты/Узлы", "--json", extra={"CLAUDECODE": "1"})
    assert code == 0 and js(out)["folder"] == "Проекты/Узлы"      # переносить в существующую вправе и модель
    assert run("folders", "move", base["@anchor"], "Новая", extra={"CLAUDECODE": "1"})[0] == 4
    code, _, _ = run("folders", "delete", "Проекты/Узлы")
    assert code == 6                                            # в папке запись
    code, out, _ = run("folders", "rename", "Проекты/Узлы", "Проекты/Крепёж")
    assert code == 0 and "Проекты/Узлы → Проекты/Крепёж" in out
    assert run("folders", "move", base["@bracket"], "-")[0] == 0
    assert run("folders", "delete", "Проекты/Крепёж")[0] == 0
    assert run("folders", "delete", "Проекты/Крепёж")[0] == 4
    assert run("folders", "create", "a/../b")[0] == 2           # folder_invalid (422)


# --- подборки ---

def test_export_inspect_import(run, base, pg2, tmp_path):
    out_zip = tmp_path / "out" / "подборка.zip"
    code, out, _ = run("export", str(out_zip), "--json")
    made = js(out)
    assert code == 0 and out_zip.is_file() and made["summary"]["counts"]["atoms"] == 2
    assert not any((tmp_path / "state" / api.BUNDLES).iterdir())     # папка состояния убрана
    assert run("export", str(out_zip))[0] == 2                         # файл не перезаписывается

    code, out, _ = run("inspect", str(out_zip), "--json")
    assert code == 0 and js(out)["report"]["ok"]
    (tmp_path / "junk.zip").write_bytes(b"not a zip")
    assert run("inspect", str(tmp_path / "junk.zip"))[0] == 2

    other = {"AMEM_DSN": _dsn_of(pg2), "AMEM_DATA": str(tmp_path / "objects2")}
    assert run("init", extra=other)[0] == 0
    code, out, _ = run("import", str(out_zip), "--json", extra=other)
    plan = js(out)
    assert code == 0 and plan["changeset_id"] is None
    assert pg2.execute("SELECT count(*) FROM atom").fetchone()[0] == 0
    code, _, err = run("import", str(out_zip), "--apply", extra={**other, "CLAUDECODE": "1"})
    assert code == 2 and "только человек" in err
    code, out, _ = run("import", str(out_zip), "--apply", extra=other)
    assert code == 0 and "Влито пакетом" in out
    assert pg2.execute("SELECT count(*) FROM atom").fetchone()[0] == 2
    assert not any((tmp_path / "state" / api.UPLOADS).iterdir())

    anthology = tmp_path / "антология.zip"
    code, out, _ = run("export", str(anthology), "--anthology", "--title", "Узлы", "--json")
    assert code == 0 and Path(js(out)["report_file"]).read_text(encoding="utf-8").lstrip().startswith("<")


# --- бэкап ---

def test_backup_create_list_verify_restore(run, pgdb, tmp_path, monkeypatch):
    if not os.environ.get("AMEM_PG_BIN") and shutil.which("pg_dump") is None:
        pytest.fail("нужен клиент PostgreSQL 18: AMEM_PG_BIN или pg_dump в PATH", pytrace=False)
    source, target = pgdb(), pgdb()
    with db.connect(source) as conn:
        db.prepare(conn)
    code, out, err = run("backup", "create", "--json", extra={"AMEM_DSN": source})
    assert code == 0, err
    made = js(out)
    code, out, _ = run("backup", "list", "--json", extra={"AMEM_DSN": source})
    assert code == 0 and [b["name"] for b in js(out)] == [Path(made["manifest"]).stem]
    code, out, err = run("backup", "verify", made["manifest"], extra={"AMEM_DSN": source})
    assert code == 0, err
    code, out, err = run("backup", "restore", made["manifest"], "--json", extra={"AMEM_DSN": target})
    assert code == 0, err
    assert js(out)["base_id"] == made["base_id"]
    code, _, err = run("backup", "restore", made["manifest"], extra={"AMEM_DSN": target})
    assert code == 1 and "не пустая" in err


# --- токены ---

def test_token_create_list_revoke(run, tmp_path):
    path = tmp_path / "conf" / "amem-tokens.toml"
    extra = {"AMEM_TOKENS": str(path)}
    code, out, _ = run("token", "create", "person:anna", "--json", extra=extra)
    made = js(out)
    token = made["token"]
    assert code == 0 and token.startswith("amem_") and len(token) == 48
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    text = path.read_text(encoding="utf-8")
    assert token not in text and settings.token_hash(token) in text
    [entry] = settings.load_tokens(path)
    assert (entry.agent, entry.write) == ("person:anna", True)
    assert settings.match_token(settings.load_tokens(path), token) == entry

    code, out, _ = run("token", "create", "model:reader", "--read-only", extra=extra)
    second = out.splitlines()[0]
    assert code == 0 and second.startswith("amem_") and second != token
    assert [t.write for t in settings.load_tokens(path)] == [True, False]
    code, out, _ = run("token", "list", "--json", extra=extra)
    listed = js(out)
    assert [(t["agent"], t["write"]) for t in listed] == [("person:anna", True), ("model:reader", False)]
    full = settings.token_hash(token).removeprefix("sha256:")
    assert full not in out and listed[0]["id"] == full[:12]
    assert full not in run("token", "list", extra=extra)[1]

    assert run("token", "revoke", "ffffff", extra=extra)[0] == 4
    assert run("token", "revoke", "x", extra=extra)[0] == 2
    assert run("token", "revoke", listed[0]["id"], extra=extra)[0] == 0
    assert [t.agent for t in settings.load_tokens(path)] == ["model:reader"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_token_rules(run, tmp_path):
    path = tmp_path / "amem-tokens.toml"
    code, _, err = run("token", "create", "person:anna")
    assert code == 2 and "AMEM_TOKENS" in err
    code, _, err = run("token", "create", "person:anna", extra={"AMEM_TOKENS": str(path), "CLAUDECODE": "1"})
    assert code == 2 and "только человек" in err and not path.exists()
    assert run("token", "create", "anna", "--file", str(path))[0] == 2
    assert run("token", "create", "person:anna", "--file", str(path))[0] == 0
    path.chmod(0o666)                                            # файл, в который пишут другие, — отказ
    code, _, err = run("token", "list", "--file", str(path))
    assert code == 2 and "chmod 600" in err


# --- таблица кодов ---

@pytest.mark.parametrize("exc, code", [
    (api.BadRequest("x"), 2),
    (api.Forbidden("x"), 2),
    (api.Ambiguous("x", candidates=[]), 3),
    (records.RecordNotFound("x"), 4),
    (api.Missing("x"), 4),
    (api.CheckRejected("x", changeset_id="c", issues=[], warnings=[]), 5),
    (review.ReviewError("x", code="closed"), 6),
    (review.ReviewError("x", code="not_found"), 4),
    (review.ReviewError("x", code="forbidden"), 2),
    (folders.FolderError("x", code="exists"), 6),
    (folders.FolderError("x", code="not_empty"), 6),
    (folders.FolderError("x", code="not_found"), 4),
    (folders.FolderError("x", code="invalid"), 2),
    (bundle.BundleError("x", code="bundle_key_collision"), 6),
    (bundle.BundleError("x", code="bundle_pack_missing"), 1),
    (bundle.BundleError("x"), 2),
    (api.StoreUnavailable("x", where="w"), 1),
    (api.QuotaExceeded("x"), 1),
    (psycopg.OperationalError("x"), 1),
    (ValueError("x"), 2),
    (RuntimeError("x"), 1),
])
def test_exit_code_follows_service_table(exc, code):
    problem = problems.to_problem(exc)
    assert errors.exit_code(problem.status, problem.code) == code
