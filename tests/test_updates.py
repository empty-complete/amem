"""Обновления (docs/superpowers/specs/2026-11-10-amemo-updates-design.md, часть U2): выбор релиза и ETag, каналы,
вид установки, путь установки с проверкой во временном venv, бэкапом и откатом, перезапуск в простое, права и пути
HTTP /updates по строгой схеме контракта, `amemo update`, `python -m amemo.service --check` (миграции с откатом на
настоящей базе) и `amemo mcp` после смены версии на диске.

GitHub, PyPI, pip, pipx, бэкап, часы и os.execv — подставные: ничего не ставится и не перезапускается по-настоящему
(tests/conftest.py сверх того выключает сеть, установку и execv у всех тестов)."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

import anyio
import pytest
from mcp import Client
from starlette.testclient import TestClient

import contract
import amemo
from amemo import db, service, settings, updates
from amemo.service import mcp, server
from conftest import SERVICE_URL
from test_service_core import tokens_file
from test_service_write import problem

pytest_plugins = ["test_service_write", "test_cli"]     # фикстуры kb, env, run

REAL_HTTP_GET = updates.http_get           # до подмены в conftest: свои тесты — с подставным urlopen и subprocess
REAL_RUN_STEP = updates.run_step
PY = "/opt/amemo/bin/python"               # «текущий» интерпретатор: по нему отличаем установку на место
CURRENT = "0.1.0a1"
NEXT = "0.1.0a2"
FAR = "99.0.0"                             # для CLI: новее любой настоящей версии, видна и в канале stable
V1 = "/api/v1"
PERSON = "person:ann"


# --- подставные GitHub, PyPI и pip ---

def release(tag, *, draft=False, prerelease=False):
    return {"tag_name": tag, "draft": draft, "prerelease": prerelease,
            "html_url": f"https://github.com/{updates.REPO}/releases/tag/{tag}"}


def digest(name, version) -> str:
    return hashlib.sha256(f"{name}-{version}".encode()).hexdigest()


class GitHub:
    """API релизов с ETag и JSON PyPI: колёса (с sha256) — у версий из wheels (по умолчанию у всех релизов
    и у текущей версии — для отката)."""

    def __init__(self, releases, wheels=None, etag='"e1"', current=CURRENT):
        self.releases, self.etag, self.calls = releases, etag, []
        tags = [r["tag_name"].lstrip("v") for r in releases] + [current]
        self.wheels = {(name, v) for v in tags for name in (updates.PACKAGE, updates.WEB)} if wheels is None \
            else set(wheels)
        self.down = False

    def __call__(self, url, headers=None):
        headers = dict(headers or {})
        self.calls.append((url, headers))
        if self.down:
            raise updates.NetworkError("api.github.com: нет сети")
        if url == updates.RELEASES:
            if headers.get("If-None-Match") == self.etag:
                return 304, {}, b""
            return 200, {"etag": self.etag}, json.dumps(self.releases).encode()
        name, version = url.split("/pypi/")[1].split("/")[:2]
        if (name, version) in self.wheels:
            return 200, {}, json.dumps({"urls": [
                {"packagetype": "sdist", "digests": {"sha256": "0" * 64}},
                {"packagetype": "bdist_wheel", "yanked": True, "digests": {"sha256": "1" * 64}},
                {"packagetype": "bdist_wheel", "yanked": False, "digests": {"sha256": digest(name, version)}}]}).encode()
        return 404, {}, b""

    def release_calls(self):
        return [headers for url, headers in self.calls if url == updates.RELEASES]


class Pip:
    """Шаги установки: venv, pip во временном venv, --check, установка на место (python -m pip, pipx, uv)."""

    def __init__(self, *, check=0, report=None, install=0, rollback=0, trial=0, version=NEXT, current=CURRENT):
        self.version, self.current = version, current
        self.calls = []
        self.check, self.install, self.rollback, self.trial = check, install, rollback, trial
        self.report = report
        self.events = []
        self.requirements = []                  # содержимое файлов -r на момент вызова

    def event(self, name):
        if not self.events or self.events[-1] != name:      # две команды одного шага — одно событие
            self.events.append(name)

    def __call__(self, argv, timeout=None, cwd=None):
        argv = list(argv)
        self.calls.append((argv, cwd))
        if "-r" in argv:
            self.requirements.append(Path(argv[argv.index("-r") + 1]).read_text(encoding="utf-8"))
        if argv[1:3] == ["-m", "venv"]:
            Path(argv[3], "bin").mkdir(parents=True, exist_ok=True)
            self.event("venv")
            return updates.Step(0, "")
        if "--check" in argv:
            self.event("check")
            assert argv[1:] == ["-I", "-m", "amemo.service", "--check"] and cwd and Path(cwd).is_dir()
            out = json.dumps(self.report if self.report is not None
                             else {"version": self.version, "migrations": [], "ui": True}) if self.check == 0 else ""
            return updates.Step(self.check, out + "\nжурнал проверки" if self.check else out, out)
        if "updates" in Path(argv[0]).parts:          # pip во временном venv AMEMO_STATE/updates/<X>/venv
            self.event("trial")
            return updates.Step(self.trial, "Successfully installed")
        back = Path(argv[argv.index("-r") + 1]).name == "rollback.txt" if "-r" in argv else \
            argv[-1].endswith("==" + self.current)
        if back:
            self.event("rollback")
            return updates.Step(self.rollback, "откат")
        self.event("install")
        return updates.Step(self.install, "Successfully installed" if self.install == 0 else "ERROR: нет места")


class Clock:
    def __init__(self, at=1000.0):
        self.at = at

    def __call__(self):
        return self.at


def state_env(tmp_path, **extra) -> dict:
    return {"HOME": str(tmp_path / "home"), "USER": "ann", "AMEMO_STATE": str(tmp_path / "state"),
            "AMEMO_BACKUPS": str(tmp_path / "backups"), "AMEMO_DSN": "postgresql://unused/db", **extra}


def make(tmp_path, *, kind="pip", extras=("web",), current=CURRENT, github=None, pip=None, env=None,
         disk=None, **kw) -> updates.Updater:
    restarts, backups = [], []

    def backup(dsn, folder):
        backups.append(folder)
        return {"manifest": str(folder / f"copy-{len(backups)}.json")}

    kw.setdefault("backup", backup)
    updater = updates.Updater(settings.load(state_env(tmp_path, **(env or {}))),
                              install=updates.Install(kind, extras, reason=kw.pop("reason", None)), current=current,
                              get=github if github is not None else GitHub([release("v" + NEXT)]),
                              run=pip if pip is not None else Pip(), python=PY, argv=["-m", "amemo.service"],
                              versions=kw.pop("versions", lambda: {"amemo": NEXT, "amemo-web": NEXT}),
                              disk=disk or (lambda: current), windows=kw.pop("windows", False),
                              execv=lambda path, args: restarts.append((path, args)), **kw)
    updater.restarts, updater.backups = restarts, backups
    updater.backup_problem = lambda: None
    return updater


def saved(updater) -> dict:
    return json.loads(updater.path.read_text(encoding="utf-8"))


# --- релизы, каналы, ETag ---

def test_parse_releases_skips_drafts_and_non_versions():
    found = updates.parse_releases([release("v0.1.0a2"), release("v0.2.0", draft=True), release("nightly"),
                                    release("0.1.0"), "мусор", {"tag_name": 5}])
    assert [(r.version, r.prerelease) for r in found] == [("0.1.0a2", True), ("0.1.0", False)]
    with pytest.raises(updates.NetworkError):
        updates.parse_releases({"message": "Not Found"})


@pytest.mark.parametrize("current, expected", [("0.1.0a1", "pre"), ("1.0.0rc2", "pre"), ("0.2.0.dev1", "pre"),
                                               ("0.1.0", "stable"), ("1.2.3", "stable")])
def test_channel_by_current_version(current, expected):
    assert updates.channel(current) == expected


def test_candidates_by_version_not_date_and_by_channel():
    releases = updates.parse_releases([release("v0.1.0"), release("v0.10.0"), release("v0.2.0b1"),
                                       release("v0.9.0", prerelease=True), release("v0.1.0a1")])
    assert [r.version for r in updates.candidates(releases, "0.1.0a1")] == ["0.10.0", "0.9.0", "0.2.0b1", "0.1.0"]
    assert [r.version for r in updates.candidates(releases, "0.1.0")] == ["0.10.0"]       # stable: без a/b и флага
    assert [r.version for r in updates.candidates(releases, "0.1.0", skip=["0.10.0"])] == []


def test_check_picks_highest_release_with_wheel_on_pypi(tmp_path):
    github = GitHub([release("v0.1.0a3"), release("v0.1.0a2"), release("v0.3.0", draft=True)],
                    wheels={("amemo", "0.1.0a2"), ("amemo-web", "0.1.0a2"), ("amemo", "0.1.0a3")})
    updater = make(tmp_path, github=github)
    status = updater.check()
    contract.component("UpdateStatus", status)
    # у 0.1.0a3 нет колеса amemo-web — берётся 0.1.0a2; черновик 0.3.0 не виден
    assert status["latest"] == {"version": "0.1.0a2", "url": f"https://github.com/{updates.REPO}/releases/tag/v0.1.0a2"}
    assert status["state"] == "available" and status["channel"] == "pre" and status["install"] == "pip"
    assert status["checked_at"] and "служба поставит её сама" in status["message"]
    without_web = make(tmp_path / "plain", github=github, extras=())
    assert without_web.check()["latest"]["version"] == "0.1.0a3"


def test_check_sends_etag_and_uses_cached_releases_on_304(tmp_path):
    github = GitHub([release("v" + NEXT)])
    updater = make(tmp_path, github=github)
    assert updater.check()["latest"]["version"] == NEXT
    assert updater.check()["latest"]["version"] == NEXT
    assert github.release_calls() == [{}, {"If-None-Match": '"e1"'}]
    assert saved(updater)["etag"] == '"e1"'


def test_check_network_error_is_quiet(tmp_path):
    github = GitHub([release("v" + NEXT)])
    github.down = True
    updater = make(tmp_path, github=github)
    status = updater.check()
    contract.component("UpdateStatus", status)
    assert status["state"] == "idle" and status["latest"] is None and status["checked_at"]
    assert "проверка не удалась" in status["message"] and "по расписанию" in status["message"]
    github.down = False
    assert updater.check()["state"] == "available"
    github.down = True
    again = updater.check()                    # сбой после удачной проверки — прежняя доступная версия остаётся
    assert again["state"] == "available" and again["latest"]["version"] == NEXT


def test_stable_channel_ignores_prereleases(tmp_path):
    updater = make(tmp_path, current="0.1.0", github=GitHub([release("v0.2.0a1"), release("v0.1.1")]))
    status = updater.check()
    assert status["channel"] == "stable" and status["latest"]["version"] == "0.1.1"


def test_real_http_get_reports_304_and_network_errors(monkeypatch):
    import urllib.error
    import urllib.request

    def not_modified(request, timeout):
        assert request.get_header("If-none-match") == '"e1"' and "amemo/" in request.get_header("User-agent")
        raise urllib.error.HTTPError(request.full_url, 304, "Not Modified", {"ETag": '"e1"'}, None)

    monkeypatch.setattr(urllib.request, "urlopen", not_modified)
    assert REAL_HTTP_GET(updates.RELEASES, {"If-None-Match": '"e1"'})[0] == 304

    def offline(request, timeout):
        raise urllib.error.URLError("Name or service not known")

    monkeypatch.setattr(urllib.request, "urlopen", offline)
    with pytest.raises(updates.NetworkError, match="api.github.com"):
        REAL_HTTP_GET(updates.RELEASES)


# --- вид установки ---

class Dist:
    def __init__(self, where, direct=None):
        self.where, self.direct = where, direct

    def read_text(self, name):
        return json.dumps(self.direct) if name == "direct_url.json" and self.direct is not None else None

    def locate_file(self, path):
        return self.where


def venv(tmp_path, *parts, marker=None) -> Path:
    prefix = tmp_path.joinpath(*parts)
    (prefix / "lib" / "site-packages").mkdir(parents=True)
    if marker:
        (prefix / marker).write_text("{}")
    return prefix


def detect(prefix, *, base=None, direct=None, env=None, which=lambda name: f"/usr/bin/{name}", **kw):
    return updates.detect(env or {}, prefix=str(prefix), base_prefix=str(base or "/usr"),
                          dist=Dist(prefix / "lib" / "site-packages", direct), extras=("web",), which=which,
                          dockerenv=str(prefix / "no-dockerenv"), **kw)


def test_detect_install_kinds(tmp_path):
    pipx = venv(tmp_path, "pipx", "venvs", "amemo", marker="pipx_metadata.json")
    found = detect(pipx)
    # pipx: в своё окружение тем же pip (runpip) — venv и интерпретатор на месте, ==X в метаданные pipx не пишется
    assert found.kind == "pipx" and found.can_install and found.command(NEXT) == [
        "/usr/bin/pipx", "runpip", "amemo", "install", "--disable-pip-version-check", "amemo[web]==0.1.0a2"]
    assert detect(pipx, which=lambda name: None).reason == "нет команды pipx в PATH"

    run = detect(venv(tmp_path, ".cache", "pipx", "0123abcd", marker="pipx_metadata.json"))
    assert run.kind == "pipx" and not run.can_install and "pipx run" in run.reason

    uv = detect(venv(tmp_path, "uv", "tools", "amemo", marker="uv-receipt.toml"))
    assert uv.kind == "uv" and uv.can_install and uv.command(NEXT, "/uv/amemo/bin/python") == [
        "/usr/bin/uv", "pip", "install", "--python", "/uv/amemo/bin/python", "amemo[web]==0.1.0a2"]

    pip = detect(venv(tmp_path, "venv"), has_pip=True)
    assert pip.kind == "pip" and pip.can_install
    assert pip.command(NEXT, "/v/bin/python") == ["/v/bin/python", "-m", "pip", "install",
                                                  "--disable-pip-version-check", "amemo[web]==0.1.0a2"]
    for kind in (found, uv, pip):
        assert not any("index-url" in part for step in kind.steps(NEXT, "/r.txt") for part in step)
    assert detect(venv(tmp_path, "nopip"), has_pip=False).reason == "в окружении нет pip"
    system = venv(tmp_path, "system")
    assert "не venv" in detect(system, base=system, has_pip=True).reason


def test_steps_install_the_checked_wheels_by_hash_then_dependencies():
    kind = updates.Install("uv", ("web", "embed"), tool="/usr/bin/uv")
    first, second = kind.steps(NEXT, "/s/requirements.txt", "/uv/bin/python")
    assert first == ["/usr/bin/uv", "pip", "install", "--python", "/uv/bin/python", "--no-deps", "--require-hashes",
                     "--only-binary=amemo", "--only-binary=amemo-web", "-r", "/s/requirements.txt"]
    assert second == ["/usr/bin/uv", "pip", "install", "--python", "/uv/bin/python", "--only-binary=amemo",
                      "--only-binary=amemo-web", "amemo[web,embed]==0.1.0a2"]
    text = updates.requirements(NEXT, {"amemo": ["a" * 64, "b" * 64], "amemo-web": ["c" * 64]})
    assert text == (f"amemo==0.1.0a2 --hash=sha256:{'a' * 64} --hash=sha256:{'b' * 64}\n"
                    f"amemo-web==0.1.0a2 --hash=sha256:{'c' * 64}\n")


def test_wheel_hashes_skip_yanked_sdists_and_bad_digests():
    github = GitHub([release("v" + NEXT)])
    assert updates.wheel_hashes(github, "amemo", NEXT) == [digest("amemo", NEXT)]
    assert updates.wheel_hashes(github, "amemo", "9.9.9") == []


def test_detect_docker_and_sources_never_install(tmp_path):
    prefix = venv(tmp_path, "venv")
    for found in (detect(prefix, env={"AMEMO_IN_CONTAINER": "1"}),
                  updates.detect({}, prefix=str(prefix), dist=Dist(prefix), dockerenv=str(tmp_path))):
        assert found.kind == "docker" and not found.can_install and "docker compose" in found.advice(NEXT)
    editable = detect(prefix, direct={"url": "file:///src/amemo", "dir_info": {"editable": True}})
    assert editable.kind == "source" and not editable.can_install and "git pull" in editable.advice(NEXT)
    wheel = detect(prefix, direct={"url": "file:///tmp/amemo-0.1.0a1-py3-none-any.whl", "archive_info": {}})
    assert wheel.kind == "source" and "не с PyPI" in wheel.reason and "тем же способом" in wheel.advice(NEXT)
    outside = updates.detect({}, prefix=str(prefix), dist=Dist(tmp_path / "elsewhere"), dockerenv=str(tmp_path / "x"),
                             extras=())
    assert outside.kind == "source" and "PYTHONPATH" in outside.reason


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="права папки — POSIX, не root")
def test_detect_read_only_venv(tmp_path):
    prefix = venv(tmp_path, "venv")
    prefix.chmod(0o555)
    try:
        assert "недоступен на запись" in detect(prefix, has_pip=True).reason
    finally:
        prefix.chmod(0o755)


# --- установка ---

def test_install_checks_in_temporary_venv_then_installs_in_place(tmp_path):
    pip = Pip()
    updater = make(tmp_path, pip=pip)
    updater.check()
    status = updater.install()
    contract.component("UpdateStatus", status)
    assert status["state"] == "ready" and "перезапуск, когда служба освободится" in status["message"]
    assert pip.events == ["venv", "trial", "check", "install"]
    (venv_cmd, _), (trial_hashed, _), (trial_deps, _), (check, cwd), (hashed, _), (deps, _) = pip.calls
    folder = tmp_path / "state" / "updates" / NEXT
    python = str(folder / "venv" / "bin" / "python")
    assert venv_cmd == [PY, "-m", "venv", str(folder / "venv")]
    # временный venv — тот же артефакт и те же extras, что потом ставятся на место
    base = [python, "-m", "pip", "install", "--disable-pip-version-check"]
    assert trial_hashed == [*base, "--no-deps", "--require-hashes", *updates.ONLY_BINARY, "-r",
                            str(folder / "requirements.txt")]
    assert trial_deps == [*base, *updates.ONLY_BINARY, "amemo[web]==0.1.0a2"]
    assert check[0] == python and cwd == str(folder)
    place = [PY, "-m", "pip", "install", "--disable-pip-version-check"]
    assert hashed == [*place, "--no-deps", "--require-hashes", *updates.ONLY_BINARY, "-r",
                      str(folder / "requirements.txt")]
    assert deps == [*place, *updates.ONLY_BINARY, "amemo[web]==0.1.0a2"]
    expected = (f"amemo==0.1.0a2 --hash=sha256:{digest('amemo', NEXT)}\n"
                f"amemo-web==0.1.0a2 --hash=sha256:{digest('amemo-web', NEXT)}\n")
    assert pip.requirements == [expected, expected]       # sha256 из JSON PyPI; отозванное колесо — не в счёт
    assert not folder.exists()                          # временный venv удалён
    assert (tmp_path / "state" / "updates").stat().st_mode & 0o777 == 0o700
    data = saved(updater)
    assert data["installed"]["version"] == NEXT and data["installed"]["previous"] == CURRENT
    assert data["installed"]["migrations"] is False and updater.backups == []
    assert [(e["event"], e["version"], e["method"]) for e in data["journal"]] == [
        ("install start", NEXT, "pip"), ("installed", NEXT, "pip")]
    assert "amemo[web]==0.1.0a2" in data["journal"][0]["detail"] and digest("amemo", NEXT) in data["journal"][0][
        "detail"]


def test_pipx_installs_inside_its_venv_with_runpip(tmp_path):
    pip = Pip()
    updater = make(tmp_path, pip=pip, kind="pipx")
    updater.kind = updates.Install("pipx", ("web",), tool="/usr/bin/pipx", venv="amemo")
    updater.check()
    assert updater.install()["state"] == "ready"
    in_place = [argv for argv, _ in pip.calls if argv[0] == "/usr/bin/pipx"]
    assert [argv[:5] for argv in in_place] == [["/usr/bin/pipx", "runpip", "amemo", "install",
                                                "--disable-pip-version-check"]] * 2
    assert not any("--force" in argv for argv, _ in pip.calls)


def test_missing_hashes_on_pypi_postpone(tmp_path):
    github = GitHub([release("v" + NEXT)])
    updater = make(tmp_path, github=github)
    updater.check()
    github.wheels.discard(("amemo-web", NEXT))
    status = updater.install()
    assert status["state"] == "available" and "нет колеса amemo-web" in status["message"]
    assert updater.run.calls == [] and "failed" not in saved(updater)


def test_symlinked_folder_is_refused(tmp_path):
    updater = make(tmp_path)
    updater.check()
    (tmp_path / "state" / "updates").mkdir()
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "state" / "updates" / NEXT).symlink_to(tmp_path / "elsewhere")
    status = updater.install()
    assert status["state"] == "available" and "символическая ссылка" in status["message"]
    assert updater.run.calls == [] and (tmp_path / "elsewhere").is_dir()


def test_check_waits_for_idle_and_postpones(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "IDLE_WAIT", 3 * updates.TICK)
    pip = Pip()
    slept = []
    updater = make(tmp_path, pip=pip, sleep=slept.append)
    updater.idle = lambda: False
    updater.check()
    status = updater.install()
    assert status["state"] == "available" and "не освободилась" in status["message"]
    assert "check" not in pip.events and slept == [updates.TICK] * 3
    answers = iter([False, True])
    updater.idle = lambda: next(answers)                 # простой наступил — проверка идёт
    assert updater.install()["state"] == "ready" and "check" in pip.events


def test_failed_check_marks_version_failed_and_keeps_installation(tmp_path):
    pip = Pip(check=1)
    github = GitHub([release("v" + NEXT)])
    updater = make(tmp_path, pip=pip, github=github)
    updater.check()
    status = updater.install()
    assert status["state"] == "failed" and "проверка новой версии не прошла" in status["message"]
    assert "install" not in pip.events and saved(updater)["failed"] == [NEXT]
    assert not (tmp_path / "state" / "updates" / NEXT).exists()
    again = updater.check()                             # эта версия больше не пробуется
    assert again["latest"] is None and again["state"] == "failed"
    github.releases.insert(0, release("v0.1.0a3"))
    github.wheels |= {("amemo", "0.1.0a3"), ("amemo-web", "0.1.0a3")}
    github.etag = '"e2"'
    newer = updater.check()                             # новее той, что не встала, — снова доступна
    assert newer["state"] == "available" and newer["latest"]["version"] == "0.1.0a3"


def test_check_without_database_is_postponed_not_failed(tmp_path):
    pip = Pip(check=updates.CHECK_TEMPORARY)
    updater = make(tmp_path, pip=pip)
    updater.check()
    status = updater.install()
    assert status["state"] == "available" and "отложена" in status["message"]
    assert "failed" not in saved(updater)


def test_check_limited_by_one_transaction_is_not_failed(tmp_path):
    pip = Pip(check=updates.CHECK_LIMITED)
    updater = make(tmp_path, pip=pip)
    updater.check()
    status = updater.install()
    assert status["state"] == "available" and "не поставлено" in status["message"]
    assert "failed" not in saved(updater) and "install" not in pip.events


def test_install_failure_rolls_back_to_previous(tmp_path):
    pip = Pip(install=1)
    updater = make(tmp_path, pip=pip)
    updater.check()
    status = updater.install()
    assert pip.events[-2:] == ["install", "rollback"]
    assert pip.calls[-1][0][-1] == "amemo[web]==0.1.0a1"           # откат — тем же путём, по хэшам прежней версии
    assert pip.requirements[-1].startswith(f"amemo==0.1.0a1 --hash=sha256:{digest('amemo', CURRENT)}")
    assert status["state"] == "failed" and f"прежняя версия {CURRENT} поставлена заново" in status["message"]


def test_rollback_that_fails_says_what_to_do(tmp_path):
    updater = make(tmp_path, pip=Pip(install=1, rollback=1))
    updater.check()
    message = updater.install()["message"]
    assert f"вернуть {CURRENT} не удалось" in message and "amemo[web]==0.1.0a1" in message


def test_version_mismatch_after_install_is_failed(tmp_path):
    pip = Pip()
    updater = make(tmp_path, pip=pip, versions=lambda: {"amemo": NEXT, "amemo-web": CURRENT})
    updater.check()
    status = updater.install()
    assert status["state"] == "failed" and "amemo-web 0.1.0a1" in status["message"]
    assert pip.events[-1] == "rollback"


def test_service_backs_up_right_before_restart(tmp_path):
    pip = Pip(report={"version": NEXT, "migrations": ["0014_next.sql"], "ui": True})
    updater = make(tmp_path, pip=pip)
    updater.idle = lambda: True                          # служба: бэкап — не при установке, а перед execv
    updater.check()
    status = updater.install()
    assert status["state"] == "ready" and "перед перезапуском бэкап" in status["message"]
    assert updater.backups == []
    assert updater.watch(lambda: False) is False and updater.backups == []    # простоя нет — и бэкапа нет
    assert updater.watch(lambda: True) is True
    assert len(updater.backups) == 1 and updater.restarts
    data = saved(updater)
    assert data["state"] == "restarting" and data["installed"]["backup"].endswith("copy-1.json")
    assert data["journal"][-1]["event"] == "restart" and "copy-1.json" in data["journal"][-1]["detail"]


def test_failed_backup_before_restart_stops_restart(tmp_path):
    def broken(dsn, folder):
        raise OSError("нет места на диске")

    pip = Pip(report={"version": NEXT, "migrations": ["0014_next.sql"], "ui": True})
    updater = make(tmp_path, pip=pip, backup=broken, disk=lambda: NEXT)
    updater.idle = lambda: True
    updater.check()
    updater.install()
    assert updater.watch(lambda: True) is False and updater.restarts == []
    status = updater.status()
    assert status["state"] == "failed" and "нет места" in status["message"] and "amemo backup create" in \
        status["message"]
    assert updater.watch(lambda: True) is False and updater.restarts == []     # и не пробует по кругу


def test_cli_install_backs_up_right_after_install(tmp_path):
    pip = Pip(report={"version": NEXT, "migrations": ["0014_next.sql"], "ui": True})
    updater = make(tmp_path, pip=pip)                    # idle не задан — это CLI: перезапуска здесь нет
    updater.check()
    status = updater.install()
    assert status["state"] == "ready" and len(updater.backups) == 1 and "бэкап: " in status["message"]
    assert saved(updater)["installed"]["backup"].endswith("copy-1.json")


def test_backup_required_when_backup_is_impossible(tmp_path):
    pip = Pip(report={"version": NEXT, "migrations": ["0014_next.sql"], "ui": True})
    updater = make(tmp_path, pip=pip)
    updater.backup_problem = lambda: "нет pg_dump: нужен клиент PostgreSQL 18"
    updater.check()
    status = updater.install()
    assert "install" not in pip.events
    assert status["state"] == "available" and "нужен бэкап: нет pg_dump" in status["message"]
    with pytest.raises(updates.UpdateError) as refused:          # ручное «Обновить сейчас» — тоже после бэкапа
        updater.ready_to_install()
    assert refused.value.code == "backup_required"
    updater.backup_problem = lambda: None                         # клиент появился — можно снова
    assert updater.ready_to_install() == NEXT


def test_backup_problem_found_before_install(tmp_path):
    pip = Pip(report={"version": NEXT, "migrations": ["0014_next.sql"], "ui": True})
    updater = make(tmp_path, pip=pip)
    updater.backup_problem = lambda: "нет места на диске"
    updater.check()
    assert "нет места" in updater.install()["message"] and "install" not in pip.events


def test_new_version_without_web_build_is_failed(tmp_path):
    updater = make(tmp_path, pip=Pip(report={"version": NEXT, "migrations": [], "ui": False}))
    updater.check()
    assert "сборки веб-интерфейса" in updater.install()["message"]


@pytest.mark.parametrize("kind, reason, words", [("docker", "образ Docker", "docker compose"),
                                                 ("source", "editable-установка из рабочей копии", "git pull"),
                                                 ("pipx", "временное окружение pipx run", "pipx run")])
def test_unsupported_install_refuses_and_says_how(tmp_path, kind, reason, words):
    updater = make(tmp_path, kind=kind, reason=reason, pip=Pip())
    status = updater.check()
    assert status["install"] == kind and status["state"] == "available" and words in status["message"]
    with pytest.raises(updates.UpdateError) as refused:
        updater.ready_to_install()
    assert refused.value.code == "update_unsupported" and words in str(refused.value)
    assert updater.scheduled()["state"] == "available" and updater.run.calls == []


def test_nothing_to_install(tmp_path):
    updater = make(tmp_path, github=GitHub([]))
    updater.check()
    with pytest.raises(updates.UpdateError) as refused:
        updater.ready_to_install()
    assert refused.value.code == "no_update"


def test_install_lock_excludes_a_second_installer(tmp_path):
    from amemo import portable

    updater = make(tmp_path)
    updater.check()
    (tmp_path / "state").mkdir(exist_ok=True)
    with portable.try_file_lock(tmp_path / "state" / updates.INSTALL_LOCK) as taken:
        assert taken
        assert updater.status()["state"] == "installing"
        with pytest.raises(updates.UpdateError) as refused:
            updater.install(NEXT)
        assert refused.value.code == "update_busy"
    assert updater.status()["state"] == "available"


def test_scheduled_installs_only_when_auto(tmp_path):
    pip = Pip()
    updater = make(tmp_path, pip=pip)
    updater.set_auto(False)
    assert updater.scheduled()["state"] == "available" and pip.calls == []
    updater.set_auto(True)
    assert updater.scheduled()["state"] == "ready" and pip.events[-1] == "install"


def test_start_install_runs_in_background(tmp_path):
    updater = make(tmp_path)
    updater.check()
    first = updater.start_install()
    contract.component("UpdateStatus", first)
    updater._thread.join(10)
    assert updater.status()["state"] == "ready"


def test_run_step_hides_pythonpath_from_new_version(monkeypatch):
    seen = {}

    def fake(argv, env, cwd, capture_output, timeout, check):
        seen.update(env=env, argv=argv)
        return subprocess.CompletedProcess(argv, 0, b'{"ok": true}\n', b"warning\n")

    monkeypatch.setenv("PYTHONPATH", "/somewhere/old")
    monkeypatch.setattr(updates.subprocess, "run", fake)
    result = REAL_RUN_STEP(["python", "-I", "-c", "pass"])
    assert result.returncode == 0 and result.stdout == '{"ok": true}\n' and "warning" in result.output
    assert "PYTHONPATH" not in seen["env"] and seen["env"]["PIP_DISABLE_PIP_VERSION_CHECK"] == "1"



# --- простой и перезапуск ---

def ready(tmp_path, **kw):
    updater = make(tmp_path, **kw)
    updater.check()
    updater.install()
    assert updater.status()["state"] == "ready"
    return updater


def test_restart_only_when_idle(tmp_path):
    updater = ready(tmp_path)
    closed = []
    updater.before_restart = lambda: closed.append(True)
    assert updater.watch(lambda: False) is False and updater.restarts == []
    assert updater.watch(lambda: True) is True
    assert updater.restarts == [(PY, [PY, "-m", "amemo.service"])] and closed == [True]
    assert saved(updater)["state"] == "restarting"
    after = make(tmp_path, current=NEXT)          # новый процесс — уже новая версия
    after.startup()
    status = after.status()
    assert status["state"] == "idle" and status["message"] == f"amemo обновлён до {NEXT}"
    assert [e["event"] for e in saved(after)["journal"]][-2:] == ["restart", "restarted"]


def test_restart_that_brought_old_version_is_failed_not_looped(tmp_path):
    updater = ready(tmp_path)
    updater.watch(lambda: True)
    again = make(tmp_path)                         # перезапуск поднял прежнюю версию
    again.startup()
    assert again.status()["state"] == "failed" and again.watch(lambda: True) is False and again.restarts == []


def test_watch_sees_install_by_another_process(tmp_path):
    disk = {"version": CURRENT}
    updater = make(tmp_path, disk=lambda: disk["version"])
    assert updater.watch(lambda: True) is False
    disk["version"] = NEXT                         # amemo update install из CLI
    assert updater.watch(lambda: False) is False
    assert updater.status()["state"] == "ready" and saved(updater)["installed"]["version"] == NEXT
    assert updater.watch(lambda: True) is True
    assert len(updater.backups) == 1          # есть ли новые миграции — неизвестно: бэкап — как при них


def test_restart_after_ready_ceiling_needs_only_free_service(tmp_path):
    clock = Clock()
    updater = ready(tmp_path, clock=clock)
    assert updater.watch(lambda: False, lambda: True) is False      # 120 с тишины нет — ждём
    clock.at += updates.READY_CEILING - 1
    assert updater.watch(lambda: False, lambda: True) is False
    clock.at += 1
    assert updater.watch(lambda: False, lambda: False) is False     # запрос в работе или пул занят — нет
    assert updater.watch(lambda: False, lambda: True) is True and updater.restarts


def test_no_restart_while_installing_or_for_docker_or_on_windows(tmp_path):
    updater = ready(tmp_path / "a")
    updater._installing = "0.1.0a3"
    assert updater.watch(lambda: True) is False
    windows = ready(tmp_path / "b", windows=True)
    assert windows.watch(lambda: True) is False and windows.restarts == []
    docker = make(tmp_path / "c", kind="docker", reason="образ Docker", disk=lambda: NEXT)
    assert docker.watch(lambda: True) is False


def test_failed_execv_is_reported(tmp_path):
    updater = ready(tmp_path)

    def broken(path, args):
        raise OSError("exec format error")

    updater.execv = broken
    assert updater.watch(lambda: True) is False
    assert updater.status()["state"] == "failed" and "перезапуск не удался" in updater.status()["message"]


def test_activity_counts_requests_but_not_quiet_paths():
    clock = Clock()
    activity = updates.Activity(clock)
    seen = []

    async def app(scope, receive, send):
        seen.append((scope["path"], activity.inflight))

    track = updates.Track(app, activity=activity)
    assert not activity.quiet_for(updates.IDLE)
    clock.at += updates.IDLE
    assert activity.quiet_for(updates.IDLE)

    async def main():
        await track({"type": "http", "method": "POST", "path": "/api/v1/submit"}, None, None)
        await track({"type": "http", "method": "GET", "path": "/mcp"}, None, None)
        await track({"type": "http", "method": "GET", "path": "/health"}, None, None)
        await track({"type": "http", "method": "GET", "path": "/api/v1/updates"}, None, None)

    clock.at += 1
    anyio.run(main)
    assert seen == [("/api/v1/submit", 1), ("/mcp", 0), ("/health", 0), ("/api/v1/updates", 0)]
    assert not activity.quiet_for(updates.IDLE)           # запрос только что кончился
    clock.at += updates.IDLE
    assert activity.quiet_for(updates.IDLE)


def test_pool_idle():
    class Pool:
        def __init__(self, **stats):
            self.stats = stats

        def get_stats(self):
            return self.stats

    assert updates.pool_idle(Pool(pool_size=2, pool_available=2, requests_waiting=0))
    assert not updates.pool_idle(Pool(pool_size=2, pool_available=1, requests_waiting=0))      # идёт транзакция
    assert not updates.pool_idle(Pool(pool_size=2, pool_available=2, requests_waiting=1))
    assert updates.pool_idle(None)


# --- настройка auto_update и переключатель ---

def test_auto_update_setting(tmp_path):
    assert settings.load(state_env(tmp_path)).auto_update is True
    for value in ("false", "off", "0", "no"):
        assert settings.load(state_env(tmp_path, AMEMO_AUTO_UPDATE=value)).auto_update is False
    config = tmp_path / "amemo.toml"
    config.write_text("auto_update = false\n", encoding="utf-8")
    assert settings.load(state_env(tmp_path, AMEMO_CONFIG=str(config))).auto_update is False
    with pytest.raises(settings.SettingsError, match="AMEMO_AUTO_UPDATE"):
        settings.load(state_env(tmp_path, AMEMO_AUTO_UPDATE="иногда"))


def test_toggle_writes_state_file_not_config(tmp_path):
    config = tmp_path / "amemo.toml"
    config.write_text('state = "state"\n', encoding="utf-8")
    updater = make(tmp_path, env={"AMEMO_CONFIG": str(config)})
    assert updater.status()["auto"] is True
    assert updater.set_auto(False)["auto"] is False
    assert saved(updater)["auto"] is False and config.read_text(encoding="utf-8") == 'state = "state"\n'
    assert updater.set_auto(True)["auto"] is True


def test_setting_off_cannot_be_overridden_by_toggle(tmp_path):
    updater = make(tmp_path, env={"AMEMO_AUTO_UPDATE": "false"})
    assert updater.status()["auto"] is False
    with pytest.raises(updates.UpdateError) as refused:
        updater.set_auto(True)
    assert refused.value.code == "auto_update_off"
    assert updater.set_auto(False)["auto"] is False


def test_broken_state_file_starts_over(tmp_path):
    updater = make(tmp_path)
    updater.path.parent.mkdir(parents=True)
    updater.path.write_text("{не json", encoding="utf-8")
    assert updater.status()["state"] == "idle"
    updater.check()
    assert saved(updater)["latest"]["version"] == NEXT


# --- HTTP /updates ---

@pytest.fixture
def http(dsn, tmp_path, kb):
    """Служба на своей схеме с подставным Updater (фоновая проверка выключена — шаги зовёт тест)."""
    clients = []

    def start(*, env=None, person=False, **kw):
        environ = {"AMEMO_DSN": dsn, "HOME": str(tmp_path / "home"), "USER": "ann",
                   "AMEMO_STATE": str(tmp_path / "state"), "AMEMO_DATA": str(tmp_path / "objects"), **(env or {})}
        updater = make(tmp_path, env={"AMEMO_DSN": dsn, **(env or {})}, **kw)
        app = service.create_app(settings.load(environ), updater=updater, update_loop=False)
        client = TestClient(app, base_url=SERVICE_URL)
        client.__enter__()
        clients.append(client)
        updater.idle = lambda: True             # служба в тесте свободна всегда: проверка не ждёт 120 с тишины
        if person:
            assert client.get(f"{V1}/session", headers={"Sec-Fetch-Site": "same-origin"}).json()["agent"] == PERSON
        return client, updater

    yield start
    for client in reversed(clients):
        client.__exit__(None, None, None)


def test_http_status_and_check_for_anyone(http):
    client, updater = http()
    status = contract.check(client.get(f"{V1}/updates"), "/updates")
    assert status["current"] == CURRENT and status["state"] == "idle" and status["checked_at"] is None
    checked = client.post(f"{V1}/updates/check")
    assert checked.status_code == 200
    body = contract.check(checked, "/updates/check", "post")
    assert body["state"] == "available" and body["latest"]["version"] == NEXT


def test_http_toggle_and_install_are_person_only(http):
    client, updater = http()                       # без cookie — модель
    updater.check()
    problem(client.put(f"{V1}/updates", json={"auto": False}), 403, "forbidden", "/updates", "put")
    problem(client.post(f"{V1}/updates/install"), 403, "forbidden", "/updates/install", "post")
    assert updater.run.calls == []


def test_http_person_toggles_and_installs(http):
    client, updater = http(person=True)
    contract.check_request(contract.example("/updates", "put"), "/updates", "put")
    toggled = client.put(f"{V1}/updates", json={"auto": False})
    assert contract.check(toggled, "/updates", "put")["auto"] is False
    problem(client.put(f"{V1}/updates", json={"auto": "нет"}), 400, "bad_request", "/updates", "put")
    problem(client.post(f"{V1}/updates/install"), 409, "no_update", "/updates/install", "post")
    updater.check()
    accepted = client.post(f"{V1}/updates/install")
    assert accepted.status_code == 202
    contract.check(accepted, "/updates/install", "post")
    updater._thread.join(10)
    assert contract.check(client.get(f"{V1}/updates"), "/updates")["state"] == "ready"


def test_http_install_refusals_409(http, tmp_path):
    client, updater = http(person=True, kind="docker", reason="образ Docker")
    updater.check()
    body = problem(client.post(f"{V1}/updates/install"), 409, "update_unsupported", "/updates/install", "post")
    assert "docker compose" in body["detail"]


def test_http_backup_required_409(http):
    client, updater = http(person=True, pip=Pip(report={"version": NEXT, "migrations": ["0014_next.sql"],
                                                         "ui": True}))
    updater.backup_problem = lambda: "нет pg_dump"
    updater.check()
    updater.install()
    body = problem(client.post(f"{V1}/updates/install"), 409, "backup_required", "/updates/install", "post")
    assert "нет pg_dump" in body["detail"]


def test_http_auto_off_by_setting_409(http):
    client, updater = http(person=True, env={"AMEMO_AUTO_UPDATE": "false"})
    problem(client.put(f"{V1}/updates", json={"auto": True}), 409, "auto_update_off", "/updates", "put")
    status = contract.check(client.get(f"{V1}/updates"), "/updates")
    assert status["auto_locked"] is True and status["auto"] is False      # интерфейс прячет переключатель


def test_http_tokens_read_only_checks_but_does_not_change(http, tmp_path):
    path = tokens_file(tmp_path, ("t-read", "person:ann", False), ("t-bot", "model:bot", True),
                       ("t-ann", "person:ann", True))
    client, updater = http(env={"AMEMO_TOKENS": path})
    read, bot, ann = ({"Authorization": f"Bearer {t}"} for t in ("t-read", "t-bot", "t-ann"))
    assert client.get(f"{V1}/updates").status_code == 401
    contract.check(client.get(f"{V1}/updates", headers=read), "/updates")
    contract.check(client.post(f"{V1}/updates/check", headers=read), "/updates/check", "post")
    problem(client.put(f"{V1}/updates", json={"auto": False}, headers=read), 403, "read_only", "/updates", "put")
    problem(client.post(f"{V1}/updates/install", headers=read), 403, "read_only", "/updates/install", "post")
    problem(client.put(f"{V1}/updates", json={"auto": False}, headers=bot), 403, "forbidden", "/updates", "put")
    assert contract.check(client.put(f"{V1}/updates", json={"auto": False}, headers=ann), "/updates", "put")[
        "auto"] is False


def test_status_schema_is_strict():
    status = {"current": CURRENT, "latest": None, "channel": "pre", "install": "pip", "auto": True, "state": "idle",
              "checked_at": None, "message": "проверки ещё не было"}
    contract.component("UpdateStatus", status)
    for broken in ({**status, "extra": 1}, {**status, "state": "busy"}, {**status, "install": "conda"},
                   {**status, "latest": {"version": NEXT}}):
        with pytest.raises(AssertionError):
            contract.component("UpdateStatus", broken)


# --- python -m amemo.service --check ---

def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT table_name FROM information_schema.tables "
                                       "WHERE table_schema = current_schema()")}


def test_check_rehearses_migrations_without_writing(pg, dsn, tmp_path, capsys):
    environ = state_env(tmp_path, AMEMO_DSN=dsn)
    assert _tables(pg) == set()
    assert server.main(["--check"], env=environ) == 0
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["version"] and report["migrations"] == sorted(p.name for p in db.SQL_DIR.glob("[0-9]*.sql"))
    assert _tables(pg) == set()                    # всё откатилось, даже учёт миграций
    db.prepare(pg)
    before = _tables(pg)
    assert server.main(["--check"], env=environ) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["migrations"] == []
    assert _tables(pg) == before


def test_check_runs_new_migrations_and_rolls_back(pg, dsn, tmp_path, monkeypatch, capsys):
    db.prepare(pg)
    folder = tmp_path / "sql"
    folder.mkdir()
    for path in db.SQL_DIR.glob("*.sql"):
        (folder / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    (folder / "9998_next.sql").write_text("CREATE TABLE next_table (id int);", encoding="utf-8")
    monkeypatch.setattr(db, "SQL_DIR", folder)
    environ = state_env(tmp_path, AMEMO_DSN=dsn)
    assert server.main(["--check"], env=environ) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["migrations"] == ["9998_next.sql"]
    assert "next_table" not in _tables(pg)
    assert pg.execute("SELECT count(*) FROM schema_migrations WHERE name = '9998_next.sql'").fetchone()[0] == 0
    (folder / "9999_broken.sql").write_text("CREATE TABLE broken (;", encoding="utf-8")
    assert server.main(["--check"], env=environ) == 1
    err = capsys.readouterr().err
    assert "9999_broken.sql" in err and "SyntaxError" in err           # точка сохранения на файл — файл назван
    assert "next_table" not in _tables(pg)


def sql_folder(tmp_path, **extra) -> Path:
    folder = tmp_path / "sql"
    folder.mkdir(exist_ok=True)
    for path in db.SQL_DIR.glob("*.sql"):
        (folder / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    for name, text in extra.items():
        (folder / f"{name}.sql").write_text(text, encoding="utf-8")
    return folder


def test_check_limited_by_one_transaction_is_its_own_code(pg, dsn, tmp_path, monkeypatch, capsys):
    """ALTER TYPE … ADD VALUE и новое значение в следующем файле: migrate (транзакция на файл) это применит,
    а одна общая транзакция — нет. Это предел проверки, не отказ версии: код CHECK_LIMITED."""
    monkeypatch.setattr(db, "SQL_DIR", sql_folder(tmp_path, **{"9997_color": "CREATE TYPE upd_color AS ENUM ('red');"}))
    db.prepare(pg)
    monkeypatch.setattr(db, "SQL_DIR", sql_folder(tmp_path, **{
        "9998_blue": "ALTER TYPE upd_color ADD VALUE 'blue';",
        "9999_use": "CREATE TABLE upd_paint AS SELECT 'blue'::upd_color AS color;"}))
    assert server.main(["--check"], env=state_env(tmp_path, AMEMO_DSN=dsn)) == updates.CHECK_LIMITED
    err = capsys.readouterr().err
    assert "не смогла прогнать миграции" in err and "9999_use.sql" in err
    assert "upd_paint" not in _tables(pg)


def test_check_sets_timeouts_before_migrations(pg, dsn, tmp_path, monkeypatch, capsys):
    db.prepare(pg)
    monkeypatch.setattr(db, "SQL_DIR", sql_folder(tmp_path, **{
        "9998_settings": "CREATE TABLE upd_seen AS SELECT current_setting('lock_timeout') AS lock, "
                         "current_setting('statement_timeout') AS statement;",
        "9999_fail": "SELECT 1 / (SELECT count(*) FROM upd_seen WHERE NOT (lock = '5s' AND statement = '1min'));"}))
    # 9999 делит на ноль, только если 9998 увидел оба таймаута: так тест читает их из откатываемой транзакции
    assert server.main(["--check"], env=state_env(tmp_path, AMEMO_DSN=dsn)) == 1
    assert "DivisionByZero" in capsys.readouterr().err


def test_check_is_postponed_while_migration_lock_is_held(pg, dsn, tmp_path, capsys):
    """Пока другой процесс держит замок миграций, проверка не ждёт и не идёт параллельно: код «отложено»."""
    import psycopg

    db.prepare(pg)
    other = psycopg.connect(dsn, autocommit=True)
    try:
        other.execute("SELECT pg_advisory_lock(%s)", (db.MIGRATION_LOCK,))
        assert server.main(["--check"], env=state_env(tmp_path, AMEMO_DSN=dsn)) == updates.CHECK_TEMPORARY
        assert "замок миграций занят" in capsys.readouterr().err
    finally:
        other.close()
    assert server.main(["--check"], env=state_env(tmp_path, AMEMO_DSN=dsn)) == 0


def test_check_without_database_is_temporary(tmp_path, capsys):
    environ = state_env(tmp_path, AMEMO_DSN="postgresql://nobody@127.0.0.1:1/none?connect_timeout=1")
    assert server.main(["--check"], env=environ) == updates.CHECK_TEMPORARY
    assert "база недоступна" in capsys.readouterr().err


# --- amemo update ---

@pytest.fixture
def cli_updates(monkeypatch):
    """amemo update с подставным GitHub и pip: вид установки — pip в venv (CLI сам его не узнает в CI)."""
    github, pip = GitHub([release("v" + FAR)]), Pip(version=FAR, current=amemo.__version__)
    monkeypatch.setattr(updates, "http_get", github)
    monkeypatch.setattr(updates, "run_step", pip)
    monkeypatch.setattr(updates, "detect", lambda: updates.Install("pip", ("web",)))
    monkeypatch.setattr(updates.Updater, "versions", lambda self: {"amemo": FAR, "amemo-web": FAR})
    monkeypatch.setattr(updates.Updater, "backup_problem", lambda self: None)
    return github, pip


def test_cli_update_check_json_and_text(run, cli_updates, env):
    code, out, err = run("update", "--json")
    assert code == 0, err
    status = json.loads(out)
    contract.component("UpdateStatus", status)
    assert status["latest"]["version"] == FAR
    code, out, _ = run("update", "check")
    assert code == 0 and f"доступна {FAR}" in out and "автообновление службы: включено" in out


def test_cli_update_check_network_failure_exit_1(run, cli_updates):
    cli_updates[0].down = True
    code, out, _ = run("update", "--json")
    assert code == 1 and "проверка не удалась" in json.loads(out)["message"]


def test_cli_update_auto_person_only(run, cli_updates, env):
    code, out, err = run("update", "auto", "off", "--json")
    assert code == 0, err
    assert json.loads(out)["auto"] is False
    assert json.loads((Path(env["AMEMO_STATE"]) / "updates.json").read_text(encoding="utf-8"))["auto"] is False
    code, _, err = run("update", "auto", "on", extra={"AMEMO_AS_MODEL": "bot"})
    assert code == 2 and "только человек" in err
    code, _, err = run("update", "auto", "on", extra={"AMEMO_AUTO_UPDATE": "false"})
    assert code == 6 and "auto_update" in err


def test_cli_update_install(run, cli_updates, env):
    code, _, err = run("update", "install", extra={"CLAUDECODE": "1"})
    assert code == 2 and "только человек" in err
    assert cli_updates[1].calls == []
    code, out, err = run("update", "install")
    assert code == 0, err
    assert f"ставится {FAR}" in err and "перезапустится сама" in out
    assert cli_updates[1].events == ["venv", "trial", "check", "install"]
    code, out, _ = run("update", "install", "--json")
    assert code == 0 and json.loads(out)["state"] == "ready"


def test_cli_update_install_unsupported_exit_1(run, cli_updates, monkeypatch):
    monkeypatch.setattr(updates, "detect", lambda: updates.Install("docker", reason="образ Docker"))
    code, out, err = run("update", "install")
    assert code == 1 and "docker compose" in err
    code, out, _ = run("update", "install", "--json")
    assert code == 1 and json.loads(out)["code"] == "update_unsupported"


def test_cli_update_install_failed_exit_1(run, cli_updates):
    cli_updates[1].check = 1
    code, out, _ = run("update", "install", "--json")
    assert code == 1 and json.loads(out)["state"] == "failed"


# --- amemo mcp после обновления ---

def test_stdio_mcp_answers_updated_and_finishes(env, kb, monkeypatch):
    disk = {"version": CURRENT}
    monkeypatch.setattr(updates, "disk_version", lambda name="amemo": disk["version"])

    async def main():
        with mcp.open_stdio(settings.load(env), agent="model:claude-code") as runtime:
            async with Client(mcp.build(runtime)) as client:
                first = await client.call_tool("amemo_vocab", {"scheme": "kind"})
                assert not first.is_error and not runtime.exiting
                disk["version"] = NEXT                     # amemo обновили под живым процессом
                runtime.next_version_check = 0
                second = await client.call_tool("amemo_vocab", {"scheme": "kind"})
                # вызов, на котором замечено обновление, выполняется как обычно; к ответу — «перезапустите агента»
                assert not second.is_error and second.structured_content == first.structured_content
                notice = second.content[-1].text
                assert notice.startswith("amemo_updated:") and "перезапустите агента" in notice and NEXT in notice
                assert runtime.exiting
    anyio.run(main)


def test_stdio_main_exits_after_updated_answer(monkeypatch):
    monkeypatch.setattr(mcp, "EXIT_GRACE", 0.01)

    class Runtime:
        done = None

        def refresh_version(self):
            return None

    runtime = Runtime()

    async def server():
        await anyio.sleep(0.05)
        runtime.done.set()                         # так делает finish() после ответа amemo_updated
        await anyio.sleep_forever()

    async def main():
        with anyio.fail_after(5):
            await mcp.stdio_main(runtime, server)
    anyio.run(main)


def test_preload_imports_the_whole_package():
    assert updates.preload() == []



# --- ревью: /ui прежней сборки, кэш ручной проверки, отказы установки, адрес релиза ---

def test_service_preloads_and_serves_old_ui_until_restart(http, tmp_path, monkeypatch):
    import sys
    import types

    dist = tmp_path / "web" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>прежняя сборка</html>", encoding="utf-8")
    module = types.ModuleType("amemo_web")
    module.static_dir = lambda: dist
    monkeypatch.setitem(sys.modules, "amemo_web", module)
    loaded = []
    real = updates.preload
    monkeypatch.setattr(updates, "preload", lambda: loaded.append(True) or real())
    client, updater = http()
    assert loaded == [True]                              # весь пакет — в памяти при старте службы
    assert "прежняя сборка" in client.get("/ui/").text
    updater.check()
    assert updater.install()["state"] == "ready"
    (dist / "index.html").write_text("<html>новая сборка</html>", encoding="utf-8")     # файлы пакета заменены
    copy = tmp_path / "state" / "updates" / f"ui-{CURRENT}"
    assert client.app.state.ui_root == copy.resolve()
    assert "прежняя сборка" in client.get("/ui/").text
    make(tmp_path, current=NEXT).startup()               # новый процесс убирает копию прежней сборки
    assert not copy.exists()


def test_manual_check_at_most_once_a_minute(tmp_path):
    from datetime import datetime, timedelta, timezone

    moment = {"now": datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)}
    github = GitHub([release("v" + NEXT)])
    updater = make(tmp_path, github=github, now=lambda: moment["now"])
    assert updater.check(manual=True)["state"] == "available"
    assert updater.check(manual=True)["state"] == "available"
    assert len(github.release_calls()) == 1              # вторая — из кэша
    moment["now"] += timedelta(seconds=updates.MANUAL_EVERY + 1)
    updater.check(manual=True)
    updater.check()                                       # плановая проверка кэшем не ограничена
    assert len(github.release_calls()) == 3


def test_ready_to_install_respects_state_and_failed_versions(tmp_path):
    updater = ready(tmp_path / "a")
    with pytest.raises(updates.UpdateError, match="уже установлена") as refused:
        updater.ready_to_install()
    assert refused.value.code == "no_update"
    other = make(tmp_path / "b")
    other.check()
    with other._changing() as data:
        data["failed"] = [NEXT]
    with pytest.raises(updates.UpdateError, match="уже не встала"):
        other.ready_to_install()


def test_release_url_only_from_our_repository(tmp_path):
    foreign = {"tag_name": "v" + NEXT, "html_url": "https://example.org/amemo/releases/tag/v0.1.0a2"}
    assert updates.parse_releases([foreign])[0].url is None
    status = make(tmp_path, github=GitHub([foreign])).check()
    contract.component("UpdateStatus", status)
    assert status["latest"] == {"version": NEXT, "url": None}


def test_http_put_accepts_only_auto(http):
    client, _ = http(person=True)
    problem(client.put(f"{V1}/updates", json={"auto": False, "extra": 1}), 400, "bad_request", "/updates", "put")
    with pytest.raises(AssertionError):
        contract.check_request({"auto": False, "extra": 1}, "/updates", "put")
