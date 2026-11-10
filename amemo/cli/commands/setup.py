"""Подготовка и запуск: init, serve, mcp, base, doctor.

mcp — сервер MCP на stdin/stdout (amemo/service/mcp.py): агент — всегда модель: --agent model:…, иначе агент
окружения (AMEMO_AS_MODEL, CLAUDECODE, Codex), иначе AMEMO_MODEL_AGENT (model:local); person: не принимается.
Пул соединений маленький и переподключается; база должна быть подготовлена (amemo init).

init — db.prepare (миграции, словари, base_id и четыре папки новой базы) и корень хранилища AMEMO_DATA. С --dsn
строка подключения ещё и запоминается в amemo.toml ($AMEMO_CONFIG или ~/.config/amemo/amemo.toml, права 0600 — в ней
бывает пароль), если файла настроек ещё нет. Корень хранилища создаётся, только если база не знает ни одного файла:
пустая папка на месте хранилища, файлы которого база знает, — неподключённый том, а не новое хранилище (код 1).
Распознавание сканов (amemo/cli/commands/ocr.py): --ocr rus,eng ставит языки tesseract; без флага в интерактивном
терминале (stdin — tty, не --json, не CI) init спрашивает языки, если OCR ещё не настроен; Enter — пропустить.

doctor — проверки по порядку: настройки, база (вход, миграции, id), хранилище, смысловой поиск (модель, провайдер,
пробный вектор и покрытие — amemo/cli/commands/embed.py; включает его amemo embed enable),
папка документов, OCR (режим, языки, папка данных; warn — ocr = tesseract, а данных нет), файл токенов, агенты (Claude Code и Codex глобально и в проекте: --project или корень git над
текущей папкой), служба (/health по AMEMO_URL или на порту AMEMO_PORT, если он слушает). У каждой — ok, warn или fail
с подсказкой; код 0 без fail, 1 — есть fail.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from ...portable import O_BINARY, home
from ..errors import ENV, USAGE, CliError
from . import add


def register(sub, shared) -> None:
    p = add(sub, shared, "init", "подготовить базу и хранилище", run_init)
    p.add_argument("--dsn", help="строка подключения PostgreSQL (запоминается в amemo.toml, если его нет)")
    p.add_argument("--ocr", metavar="ЯЗЫКИ",
                   help="распознавать сканы PDF: языки tesseract через запятую (rus,eng) — скачать и включить")

    p = add(sub, shared, "serve", "служба HTTP и веб-интерфейс", run_serve)
    p.add_argument("--host", help="адрес привязки (AMEMO_HOST, по умолчанию 127.0.0.1)")
    p.add_argument("--port", type=int, help="порт (AMEMO_PORT, по умолчанию 8767)")
    p.add_argument("--no-auth", action="store_true",
                   help="разрешить адрес не loopback без AMEMO_TOKENS (закрытая сеть, compose)")

    add(sub, shared, "mcp", "сервер MCP на stdio для агента (агент — model:…, --agent model:имя)", run_mcp)

    p = add(sub, shared, "base", "база: сводка; base name [ИМЯ] — имя базы", run_base)
    p.add_argument("what", nargs="?", choices=("name",), help="name — показать или задать имя базы")
    p.add_argument("name", nargs="?", metavar="ИМЯ", help="новое имя базы (только человек)")

    p = add(sub, shared, "doctor", "проверка: база, хранилище, модель, документы, агенты, служба", run_doctor)
    p.add_argument("--project", metavar="DIR", type=Path,
                   help="проект для проверки агентов (по умолчанию — корень git над текущей папкой)")


# --- init ---

def _config_path(ctx) -> Path:
    explicit = ctx.env.get("AMEMO_CONFIG", "").strip()
    return Path(explicit).expanduser() if explicit else home(ctx.env) / ".config" / "amemo" / "amemo.toml"


def _save_dsn(ctx, dsn: str) -> str | None:
    """Запомнить DSN в amemo.toml, если файла настроек нет; путь записанного файла или None."""
    import json

    path = _config_path(ctx)
    if path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_BINARY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# настройки amemo (amemo init)\ndsn = {json.dumps(dsn, ensure_ascii=False)}\n")
    return str(path)


def run_init(ctx, args) -> int:
    from ... import api, db, settings as settings_
    from ...ocfl_store import StoreError

    if args.dsn:
        ctx._settings = settings_.load(ctx.env, dsn=args.dsn)
    conn = ctx.connect(ready=False)
    applied = db.prepare(conn)
    saved = _save_dsn(ctx, args.dsn) if args.dsn and not ctx.env.get("AMEMO_DSN", "").strip() else None
    if args.dsn and saved is None:
        why = ("задан AMEMO_DSN" if ctx.env.get("AMEMO_DSN", "").strip()
               else f"файл настроек {_config_path(ctx)} уже есть и не переписывается")
        ctx.note(f"amemo: --dsn не сохранён ({why}) — впишите dsn в amemo.toml или задайте AMEMO_DSN сами")
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
              "store": str(root), "state": str(ctx.settings.state), "config_saved": saved,
              "ocr": _init_ocr(ctx, args)}

    def text(r):
        lines = [f"База готова: {r['base_id']}" + (f" ({r['name']})" if r["name"] else ""),
                 f"миграций применено: {len(r['migrations_applied'])}", f"хранилище: {r['store']}"]
        if r["config_saved"]:
            lines.append(f"строка подключения записана в {r['config_saved']}")
        if r["ocr"]:
            got = [x["language"] for x in r["ocr"]["installed"]] + r["ocr"]["already"]
            lines.append(f"распознавание сканов: {', '.join(got)} ({r['ocr']['data']})")
        return "\n".join(lines)
    ctx.emit(result, text)
    return 0


OCR_QUESTION = "Распознавать сканы PDF? Языки через пробел (Enter — пропустить): "


def _asks(ctx) -> bool:
    """Спросить про OCR: интерактивный терминал человека, не --json и не CI, OCR ещё не настроен."""
    import sys

    from ... import sources

    try:
        tty = sys.stdin.isatty()
    except (AttributeError, ValueError, OSError):
        return False
    return (tty and not ctx.json and not ctx.env.get("CI", "").strip() and ctx.is_person
            and ctx.settings.ocr == "auto" and sources.ocr_setup(ctx.settings) is None)


def _init_ocr(ctx, args) -> dict | None:
    """Языки OCR при init: --ocr или ответ на вопрос; None — пропущено."""
    import sys

    from . import ocr

    answer = args.ocr
    if answer is None and _asks(ctx):
        print(OCR_QUESTION, end="", file=ctx.err, flush=True)
        answer = sys.stdin.readline().strip()
    if not answer or not answer.strip():
        return None
    return ocr.install(ctx, ocr.languages_of([answer]))


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
    """Агент amemo mcp: --agent (только model:), иначе агент окружения, иначе AMEMO_MODEL_AGENT."""
    from ... import settings as settings_
    from ..context import detected_agent

    explicit = getattr(ctx.args, "agent", None)
    if explicit is not None:
        explicit = explicit.strip()
        if not settings_.MODEL.fullmatch(explicit):
            raise CliError(f"--agent {explicit!r}: amemo mcp пишет от модели — нужен model:<имя> (строчные латинские "
                           f"буквы, цифры, «_.-»)", exit=USAGE, code="bad_agent")
        return explicit
    detected = detected_agent(ctx.env)
    return detected[0] if detected is not None else ctx.settings.model_agent


def run_mcp(ctx, args) -> int:
    from psycopg_pool import PoolTimeout

    from ...service import mcp
    from ..context import pending_migrations

    if not logging.getLogger().handlers:          # stdout — канал протокола: журнал только в stderr
        logging.basicConfig(level=logging.WARNING, format="amemo mcp: %(levelname)s %(name)s: %(message)s")
    agent = mcp_agent(ctx)
    ctx.dsn()                                     # нет AMEMO_DSN — код 1 с подсказкой

    def ready(conn) -> None:
        pending = pending_migrations(conn)
        if pending is None or pending:
            raise CliError("база не подготовлена" + (f": не применены миграции {', '.join(pending)}" if pending
                                                    else ": в ней нет схемы amemo"), exit=ENV, code="not_ready")

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
            raise CliError("amemo base: имя задаётся так — amemo base name ИМЯ", exit=2, code="usage")
        info = api.base(conn)
        ctx.emit(info, lambda b: f"База {b['base_id']}" + (f" «{b['name']}»" if b["name"] else "")
                 + f", amemo {b['amem_version']}\n"
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

SERVICE_TIMEOUT = 3                  # с на /health службы
PORT_PROBE = 0.3                     # с на «порт слушает?»


def run_doctor(ctx, args) -> int:
    from ... import api, settings as settings_
    from ..context import pending_migrations

    checks = []

    def check(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    conn = None
    try:
        settings = ctx.settings
        check("настройки", "ok", f"amemo.toml: {settings.config}" if settings.config else "из окружения")
    except settings_.SettingsError as e:
        check("настройки", "fail", str(e))
        settings = None
    if settings is not None:
        if not settings.dsn:
            check("база", "fail", "AMEMO_DSN не задан — задайте AMEMO_DSN или выполните amemo init --dsn …")
        else:
            try:
                conn = ctx.connect(ready=False)
                check("база", "ok", f"PostgreSQL {conn.info.server_version // 10000}")
            except Exception as e:                      # noqa: BLE001 — любой отказ входа — строка отчёта
                from .. import _auth_failed

                if _auth_failed(e):
                    check("база", "fail", "вход не удался — проверьте пользователя и пароль в AMEMO_DSN")
                else:
                    check("база", "fail", f"недоступна ({type(e).__name__}) — проверьте, что PostgreSQL запущен "
                                          f"и AMEMO_DSN верен")
        ready = False
        if conn is not None:
            pending = pending_migrations(conn)
            if pending is None:
                check("миграции", "fail", "схемы amemo нет — выполните amemo init")
            elif pending:
                check("миграции", "fail", f"не применены: {', '.join(pending)} — выполните amemo init")
            else:
                check("миграции", "ok", "все применены")
                ready = True
        if ready:
            info = api.base(conn)
            if info["base_id"]:
                check("id базы", "ok", info["base_id"] + (f" «{info['name']}»" if info["name"] else ""))
            else:
                check("id базы", "fail", "у базы нет id — выполните amemo init")
        root = Path(settings.data)
        files = None
        if ready:
            files = conn.execute("SELECT count(*) FROM object_version WHERE digest IS NOT NULL").fetchone()[0]
        if (root / api.STORE_MARK).is_file():
            check("хранилище", "ok", str(root))
        elif files:
            check("хранилище", "fail", f"{root}: нет корня OCFL, а база знает файлов: {files} — подключите том "
                                      f"данных или восстановите хранилище")
        else:
            check("хранилище", "warn", f"{root}: корня ещё нет — его создаст amemo init или первая запись файла")
        if ready:
            from . import embed

            check("смысловой поиск", *embed.doctor_line(embed.state(ctx, conn)))
        if settings.docs is None:
            check("документы", "warn", "AMEMO_DOCS не задан — источники с path получат замечание source_unresolved")
        elif Path(settings.docs).is_dir():
            check("документы", "ok", str(settings.docs))
        else:
            check("документы", "fail", f"{settings.docs}: папки нет — проверьте AMEMO_DOCS или подключите том")
        _check_ocr(settings, check)
        if settings.tokens is not None:
            try:
                count = len(settings_.load_tokens(settings.tokens))
                check("токены", "ok", f"{settings.tokens}: {count}")
            except settings_.SettingsError as e:
                check("токены", "fail", str(e))
    _check_agents(ctx, args, check)
    _check_service(ctx, settings, check)
    ok = all(c["status"] != "fail" for c in checks)
    marks = {"ok": "ok  ", "warn": "!   ", "fail": "FAIL"}
    ctx.emit({"ok": ok, "checks": checks},
             lambda r: "\n".join(f"{marks[c['status']]}  {c['name']}: {c['detail']}" for c in r["checks"]))
    return 0 if ok else ENV


def _check_ocr(settings, check) -> None:
    """OCR: режим, языки, папка; warn — ocr = tesseract, а языковых данных нет."""
    from . import ocr

    try:
        found = ocr.status(settings)
    except OSError as e:
        check("OCR", "fail", f"папка языковых данных не читается: {e}")
        return
    if found["mode"] == "tesseract":
        check("OCR", "ok", f"tesseract, {'+'.join(found['languages'])}: {found['tessdata']}"
                           + (" (системный)" if found["system"] else ""))
    elif settings.ocr == "tesseract":
        check("OCR", "warn", f"ocr = tesseract, а языковых данных ({'+'.join(found['wanted'])}) нет в "
                             f"{found['data']} и у системного tesseract — сканы не распознаются: "
                             f"amemo ocr install {' '.join(found['wanted'])}")
    elif settings.ocr == "none":
        check("OCR", "ok", "выключено (ocr = none): сканы PDF не распознаются")
    else:
        check("OCR", "ok", f"не установлено: сканы PDF не распознаются — по желанию amemo ocr install rus eng "
                           f"(данные — в {found['data']})")


def _check_agents(ctx, args, check) -> None:
    """Агенты глобально и в проекте; не установленные молчат, а если amemo нет нигде — одно предупреждение."""
    from ...agents import hooks, install, platforms

    project = getattr(args, "project", None)
    if project is not None:
        project = Path(project).expanduser().absolute()
        if not project.is_dir():
            check("агенты", "fail", f"--project {project}: папки нет")
            return
    else:
        project = hooks.project_root(str(Path.cwd()))
    found = 0
    for agent in platforms.AGENTS:
        for where in (None, project) if project is not None else (None,):
            try:
                result = install.inspect(agent, ctx.env, where)
            except OSError as e:
                check(f"агент {agent}", "fail", f"файлы агента не читаются: {e}")
                continue
            if result is None:
                continue
            found += 1
            name = f"агент {agent}" + (f" (проект {where})" if where is not None else "")
            check(name, result.status, result.detail)
    if not found:
        check("агенты", "warn", "amemo не поставлен ни в Claude Code, ни в Codex — amemo install claude-code "
                                "(или codex), для проекта — с --project DIR")


def _check_service(ctx, settings, check) -> None:
    """Служба: /health по AMEMO_URL; без него — на AMEMO_PORT этой машины, если порт слушает (иначе молчим)."""
    import socket
    import urllib.error
    import urllib.request

    url = ctx.env.get("AMEMO_URL", "").strip().rstrip("/")
    if not url:
        if settings is None:
            return
        host = settings.host if settings.host not in ("0.0.0.0", "::", "") else "127.0.0.1"
        try:
            with socket.create_connection((host, settings.port), timeout=PORT_PROBE):
                pass
        except OSError:
            return                                       # служба не запущена — это не ошибка
        url = f"http://{f'[{host}]' if ':' in host else host}:{settings.port}"
        explicit = False
    else:
        explicit = True
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=SERVICE_TIMEOUT) as r:   # noqa: S310 — адрес из настроек
            body = r.read(64).decode("utf-8", "replace").strip()
            status = r.status
    except urllib.error.HTTPError as e:
        hint = "база службы недоступна" if e.code == 503 else "ответ не от amemo?"
        check("служба", "fail" if explicit else "warn", f"{url}/health: {e.code} — {hint}")
        return
    except (OSError, ValueError) as e:
        reason = getattr(e, "reason", e)
        check("служба", "fail" if explicit else "warn", f"{url}/health не отвечает ({reason}) — запущена ли служба "
                                                         f"(amemo serve, docker compose up -d amemo)? Проверьте AMEMO_URL")
        return
    if status == 200 and body == "ok":
        check("служба", "ok", f"{url}: /health ok")
    else:
        check("служба", "fail" if explicit else "warn", f"{url}/health: {status} {body!r} — ответ не от amemo?")
