"""Токены общей службы (спецификация подпроекта 4, разд. 3.1): create, list, revoke над файлом AMEMO_TOKENS.

Токен — «amemo_» и 32 случайных байта (secrets.token_urlsafe); показывается один раз, в файл пишется только его
sha256 (settings.token_hash) — строки [[token]] с hash, agent, write и created_at, как читает settings.load_tokens.
Файл пишется целиком во временный рядом (O_EXCL, 0600) и встаёт на место переименованием: прерванная запись не
оставляет полфайла, права у нового файла — 0600 сразу, без окна с правами по umask. Правка идёт под замком
(portable.file_lock на .<имя>.lock рядом): параллельные create и revoke не теряют записей. Файл-симлинк правится
в своей цели (замена — рядом с целью, ссылка остаётся); ссылка в никуда — отказ. Прежний файл перед правкой
читается load_tokens — с той же проверкой прав и владельца, что у службы.

Токены выдаёт и отзывает только человек: модель, выдавшая себе токен person:, писала бы от имени человека.
В list и revoke токен называется началом хэша (id — первые 12 шестнадцатеричных знаков), сам хэш целиком
не печатается.
"""
from __future__ import annotations

import contextlib
import os
import secrets
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from ...portable import O_BINARY, file_lock
from ..errors import AMBIGUOUS, NOT_FOUND, USAGE, CliError
from . import add, group

PREFIX = "amemo_"
ID_LEN = 12                         # знаков хэша в id токена
ID_MIN = 6                          # не короче — для revoke


def register(sub, shared) -> None:
    _, inner = group(sub, shared, "token", "токены общей службы (AMEMO_TOKENS)")
    p = add(inner, shared, "create", "выдать токен (показывается один раз)", run_create)
    p.add_argument("token_agent", metavar="AGENT", help="кто входит по токену: person:<имя> или model:<имя>")
    p.add_argument("--read-only", action="store_true", help="только чтение (без права записи)")
    p.add_argument("--file", help="файл токенов (по умолчанию AMEMO_TOKENS)")
    p = add(inner, shared, "list", "выданные токены (без хэшей)", run_list)
    p.add_argument("--file", help="файл токенов (по умолчанию AMEMO_TOKENS)")
    p = add(inner, shared, "revoke", "отозвать токен по id (начало хэша)", run_revoke)
    p.add_argument("token_id", metavar="ID", help="id из amemo token list")
    p.add_argument("--file", help="файл токенов (по умолчанию AMEMO_TOKENS)")


def _path(ctx, args) -> Path:
    if args.file:
        return Path(args.file).expanduser()
    if ctx.settings.tokens is None:
        raise CliError("файл токенов не задан", exit=USAGE, code="tokens")
    return ctx.settings.tokens


def _target(path: Path) -> Path:
    """Файл, который правится: у симлинка — его цель (служба читает её же), чтобы замена рядом с целью оставила
    ссылку на месте; ссылка в никуда — отказ: создавать файл токенов там, куда она указывает, без спроса нельзя."""
    if not path.is_symlink():
        return path
    target = Path(os.path.realpath(path))
    if not target.exists():
        raise CliError(f"{path}: ссылка на файл токенов ведёт на несуществующий {target} — создайте файл или "
                       f"поправьте ссылку", exit=USAGE, code="tokens")
    return target


@contextlib.contextmanager
def _locked(path: Path):
    """Замок на время правки (portable.file_lock на .<имя>.lock рядом): два token create не теряют запись друг
    друга — второй читает файл уже после замены первым."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with file_lock(path.with_name(f".{path.name}.lock"), 0o600):
        yield


def _person(ctx, what: str) -> None:
    if not ctx.is_person:
        from ... import api

        raise api.Forbidden(f"токены {what} только человек (person:), а не {ctx.agent}")


def _entries(path: Path) -> list[dict]:
    """Строки [[token]] файла как есть (с created_at и прочими полями); нет файла — пусто."""
    from ... import settings

    if not path.exists() and not path.is_symlink():
        return []
    settings.load_tokens(path)                    # права, владелец, формат — как у службы
    return tomllib.loads(path.read_text(encoding="utf-8")).get("token", [])


def _toml(value) -> str:
    import json

    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)      # строка JSON — и базовая строка TOML
    if isinstance(value, datetime):
        return value.isoformat()
    raise CliError(f"значение {value!r} в файле токенов не переписать: допустимы строки, числа и true/false",
                   exit=USAGE, code="tokens")


def _write(path: Path, entries: list[dict]) -> None:
    lines = ["# Токены общей службы amemo: только sha256, сами токены не хранятся (amemo token create).", ""]
    for entry in entries:
        lines.append("[[token]]")
        lines += [f"{key} = {_toml(value)}" for key, value in entry.items()]
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_BINARY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines))
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)                       # umask не расширяет, но и не сужает ниже 0600 — явно
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _view(entry: dict) -> dict:
    return {"id": entry["hash"].removeprefix("sha256:")[:ID_LEN], "agent": entry["agent"],
            "write": entry.get("write", False), "created_at": entry.get("created_at")}


def run_create(ctx, args) -> int:
    from ... import settings

    _person(ctx, "выдаёт")
    agent = args.token_agent.strip()
    if not settings.AGENT.fullmatch(agent):
        raise CliError(f"агент {agent!r}: нужен person:<имя> или model:<имя>", exit=USAGE, code="bad_agent")
    path = _target(_path(ctx, args))
    token = PREFIX + secrets.token_urlsafe(32)
    entry = {"hash": settings.token_hash(token), "agent": agent, "write": not args.read_only,
             "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with _locked(path):
        _write(path, [*_entries(path), entry])
    result = {**_view(entry), "token": token, "file": str(path)}
    ctx.emit(result, lambda r: f"{r['token']}\nтокен для {r['agent']} ({'запись' if r['write'] else 'чтение'}), "
                               f"id {r['id']}: показан один раз, в {r['file']} — только его хэш")
    return 0


def run_list(ctx, args) -> int:
    entries = [_view(entry) for entry in _entries(_path(ctx, args))]
    ctx.emit(entries, lambda found: "\n".join(
        f"{t['id']}  {t['agent']}  {'запись' if t['write'] else 'чтение'}  {t['created_at'] or ''}".rstrip()
        for t in found) or "Токенов нет.")
    return 0


def run_revoke(ctx, args) -> int:
    _person(ctx, "отзывает")
    wanted = args.token_id.strip().lower().removeprefix("sha256:")
    if len(wanted) < ID_MIN or any(ch not in "0123456789abcdef" for ch in wanted):
        raise CliError(f"id {args.token_id!r}: нужно начало хэша из amemo token list (от {ID_MIN} знаков)",
                       exit=USAGE, code="usage")
    path = _target(_path(ctx, args))
    with _locked(path):
        entries = _entries(path)
        found = [e for e in entries if e["hash"].removeprefix("sha256:").startswith(wanted)]
        if not found:
            raise CliError(f"токена {wanted} нет в {path}", exit=NOT_FOUND, code="not_found",
                           hint="выданные токены: amemo token list")
        if len(found) > 1:
            raise CliError(f"id {wanted}: подходит токенов {len(found)} — нужно больше знаков", exit=AMBIGUOUS,
                           code="ambiguous", candidates=[{"ref": v["id"], "label": v["agent"]}
                                                         for v in map(_view, found)])
        _write(path, [e for e in entries if e is not found[0]])
    gone = _view(found[0])
    ctx.emit({**gone, "revoked": True}, f"Токен {gone['id']} ({gone['agent']}) отозван.")
    return 0
