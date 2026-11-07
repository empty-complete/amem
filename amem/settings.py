"""Настройки службы, CLI и хуков (спецификация подпроекта 4, разд. 2) и файл токенов общей службы (разд. 3.1).

Порядок источников: явный аргумент → окружение (AMEM_…) → amem.toml ($AMEM_CONFIG, затем ~/.config/amem/amem.toml).
Ключи amem.toml — имена полей Settings (dsn, data, docs, state, backups, host, port, agent, model_agent, ui_origins,
tokens, query_log); неизвестный ключ — ошибка, а не тихий пропуск опечатки. Относительный путь в amem.toml считается
от папки файла, в окружении и аргументе — от текущей папки; «~» раскрывается везде.

Токены общей службы — amem-tokens.toml с правами 0600: строки [[token]] с hash = "sha256:…", agent и write. Сам токен
в файле не хранится: служба сравнивает sha256 предъявленного токена с записанными.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8767            # 8765 на машинах разработчиков часто занят другими службами
DEFAULT_MODEL_AGENT = "model:local"
FALLBACK_NAME = "local"        # имя человека, если от имени пользователя ОС ничего не осталось
QUERY_LOG_OFF = "off"
PERSON = re.compile(r"^person:[a-z0-9_.-]+$")       # шаблон агента — как CHECK таблицы agent (objects.AGENT)
MODEL = re.compile(r"^model:[a-z0-9_.-]+$")
AGENT = re.compile(r"^(person|model):[a-z0-9_.-]+$")
TOKEN_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
log = logging.getLogger("amem.settings")

# поле → переменная окружения; порядок — как в таблице разд. 2
ENV = {
    "dsn": "AMEM_DSN", "data": "AMEM_DATA", "docs": "AMEM_DOCS", "state": "AMEM_STATE", "backups": "AMEM_BACKUPS",
    "host": "AMEM_HOST", "port": "AMEM_PORT", "agent": "AMEM_AGENT", "model_agent": "AMEM_MODEL_AGENT",
    "ui_origins": "AMEM_UI_ORIGINS", "tokens": "AMEM_TOKENS", "query_log": "AMEM_QUERY_LOG",
}
PATHS = frozenset({"data", "docs", "state", "backups", "tokens", "query_log"})


class SettingsError(ValueError):
    """Неверная настройка; сообщение называет источник (аргумент, переменную окружения или файл)."""


@dataclass(frozen=True)
class Settings:
    dsn: str | None                 # обязательна для базы; проверяет тот, кому она нужна (create_app, CLI)
    data: Path                      # хранилище копий объектов
    docs: Path | None               # папка документов; без неё источник с path получает source_unresolved
    state: Path                     # загрузки, подборки, журнал запросов
    backups: Path
    host: str
    port: int
    agent: str                      # человек локальной службы: person:…
    model_agent: str                # клиенты без cookie и токена: model:…
    ui_origins: tuple[str, ...]     # разрешённые источники интерфейса (dev-сервер веба), без «/» в конце
    tokens: Path | None             # файл токенов общей службы; None — локальная служба
    query_log: Path | None          # журнал запросов; None — выключен (AMEM_QUERY_LOG=off)
    config: Path | None             # прочитанный amem.toml, если был


@dataclass(frozen=True)
class Token:
    hash: str
    agent: str
    write: bool


def load(env: Mapping[str, str] | None = None, **explicit) -> Settings:
    """Настройки из явных аргументов (None — не задан), окружения env (по умолчанию os.environ) и amem.toml."""
    env = os.environ if env is None else env
    unknown = set(explicit) - set(ENV)
    if unknown:
        raise TypeError(f"settings.load: неизвестные настройки {sorted(unknown)}")
    home = Path(env.get("HOME") or Path.home())
    config, table = _config(env, home)
    raw: dict[str, tuple[object, str, Path | None]] = {}       # поле → (значение, источник, база относительных путей)
    for name, var in ENV.items():
        if explicit.get(name) is not None:
            raw[name] = (explicit[name], f"аргумент {name}", None)
        elif env.get(var, "").strip():
            raw[name] = (env[var].strip(), var, None)
        elif name in table:
            raw[name] = (table[name], f"{config}: {name}", config.parent)

    def path(name: str) -> Path | None:
        if name not in raw:
            return None
        value, where, base = raw[name]
        if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
            raise SettingsError(f"{where}: нужен путь, получено {value!r}")
        result = _expand(str(value).strip(), home)
        return base / result if base is not None and not result.is_absolute() else result

    def text(name: str, default: str | None = None) -> str | None:
        if name not in raw:
            return default
        value, where, _ = raw[name]
        if not isinstance(value, str) or not value.strip():
            raise SettingsError(f"{where}: нужна строка, получено {value!r}")
        return value.strip()

    state = path("state") or home / ".local" / "state" / "amem"
    query_log = None if _is_off(raw.get("query_log")) else (path("query_log") or state / "queries.jsonl")
    return Settings(
        dsn=text("dsn"),
        data=path("data") or home / ".local" / "share" / "amem" / "objects",
        docs=path("docs"),
        state=state,
        backups=path("backups") or state / "backups",
        host=text("host", DEFAULT_HOST),
        port=_port(raw.get("port")),
        agent=_agent(raw.get("agent"), PERSON, "person:", default=default_agent(env)),
        model_agent=_agent(raw.get("model_agent"), MODEL, "model:", default=DEFAULT_MODEL_AGENT),
        ui_origins=_origins(raw.get("ui_origins")),
        tokens=path("tokens"),
        query_log=query_log,
        config=config,
    )


def default_agent(env: Mapping[str, str] | None = None) -> str:
    """person: + имя пользователя ОС, приведённое к шаблону агента: без диакритики, строчными, прочие знаки — «-»."""
    return "person:" + agent_name(_os_user(os.environ if env is None else env))


def agent_name(raw: str) -> str:
    """Имя для шаблона агента [a-z0-9_.-]+ из произвольной строки; пустой результат — FALLBACK_NAME."""
    plain = "".join(ch for ch in unicodedata.normalize("NFKD", raw) if not unicodedata.combining(ch))
    name = re.sub(r"[^a-z0-9_.-]+", "-", plain.lower()).strip("-")
    return name or FALLBACK_NAME


def token_hash(token: str) -> str:
    """Запись токена в файле: sha256 его текста (UTF-8)."""
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_tokens(path: Path | str) -> tuple[Token, ...]:
    """Токены из amem-tokens.toml; нет файла или он неверен — SettingsError с местом."""
    path = Path(path)
    try:
        mode = path.stat().st_mode
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SettingsError(f"{path}: файла токенов нет — создайте токен (amem token create) или уберите AMEM_TOKENS")
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise SettingsError(f"{path}: не читается: {e}") from e
    if os.name == "posix":
        # кто может писать в файл, тот впишет свой токен с правом записи; хэши сами по себе не раскрывают токены
        if mode & 0o022:
            raise SettingsError(f"{path}: файл токенов доступен на запись другим пользователям — chmod 600 {path}")
        if mode & 0o044:
            log.warning("%s: файл токенов читают другие пользователи — chmod 600 %s", path, path)
    entries = data.get("token", [])
    if set(data) - {"token"} or not isinstance(entries, list):
        raise SettingsError(f"{path}: нужны только таблицы [[token]]")
    tokens = []
    for i, entry in enumerate(entries, 1):
        where = f"{path}: token {i}"
        if not isinstance(entry, dict):
            raise SettingsError(f"{where}: нужна таблица [[token]]")
        if not isinstance(entry.get("hash"), str) or not TOKEN_HASH.match(entry["hash"]):
            raise SettingsError(f"{where}: hash — нужно sha256:<64 шестнадцатеричных знака>")
        if not isinstance(entry.get("agent"), str) or not AGENT.match(entry["agent"]):
            raise SettingsError(f"{where}: agent {entry.get('agent')!r} — нужен person:<имя> или model:<имя>")
        write = entry.get("write", False)              # без явного права — только чтение
        if not isinstance(write, bool):
            raise SettingsError(f"{where}: write — нужно true или false")
        tokens.append(Token(entry["hash"], entry["agent"], write))
    return tuple(tokens)


def match_token(tokens: tuple[Token, ...], token: str) -> Token | None:
    """Запись предъявленного токена или None. Сравниваются все записи, без раннего выхода."""
    digest = token_hash(token)
    found = None
    for entry in tokens:
        if hmac.compare_digest(entry.hash, digest):
            found = entry
    return found


def _os_user(env: Mapping[str, str]) -> str:
    # как getpass.getuser, но по переданному окружению: тесты и CLI не зависят от окружения процесса
    for var in ("LOGNAME", "USER", "LNAME", "USERNAME"):
        if env.get(var):
            return env[var]
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_name
    except (ImportError, KeyError, OSError):
        return ""


def _expand(value: str, home: Path) -> Path:
    # «~» — домашняя папка из того же окружения, что и HOME настроек, а не из окружения процесса
    if value == "~" or value.startswith("~/"):
        return Path(str(home) + value[1:])
    return Path(value)


def _config(env: Mapping[str, str], home: Path) -> tuple[Path | None, dict]:
    explicit = env.get("AMEM_CONFIG", "").strip()
    path = _expand(explicit, home) if explicit else home / ".config" / "amem" / "amem.toml"
    if not path.is_file():
        if explicit:
            raise SettingsError(f"AMEM_CONFIG: файла {path} нет")
        return None, {}
    try:
        table = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise SettingsError(f"{path}: не читается как TOML: {e}") from e
    unknown = set(table) - set(ENV)
    if unknown:
        raise SettingsError(f"{path}: неизвестные ключи {', '.join(sorted(unknown))}; "
                            f"допустимы {', '.join(ENV)}")
    return path, table


def _is_off(entry) -> bool:
    return entry is not None and isinstance(entry[0], str) and entry[0].strip().lower() == QUERY_LOG_OFF


def _port(entry) -> int:
    if entry is None:
        return DEFAULT_PORT
    value, where, _ = entry
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise SettingsError(f"{where}: порт — целое число, получено {value!r}")
    try:
        port = int(value)
    except ValueError:
        raise SettingsError(f"{where}: порт — целое число, получено {value!r}") from None
    if not 1 <= port <= 65535:
        raise SettingsError(f"{where}: порт {port} — нужен от 1 до 65535")
    return port


def _agent(entry, pattern: re.Pattern, prefix: str, *, default: str) -> str:
    if entry is None:
        return default
    value, where, _ = entry
    if not isinstance(value, str) or not pattern.match(value.strip()):
        raise SettingsError(f"{where}: агент {value!r} — нужен {prefix}<имя> из строчных латинских букв, цифр, «_.-»")
    return value.strip()


def _origins(entry) -> tuple[str, ...]:
    if entry is None:
        return ()
    value, where, _ = entry
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        items = value
    else:
        raise SettingsError(f"{where}: нужен список источников или строка через запятую, получено {value!r}")
    origins = []
    for item in (item.strip() for item in items):
        if not item:
            continue
        origin = item.rstrip("/").lower()
        parts = urlsplit(origin)
        if parts.scheme not in ("http", "https") or not parts.netloc or parts.path or parts.query or parts.fragment:
            raise SettingsError(f"{where}: источник {item!r} — нужен вид http://хост:порт, без пути")
        origins.append(origin)
    return tuple(dict.fromkeys(origins))
