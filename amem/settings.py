"""Настройки службы, CLI и хуков (спецификация подпроекта 4, разд. 2) и файл токенов общей службы (разд. 3.1).

Порядок источников: явный аргумент → окружение (AMEM_…) → amem.toml ($AMEM_CONFIG, затем ~/.config/amem/amem.toml).
Ключи amem.toml — имена полей Settings (dsn, data, docs, state, backups, host, port, agent, model_agent, ui_origins,
allowed_hosts, tokens, query_log, state_quota, lang); неизвестный ключ — ошибка, а не тихий пропуск опечатки. Относительный путь в amem.toml считается
от папки файла, в окружении и аргументе — от текущей папки; «~» раскрывается везде.

Токены общей службы — amem-tokens.toml с правами 0600: строки [[token]] с hash = "sha256:…", agent и write. Сам токен
в файле не хранится: служба сравнивает sha256 предъявленного токена с записанными. Файл принадлежит пользователю
службы (или root); права и владелец проверяются по уже открытому файлу (fstat), а не по имени: между проверкой
и чтением файл не подменить.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import os
import re
import stat
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
DEFAULT_STATE_QUOTA = 10 << 30     # байт подборок и загрузок одного владельца в AMEM_STATE (10 ГиБ)
QUOTA_UNITS = {"": 1, "k": 1 << 10, "kib": 1 << 10, "m": 1 << 20, "mib": 1 << 20, "g": 1 << 30, "gib": 1 << 30,
               "t": 1 << 40, "tib": 1 << 40}
# имя хоста по RFC 1123: метки из латиницы, цифр и «-» (не с краю), через точку; без порта, схемы и пути
HOSTNAME = re.compile(r"(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*")
# шаблоны — только целиком (fullmatch): у re.match с «$» проходит и строка с переводом строки на конце
PERSON = re.compile(r"person:[a-z0-9_.-]+")         # шаблон агента — как CHECK таблицы agent (objects.AGENT)
MODEL = re.compile(r"model:[a-z0-9_.-]+")
AGENT = re.compile(r"(person|model):[a-z0-9_.-]+")
TOKEN_HASH = re.compile(r"sha256:[0-9a-f]{64}")
log = logging.getLogger("amem.settings")

# поле → переменная окружения; порядок — как в таблице разд. 2
ENV = {
    "dsn": "AMEM_DSN", "data": "AMEM_DATA", "docs": "AMEM_DOCS", "state": "AMEM_STATE", "backups": "AMEM_BACKUPS",
    "host": "AMEM_HOST", "port": "AMEM_PORT", "agent": "AMEM_AGENT", "model_agent": "AMEM_MODEL_AGENT",
    "ui_origins": "AMEM_UI_ORIGINS", "allowed_hosts": "AMEM_ALLOWED_HOSTS", "tokens": "AMEM_TOKENS",
    "query_log": "AMEM_QUERY_LOG", "state_quota": "AMEM_STATE_QUOTA", "lang": "AMEM_LANG",
}


class SettingsError(ValueError):
    """Неверная настройка; сообщение называет источник (аргумент, переменную окружения или файл)."""


@dataclass(frozen=True)
class Settings:
    dsn: str | None                 # обязательна для базы; проверяет тот, кому она нужна (create_app, CLI)
    data: Path                      # хранилище копий объектов
    docs: Path | None               # папка документов; без неё источник с path получает source_unresolved
    state: Path                     # загрузки, подборки, журнал запросов
    backups: Path
    host: str                       # адрес привязки: IPv4, IPv6 (без скобок) или имя, без порта
    port: int
    agent: str                      # человек локальной службы: person:…
    model_agent: str                # клиенты без cookie и токена: model:…
    ui_origins: tuple[str, ...]     # разрешённые источники интерфейса (dev-сервер веба), без «/» в конце
    allowed_hosts: tuple[str, ...]  # имена в Host сверх локальных и адреса привязки (compose: имя службы)
    tokens: Path | None             # файл токенов общей службы; None — локальная служба
    query_log: Path | None          # журнал запросов; None — выключен (AMEM_QUERY_LOG=off)
    state_quota: int                # байт подборок и загрузок одного владельца в AMEM_STATE
    lang: str | None                # язык подписей CLI и MCP без явного (ru | en); None — ru, затем en (amem.lang)
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
        host=_host(raw.get("host")),
        port=_port(raw.get("port")),
        agent=_agent(raw.get("agent"), PERSON, "person:", default=default_agent(env)),
        model_agent=_agent(raw.get("model_agent"), MODEL, "model:", default=DEFAULT_MODEL_AGENT),
        ui_origins=_origins(raw.get("ui_origins")),
        allowed_hosts=_allowed_hosts(raw.get("allowed_hosts")),
        tokens=path("tokens"),
        query_log=query_log,
        state_quota=_quota(raw.get("state_quota")),
        lang=_lang(raw.get("lang")),
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
        # O_NONBLOCK: канал (FIFO) на месте файла не вешает запуск — открытие возвращается сразу, а S_ISREG по fstat
        # отвергает его до чтения
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0))
        with os.fdopen(fd, "rb") as f:
            info = os.fstat(f.fileno())          # права и владелец — того файла, который читаем
            raw = f.read() if stat.S_ISREG(info.st_mode) else None
    except FileNotFoundError:
        raise SettingsError(f"{path}: файла токенов нет — создайте токен (amem token create) или уберите AMEM_TOKENS")
    except OSError as e:
        raise SettingsError(f"{path}: не читается: {e}") from e
    if raw is None:
        raise SettingsError(f"{path}: это не обычный файл")
    if os.name == "posix":
        # кто может писать в файл, тот впишет свой токен с правом записи; хэши сами по себе не раскрывают токены.
        # Чужой файл (владелец — другой пользователь, кроме root) его владелец перепишет когда угодно
        if info.st_uid not in (os.getuid(), 0):
            raise SettingsError(f"{path}: файл токенов принадлежит другому пользователю (uid {info.st_uid}) — "
                                f"создайте его от пользователя службы")
        if info.st_mode & 0o022:
            raise SettingsError(f"{path}: файл токенов доступен на запись другим пользователям — chmod 600 {path}")
        if info.st_mode & 0o044:
            log.warning("%s: файл токенов читают другие пользователи — chmod 600 %s", path, path)
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise SettingsError(f"{path}: не читается: {e}") from e
    entries = data.get("token", [])
    if set(data) - {"token"} or not isinstance(entries, list):
        raise SettingsError(f"{path}: нужны только таблицы [[token]]")
    tokens = []
    for i, entry in enumerate(entries, 1):
        where = f"{path}: token {i}"
        if not isinstance(entry, dict):
            raise SettingsError(f"{where}: нужна таблица [[token]]")
        if not isinstance(entry.get("hash"), str) or not TOKEN_HASH.fullmatch(entry["hash"]):
            raise SettingsError(f"{where}: hash — нужно sha256:<64 шестнадцатеричных знака>")
        if not isinstance(entry.get("agent"), str) or not AGENT.fullmatch(entry["agent"]):
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
    if not isinstance(value, str) or not pattern.fullmatch(value.strip()):
        raise SettingsError(f"{where}: агент {value!r} — нужен {prefix}<имя> из строчных латинских букв, цифр, «_.-»")
    return value.strip()


def _origins(entry) -> tuple[str, ...]:
    if entry is None:
        return ()
    value, where, _ = entry
    items = _list(value, where, "источников")
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


def host_value(value: str) -> str | None:
    """Адрес или имя хоста без порта, строчными; IPv6 — без скобок («[::1]» → «::1»). Не адрес и не имя — None."""
    host = value.strip().lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
        try:
            return str(ipaddress.IPv6Address(host)) if "%" not in host else None
        except ValueError:
            return None
    try:
        return str(ipaddress.ip_address(host)) if "%" not in host else None
    except ValueError:
        pass
    return host if HOSTNAME.fullmatch(host) and not host.replace(".", "").isdigit() else None


def _host(entry) -> str:
    if entry is None:
        return DEFAULT_HOST
    value, where, _ = entry
    host = host_value(value) if isinstance(value, str) else None
    if host is None:
        raise SettingsError(f"{where}: адрес {value!r} — нужен IPv4, IPv6 или имя хоста, без порта и схемы "
                            f"(порт — AMEM_PORT)")
    return host


def _list(value, where: str, what: str) -> list[str]:
    if isinstance(value, str):
        return value.split(",")
    if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        return list(value)
    raise SettingsError(f"{where}: нужен список {what} или строка через запятую, получено {value!r}")


def _allowed_hosts(entry) -> tuple[str, ...]:
    if entry is None:
        return ()
    value, where, _ = entry
    hosts = []
    for item in (item.strip() for item in _list(value, where, "имён")):
        if not item:
            continue
        host = host_value(item)
        if host is None:
            raise SettingsError(f"{where}: {item!r} — нужно имя хоста или адрес без порта и схемы: Host сверяется "
                                f"по имени, порт любой (например amem)")
        hosts.append(host)
    return tuple(dict.fromkeys(hosts))


def _lang(entry) -> str | None:
    from . import lang

    if entry is None:
        return None
    value, where, _ = entry
    try:
        return lang.check(value)
    except lang.LangError:
        raise SettingsError(f"{where}: язык {value!r} — допустимы {', '.join(lang.LANGS)}") from None


def _quota(entry) -> int:
    if entry is None:
        return DEFAULT_STATE_QUOTA
    value, where, _ = entry
    if isinstance(value, int) and not isinstance(value, bool):
        number, unit = value, ""
    elif isinstance(value, str) and (found := re.fullmatch(r"\s*([0-9]+)\s*([a-zA-Z]*)\s*", value)):
        number, unit = int(found[1]), found[2].lower()
    else:
        number, unit = None, ""
    if number is None or unit not in QUOTA_UNITS or number <= 0:
        raise SettingsError(f"{where}: предел {value!r} — нужно целое число байт больше нуля или с единицей "
                            f"(500M, 10G, 1T — двоичные: МиБ, ГиБ, ТиБ)")
    return number * QUOTA_UNITS[unit]
