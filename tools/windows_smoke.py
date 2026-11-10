"""Проверка amemo на Windows в CI (job windows в .github/workflows/ci.yml) — путь пользователя без WSL.

amemo — из PATH: колесо этой ветки, поставленное `uv tool install`; база — PostgreSQL с pgvector на этой же машине,
DSN — первый аргумент. Шаги — как в docs/install-agent.md: amemo init, amemo install claude-code (глобально),
amemo doctor; хуки запускаются так, как их запускает Claude Code (форма exec: command и args, без оболочки);
токены общей службы (два token create разом — замок файла); amemo serve: /health и поиск с токеном (журнал запросов).

HOME намеренно указывает в другую папку: на Windows amemo и агенты живут в %USERPROFILE%.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.request
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8")         # кириллица в журнале CI: канал на Windows — в кодовой странице ANSI

DSN = sys.argv[1]
PROFILE = Path(os.environ["USERPROFILE"])
TMP = Path(os.environ["RUNNER_TEMP"])
PORT = 8767
EVENTS = {"SessionStart": {"source": "startup"}, "UserPromptSubmit": {"prompt": "проверка amemo на Windows"},
          "PreCompact": {"trigger": "manual", "custom_instructions": ""}}

AMEMO = shutil.which("amemo")
assert AMEMO and Path(AMEMO).suffix.lower() == ".exe", f"amemo в PATH: {AMEMO}"


def amemo(*args: str, env: dict | None = None) -> str:
    print("+ amemo", *args, flush=True)
    done = subprocess.run([AMEMO, *args], capture_output=True, text=True, encoding="utf-8", env=env)
    print(done.stdout, end="")
    print(done.stderr, end="", file=sys.stderr)
    assert done.returncode == 0, f"amemo {' '.join(args)}: код {done.returncode}"
    return done.stdout


def no_cr(path: Path) -> None:
    """Файл amemo записан с \\n, а не \\r\\n (os.open на Windows — текстовый режим без O_BINARY)."""
    assert b"\r" not in path.read_bytes(), f"{path}: в файле \\r"


def check_init() -> None:
    print(amemo("--version"))
    amemo("init", "--dsn", DSN)
    config = PROFILE / ".config" / "amemo" / "amemo.toml"
    assert config.is_file(), config
    no_cr(config)
    assert tomllib.loads(config.read_text(encoding="utf-8"))["dsn"] == DSN


def check_install() -> list[dict]:
    amemo("install", "claude-code")
    user = json.loads((PROFILE / ".claude.json").read_text(encoding="utf-8"))
    server = user["mcpServers"]["amemo"]
    assert Path(server["command"]).is_file() and server["args"][-3:] == ["mcp", "--agent", "model:claude-code"], server
    settings = json.loads((PROFILE / ".claude" / "settings.json").read_text(encoding="utf-8"))
    handlers = []
    for event in EVENTS:
        (group,) = settings["hooks"][event]
        (handler,) = group["hooks"]
        assert handler["args"] == ["hook", event] and Path(handler["command"]).is_file(), handler
        handlers.append(handler)
    for name in ("amemo-remember", "amemo-answer", "amemo-verify"):
        assert (PROFILE / ".claude" / "skills" / name / "SKILL.md").is_file(), name
    return handlers


def check_doctor() -> None:
    amemo("doctor")
    checks = {c["name"]: c for c in json.loads(amemo("doctor", "--json"))["checks"]}
    for name in ("база", "миграции", "id базы", "хранилище", "агент claude-code"):
        assert checks.get(name, {}).get("status") == "ok", (name, checks.get(name))


def check_hooks(handlers: list[dict]) -> None:
    """Хук — как у Claude Code: программа с аргументами без оболочки, JSON события на stdin, CLAUDECODE=1."""
    env = {**os.environ, "CLAUDECODE": "1"}
    for handler in handlers:
        event = handler["args"][-1]
        payload = {"session_id": "ci", "transcript_path": "", "cwd": str(TMP), "hook_event_name": event,
                   **EVENTS[event]}
        done = subprocess.run([handler["command"], *handler["args"]], input=json.dumps(payload).encode("utf-8"),
                              capture_output=True, env=env, timeout=60)
        out = done.stdout.decode("utf-8")
        print(f"hook {event}: код {done.returncode}, {len(out)} знаков", flush=True)
        assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
        if out.strip() and event != "PreCompact":
            assert json.loads(out)["hookSpecificOutput"]["hookEventName"] == event
    log = PROFILE / ".local" / "state" / "amemo" / "hooks.log"
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    print("hooks.log:", *lines, sep="\n  ")
    # холодный запуск на машине CI может не уложиться в бюджет — это не сбой; всё прочее в журнале — сбой
    assert all("бюджет" in line for line in lines), lines


def check_tokens() -> tuple[Path, str]:
    tokens = TMP / "amemo-tokens.toml"
    token = json.loads(amemo("token", "create", "person:ci", "--file", str(tokens), "--json"))["token"]
    # два create разом: второй ждёт замка первого и дописывает, а не теряет его запись
    both = [subprocess.Popen([AMEMO, "token", "create", f"model:ci-{i}", "--read-only", "--file", str(tokens)],
                             stdout=subprocess.DEVNULL) for i in (1, 2)]
    assert [p.wait(timeout=60) for p in both] == [0, 0]
    listed = json.loads(amemo("token", "list", "--file", str(tokens), "--json"))
    agents = sorted(t["agent"] for t in listed)
    assert agents == ["model:ci-1", "model:ci-2", "person:ci"], agents
    no_cr(tokens)
    return tokens, token


def get(path: str, token: str | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.read()


def check_serve(tokens: Path, token: str) -> None:
    env = {**os.environ, "AMEMO_TOKENS": str(tokens)}
    log = open(TMP / "amemo-serve.log", "wb")
    service = subprocess.Popen([AMEMO, "serve", "--port", str(PORT)], env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 90
        while True:
            try:
                status, body = get("/health")
                break
            except OSError:
                assert service.poll() is None, "amemo serve вышла"
                assert time.monotonic() < deadline, "/health не ответил за 90 с"
                time.sleep(1)
        print("/health:", status, body.decode("utf-8"))
        assert status == 200
        status, body = get("/api/v1/search?q=%D0%BF%D1%80%D0%BE%D0%B2%D0%B5%D1%80%D0%BA%D0%B0", token)
        assert status == 200, body
        journal = PROFILE / ".local" / "state" / "amemo" / "queries.jsonl"
        assert journal.is_file(), journal
        no_cr(journal)
        assert json.loads(journal.read_text(encoding="utf-8").splitlines()[-1])["query"] == "проверка"
    finally:
        service.terminate()
        service.wait(timeout=30)
        log.close()
        print((TMP / "amemo-serve.log").read_text(encoding="utf-8", errors="replace"))


def main() -> None:
    check_init()
    handlers = check_install()
    check_doctor()
    check_hooks(handlers)
    check_serve(*check_tokens())
    print("amemo на Windows: всё прошло")


if __name__ == "__main__":
    main()
