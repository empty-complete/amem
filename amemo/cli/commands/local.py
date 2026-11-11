"""Своя установка amemo без Docker и без прав администратора: setup и pg (amemo/localpg.py).

`amemo setup --pg-bin DIR [--data DIR] [--docs DIR] [--lang ru|en] [--port N] [--embed [--embed-models DIR]]
[--ocr ЯЗЫКИ] [--agents claude-code,codex,cowork] [--plugin-out FILE] [--no-auto-update] [--progress]` — всё, что делает установщик (спецификация приложения
для Windows, D1), одной командой без вопросов:
1. кластер PostgreSQL в <data>/pg (initdb: роль amemo со случайным паролем, UTF8, только localhost, первый свободный
   порт от 5436), если его ещё нет;
2. amemo.toml ($AMEMO_CONFIG или ~/.config/amemo/amemo.toml, права 0600): dsn, хранилище <data>/objects, состояние
   <data>/state, бэкапы <data>/backups, docs, lang, pg_bin, pg_data, auto_update;
3. запуск кластера, база amemo и расширения vector, btree_gist (и в template1 — для backup verify);
4. миграции, словари и хранилище — как amemo init;
5. --embed — смысловой поиск, как amemo embed enable (файлы модели из --embed-models или загрузка); --ocr — языки
   распознавания, как amemo ocr install; оба — действия человека: из окружения агента — отказ (код 2) до любых
   изменений;
6. --agents — amemo install для каждого агента; cowork — zip-плагин для приложения Claude (`--plugin-out`, по
   умолчанию ~/amemo-plugin.zip), который человек загружает в аккаунт сам.

--progress — ход по шагам для приложения amemo для Windows: строки JSON `{"stage": …, "state": …}` в stderr
(шаги database, store, search, ocr, agents; состояния running, done, skipped), как у экрана установки мастера.

Повторный запуск продолжает с того места, где остановился: кластер и amemo.toml, созданные setup, переиспользуются
(пароль не меняется). Другой --pg-bin той же мажорной версии (новый комплект приложения для Windows) — pg_bin в
amemo.toml переписывается, база остаётся; другая мажорная версия — отказ: нужен pg_upgrade. Файл настроек, который создал не setup (в нём нет pg_data этой установки), не переписывается —
отказ с подсказкой.

`amemo pg start|stop|status` — кластер из pg_bin и pg_data настроек.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import sys
from pathlib import Path

from ...portable import O_BINARY, home
from ..errors import ENV, USAGE, CliError
from . import add, group

AGENTS = ("claude-code", "codex", "cowork")
OVERRIDES = ("AMEMO_DSN", "AMEMO_DATA", "AMEMO_STATE", "AMEMO_BACKUPS", "AMEMO_PG_DATA")


def register(sub, shared) -> None:
    p = add(sub, shared, "setup", "своя установка: PostgreSQL в папке данных, amemo.toml, база, поиск, агенты",
            run_setup)
    p.add_argument("--pg-bin", metavar="DIR", type=Path, required=True,
                   help="программы PostgreSQL 18+ с pgvector (initdb, pg_ctl, postgres)")
    p.add_argument("--data", metavar="DIR", type=Path, help="папка данных (по умолчанию ~/amemo-data)")
    p.add_argument("--docs", metavar="DIR", type=Path, help="папка документов, которые цитирует amemo")
    p.add_argument("--port", type=int, help="порт PostgreSQL (по умолчанию — первый свободный от 5436)")
    p.add_argument("--embed", action="store_true", help="включить смысловой поиск (только человек)")
    p.add_argument("--embed-models", metavar="DIR", type=Path,
                   help="готовые файлы модели (раскладка кэша fastembed) вместо загрузки")
    p.add_argument("--ocr", metavar="ЯЗЫКИ", help="распознавать сканы: языки tesseract через запятую (только человек)")
    p.add_argument("--agents", metavar="СПИСОК", help="подключить агентов: claude-code,codex,cowork")
    p.add_argument("--plugin-out", metavar="FILE", type=Path,
                   help="cowork: куда положить zip плагина (по умолчанию ~/amemo-plugin.zip)")
    p.add_argument("--no-auto-update", action="store_true",
                   help="auto_update = false: обновляет не служба, а программа установки")
    p.add_argument("--progress", action="store_true",
                   help="ход по шагам — строки JSON в stderr (приложение amemo для Windows)")

    _, inner = group(sub, shared, "pg", "свой PostgreSQL (amemo setup): start, stop, status")
    for name, help_ in (("start", "запустить кластер"), ("stop", "остановить кластер"),
                        ("status", "запущен ли кластер")):
        add(inner, shared, name, help_, run_pg)


# --- настройки ---

def _config_path(ctx) -> Path:
    explicit = ctx.env.get("AMEMO_CONFIG", "").strip()
    return Path(explicit).expanduser() if explicit else home(ctx.env) / ".config" / "amemo" / "amemo.toml"


def _toml(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(str(value), ensure_ascii=False)        # строка JSON — допустимая базовая строка TOML


def _write_private(path: Path, text: str) -> None:
    """Файл атомарно, с правами 0600 (в amemo.toml — пароль в dsn)."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | O_BINARY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_config(path: Path, values: dict) -> None:
    """amemo.toml целиком."""
    lines = ["# настройки amemo (amemo setup); пароль — в dsn, файл читает только владелец"]
    lines += [f"{key} = {_toml(value)}" for key, value in values.items() if value is not None]
    _write_private(path, "\n".join(lines) + "\n")


def set_config_value(path: Path, key: str, value) -> None:
    """Одна строка верхнего уровня `ключ = значение` в amemo.toml; остальное — как было. Нет строки — дописывается
    перед первой таблицей."""
    lines = path.read_text(encoding="utf-8").splitlines()
    line = f"{key} = {_toml(value)}"
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    tables = next((i for i, x in enumerate(lines) if x.lstrip().startswith("[")), len(lines))
    for i, x in enumerate(lines[:tables]):
        if pattern.match(x):
            lines[i] = line
            break
    else:
        lines.insert(tables, line)
    _write_private(path, "\n".join(lines) + "\n")


def _existing(ctx, path: Path, pg_data: Path):
    """Прежние настройки этой же установки (повторный setup) или None; чужой amemo.toml — отказ."""
    from ... import settings as settings_

    if not path.exists():
        return None
    try:
        found = settings_.load({k: v for k, v in ctx.env.items() if not k.startswith("AMEMO_") or k == "AMEMO_CONFIG"})
    except settings_.SettingsError as e:
        raise CliError(f"{path}: {e}", exit=ENV, code="bad_config") from None
    if found.pg_data is None or Path(found.pg_data).resolve() != pg_data.resolve() or not found.dsn:
        raise CliError(f"{path}: файл настроек уже есть и создан не этой установкой — setup его не переписывает",
                       exit=USAGE, code="config_exists",
                       hint="задайте другой файл в AMEMO_CONFIG или перенесите прежний, затем повторите amemo setup")
    return found


def _agents(raw: str | None) -> list[str]:
    if not raw:
        return []
    names = [x.strip() for x in raw.split(",") if x.strip()]
    wrong = [x for x in names if x not in AGENTS]
    if wrong:
        raise CliError(f"--agents: неизвестные {', '.join(wrong)} — допустимы {', '.join(AGENTS)}", exit=USAGE,
                       code="bad_agents")
    return list(dict.fromkeys(names))


# --- setup ---

def run_setup(ctx, args) -> int:
    from ... import localpg, settings as settings_
    from ...agents import cowork, install
    from . import embed as embed_cmd, ocr as ocr_cmd
    from .setup import prepare

    agents = _agents(args.agents)
    config = _config_path(ctx)
    if not config.exists() and ctx.env.get("AMEMO_CONFIG", "").strip():
        # AMEMO_CONFIG указывает на файл, который setup только напишет: до того настройки (агент) — без него
        try:
            ctx._settings = settings_.load({k: v for k, v in ctx.env.items() if k != "AMEMO_CONFIG"})
        except settings_.SettingsError as e:
            raise CliError(str(e), exit=ENV, code="bad_config") from None
    if (args.embed or args.ocr) and not ctx.is_person:             # отказ до любых изменений
        from ... import api

        what = "смысловой поиск включает" if args.embed else "языки OCR ставит"
        raise api.Forbidden(f"{what} только человек (person:), а не {ctx.agent}: setup с --embed или --ocr "
                            f"запускает человек")
    if args.plugin_out and "cowork" not in agents:
        raise CliError("--plugin-out — только вместе с --agents cowork", exit=USAGE, code="bad_args")
    if args.embed_models and not args.embed:
        raise CliError("--embed-models — только вместе с --embed", exit=USAGE, code="bad_args")
    overridden = [var for var in OVERRIDES if ctx.env.get(var, "").strip()]
    if overridden:
        raise CliError(f"{', '.join(overridden)} в окружении перекрыли бы настройки, которые пишет setup", exit=USAGE,
                       code="env_overrides", hint="уберите эти переменные из окружения и повторите amemo setup")
    data = (args.data or home(ctx.env) / "amemo-data").expanduser().absolute()
    cluster = localpg.Cluster(args.pg_bin.expanduser().absolute(), data / "pg")
    try:
        major = cluster.check()
    except localpg.LocalPgError as e:
        raise CliError(str(e), exit=ENV, code="pg_bin") from None

    def stage(name: str, state: str) -> None:
        if args.progress:
            print(json.dumps({"stage": name, "state": state}), file=sys.stderr, flush=True)

    previous = _existing(ctx, config, cluster.data)
    steps = []
    stage("database", "running")
    try:
        if previous is None:
            port = args.port or localpg.free_port()
            password = secrets.token_urlsafe(24)
            if not cluster.exists:
                cluster.init(password, port)
                steps.append(f"кластер PostgreSQL {major}: {cluster.data}, порт {port}")
            else:
                raise CliError(f"{cluster.data}: кластер уже есть, а настроек для него нет — пароль неизвестен",
                               exit=ENV, code="cluster_orphan",
                               hint="выберите другую папку данных (--data) или удалите прежний кластер сами")
            values = {"dsn": localpg.dsn(password, port), "data": data / "objects", "docs": args.docs,
                      "state": data / "state", "backups": data / "backups",
                      "lang": getattr(args, "lang", None),               # общая опция --lang: и запишется в настройки
                      "pg_bin": localpg.native(cluster.bin), "pg_data": cluster.data,      # pg_dump бэкапа — оттуда же
                      "auto_update": False if args.no_auto_update else None}
            write_config(config, values)
            steps.append(f"настройки: {config}")
        else:
            steps.append(f"настройки уже есть: {config}")
            wanted = localpg.native(cluster.bin)
            if str(previous.pg_bin or "") != wanted:
                # новый комплект приложения: те же данные, программы PostgreSQL из другой папки
                on_disk = (cluster.data / "PG_VERSION").read_text(encoding="utf-8").strip()
                if on_disk != str(major):
                    raise CliError(f"кластер {cluster.data} — PostgreSQL {on_disk}, а программы {cluster.bin} — "
                                   f"{major}: данные другой мажорной версии без pg_upgrade не открыть", exit=ENV,
                                   code="pg_major")
                set_config_value(config, "pg_bin", wanted)
                steps.append(f"программы PostgreSQL: {wanted}")
        if cluster.start():
            steps.append("кластер запущен")
        ctx._settings = settings_.load(ctx.env)
        from psycopg.conninfo import make_conninfo

        made = localpg.ensure_database(make_conninfo(ctx.dsn(), dbname="postgres"))
        steps += made
    except localpg.LocalPgError as e:
        raise CliError(str(e), exit=ENV, code="local_pg") from None

    stage("database", "done")
    stage("store", "running")
    applied, base, root = prepare(ctx)
    stage("store", "done")
    result = {"base_id": base["base_id"], "config": str(config), "pg_data": str(cluster.data),
              "pg_bin": str(cluster.bin), "port": cluster.port(), "store": str(root),
              "migrations_applied": applied, "steps": steps, "embed": None, "ocr": None, "agents": []}

    stage("search", "running" if args.embed else "skipped")
    if args.embed:
        if args.embed_models:
            from ... import embed

            target = embed.models_dir()
            shutil.copytree(args.embed_models.expanduser(), target, dirs_exist_ok=True)
            steps.append(f"файлы модели: {target}")

        class _Yes:
            yes = True
        result["embed"] = embed_cmd.enable(ctx, _Yes())
        stage("search", "done")
    stage("ocr", "running" if args.ocr else "skipped")
    if args.ocr:
        result["ocr"] = ocr_cmd.install(ctx, ocr_cmd.languages_of([args.ocr]))
        stage("ocr", "done")
    stage("agents", "running" if agents else "skipped")
    for name in agents:
        try:
            if name == "cowork":
                plugin = cowork.build(ctx.env, args.plugin_out)
                result["agents"].append({"agent": name, "changed": plugin.action is not None,
                                         "path": str(plugin.path), "warnings": plugin.warnings})
                continue
            report = install.install(name, ctx.env)
        except (install.InstallError, install.AgentCommandError) as e:
            raise CliError(f"amemo install {name}: {e}", exit=ENV, code="install_failed") from None
        result["agents"].append({"agent": name, "changed": bool(report.changes or report.commands),
                                 "warnings": report.warnings})
    if agents:
        stage("agents", "done")

    def text(r):
        lines = [f"amemo готов: база {r['base_id']}, PostgreSQL на 127.0.0.1:{r['port']}",
                 *(f"  {s}" for s in r["steps"]), f"  хранилище: {r['store']}"]
        if r["embed"]:
            lines.append(f"  смысловой поиск: {r['embed']['model']['name']}")
        if r["ocr"]:
            got = [x["language"] for x in r["ocr"]["installed"]] + r["ocr"]["already"]
            lines.append(f"  распознавание сканов: {', '.join(got)}")
        for a in r["agents"]:
            if a["agent"] == "cowork":
                lines.append(f"  плагин для приложения Claude: {a['path']} — загрузите его: {cowork.UPLOAD}")
                continue
            lines.append(f"  агент {a['agent']}: " + ("подключён" if a["changed"] else "уже был подключён"))
        lines.append("дальше: amemo serve — веб-интерфейс на http://127.0.0.1:8767/ui/; "
                     "после перезагрузки — amemo pg start")
        return "\n".join(lines)
    ctx.emit(result, text)
    return 0


# --- pg ---

def run_pg(ctx, args) -> int:
    from ... import localpg

    action = args.pg_command
    s = ctx.settings
    if s.pg_bin is None or s.pg_data is None:
        raise CliError("своего PostgreSQL нет: в настройках нет pg_bin и pg_data", exit=ENV, code="no_local_pg",
                       hint="его создаёт amemo setup; база чужая — запускайте её своими средствами")
    cluster = localpg.Cluster(Path(s.pg_bin), Path(s.pg_data))
    try:
        if action == "start":
            changed = cluster.start()
        elif action == "stop":
            changed = cluster.stop()
        else:
            changed = False
        running = cluster.running()
        port = cluster.port()
    except localpg.LocalPgError as e:
        raise CliError(str(e), exit=ENV, code="local_pg") from None
    result = {"action": action, "changed": changed, "running": running, "pg_data": str(cluster.data), "port": port}
    ctx.emit(result, lambda r: f"PostgreSQL {'запущен' if r['running'] else 'остановлен'}: {r['pg_data']}, "
                               f"порт {r['port']}" + ("" if r["changed"] or action == "status" else " (уже так)"))
    return 0
