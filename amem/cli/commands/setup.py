"""Подготовка и запуск: init, serve, mcp, base, doctor.

mcp — сервер MCP на stdin/stdout (amem/service/mcp.py): агент — всегда модель: --agent model:…, иначе агент
окружения (AMEM_AS_MODEL, CLAUDECODE, Codex), иначе AMEM_MODEL_AGENT (model:local); person: не принимается.
Пул соединений маленький и переподключается; база должна быть подготовлена (amem init).

init — db.prepare (миграции, словари, base_id и четыре папки новой базы) и корень хранилища AMEM_DATA. С --dsn
строка подключения ещё и запоминается в amem.toml ($AMEM_CONFIG или ~/.config/amem/amem.toml, права 0600 — в ней
бывает пароль), если файла настроек ещё нет. Корень хранилища создаётся, только если база не знает ни одного файла:
пустая папка на месте хранилища, файлы которого база знает, — неподключённый том, а не новое хранилище (код 1).

doctor здесь короткий — база, миграции, хранилище, смысловой поиск, файл токенов; полный (агенты, установка) —
в части 4c.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from ..errors import ENV, USAGE, CliError
from . import add


def register(sub, shared) -> None:
    p = add(sub, shared, "init", "подготовить базу и хранилище", run_init)
    p.add_argument("--dsn", help="строка подключения PostgreSQL (запоминается в amem.toml, если его нет)")

    p = add(sub, shared, "serve", "служба HTTP и веб-интерфейс", run_serve)
    p.add_argument("--host", help="адрес привязки (AMEM_HOST, по умолчанию 127.0.0.1)")
    p.add_argument("--port", type=int, help="порт (AMEM_PORT, по умолчанию 8767)")
    p.add_argument("--no-auth", action="store_true",
                   help="разрешить адрес не loopback без AMEM_TOKENS (закрытая сеть, compose)")

    add(sub, shared, "mcp", "сервер MCP на stdio для агента (агент — model:…, --agent model:имя)", run_mcp)

    p = add(sub, shared, "base", "база: сводка; base name [ИМЯ] — имя базы", run_base)
    p.add_argument("what", nargs="?", choices=("name",), help="name — показать или задать имя базы")
    p.add_argument("name", nargs="?", metavar="ИМЯ", help="новое имя базы (только человек)")

    add(sub, shared, "doctor", "проверка: база, миграции, хранилище, смысловой поиск", run_doctor)


# --- init ---

def _config_path(ctx) -> Path:
    explicit = ctx.env.get("AMEM_CONFIG", "").strip()
    home = Path(ctx.env.get("HOME") or Path.home())
    return Path(explicit).expanduser() if explicit else home / ".config" / "amem" / "amem.toml"


def _save_dsn(ctx, dsn: str) -> str | None:
    """Запомнить DSN в amem.toml, если файла настроек нет; путь записанного файла или None."""
    import json

    path = _config_path(ctx)
    if path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"# настройки amem (amem init)\ndsn = {json.dumps(dsn, ensure_ascii=False)}\n")
    return str(path)


def run_init(ctx, args) -> int:
    from ... import api, db, settings as settings_
    from ...ocfl_store import StoreError

    if args.dsn:
        ctx._settings = settings_.load(ctx.env, dsn=args.dsn)
    conn = ctx.connect(ready=False)
    applied = db.prepare(conn)
    saved = _save_dsn(ctx, args.dsn) if args.dsn and not ctx.env.get("AMEM_DSN", "").strip() else None
    if args.dsn and saved is None:
        why = ("задан AMEM_DSN" if ctx.env.get("AMEM_DSN", "").strip()
               else f"файл настроек {_config_path(ctx)} уже есть и не переписывается")
        ctx.note(f"amem: --dsn не сохранён ({why}) — впишите dsn в amem.toml или задайте AMEM_DSN сами")
    store = ctx.store()
    root = Path(store.root)
    files = conn.execute("SELECT count(*) FROM object_version WHERE digest IS NOT NULL").fetchone()[0]
    if not (root / api.STORE_MARK).is_file() and files:
        raise CliError(f"хранилище копий не подключено: в {root} нет корня OCFL, а база знает файлов: {files}",
                       exit=ENV, code="store_unavailable")
    try:
        store.init(create=True)
    except StoreError as e:
        raise CliError(f"хранилище копий: {e}", exit=ENV, code="store_unavailable") from None
    Path(ctx.settings.state).mkdir(parents=True, exist_ok=True)
    base = api.base(conn)
    result = {"base_id": base["base_id"], "name": base["name"], "migrations_applied": applied,
              "store": str(root), "state": str(ctx.settings.state), "config_saved": saved}

    def text(r):
        lines = [f"База готова: {r['base_id']}" + (f" ({r['name']})" if r["name"] else ""),
                 f"миграций применено: {len(r['migrations_applied'])}", f"хранилище: {r['store']}"]
        if r["config_saved"]:
            lines.append(f"строка подключения записана в {r['config_saved']}")
        return "\n".join(lines)
    ctx.emit(result, text)
    return 0


# --- serve ---

def run_serve(ctx, args) -> int:
    from ... import settings as settings_
    from ...service import server

    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = settings_.load(ctx.env, host=args.host, port=args.port)
    if not settings.dsn:
        raise CliError("база не задана", exit=ENV, code="no_dsn")
    kw = {"runner": ctx.runner} if ctx.runner is not None else {}
    server.serve(settings, no_auth=args.no_auth, **kw)
    return 0


# --- mcp ---

def mcp_agent(ctx) -> str:
    """Агент amem mcp: --agent (только model:), иначе агент окружения, иначе AMEM_MODEL_AGENT."""
    from ... import settings as settings_
    from ..context import detected_agent

    explicit = getattr(ctx.args, "agent", None)
    if explicit is not None:
        explicit = explicit.strip()
        if not settings_.MODEL.fullmatch(explicit):
            raise CliError(f"--agent {explicit!r}: amem mcp пишет от модели — нужен model:<имя> (строчные латинские "
                           f"буквы, цифры, «_.-»)", exit=USAGE, code="bad_agent")
        return explicit
    detected = detected_agent(ctx.env)
    return detected[0] if detected is not None else ctx.settings.model_agent


def run_mcp(ctx, args) -> int:
    from psycopg_pool import PoolTimeout

    from ...service import mcp
    from ..context import pending_migrations

    if not logging.getLogger().handlers:          # stdout — канал протокола: журнал только в stderr
        logging.basicConfig(level=logging.WARNING, format="amem mcp: %(levelname)s %(name)s: %(message)s")
    agent = mcp_agent(ctx)
    ctx.dsn()                                     # нет AMEM_DSN — код 1 с подсказкой

    def ready(conn) -> None:
        pending = pending_migrations(conn)
        if pending is None or pending:
            raise CliError("база не подготовлена" + (f": не применены миграции {', '.join(pending)}" if pending
                                                    else ": в ней нет схемы amem"), exit=ENV, code="not_ready")

    try:
        with mcp.open_stdio(ctx.settings, agent=agent, ready=ready) as runtime:
            mcp.serve_stdio(runtime)
    except PoolTimeout:
        raise CliError("база недоступна: соединение не открылось", exit=ENV, code="db_unavailable") from None
    return 0


# --- base ---

def run_base(ctx, args) -> int:
    from ... import api

    conn = ctx.connect()
    if args.what is None:
        if args.name is not None:
            raise CliError("amem base: имя задаётся так — amem base name ИМЯ", exit=2, code="usage")
        info = api.base(conn)
        ctx.emit(info, lambda b: f"База {b['base_id']}" + (f" «{b['name']}»" if b["name"] else "")
                 + f", amem {b['amem_version']}\n"
                 + ", ".join(f"{k} {v}" for k, v in b["counts"].items()) + f"; на проверке {b['review_open']}")
        return 0
    if args.name is None:
        info = api.base(conn)
        ctx.emit({"name": info["name"]}, info["name"] or "Имя базы не задано.")
        return 0
    info = api.base_rename(conn, args.name, agent=ctx.agent)
    ctx.emit(info, f"Имя базы: {info['name']}")
    return 0


# --- doctor ---

def run_doctor(ctx, args) -> int:
    from ... import api, recipes, settings as settings_
    from ..context import pending_migrations

    checks = []

    def check(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    conn = None
    try:
        settings = ctx.settings
        check("настройки", "ok", f"amem.toml: {settings.config}" if settings.config else "из окружения")
    except settings_.SettingsError as e:
        check("настройки", "fail", str(e))
        settings = None
    if settings is not None:
        if not settings.dsn:
            check("база", "fail", "AMEM_DSN не задан — задайте AMEM_DSN или выполните amem init --dsn …")
        else:
            try:
                conn = ctx.connect(ready=False)
                check("база", "ok", f"PostgreSQL {conn.info.server_version // 10000}")
            except Exception as e:                      # noqa: BLE001 — любой отказ входа — строка отчёта
                from .. import _auth_failed

                if _auth_failed(e):
                    check("база", "fail", "вход не удался — проверьте пользователя и пароль в AMEM_DSN")
                else:
                    check("база", "fail", f"недоступна ({type(e).__name__}) — проверьте, что PostgreSQL запущен "
                                          f"и AMEM_DSN верен")
        if conn is not None:
            pending = pending_migrations(conn)
            if pending is None:
                check("миграции", "fail", "схемы amem нет — выполните amem init")
            elif pending:
                check("миграции", "fail", f"не применены: {', '.join(pending)} — выполните amem init")
            else:
                check("миграции", "ok", "все применены")
        root = Path(settings.data)
        files = None
        if conn is not None and pending_migrations(conn) == []:
            files = conn.execute("SELECT count(*) FROM object_version WHERE digest IS NOT NULL").fetchone()[0]
        if (root / api.STORE_MARK).is_file():
            check("хранилище", "ok", str(root))
        elif files:
            check("хранилище", "fail", f"{root}: нет корня OCFL, а база знает файлов: {files} — подключите том "
                                      f"данных или восстановите хранилище")
        else:
            check("хранилище", "warn", f"{root}: корня ещё нет — его создаст amem init или первая запись файла")
        if conn is not None and files is not None:
            found = recipes.availability(conn, ctx.provider())
            if found["semantic"] == "used":
                check("смысловой поиск", "ok", "модель и провайдер на месте")
            else:
                check("смысловой поиск", "warn", f"недоступен ({found['reason']}): работают марки и полнотекстовый")
        if settings.tokens is not None:
            try:
                count = len(settings_.load_tokens(settings.tokens))
                check("токены", "ok", f"{settings.tokens}: {count}")
            except settings_.SettingsError as e:
                check("токены", "fail", str(e))
    ok = all(c["status"] != "fail" for c in checks)
    marks = {"ok": "ok  ", "warn": "!   ", "fail": "FAIL"}
    ctx.emit({"ok": ok, "checks": checks},
             lambda r: "\n".join(f"{marks[c['status']]}  {c['name']}: {c['detail']}" for c in r["checks"]))
    return 0 if ok else ENV
