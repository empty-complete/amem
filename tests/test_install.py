"""Установщик amemo в агентов (подпроект 4, часть 4c, задача 14): `amemo install|uninstall claude-code|codex`.

Всё — на временном HOME и временной папке проекта; настоящий `claude` не запускается: в PATH лежит заглушка,
которая правит ~/.claude.json так же, как `claude mcp add|remove --scope user`, и пишет свои вызовы в журнал.
"""
import json
import os
import stat
import sys
import tomllib
from pathlib import Path

import pytest

from amemo import cli
from amemo.agents import install, platforms

ROOT = Path(__file__).resolve().parent.parent

STUB = """#!{python}
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\\n")
path = Path(os.environ["HOME"]) / ".claude.json"
data = json.loads(path.read_text()) if path.exists() else {{}}
fail = os.environ.get("STUB_FAIL_ADD")
if args[:2] == ["mcp", "add"] and fail and fail in args:
    print("add failed", file=sys.stderr)
    sys.exit(1)
if args[:2] == ["mcp", "add"]:
    rest = args[2:]
    sep = rest.index("--")
    opts, command = rest[:sep], rest[sep + 1:]
    env = {{}}
    i = 0
    while i < len(opts) - 1:
        if opts[i] == "--env":
            key, _, value = opts[i + 1].partition("=")
            env[key] = value
            i += 2
        elif opts[i] in ("--scope", "--transport"):
            i += 2
        else:
            break
    name = opts[-1]
    if name in data.get("mcpServers", {{}}):
        print(f"MCP server {{name}} already exists", file=sys.stderr)
        sys.exit(1)
    data.setdefault("mcpServers", {{}})[name] = {{"type": "stdio", "command": command[0], "args": command[1:],
                                                "env": env}}
elif args[:2] == ["mcp", "remove"]:
    del data["mcpServers"][args[-1]]
else:
    sys.exit(2)
path.write_text(json.dumps(data, indent=2))
"""


@pytest.fixture
def home(tmp_path):
    folder = tmp_path / "home"
    folder.mkdir()
    return folder


@pytest.fixture
def env(home, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    return {"HOME": str(home), "PATH": str(bin_dir), "STUB_LOG": str(tmp_path / "claude.log")}


@pytest.fixture
def claude(env, tmp_path):
    """Заглушка `claude` в PATH; возвращает функцию — список её вызовов."""
    path = Path(env["PATH"]) / "claude"
    path.write_text(STUB.format(python=sys.executable), encoding="utf-8")
    path.chmod(0o755)
    log = Path(env["STUB_LOG"])
    return lambda: [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    return folder


def tree(folder: Path) -> dict:
    """Снимок папки: путь → (содержимое, права); для проверки «ничего не записано»."""
    return {str(p.relative_to(folder)): (p.read_bytes(), stat.S_IMODE(p.lstat().st_mode))
            for p in sorted(folder.rglob("*")) if p.is_file() or p.is_symlink()}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def amemo_hooks(settings: dict) -> dict:
    return {event: [h for g in groups for h in g["hooks"] if install.is_our_hook(h)]
            for event, groups in settings.get("hooks", {}).items()}


def seed_claude(home: Path) -> tuple[dict, dict]:
    user = {"numStartups": 7, "mcpServers": {"other": {"type": "stdio", "command": "other-mcp", "args": []}},
            "projects": {"/x": {"allowedTools": []}}}
    settings = {"model": "opus", "hooks": {
        "SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "echo привет"}]}],
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "./check.sh"}]}]}}
    (home / ".claude.json").write_text(json.dumps(user), encoding="utf-8")
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text(json.dumps(settings, indent=4), encoding="utf-8")
    return user, settings


# --- Claude Code, глобально ---

def test_claude_global_with_claude_in_path_calls_mcp_add(home, env, claude):
    user, settings = seed_claude(home)
    report = install.install("claude-code", env)
    calls = claude()
    assert len(calls) == 1 and calls[0][:4] == ["mcp", "add", "--scope", "user"]
    assert "AMEMO_AS_MODEL=claude-code" in calls[0] and calls[0][calls[0].index("--") - 1] == "amemo"
    assert calls[0][-3:] == ["mcp", "--agent", "model:claude-code"]
    server = read_json(home / ".claude.json")["mcpServers"]["amemo"]
    assert server["env"] == {"AMEMO_AS_MODEL": "claude-code"}
    assert server["args"][-3:] == ["mcp", "--agent", "model:claude-code"]
    assert report.warnings == [] and any("claude" in note for note in report.notes)
    # хуки — три события, AMEMO_AS_MODEL и явный timeout; чужие хуки на месте
    written = read_json(home / ".claude" / "settings.json")
    ours = amemo_hooks(written)
    for event in ("SessionStart", "UserPromptSubmit", "PreCompact"):
        (hook,) = ours[event]
        assert hook["command"].startswith("AMEMO_AS_MODEL=claude-code ")
        assert hook["command"].endswith(f"hook {event}") and hook["timeout"] == platforms.HOOK_TIMEOUT
    assert written["model"] == "opus" and written["hooks"]["PreToolUse"] == settings["hooks"]["PreToolUse"]
    assert written["hooks"]["SessionStart"][0] == settings["hooks"]["SessionStart"][0]
    # навыки
    for name in platforms.SKILLS:
        assert (home / ".claude" / "skills" / name / "SKILL.md").read_text(encoding="utf-8") == \
            install.skill_text(name)
    # повтор — ничего: ни команды, ни записи
    snapshot = tree(home)
    again = install.install("claude-code", env)
    assert again.changes == [] and again.commands == [] and tree(home) == snapshot and len(claude()) == 1
    # uninstall — claude mcp remove и файлы как были (разобранный JSON)
    install.uninstall("claude-code", env)
    assert claude()[-1] == ["mcp", "remove", "--scope", "user", "amemo"]
    assert read_json(home / ".claude.json") == user
    assert read_json(home / ".claude" / "settings.json") == settings
    assert not (home / ".claude" / "skills" / "amemo-remember").exists()


def test_claude_global_without_claude_edits_claude_json_with_a_warning(home, env):
    user, settings = seed_claude(home)
    original = (home / ".claude.json").read_bytes()
    report = install.install("claude-code", env)
    assert any("Claude Code может переписать" in w for w in report.warnings)
    data = read_json(home / ".claude.json")
    assert data["mcpServers"]["other"] == user["mcpServers"]["other"] and data["numStartups"] == 7
    assert data["mcpServers"]["amemo"]["type"] == "stdio"
    assert Path(data["mcpServers"]["amemo"]["command"]).is_absolute()          # глобально — полный путь
    assert data["mcpServers"]["amemo"]["env"] == {"AMEMO_AS_MODEL": "claude-code"}
    # резервная копия — исходный файл байт в байт, и повторная правка её не трогает
    assert (home / ".claude.json.amemo-backup").read_bytes() == original
    install.uninstall("claude-code", env)
    install.install("claude-code", env)
    assert (home / ".claude.json.amemo-backup").read_bytes() == original
    install.uninstall("claude-code", env)
    assert read_json(home / ".claude.json") == user
    assert read_json(home / ".claude" / "settings.json") == settings


def test_claude_global_on_a_clean_home_creates_and_then_removes_its_files(home, env):
    install.install("claude-code", env)
    assert (home / ".claude.json").exists() and (home / ".claude" / "settings.json").exists()
    assert stat.S_IMODE(os.stat(home / ".claude.json").st_mode) == 0o600
    install.uninstall("claude-code", env)
    assert not (home / ".claude.json").exists() and not (home / ".claude" / "settings.json").exists()
    assert not list(home.rglob("*.amemo-backup"))
    assert not list(home.rglob("SKILL.md"))


# --- Claude Code, проект ---

def test_claude_project_writes_mcp_json_settings_and_skills(home, env, project, claude):
    (project / ".mcp.json").write_text(json.dumps({"mcpServers": {"db": {"command": "db-mcp"}}}), encoding="utf-8")
    report = install.install("claude-code", env, project)
    assert claude() == []                          # в проект — без claude: .mcp.json правится сам
    servers = read_json(project / ".mcp.json")["mcpServers"]
    assert servers["db"] == {"command": "db-mcp"} and servers["amemo"]["env"] == {"AMEMO_AS_MODEL": "claude-code"}
    assert servers["amemo"]["command"] == "amemo"                    # в проекте — без пути этой машины
    ours = amemo_hooks(read_json(project / ".claude" / "settings.json"))
    assert sorted(ours) == ["PreCompact", "SessionStart", "UserPromptSubmit"]
    assert all(h[0]["command"] == f"AMEMO_AS_MODEL=claude-code amemo hook {e}" for e, h in ours.items())
    assert any("PATH агента" in note for note in report.notes)
    assert str(Path(sys.executable).parent) not in (project / ".mcp.json").read_text(encoding="utf-8")
    assert all((project / ".claude" / "skills" / n / "SKILL.md").exists() for n in platforms.SKILLS)
    assert list(home.iterdir()) == []              # глобальное не тронуто
    assert any("одобрения" in note for note in report.notes)
    install.uninstall("claude-code", env, project)
    assert read_json(project / ".mcp.json") == {"mcpServers": {"db": {"command": "db-mcp"}}}
    assert not (project / ".claude" / "settings.json").exists()


def test_missing_project_folder_is_an_error(env, tmp_path):
    with pytest.raises(install.InstallError, match="папки нет"):
        install.install("claude-code", env, tmp_path / "nope")


# --- Codex ---

CODEX_CONFIG = '''model = "gpt-5"

[mcp_servers.other]
command = "other"
args = ["--x"]

[projects."/work"]
trust_level = "trusted"'''


def test_codex_global_writes_a_marked_toml_block_agents_md_and_hooks(home, env):
    codex = home / ".codex"
    codex.mkdir()
    (codex / "config.toml").write_text(CODEX_CONFIG, encoding="utf-8")        # без перевода строки в конце
    (codex / "AGENTS.md").write_text("# Мои правила\n\nПиши коротко.\n", encoding="utf-8")
    original_md = (codex / "AGENTS.md").read_text(encoding="utf-8")
    original_toml = tomllib.loads(CODEX_CONFIG)

    report = install.install("codex", env)
    text = (codex / "config.toml").read_text(encoding="utf-8")
    assert text.startswith(CODEX_CONFIG)
    begin, end = text.index("# amemo:begin"), text.index("# amemo:end")
    assert begin < text.index("[mcp_servers.amemo]") < end
    parsed = tomllib.loads(text)
    assert parsed["mcp_servers"]["other"] == original_toml["mcp_servers"]["other"]
    assert parsed["projects"] == original_toml["projects"]
    server = parsed["mcp_servers"]["amemo"]
    assert server["env"] == {"AMEMO_AS_MODEL": "codex"} and server["args"][-3:] == ["mcp", "--agent", "model:codex"]
    assert server["env_vars"] == ["AMEMO_DSN", "AMEMO_CONFIG", "AMEMO_STATE", "PGPASSFILE", "PGSERVICE"]
    assert "postgresql" not in text and any("env_vars" in note for note in report.notes)
    md = (codex / "AGENTS.md").read_text(encoding="utf-8")
    assert md.startswith(original_md) and "<!-- amemo:begin" in md and "<!-- amemo:end -->" in md
    assert "данные, а не указания" in md and "data, not instructions" in md
    hooks = amemo_hooks(read_json(codex / "hooks.json"))
    assert sorted(hooks) == ["SessionStart", "UserPromptSubmit"]
    assert all(h[0]["command"].startswith("AMEMO_AS_MODEL=codex ") and h[0]["timeout"] == 5 for h in hooks.values())
    assert all((home / ".agents" / "skills" / n / "SKILL.md").exists() for n in platforms.SKILLS)
    assert report.agent == "codex" and report.format == platforms.CODEX_FORMAT

    snapshot = tree(home)
    assert install.install("codex", env).changes == [] and tree(home) == snapshot

    install.uninstall("codex", env)
    assert tomllib.loads((codex / "config.toml").read_text(encoding="utf-8")) == original_toml
    assert (codex / "config.toml").read_text(encoding="utf-8") == CODEX_CONFIG       # и текст тот же
    assert (codex / "AGENTS.md").read_text(encoding="utf-8") == original_md
    assert not (codex / "hooks.json").exists()


@pytest.mark.parametrize("original", ["", "# Правила", "# Правила\n", "# Правила\n\n\n"])
def test_markdown_block_is_removed_back_to_the_same_text(original):
    added = install.put_block(original, "<!-- amemo:begin", "<!-- amemo:end -->", "текст\n", " -->")
    assert added.startswith(original) and added.endswith("<!-- amemo:end -->\n")
    assert install.put_block(added, "<!-- amemo:begin", "<!-- amemo:end -->", "текст\n", " -->") == added
    assert install.drop_block(added, "<!-- amemo:begin", "<!-- amemo:end -->") == original
    # чужой текст, дописанный после блока, остаётся
    later = added + "Ещё правило.\n"
    assert install.drop_block(later, "<!-- amemo:begin", "<!-- amemo:end -->").endswith("Ещё правило.\n")


def test_codex_project_uses_project_files_and_warns_about_trust(home, env, project):
    report = install.install("codex", env, project)
    server = tomllib.loads((project / ".codex" / "config.toml").read_text())["mcp_servers"]["amemo"]
    assert server["env"] == {"AMEMO_AS_MODEL": "codex"} and server["command"] == "amemo"
    assert all(h[0]["command"].startswith("AMEMO_AS_MODEL=codex amemo hook ")
               for h in amemo_hooks(read_json(project / ".codex" / "hooks.json")).values())
    assert "<!-- amemo:begin" in (project / "AGENTS.md").read_text(encoding="utf-8")
    assert (project / ".codex" / "hooks.json").exists()
    assert all((project / ".agents" / "skills" / n / "SKILL.md").exists() for n in platforms.SKILLS)
    assert any("доверенн" in note for note in report.notes)
    assert list(home.iterdir()) == []
    install.uninstall("codex", env, project)
    assert not (project / "AGENTS.md").exists() and not (project / ".codex" / "config.toml").exists()


def test_codex_server_amemo_outside_the_block_is_not_overwritten(home, env):
    (home / ".codex").mkdir()
    config = home / ".codex" / "config.toml"
    config.write_text('[mcp_servers.amemo]\ncommand = "mine"\n', encoding="utf-8")
    with pytest.raises(install.InstallError, match="вне блока"):
        install.install("codex", env)
    assert config.read_text() == '[mcp_servers.amemo]\ncommand = "mine"\n'
    assert cli.main(["install", "codex"], env=env) == 2


def test_codex_home_moves_codex_files(home, env, tmp_path):
    other = tmp_path / "codex-home"
    install.install("codex", {**env, "CODEX_HOME": str(other)})
    assert (other / "config.toml").exists() and not (home / ".codex").exists()


# --- общие правила ---

def test_dry_run_writes_nothing_and_shows_the_changes(home, env, project, claude, capsys):
    seed_claude(home)
    before_home, before_project = tree(home), tree(project)
    for argv in (["install", "claude-code", "--dry-run"], ["install", "codex", "--dry-run"],
                 ["install", "claude-code", "--project", str(project), "--dry-run"]):
        assert cli.main(argv, env=env) == 0
    out = capsys.readouterr().out
    assert "будет выполнено: " in out and "mcp add --scope user" in out
    assert "будет изменён: " in out and "будет создан: " in out and "+++ " in out
    assert tree(home) == before_home and tree(project) == before_project and claude() == []


def test_foreign_hooks_in_a_shared_group_stay_and_reinstall_is_stable(home, env):
    seed_claude(home)
    install.install("claude-code", env)
    path = home / ".claude" / "settings.json"
    data = read_json(path)
    # пользователь дописал свой хук в группу amemo и свою группу после неё
    data["hooks"]["UserPromptSubmit"][0]["hooks"].append({"type": "command", "command": "my-hook"})
    data["hooks"]["UserPromptSubmit"].append({"hooks": [{"type": "command", "command": "late"}]})
    path.write_text(json.dumps(data), encoding="utf-8")
    install.install("claude-code", env)
    again = read_json(path)
    commands = [h["command"] for g in again["hooks"]["UserPromptSubmit"] for h in g["hooks"]]
    assert "my-hook" in commands and "late" in commands
    assert sum(1 for c in commands if c.endswith("hook UserPromptSubmit")) == 1
    assert install.install("claude-code", env).changes == []
    install.uninstall("claude-code", env)
    left = [h["command"] for g in read_json(path)["hooks"]["UserPromptSubmit"] for h in g["hooks"]]
    assert left == ["my-hook", "late"]


def test_write_keeps_file_mode_and_writes_through_a_symlink(home, env, tmp_path):
    seed_claude(home)
    settings = home / ".claude" / "settings.json"
    real = tmp_path / "dotfiles" / "settings.json"
    real.parent.mkdir()
    settings.rename(real)
    settings.symlink_to(real)
    real.chmod(0o640)
    install.install("claude-code", env)
    assert settings.is_symlink() and amemo_hooks(read_json(real))
    assert stat.S_IMODE(os.stat(real).st_mode) == 0o640
    assert (real.parent / "settings.json.amemo-backup").exists()
    assert not list(real.parent.glob("*.amemo-tmp"))


def test_broken_json_is_left_alone(home, env):
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text("{не json", encoding="utf-8")
    with pytest.raises(install.InstallError, match="не JSON"):
        install.install("claude-code", env)
    assert (home / ".claude" / "settings.json").read_text(encoding="utf-8") == "{не json"


def test_changed_skill_is_kept_on_uninstall(home, env):
    install.install("claude-code", env)
    skill = home / ".claude" / "skills" / "amemo-answer" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nмоя правка\n", encoding="utf-8")
    report = install.uninstall("claude-code", env)
    assert skill.exists() and any("изменён после установки" in w for w in report.warnings)


def test_agent_command_failure_is_an_environment_error(home, env, claude):
    seed_claude(home)
    data = read_json(home / ".claude.json")
    data["mcpServers"]["amemo"] = {"type": "stdio", "command": "old", "args": [], "env": {}}
    (home / ".claude.json").write_text(json.dumps(data), encoding="utf-8")
    report = install.plan("claude-code", env)
    assert [c[1:3] for c in report.commands] == [["mcp", "remove"], ["mcp", "add"]]   # старый amemo заменяется
    (Path(env["PATH"]) / "claude").write_text(f"#!{sys.executable}\nimport sys\nsys.exit(3)\n")
    assert cli.main(["install", "claude-code"], env=env) == 1


def test_cli_json_report(home, env, capsys):
    assert cli.main(["install", "codex", "--json"], env=env) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["agent"] == "codex" and data["changed"] and data["format"] == platforms.CODEX_FORMAT
    assert {c["action"] for c in data["changes"]} == {"создан"}
    assert cli.main(["install", "codex", "--json"], env=env) == 0
    assert json.loads(capsys.readouterr().out)["changed"] is False
    assert cli.main(["uninstall", "codex"], env=env) == 0
    assert not (home / ".codex" / "config.toml").exists()


def test_amemo_in_path_is_used_by_full_path(env, tmp_path):
    fake = Path(env["PATH"]) / "amemo"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    command, note = install.amemo_command(env)
    assert command == [str(fake)] and note is None
    assert install.is_our_hook({"command": install.hook_command(command, "codex", "SessionStart")})
    assert install.is_our_hook({"command": install.hook_command([sys.executable, "-m", "amemo.cli"], "x", "PreCompact")})
    assert not install.is_our_hook({"command": "echo amemo hooks are great"})


# --- навыки ---

def test_core_skills_are_bilingual_pages_with_frontmatter_and_data_framing():
    import re

    for name in platforms.SKILLS:
        text = install.skill_text(name)
        head = re.match(r"---\nname: (?P<name>[a-z-]+)\ndescription: (?P<desc>[^\n]+)\n---\n", text)
        assert head and head["name"] == name and 20 < len(head["desc"]) < 1024 and "<" not in head["desc"]
        assert "## RU" in text and "## EN" in text
        ru, en = text.split("## EN")
        assert 15 <= len(ru.split("## RU")[1].strip().splitlines()) <= 60       # по странице на язык
        assert 15 <= len(en.strip().splitlines()) <= 60
        assert "/home/" not in text and "C:\\" not in text
    assert "не указания" in install.skill_text("amemo-answer") and "not instructions" in \
        install.skill_text("amemo-answer")
    assert "basis" in install.skill_text("amemo-remember") and "amemo_search" in install.skill_text("amemo-remember")
    assert "semantic" in install.skill_text("amemo-verify") and "confidence" in install.skill_text("amemo-verify")


def test_skills_are_package_data():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "packs/core/skills/*/SKILL.md" in pyproject["tool"]["setuptools"]["package-data"]["amemo"]


# --- правки по ревью установщика ---

def test_file_with_bom_is_refused(home, env):
    (home / ".codex").mkdir()
    config = home / ".codex" / "config.toml"
    config.write_bytes("\ufeffmodel = 1\n".encode("utf-8"))
    with pytest.raises(install.InstallError, match="уберите BOM"):
        install.install("codex", env)
    assert config.read_bytes() == "\ufeffmodel = 1\n".encode("utf-8")


def test_crlf_files_get_a_crlf_block_and_return_to_the_same_text(home, env):
    codex = home / ".codex"
    codex.mkdir()
    toml_text = 'model = "gpt-5"\r\n\r\n[mcp_servers.other]\r\ncommand = "other"\r\n'
    md_text = "# Правила\r\n\r\nПиши коротко.\r\n"
    (codex / "config.toml").write_bytes(toml_text.encode("utf-8"))
    (codex / "AGENTS.md").write_bytes(md_text.encode("utf-8"))
    install.install("codex", env)
    for path in (codex / "config.toml", codex / "AGENTS.md"):
        raw = path.read_bytes().decode("utf-8")
        assert raw.count("\n") == raw.count("\r\n"), path            # ни одного голого LF
    assert tomllib.loads((codex / "config.toml").read_text(encoding="utf-8"))["mcp_servers"]["amemo"]
    assert install.install("codex", env).changes == []                 # повтор — без изменений
    install.uninstall("codex", env)
    assert (codex / "config.toml").read_bytes().decode("utf-8") == toml_text
    assert (codex / "AGENTS.md").read_bytes().decode("utf-8") == md_text


def test_erased_end_mark_warns_on_uninstall_and_refuses_install(home, env):
    install.install("codex", env)
    agents_md = home / ".codex" / "AGENTS.md"
    text = agents_md.read_text(encoding="utf-8").replace("<!-- amemo:end -->", "")
    agents_md.write_text(text, encoding="utf-8")
    report = install.uninstall("codex", env)
    assert any("стёрта" in w for w in report.warnings)
    assert agents_md.read_text(encoding="utf-8") == text               # чужое без метки конца не трогается
    with pytest.raises(install.InstallError, match="стёрта"):
        install.install("codex", env)


def test_failed_add_after_remove_restores_the_old_server(home, env, claude):
    seed_claude(home)
    data = read_json(home / ".claude.json")
    old = {"type": "stdio", "command": "old-amemo", "args": ["mcp"], "env": {"K": "v"}}
    data["mcpServers"]["amemo"] = old
    (home / ".claude.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(install.AgentCommandError, match="возвращена"):
        install.install("claude-code", {**env, "STUB_FAIL_ADD": "model:claude-code"})
    assert [c[:2] for c in claude()] == [["mcp", "remove"], ["mcp", "add"], ["mcp", "add"]]
    assert read_json(home / ".claude.json")["mcpServers"]["amemo"] == old


def test_same_server_without_type_or_with_extra_keys_runs_no_command(home, env, claude):
    seed_claude(home)
    install.install("claude-code", env)
    data = read_json(home / ".claude.json")
    entry = data["mcpServers"]["amemo"]
    del entry["type"]
    entry["timeout"] = 30                                              # ключ, который агент мог дописать сам
    (home / ".claude.json").write_text(json.dumps(data), encoding="utf-8")
    assert install.plan("claude-code", env).commands == []


def test_uninstall_touches_amemo_hooks_only_in_its_own_events(home, env):
    seed_claude(home)
    install.install("claude-code", env)
    path = home / ".claude" / "settings.json"
    data = read_json(path)
    mine = {"matcher": "Bash", "hooks": [{"type": "command", "command": "amemo hook PreToolUse"}]}
    data["hooks"]["PreToolUse"].append(mine)                           # свой хук пользователя с amemo hook
    path.write_text(json.dumps(data), encoding="utf-8")
    install.uninstall("claude-code", env)
    assert mine in read_json(path)["hooks"]["PreToolUse"]


def test_reports_tell_about_backups_and_empty_folders(home, env):
    seed_claude(home)
    report = install.install("claude-code", env)
    assert any(".amemo-backup" in n and "перед правкой" in n for n in report.notes)
    report = install.uninstall("claude-code", env)
    assert any("копия до установки оставлена" in n for n in report.notes)
    clean = home.parent / "clean"
    clean.mkdir()
    install.install("claude-code", {**env, "HOME": str(clean)})
    report = install.uninstall("claude-code", {**env, "HOME": str(clean)})
    (note,) = [n for n in report.notes if "пустые папки" in n]
    assert str(clean / ".claude" / "skills") in note and str(clean / ".claude") in note


# --- Windows: хуки без оболочки sh ---

def test_hook_forms_for_windows_are_recognised_and_parsed():
    exe = r"C:\Users\Ann Lee\.local\bin\amemo.EXE"
    # Claude Code: exec — программа и аргументы, без оболочки (Git Bash или PowerShell — всё равно)
    handler = install.hook_handler([exe], "claude-code", "SessionStart", "exec")
    assert handler == {"type": "command", "command": exe, "args": ["hook", "SessionStart"],
                       "timeout": platforms.HOOK_TIMEOUT}
    assert install.is_our_hook(handler) and install._hook_argv(handler) == [exe, "hook", "SessionStart"]
    python = install.hook_handler([r"C:\Python312\python.exe", "-m", "amemo.cli"], "x", "PreCompact", "exec")
    assert install.is_our_hook(python)
    # Codex: строка для cmd.exe /C — программа в кавычках, «\» — не экран
    handler = install.hook_handler([exe], "codex", "UserPromptSubmit", "cmd")
    assert handler["command"] == f'"{exe}" hook UserPromptSubmit'
    assert install.is_our_hook(handler)
    assert install._hook_argv(handler, "cmd") == [exe, "hook", "UserPromptSubmit"]
    assert install.is_our_hook(install.hook_handler(["amemo"], "codex", "SessionStart", "cmd"))
    # чужое — не наше
    assert not install.is_our_hook({"command": "node", "args": ["check.js", "hook", "SessionStart"]})
    assert not install.is_our_hook({"command": exe, "args": ["mcp"]})
    assert not install.is_our_hook({"command": exe, "args": "hook SessionStart"})


def test_windows_install_writes_exec_hooks_for_claude_and_cmd_hooks_for_codex(home, env, project, monkeypatch):
    monkeypatch.setattr(platforms, "WINDOWS", True)
    stub = Path(env["PATH"]) / "amemo"
    stub.write_text("#!/bin/sh\n")
    stub.chmod(0o755)

    install.install("claude-code", env, project)
    ours = amemo_hooks(read_json(project / ".claude" / "settings.json"))
    for event in ("SessionStart", "UserPromptSubmit", "PreCompact"):
        (hook,) = ours[event]
        assert hook == {"type": "command", "command": "amemo", "args": ["hook", event],
                        "timeout": platforms.HOOK_TIMEOUT}
    assert install.install("claude-code", env, project).changes == []          # повтор ничего не меняет
    found = install.inspect("claude-code", env, project)
    assert found is not None and found.status == "ok", found

    install.install("codex", env, project)
    ours = amemo_hooks(read_json(project / ".codex" / "hooks.json"))
    for event in ("SessionStart", "UserPromptSubmit"):
        (hook,) = ours[event]
        assert hook["command"] == f'"amemo" hook {event}'
    found = install.inspect("codex", env, project)
    assert found is not None and found.status in ("ok", "warn") and "такой команды нет" not in found.detail, found

    install.uninstall("claude-code", env, project)
    install.uninstall("codex", env, project)
    assert not (project / ".claude" / "settings.json").exists() and not (project / ".codex" / "hooks.json").exists()


def test_windows_home_is_userprofile(monkeypatch, tmp_path):
    from amemo import portable

    monkeypatch.setattr(portable, "WINDOWS", True)
    profile = tmp_path / "profile"
    lay = platforms.layout("claude-code", {"USERPROFILE": str(profile), "HOME": str(tmp_path / "msys")})
    assert lay.mcp_json == profile / ".claude.json" and lay.hooks_json == profile / ".claude" / "settings.json"
    assert portable.home({"HOME": str(tmp_path)}) == tmp_path
