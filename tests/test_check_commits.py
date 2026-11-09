"""tools/check_commits.py: Conventional Commits in English."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "check_commits.py"
spec = importlib.util.spec_from_file_location("check_commits", TOOL)
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)


@pytest.mark.parametrize("message", [
    "feat: add a thing",
    "fix(sources): handle broken PDFs",
    "refactor(amem)!: rename the package",
    "docs(migration): SP 50 done\n\nBody in English.\n\nCo-Authored-By: A <a@example.com>",
    "feat(migration): wave 1\n\nPaths stay as they are: `docs/перелив/опись.md`, «приложением Д».",
    "Merge branch 'main' into feature",
    'Revert "feat: add a thing"',
    "fixup! feat: add a thing",
])
def test_valid(message):
    assert cc.problems(message) == []


@pytest.mark.parametrize("message, expected", [
    ("Add a thing", "type(scope): subject"),
    ("feature: add a thing", "unknown type"),
    ("feat(Sources): add a thing", "lowercase"),
    ("feat: add a thing.", "period"),
    ("feat: ", "type(scope): subject"),
    ("feat:  two spaces", "extra spaces"),
    ("feat: " + "x" * 95, "at most 100"),
    ("feat: перелив волны 2", "English"),
    ("feat: add a thing\nbody right after the header", "blank line"),
    ("feat: add a thing\n\nТекст по-русски.", "line 3"),
    ("", "empty"),
])
def test_invalid(message, expected):
    found = cc.problems(message)
    assert found and any(expected in p for p in found), found


def test_hook_ignores_editor_comments(tmp_path):
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("fix: a thing\n\n# Комментарий редактора\n"
                   "# ------------------------ >8 ------------------------\nдифф\n", encoding="utf-8")
    assert cc.check_file(str(msg)) == 0


def test_hook_rejects_and_keeps_the_message(tmp_path, capsys):
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("перелив: волна 2\n", encoding="utf-8")
    assert cc.check_file(str(msg)) == 1
    assert str(msg) in capsys.readouterr().err


def test_revs_checks_every_commit(tmp_path, capsys, monkeypatch):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.name", "t")
    git("config", "user.email", "t@example.com")
    git("commit", "-q", "--allow-empty", "-m", "feat: first")
    git("commit", "-q", "--allow-empty", "-m", "Второй коммит")
    monkeypatch.chdir(tmp_path)
    assert cc.check_revs(["HEAD"]) == 1
    assert "2 commits checked, 1 do not follow" in capsys.readouterr().out
