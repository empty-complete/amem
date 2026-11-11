"""Плагин amemo для Claude Cowork: `amemo install|uninstall cowork` собирает и убирает zip (amemo/agents/cowork.py).

Всё — на временном HOME; в PATH — заглушка amemo, чтобы путь к команде был известен.
"""
import json
import zipfile
from pathlib import Path

import pytest

from amemo import cli
from amemo.agents import cowork, install, platforms


@pytest.fixture
def home(tmp_path):
    folder = tmp_path / "home"
    folder.mkdir()
    return folder


@pytest.fixture
def env(home, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "amemo"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    return {"HOME": str(home), "USERPROFILE": str(home), "PATH": str(bin_dir)}


def read_zip(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name).decode("utf-8") for name in archive.namelist()}


def test_build_writes_a_plugin_zip_with_manifest_server_and_skills(home, env):
    report = cowork.build(env)
    path = home / cowork.FILENAME
    assert report.path == path and report.action == "создан" and path.exists()
    files = read_zip(path)
    assert set(files) == {".claude-plugin/plugin.json", ".mcp.json", "hooks/hooks.json",
                          *(f"skills/{name}/SKILL.md" for name in platforms.SKILLS)}
    manifest = json.loads(files[".claude-plugin/plugin.json"])
    assert manifest["name"] == "amemo" and manifest["version"] and manifest["license"] == "MIT"
    assert {"displayName", "description", "author", "homepage"} <= set(manifest)
    server = json.loads(files[".mcp.json"])["mcpServers"]["amemo"]
    command, _ = install.amemo_command(env)          # на Windows заглушки без .exe нет — тогда python -m amemo.cli
    assert [server["command"], *server["args"]] == [*command, "mcp", "--agent", "model:cowork"]
    assert server["env"] == {"AMEMO_AS_MODEL": "cowork"}
    for name in platforms.SKILLS:
        assert files[f"skills/{name}/SKILL.md"] == install.skill_text(name)
    # хуки — как у Claude Code: три события, форма exec (команда и аргументы без оболочки), их узнаёт установщик
    hooks = json.loads(files["hooks/hooks.json"])["hooks"]
    assert set(hooks) == set(install.ALL_EVENTS)
    for event, groups in hooks.items():
        assert groups == [{"hooks": [{"type": "command", "command": command[0],
                                      "args": [*command[1:], "hook", event], "timeout": platforms.HOOK_TIMEOUT}]}]
        assert install.is_our_hook(groups[0]["hooks"][0])
    assert not any(name.startswith("bin/") for name in files)     # bin/ нельзя в плагине из настроек claude.ai
    assert any("Upload plugin" in note for note in report.notes)


def test_rebuild_is_stable_and_byte_identical(home, env):
    cowork.build(env)
    first = (home / cowork.FILENAME).read_bytes()
    again = cowork.build(env)
    assert again.action is None and (home / cowork.FILENAME).read_bytes() == first
    assert cowork.zip_bytes(cowork.plugin_files(install.amemo_command(env)[0])) == first


def test_dry_run_writes_nothing(home, env):
    report = cowork.build(env, dry_run=True)
    assert report.action == "создан" and not (home / cowork.FILENAME).exists()


def test_foreign_file_is_not_overwritten_and_not_removed(home, env):
    target = home / "notes.zip"
    target.write_bytes(b"not a plugin")
    with pytest.raises(install.InstallError, match="не плагин amemo"):
        cowork.build(env, target)
    report = cowork.remove(env, target)
    assert report.action is None and report.warnings and target.read_bytes() == b"not a plugin"


def test_custom_out_path_and_folder_is_refused(home, env, tmp_path):
    out = tmp_path / "dist" / "amemo.zip"
    assert cowork.build(env, out).path == out and cowork.is_ours(out)
    with pytest.raises(install.InstallError, match="папка"):
        cowork.build(env, tmp_path)


def test_cli_install_and_uninstall_cowork(home, env, capsys):
    assert cli.main(["install", "cowork", "--json"], env=env) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["agent"] == "cowork" and data["format"] == cowork.FORMAT and data["changed"]
    assert data["path"] == str(home / cowork.FILENAME) and ".mcp.json" in data["files"]
    assert cli.main(["install", "cowork", "--json"], env=env) == 0
    assert json.loads(capsys.readouterr().out)["changed"] is False
    assert cli.main(["uninstall", "cowork"], env=env) == 0
    assert not (home / cowork.FILENAME).exists()


def test_cli_rejects_project_for_cowork_and_out_for_other_agents(home, env, tmp_path):
    assert cli.main(["install", "cowork", "--project", str(tmp_path)], env=env) == 2
    assert cli.main(["install", "codex", "--out", str(tmp_path / "x.zip")], env=env) == 2


def test_amemo_from_a_temporary_environment_is_refused(home, env, tmp_path):
    """`uv tool run` и `uvx` ставят amemo во временную папку: путь в плагине исчез бы сразу после сборки."""
    cache = tmp_path / "uvcache"
    fake = cache / "archive-v0" / "abc" / "bin" / "amemo"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    temp_env = {**env, "PATH": str(fake.parent), "UV_CACHE_DIR": str(cache)}
    assert cowork.ephemeral([str(fake)], temp_env)
    with pytest.raises(install.InstallError, match="временного окружения"):
        cowork.build(temp_env)
    assert not (home / cowork.FILENAME).exists()
    assert cowork.ephemeral(install.amemo_command(env)[0], env) is None


def test_plugin_uses_the_launcher_of_the_windows_app(home, env, tmp_path):
    launcher = tmp_path / "app" / "bin" / "amemo.exe"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("")
    cowork.build({**env, "AMEMO_LAUNCHER": str(launcher)})
    files = read_zip(home / cowork.FILENAME)
    assert json.loads(files[".mcp.json"])["mcpServers"]["amemo"]["command"] == str(launcher)
    hooks = json.loads(files["hooks/hooks.json"])["hooks"]
    assert {groups[0]["hooks"][0]["command"] for groups in hooks.values()} == {str(launcher)}
