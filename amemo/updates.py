"""Обновления amemo (спецификация docs/superpowers/specs/2026-11-10-amemo-updates-design.md, разд. 2, 3, 6).

Источник правды — релизы GitHub нашего репозитория (REPO зашит в код: из настроек его не взять). Проверка — при старте
службы и раз в CHECK_EVERY, с If-None-Match (ETag): без токена это укладывается в лимит API. Ошибка сети или API —
тихо: итог и время последней проверки — в статусе, следующая попытка — по расписанию.

Выбор релиза: черновики пропускаются; канал — по текущей версии (предварительная a/b/rc/dev — канал pre: и стабильные,
и предварительные; стабильная — stable: только стабильные); порядок — packaging.version, а не дата; берётся
наибольшая версия новее текущей, у которой на PyPI есть колесо (и колесо amemo-web, если веб стоит); версия, которая
однажды не встала, больше не пробуется.

Вид установки (detect) определяется при старте: pipx, uv (uv tool install), pip в venv, docker, source (editable или
поставлен не с PyPI — локальное колесо, git). Ставят только pipx, uv и pip; docker и source — только сообщают, чем
обновиться. Временное окружение pipx run не обновляется.

Установка (Updater.install) — под файловым замком AMEMO_STATE/updates.install.lock (служба и amemo update из CLI
не ставят одновременно):
  1. временный venv AMEMO_STATE/updates/<X>, в нём pip install "amemo[…]==X";
  2. там же python -I -m amemo.service --check (self_check): импорт всего пакета, сборка приложения и /ui, миграции
     новой версии — в транзакции с откатом на рабочей базе под замком миграций (db.rehearse); в базу — ничего.
     Не прошла — failed, версия больше не пробуется; рабочая установка не тронута;
  3. у новой версии есть новые миграции — сначала бэкап (backup.create без ротации); бэкап невозможен — версия
     не ставится: available и «нужен бэкап: …»;
  4. установка на место — pipx, uv или pip той же среды, точная версия ==X, без --index-url (зеркало и настройки pip
     пользователя работают); упала — запасной откат на прежнюю ==;
  5. сверка importlib.metadata.version у amemo и amemo-web в новом процессе; не сошлось — failed (и откат).
Временный venv удаляется в любом исходе. Затем ready: служба перезапускается сама в простое (watch: нет запросов HTTP
IDLE секунд, ни одного занятого соединения пула, ничего не ставится) — os.execv того же процесса с теми же
аргументами; при старте db.prepare применит миграции. Установку из CLI служба тоже замечает: версия на диске
сменилась — ready и перезапуск в простое.

Состояние — AMEMO_STATE/updates.json (замок updates.json.lock, запись — временный файл и переименование): переключатель
auto из веба, ETag и список релизов, итог проверки, последняя доступная версия, не вставшие версии, журнал (что,
когда, каким способом ставилось). checking и installing не пишутся в файл: их показывает сам процесс (и замок
установки — для другого процесса), поэтому оборванная проверка или установка не оставляет вечного «installing».
"""
from __future__ import annotations

import contextlib
import importlib
import importlib.metadata
import importlib.util
import json
import logging
import os
import pkgutil
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from packaging.version import InvalidVersion, Version

from . import __version__, portable

REPO = "empty-complete/amemo"                    # только этот репозиторий: адрес не настраивается
RELEASES = f"https://api.github.com/repos/{REPO}/releases?per_page=100"
PYPI = "https://pypi.org/pypi/{name}/{version}/json"
PACKAGE, WEB = "amemo", "amemo-web"
CHECK_EVERY = 6 * 3600         # с между проверками релизов
IDLE = 120.0                   # с без запросов HTTP — служба свободна для перезапуска
TICK = 15.0                    # с между взглядами службы на простой и версию на диске
HTTP_TIMEOUT = 15.0            # с на запрос к GitHub и PyPI
HTTP_MAX = 4 << 20             # байт ответа API — больше не читаем
PYPI_TRIES = 5                 # кандидатов, которых сверяем с PyPI за одну проверку
STEP_TIMEOUT = 1800            # с на шаг установки (venv, pip, pipx, uv)
CHECK_TIMEOUT = 600            # с на --check новой версии
JOURNAL_KEPT = 200             # записей журнала в updates.json
OUTPUT_KEPT = 2000             # знаков вывода упавшей команды в сообщении и журнале
CHECK_TEMPORARY = 3            # код выхода --check: проверка не состоялась (база недоступна или занята) — позже
STATES = ("idle", "checking", "available", "installing", "ready", "restarting", "failed")
KINDS = ("pipx", "pip", "uv", "docker", "source")
INSTALLERS = frozenset({"pipx", "pip", "uv"})
STATE_FILE, STATE_LOCK, INSTALL_LOCK, VENVS = "updates.json", "updates.json.lock", "updates.install.lock", "updates"
# строка для нового процесса: версии на диске после установки (importlib.metadata внутри процесса может помнить старое)
VERSIONS_SCRIPT = ("import importlib.metadata as m, json\n"
                   "def v(n):\n"
                   "    try:\n        return m.version(n)\n"
                   "    except m.PackageNotFoundError:\n        return None\n"
                   f"print(json.dumps({{'amemo': v({PACKAGE!r}), 'amemo-web': v({WEB!r})}}))")
log = logging.getLogger("amemo.updates")


class UpdateError(ValueError):
    """Отказ обновления, который служба отдаёт как 409 с кодом: update_unsupported, backup_required, no_update,
    update_busy, auto_update_off."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class NetworkError(Exception):
    """GitHub или PyPI не ответили как надо: сеть, таймаут, статус, не JSON."""


# --- версии и релизы ---

def channel(current: str) -> str:
    """pre — стоит предварительная версия (a, b, rc, dev), иначе stable."""
    try:
        return "pre" if Version(current).is_prerelease else "stable"
    except InvalidVersion:
        return "stable"


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    prerelease: bool

    def view(self) -> dict:
        return {"version": self.version, "url": self.url}


def parse_releases(data) -> list[Release]:
    """Релизы из ответа GitHub: черновики и метки, которые не версия (v0.1.0, 0.1.0), пропускаются."""
    if not isinstance(data, list):
        raise NetworkError("GitHub: ответ — не список релизов")
    out = []
    for item in data:
        if not isinstance(item, dict) or item.get("draft") or not isinstance(item.get("tag_name"), str):
            continue
        tag = item["tag_name"].strip()
        try:
            version = Version(tag[1:] if tag[:1] in ("v", "V") else tag)
        except InvalidVersion:
            continue
        url = item.get("html_url") if isinstance(item.get("html_url"), str) else \
            f"https://github.com/{REPO}/releases/tag/{tag}"
        out.append(Release(str(version), url, bool(item.get("prerelease")) or version.is_prerelease))
    return out


def candidates(releases: Sequence[Release], current: str, *, skip: Sequence[str] = ()) -> list[Release]:
    """Релизы новее текущей версии в её канале, от наибольшей; skip — версии, которые не встали."""
    now = Version(current)
    pre = channel(current) == "pre"
    skipped = set()
    for value in skip:
        with contextlib.suppress(InvalidVersion):
            skipped.add(Version(value))
    found = [r for r in releases if Version(r.version) > now and (pre or not r.prerelease)
             and Version(r.version) not in skipped]
    return sorted(found, key=lambda r: Version(r.version), reverse=True)


def http_get(url: str, headers: Mapping[str, str] | None = None, *, timeout: float = HTTP_TIMEOUT) \
        -> tuple[int, dict[str, str], bytes]:
    """GET без токенов: статус, заголовки (имена строчными) и тело. Ошибка сети — NetworkError."""
    request = urllib.request.Request(url, headers={"User-Agent": f"amemo/{__version__}",
                                                   "Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read(HTTP_MAX)
    except urllib.error.HTTPError as e:                  # 304, 404, 403 лимита — ответ, а не сбой сети
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, b""
    except (OSError, ValueError) as e:                   # URLError, таймаут, обрыв
        raise NetworkError(f"{url.split('/')[2]}: {getattr(e, 'reason', None) or e}") from None


def _json(body: bytes, where: str):
    try:
        return json.loads(body)
    except ValueError:
        raise NetworkError(f"{where}: ответ — не JSON") from None


def has_wheel(get: Callable, name: str, version: str) -> bool:
    """Есть ли на PyPI колесо name==version (не отозванное)."""
    status, _, body = get(PYPI.format(name=name, version=version))
    if status == 404:
        return False
    if status != 200:
        raise NetworkError(f"PyPI {name} {version}: ответ {status}")
    files = _json(body, "PyPI").get("urls") or []
    return any(isinstance(f, dict) and f.get("packagetype") == "bdist_wheel" and not f.get("yanked") for f in files)


# --- вид установки ---

@dataclass(frozen=True)
class Install:
    kind: str                       # pipx | pip | uv | docker | source
    extras: tuple[str, ...] = ()    # extras amemo, которые стоят сейчас (web, embed): ставятся и в новую версию
    reason: str | None = None       # почему этот вид не ставит сам (None — ставит)
    tool: str | None = None         # pipx или uv: путь к команде

    @property
    def can_install(self) -> bool:
        return self.kind in INSTALLERS and self.reason is None

    def spec(self, version: str) -> str:
        return f"{PACKAGE}[{','.join(self.extras)}]=={version}" if self.extras else f"{PACKAGE}=={version}"

    def command(self, version: str, python: str = sys.executable) -> list[str]:
        """Команда установки на место — без --index-url и без shell."""
        if self.kind == "pipx":
            return [self.tool or "pipx", "install", "--force", self.spec(version)]
        if self.kind == "uv":
            return [self.tool or "uv", "tool", "install", "--force", self.spec(version)]
        return [python, "-m", "pip", "install", "--disable-pip-version-check", self.spec(version)]

    def advice(self, version: str | None) -> str:
        """Как обновиться человеку — для docker, source и случаев, когда ставить самой нельзя."""
        if self.kind == "docker":
            return "обновите образ: git pull, затем docker compose up -d --build"
        if self.kind == "source":
            if "не с PyPI" in (self.reason or ""):
                return "поставьте новую версию тем же способом, каким ставили эту"
            return "обновите рабочую копию: git pull, затем pip install -e ."
        if version is None:
            return "обновлений нет"
        return " ".join(f'"{part}"' if "[" in part or "=" in part else part for part in self.command(version))


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() not in ("", "0", "false", "no", "off")


def _dist(name: str):
    try:
        return importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def detect(env: Mapping[str, str] | None = None, *, prefix: str | None = None, base_prefix: str | None = None,
           dist=None, extras: tuple[str, ...] | None = None, which: Callable = shutil.which,
           dockerenv: str = "/.dockerenv", has_pip: bool | None = None) -> Install:
    """Вид установки текущего процесса. Аргументы — для тестов; по умолчанию — sys и importlib.metadata."""
    env = os.environ if env is None else env
    prefix = Path(sys.prefix if prefix is None else prefix)
    base_prefix = Path(sys.base_prefix if base_prefix is None else base_prefix)
    if _truthy(env.get("AMEMO_IN_CONTAINER")) or os.path.exists(dockerenv):
        return Install("docker", reason="образ Docker")
    dist = _dist(PACKAGE) if dist is None else dist
    if dist is None:
        return Install("source", reason="пакет amemo не установлен — код запущен из исходников")
    if extras is None:
        extras = tuple(name for name, package in (("web", WEB), ("embed", "fastembed")) if _dist(package))
    direct = None
    with contextlib.suppress(ValueError, TypeError):
        direct = json.loads(dist.read_text("direct_url.json") or "null")
    if isinstance(direct, dict):
        if (direct.get("dir_info") or {}).get("editable"):
            return Install("source", extras, reason="editable-установка из рабочей копии")
        return Install("source", extras, reason=f"поставлен не с PyPI ({direct.get('url') or 'прямая ссылка'})")
    with contextlib.suppress(ValueError, OSError):
        where = Path(dist.locate_file("")).resolve()
        if not where.is_relative_to(prefix.resolve()):
            return Install("source", extras, reason=f"пакет amemo лежит вне окружения {prefix} (PYTHONPATH)")
    parts = [part.lower() for part in prefix.parts]
    if (prefix / "pipx_metadata.json").exists() or "pipx" in parts:
        if any(part in (".cache", "cache") for part in parts):
            return Install("pipx", extras, reason="временное окружение pipx run — свежую версию оно возьмёт само "
                                                  "при следующем запуске")
        tool = which("pipx")
        return Install("pipx", extras, reason=None if tool else "нет команды pipx в PATH", tool=tool)
    if (prefix / "uv-receipt.toml").exists():
        tool = which("uv")
        return Install("uv", extras, reason=None if tool else "нет команды uv в PATH", tool=tool)
    if prefix.resolve() == base_prefix.resolve():
        return Install("pip", extras, reason="системный Python, не venv — обновлять его amemo не берётся")
    if not os.access(prefix, os.W_OK):
        return Install("pip", extras, reason=f"venv {prefix} недоступен на запись этому пользователю")
    if not (importlib.util.find_spec("pip") is not None if has_pip is None else has_pip):
        return Install("pip", extras, reason="в окружении нет pip")
    return Install("pip", extras)


def disk_version(name: str = PACKAGE) -> str | None:
    """Версия пакета на диске сейчас (а не та, что в памяти процесса)."""
    importlib.invalidate_caches()
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def preload(package: str = PACKAGE) -> list[tuple[str, str]]:
    """Импортировать все модули пакета заранее: после замены файлов на диске процесс доживает на коде из памяти,
    а не смешивает старое с новым. Вернуть модули, которые не импортировались, и причину."""
    root = importlib.import_module(package)
    failed = []
    for info in pkgutil.walk_packages(root.__path__, f"{package}."):
        if info.name.rsplit(".", 1)[-1] == "__main__":        # __main__ запускает команду, а не модуль
            continue
        try:
            importlib.import_module(info.name)
        except Exception as e:  # noqa: BLE001 — причина уходит в отчёт --check
            failed.append((info.name, f"{type(e).__name__}: {e}"))
    return failed


# --- проверка новой версии: python -m amemo.service --check ---

def self_check(settings) -> dict:
    """Проверка этой версии кода на рабочей базе без записи: импорт всего пакета, сборка приложения и /ui, миграции
    в транзакции с откатом (db.rehearse). Ответ: version, migrations (новые для базы), ui (есть ли сборка веба)."""
    failed = preload()
    if failed:
        raise RuntimeError("не импортируются: " + "; ".join(f"{name} ({why})" for name, why in failed))
    from . import db
    from .service import app as app_
    from .service import problems, ui

    app_.create_app(settings)                      # маршруты, защита, MCP — без lifespan: пул не открывается
    try:
        ui.static_root()
        has_ui = True
    except problems.Problem:
        has_ui = False
    conn = db.connect(settings.dsn, connect_timeout=10)
    try:
        migrations = db.rehearse(conn)
    finally:
        conn.close()
    return {"version": __version__, "migrations": migrations, "ui": has_ui}


def run_check(settings, out=None, err=None) -> int:
    """--check: JSON self_check в stdout и код 0; база недоступна или занята — CHECK_TEMPORARY; прочее — 1."""
    import psycopg

    out, err = out or sys.stdout, err or sys.stderr
    try:
        result = self_check(settings)
    except psycopg.OperationalError as e:
        print(f"amemo --check: база недоступна или занята: {type(e).__name__}: {e}", file=err)
        return CHECK_TEMPORARY
    except Exception as e:  # noqa: BLE001 — любой сбой проверки — отказ этой версии
        print(f"amemo --check: {type(e).__name__}: {e}", file=err)
        return 1
    print(json.dumps(result, ensure_ascii=False), file=out)
    return 0


# --- состояние ---

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _tail(text: str | bytes | None) -> str:
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    text = (text or "").strip()
    return text if len(text) <= OUTPUT_KEPT else "…" + text[-OUTPUT_KEPT:]


@dataclass
class Step:
    returncode: int
    output: str                     # stdout и stderr вместе (хвост) — для сообщения и журнала
    stdout: str = ""                # stdout целиком — ответ команды (JSON у --check)


def run_step(argv: Sequence[str], *, timeout: float = STEP_TIMEOUT, cwd: str | None = None) -> Step:
    """Шаг установки: процесс без shell, окружение — как у службы, но без PYTHONPATH и PYTHONHOME (новая версия
    не должна видеть старый код); вывод — stdout и stderr вместе."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP")}
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    try:
        done = subprocess.run(list(argv), env=env, cwd=cwd, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as e:
        return Step(124, f"{Path(argv[0]).name}: не уложился в {timeout:g} с\n{_tail(e.output)}")
    except OSError as e:
        return Step(127, f"{argv[0]} не запускается: {e}")
    stdout = done.stdout.decode("utf-8", "replace")
    return Step(done.returncode, _tail(stdout) + ("\n" + _tail(done.stderr) if done.stderr else ""), stdout)


def restart_process(path: str, args: Sequence[str]) -> None:
    """Заменить процесс службы новым с теми же аргументами (os.execv): сокеты и соединения закрываются (CLOEXEC)."""
    os.execv(path, list(args))


class Updater:
    """Обновления одного процесса (служба или CLI) над AMEMO_STATE. Всё внешнее подставляется: get — HTTP GET,
    run — шаги установки, backup — бэкап (dsn, папка) → манифест, clock — монотонные часы, now — время UTC,
    execv — перезапуск, versions — версии на диске новым процессом, disk — версия на диске в этом процессе."""

    def __init__(self, settings, *, install: Install | None = None, current: str = __version__,
                 get: Callable | None = None, run: Callable | None = None, backup: Callable | None = None,
                 clock: Callable[[], float] = time.monotonic, now: Callable[[], datetime] = _utcnow,
                 execv: Callable | None = None, python: str = sys.executable, argv: Sequence[str] | None = None,
                 versions: Callable[[], dict] | None = None, disk: Callable[[], str | None] | None = None,
                 windows: bool = portable.WINDOWS) -> None:
        self.settings = settings
        self.root = Path(settings.state)
        self.kind = install if install is not None else detect()
        self.current = current
        # по умолчанию — функции модуля, взятые в момент вызова: тесты подменяют их у модуля (tests/conftest.py)
        self.get = get or (lambda url, headers=None: http_get(url, headers))
        self.run = run or (lambda argv, **kw: run_step(argv, **kw))
        self.execv = execv or (lambda path, args: restart_process(path, args))
        self.clock, self.now = clock, now
        self._backup = backup
        self.python = python
        self.argv = list(sys.orig_argv[1:] if argv is None else argv)
        self._versions = versions
        self.disk = disk or (lambda: disk_version())
        self.windows = windows
        self.baseline = self.disk()            # версия на диске при старте: сменилась — поставил кто-то другой
        self.before_restart: Callable[[], None] = lambda: None
        self._lock = threading.Lock()          # проверки и смены состояния одного процесса — по очереди
        self._checking = False
        self._installing: str | None = None   # версия, которую ставит этот процесс
        self._thread: threading.Thread | None = None

    # --- файл состояния ---

    @property
    def path(self) -> Path:
        return self.root / STATE_FILE

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            log.warning("%s не читается (%s): состояние обновлений — с нуля", self.path, e)
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict) -> None:
        tmp = self.path.with_name(f".{STATE_FILE}.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | portable.O_BINARY, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        with contextlib.suppress(OSError):
            portable.fsync_dir(self.root)

    @contextlib.contextmanager
    def _changing(self):
        """Прочитать, изменить и записать updates.json под замком файла (другой процесс ждёт)."""
        self._ensure_root()
        with portable.file_lock(self.root / STATE_LOCK):
            data = self.read()
            yield data
            self._write(data)

    def _journal(self, data: dict, event: str, version: str | None = None, detail: str | None = None) -> None:
        entry = {"at": _iso(self.now()), "event": event, "version": version, "method": self.kind.kind,
                 "from": self.current}
        if detail:
            entry["detail"] = detail
        data["journal"] = [*(data.get("journal") or []), entry][-JOURNAL_KEPT:]
        log.info("обновление: %s %s (%s, с %s)%s", event, version or "", self.kind.kind, self.current,
                 f": {detail}" if detail else "")

    # --- статус ---

    def auto(self, data: dict | None = None) -> bool:
        """Автообновление: auto_update настроек выключает его совсем; иначе — переключатель (по умолчанию вкл.)."""
        data = self.read() if data is None else data
        return bool(self.settings.auto_update) and data.get("auto") is not False

    def _install_busy(self) -> bool:
        if self._installing:
            return True
        self._ensure_root()
        with portable.try_file_lock(self.root / INSTALL_LOCK) as taken:
            return not taken

    def _latest(self, data: dict) -> dict | None:
        latest = data.get("latest")
        if not isinstance(latest, dict):
            return None
        try:
            return latest if Version(latest["version"]) > Version(self.current) else None
        except (InvalidVersion, KeyError, TypeError):
            return None

    def status(self, data: dict | None = None) -> dict:
        """UpdateStatus контракта: current, latest, channel, install, auto, state, checked_at, message."""
        data = self.read() if data is None else data
        latest = self._latest(data)
        state = data.get("state") if data.get("state") in STATES else "idle"
        message = data.get("message") if isinstance(data.get("message"), str) else None
        if state in ("idle", "available"):
            plain = "available" if latest else "idle"
            if plain != state or state == "available":
                message = None             # «доступна …» — по виду установки и переключателю, а не из файла
            state = plain
        if self._install_busy():
            state = "installing"
            message = f"ставится {self._installing}" if self._installing else \
                "ставится обновление (другим процессом amemo)"
        elif self._checking:
            state = "checking"
        if message is None:
            message = self._describe(state, latest, data)
        return {"current": self.current, "latest": {"version": latest["version"], "url": latest["url"]}
                if latest else None, "channel": channel(self.current), "install": self.kind.kind,
                "auto": self.auto(data), "state": state, "checked_at": data.get("checked_at"), "message": message}

    def _describe(self, state: str, latest: dict | None, data: dict) -> str:
        if state == "checking":
            return "идёт проверка релизов"
        if state == "installing":
            return "ставится обновление"
        if latest is None:
            if data.get("check_error"):
                return f"проверка не удалась: {data['check_error']}; следующая — по расписанию"
            return "обновлений нет" if data.get("checked_at") else "проверки ещё не было"
        version = latest["version"]
        need = data.get("backup_needed") or {}
        if need.get("version") == version:
            return f"доступна версия {version}, но нужен бэкап: {need.get('reason')}"
        if not self.kind.can_install:
            return f"доступна версия {version} — {self.kind.reason}; {self.kind.advice(version)}" \
                if self.kind.kind in INSTALLERS else f"доступна версия {version} — {self.kind.advice(version)}"
        if self.auto(data):
            return f"доступна версия {version} — служба поставит её сама"
        return f"доступна версия {version} — «Обновить сейчас» или amemo update install"

    # --- проверка ---

    def _fetch(self, data: dict) -> list[Release]:
        headers = {"If-None-Match": data["etag"]} if isinstance(data.get("etag"), str) and data.get("releases") \
            is not None else {}
        status, response_headers, body = self.get(RELEASES, headers)
        if status == 304:
            return [Release(r["version"], r["url"], bool(r.get("prerelease"))) for r in data.get("releases") or []
                    if isinstance(r, dict) and isinstance(r.get("version"), str)]
        if status != 200:
            raise NetworkError(f"GitHub: ответ {status}" + (" (лимит запросов)" if status in (403, 429) else ""))
        releases = parse_releases(_json(body, "GitHub"))
        data["etag"] = response_headers.get("etag")
        data["releases"] = [{"version": r.version, "url": r.url, "prerelease": r.prerelease} for r in releases]
        return releases

    def _choose(self, releases: list[Release], data: dict) -> Release | None:
        for release in candidates(releases, self.current, skip=data.get("failed") or [])[:PYPI_TRIES]:
            names = [PACKAGE, *([WEB] if "web" in self.kind.extras else [])]
            if all(has_wheel(self.get, name, release.version) for name in names):
                return release
        return None

    def check(self) -> dict:
        """Проверить релизы сейчас. Ошибка сети или API — тихо: итог в check_error, статус прежний."""
        with self._lock:
            self._checking = True
            try:
                snapshot = self.read()
                error = None
                try:
                    found = self._choose(self._fetch(snapshot), snapshot)
                except NetworkError as e:
                    error, found = str(e), None
                    log.info("проверка обновлений не удалась: %s", e)
                with self._changing() as data:
                    data["checked_at"] = _iso(self.now())
                    data["check_error"] = error
                    if error is None:
                        data["etag"], data["releases"] = snapshot.get("etag"), snapshot.get("releases")
                        data["latest"] = found.view() if found else None
                        if data.get("state") in (None, "idle", "available"):
                            data["state"], data["message"] = ("available" if found else "idle"), None
                        elif data.get("state") == "failed" and found:
                            data["state"], data["message"] = "available", None     # новее той, что не встала
            finally:
                self._checking = False
        return self.status()

    def set_auto(self, auto: bool) -> dict:
        if not isinstance(auto, bool):
            raise UpdateError("bad_request", "auto: нужно true или false")
        if auto and not self.settings.auto_update:
            raise UpdateError("auto_update_off", "автообновление выключено настройкой auto_update (amemo.toml или "
                                                 "AMEMO_AUTO_UPDATE) — включите его там")
        with self._lock, self._changing() as data:
            data["auto"] = auto
            self._journal(data, "auto on" if auto else "auto off")
            status = self.status(data)
        return status

    # --- установка ---

    def backup_problem(self) -> str | None:
        """Почему бэкап сейчас невозможен (нет клиента PostgreSQL 18, папка бэкапов не создаётся) или None."""
        from . import backup

        try:
            backup._tool("pg_dump")
            Path(self.settings.backups).mkdir(parents=True, exist_ok=True)
        except (backup.BackupError, OSError) as e:
            return str(e)
        if not self.settings.dsn:
            return "база не задана (AMEMO_DSN)"
        return None

    def _make_backup(self) -> dict:
        if self._backup is not None:
            return self._backup(self.settings.dsn, Path(self.settings.backups))
        from . import backup

        return backup.create(self.settings.dsn, Path(self.settings.backups), keep=None)

    def ready_to_install(self) -> str:
        """Версия, которую можно ставить сейчас; иначе UpdateError с кодом и словами (для 409 и CLI)."""
        data = self.read()
        latest = self._latest(data)
        if not self.kind.can_install:
            version = latest["version"] if latest else None
            raise UpdateError("update_unsupported", f"{self.kind.reason or 'этот вид установки не обновляется сам'}"
                                                    f": {self.kind.advice(version)}")
        if latest is None:
            raise UpdateError("no_update", "обновлений нет: ставить нечего (проверить заново — amemo update check)")
        if self._install_busy():
            raise UpdateError("update_busy", "обновление уже ставится")
        need = data.get("backup_needed") or {}
        if need.get("version") == latest["version"]:
            problem = self.backup_problem()
            if problem is not None:
                raise UpdateError("backup_required", f"у версии {latest['version']} новые миграции, а бэкап "
                                                     f"невозможен: {problem}")
        return latest["version"]

    def start_install(self) -> dict:
        """Поставить доступную версию в фоне (POST /updates/install): отказы, известные заранее, — UpdateError."""
        version = self.ready_to_install()
        self._installing = version
        thread = threading.Thread(target=self._install_in_background, args=(version,), name="amemo-update",
                                  daemon=True)
        self._thread = thread
        thread.start()
        return self.status()

    def _install_in_background(self, version: str) -> None:
        try:
            self.install(version)
        except UpdateError as e:
            log.info("обновление до %s не началось: %s", version, e)
        except Exception:  # noqa: BLE001 — фоновая установка не роняет службу
            log.exception("обновление до %s: необработанная ошибка", version)
            with self._changing() as data:
                data["state"], data["message"] = "failed", f"обновление до {version} не встало: внутренняя ошибка"
        finally:
            self._installing = None

    def install(self, version: str | None = None) -> dict:
        """Поставить version (по умолчанию доступную) по шагам разд. 2 п. 6 под замком установки; вернуть статус."""
        version = version or self.ready_to_install()
        self._ensure_root()
        with portable.try_file_lock(self.root / INSTALL_LOCK) as taken:
            if not taken:
                raise UpdateError("update_busy", "обновление уже ставится (другой процесс amemo)")
            self._installing = version
            try:
                self._install(version)
            finally:
                self._installing = None
                shutil.rmtree(self.root / VENVS / version, ignore_errors=True)
        return self.status()

    def _set(self, state: str | None, message: str | None, event: str, version: str, detail: str | None = None,
             **fields) -> None:
        """Записать переход (state None — состояние прежнее, только журнал); failed — версия больше не пробуется."""
        with self._changing() as data:
            if state is not None:
                data["state"], data["message"] = state, message
            for key, value in fields.items():
                data[key] = value
            if state == "failed":
                data["failed"] = sorted({*(data.get("failed") or []), version}, key=Version)
            self._journal(data, event, version, detail)

    def _venv_python(self, venv: Path) -> str:
        return str(venv / ("Scripts" if self.windows else "bin") / ("python.exe" if self.windows else "python"))

    def _install(self, version: str) -> None:
        kind = self.kind
        self._set(None, None, "install start", version, detail=" ".join(kind.command(version, self.python)))
        venv = self.root / VENVS / version
        shutil.rmtree(venv, ignore_errors=True)
        venv.parent.mkdir(parents=True, exist_ok=True)
        python = self._venv_python(venv)
        trial_spec = f"{PACKAGE}[web]=={version}" if "web" in kind.extras else f"{PACKAGE}=={version}"
        for argv in ([self.python, "-m", "venv", str(venv)],
                     [python, "-m", "pip", "install", "--disable-pip-version-check", trial_spec]):
            step = self.run(argv)
            if step.returncode != 0:
                return self._set("failed", f"обновление до {version} не встало: временное окружение не собралось "
                                 f"({Path(argv[0]).name} {' '.join(argv[1:3])}): {step.output[-300:]}",
                                 "trial failed", version, detail=step.output)
        step = self.run([python, "-I", "-m", "amemo.service", "--check"], timeout=CHECK_TIMEOUT, cwd=str(venv))
        if step.returncode == CHECK_TEMPORARY:
            return self._set("available", f"проверка {version} отложена: {step.output[-300:]}", "check postponed",
                             version, detail=step.output)
        report = None
        if step.returncode == 0:
            with contextlib.suppress(ValueError, IndexError):
                report = json.loads(step.stdout.strip().splitlines()[-1])
        if not isinstance(report, dict) or report.get("version") != version:
            return self._set("failed", f"обновление до {version} не встало: проверка новой версии не прошла: "
                             f"{step.output[-500:]}", "check failed", version, detail=step.output)
        if "web" in kind.extras and not report.get("ui"):
            return self._set("failed", f"обновление до {version} не встало: в новой версии нет сборки веб-интерфейса",
                             "check failed", version)
        made = None
        if report.get("migrations"):
            problem = self.backup_problem()
            if problem is None:
                try:
                    made = self._make_backup()
                except Exception as e:  # noqa: BLE001 — BackupError, OSError: бэкапа нет — версия не ставится
                    problem = str(e)
            if problem is not None:
                return self._set("available", None, "backup required", version, detail=problem,
                                 backup_needed={"version": version, "reason": problem})
        manifest = made.get("manifest") if made else None
        step = self.run(kind.command(version, self.python))
        if step.returncode != 0:
            return self._rollback(version, f"установка на место упала: {step.output[-300:]}", step.output, manifest)
        found = self.versions()
        if found.get("amemo") != version or ("web" in kind.extras and found.get("amemo-web") != version):
            return self._rollback(version, f"после установки на диске amemo {found.get('amemo')}, amemo-web "
                                  f"{found.get('amemo-web')}, а не {version}", json.dumps(found), manifest)
        restore = f"; если новая версия не запустится — amemo backup restore {manifest}" if manifest else ""
        return self._set("ready", f"обновление {version} установлено — перезапуск, когда служба освободится{restore}",
                         "installed", version, detail=manifest and f"бэкап {manifest}",
                         installed={"version": version, "previous": self.current, "at": _iso(self.now()),
                                    "backup": manifest}, backup_needed=None)

    def _rollback(self, version: str, why: str, output: str, manifest: str | None) -> None:
        back = self.run(self.kind.command(self.current, self.python))
        if back.returncode == 0:
            tail = f"прежняя версия {self.current} поставлена заново"
        else:
            tail = (f"вернуть {self.current} не удалось — поставьте её сами: {self.kind.advice(self.current)}"
                    + (f"; бэкап базы — {manifest}" if manifest else ""))
        return self._set("failed", f"обновление до {version} не встало: {why}; {tail}", "install failed", version,
                         detail=f"{output}\nоткат: {back.returncode} {back.output}")

    def versions(self) -> dict:
        """Версии amemo и amemo-web на диске — новым процессом той же среды."""
        if self._versions is not None:
            return self._versions()
        step = self.run([self.python, "-I", "-c", VERSIONS_SCRIPT], timeout=60)
        with contextlib.suppress(ValueError, IndexError):
            found = json.loads(step.stdout.strip().splitlines()[-1])
            if isinstance(found, dict):
                return found
        return {}

    # --- служба: расписание, простой, перезапуск ---

    def startup(self) -> None:
        """Служба стартовала: завершить переход после перезапуска (или признать, что он не удался)."""
        with self._lock, self._changing() as data:
            installed = data.get("installed") or {}
            state = data.get("state")
            if state in ("ready", "restarting") and installed.get("version") == self.current:
                data["state"], data["message"], data["installed"] = "idle", f"amemo обновлён до {self.current}", None
                self._journal(data, "restarted", self.current)
            elif state in ("ready", "restarting"):
                # перезапуск (свой или ручной) поднял не ту версию: ещё раз — по кругу, поэтому только сообщить
                data["state"] = "failed"
                data["message"] = (f"после перезапуска работает {self.current}, а не {installed.get('version')}"
                                   + (f"; бэкап базы — {installed['backup']}: amemo backup restore "
                                      f"{installed['backup']}" if installed.get("backup") else ""))
                data["installed"] = None
                self._journal(data, "restart failed", installed.get("version"))
            if self._latest(data) is None and data.get("state") == "available":
                data["state"], data["message"] = "idle", None

    def scheduled(self) -> dict:
        """Плановая проверка; доступна версия и включено автообновление — поставить."""
        status = self.check()
        if status["state"] == "available" and status["auto"] and self.kind.can_install:
            try:
                version = self.ready_to_install()
            except UpdateError as e:
                log.info("автообновление отложено: %s", e)
                return status
            self._installing = version
            self._install_in_background(version)
            status = self.status()
        return status

    def watch(self, idle: Callable[[], bool]) -> bool:
        """Взгляд службы раз в TICK: стоит новая версия (наша установка или версия на диске сменилась) и служба
        свободна — перезапуск (os.execv). True — перезапуск начат (в тестах execv подставной)."""
        if not self.kind.can_install or self._installing:
            return False
        data = self.read()
        if data.get("state") != "ready":
            disk = self.disk()
            if disk is None or disk == self.baseline or self._install_busy():
                return False
            with self._lock, self._changing() as data:
                data["state"] = "ready"
                data["message"] = f"обновление {disk} установлено — перезапуск, когда служба освободится"
                data["installed"] = {"version": disk, "previous": self.current, "at": _iso(self.now()),
                                     "backup": None}
                self._journal(data, "installed elsewhere", disk)
        if self.windows:
            return False                      # перезапуск на Windows — вручную: os.execv там не заменяет процесс
        if not idle():
            return False
        with self._lock, self._changing() as data:
            version = (data.get("installed") or {}).get("version")
            data["state"], data["message"] = "restarting", f"перезапуск на {version}"
            self._journal(data, "restart", version)
        with contextlib.suppress(Exception):
            self.before_restart()
        for handler in logging.getLogger().handlers:
            with contextlib.suppress(Exception):
                handler.flush()
        try:
            self.execv(self.python, [self.python, *self.argv])
        except OSError as e:
            with self._lock, self._changing() as data:
                data["state"], data["message"] = "failed", f"перезапуск не удался: {e} — перезапустите службу сами"
                data["installed"] = None
                self._journal(data, "restart failed", version, str(e))
            self.baseline = self.disk()
            return False
        return True


class Activity:
    """Сколько запросов HTTP идёт и когда закончился последний — для простоя (watch). Считает слой Track."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.inflight = 0
        self.last = clock()

    def quiet_for(self, seconds: float) -> bool:
        return self.inflight == 0 and self.clock() - self.last >= seconds


class Track:
    """Промежуточный слой ASGI над Activity. Не считаются: поток событий MCP (GET /mcp висит всегда), /health (его
    опрашивает compose) и GET /api/v1/updates (его опрашивает веб, пока ждёт перезапуска)."""

    QUIET = frozenset({("GET", "/mcp"), ("GET", "/health"), ("GET", "/api/v1/updates")})

    def __init__(self, app, *, activity: Activity) -> None:
        self.app = app
        self.activity = activity

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or (scope["method"], scope["path"]) in self.QUIET:
            await self.app(scope, receive, send)
            return
        self.activity.inflight += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.activity.inflight -= 1
            self.activity.last = self.activity.clock()


def pool_idle(pool) -> bool:
    """Ни одного занятого соединения пула (нет открытой транзакции, в том числе записи) и никто не ждёт."""
    if pool is None:
        return True
    stats = pool.get_stats()
    return stats.get("requests_waiting", 0) == 0 and stats.get("pool_available", 0) >= stats.get("pool_size", 0)
