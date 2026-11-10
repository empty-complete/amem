"""Смысловой поиск — расширение на выбор: amemo embed enable|status.

amemo embed enable (только человек) включает смысловой канал поиска. По порядку: AMEMO_BACKEND не выключает канал
(none) и пакет fastembed установлен (extra amemo[embed]); база готова — до скачивания, а не после; модель по
умолчанию (embed.DEFAULT_MODEL, около 250 МБ) есть в папке embed.models_dir() — иначе скачивается, но только с
разрешения: --yes или «да» на вопрос в интерактивном терминале (stdin — tty, не --json, не CI). Затем модель
регистрируется в базе (embed.register_model), вектора всех текущих поисковых документов считаются
(embed.sync_embeddings), и модель становится активной (embed.activate_model). Запись между счётом и активацией
оставила бы документ без вектора — тогда счёт повторяется (до ATTEMPTS раз).

Повторный запуск ничего не качает и досчитывает вектора записей, появившихся или изменившихся с прошлого раза: сама
запись вектор не считает, и покрытие (amemo embed status) со временем падает.

amemo embed status — всем: AMEMO_BACKEND, пакет fastembed, папка модели, активная модель, покрытие текущих
документов и пойдёт ли смысловой канал. Модель активна и провайдер её — пробный вектор из локальных файлов (без
сети): не считается — reason embedding_failed. Код 0. То же состояние — строка «смысловой поиск» у amemo doctor.
"""
from __future__ import annotations

import importlib.util
import os
import sys

from ..errors import ENV, USAGE, CliError
from . import add, group

MB = 250                            # примерный размер файлов модели по умолчанию (embed.DEFAULT_MODEL)
PROBE = "amemo"                     # текст пробного вектора
ATTEMPTS = 3                        # счёт и активация: запись между ними — посчитать недостающее снова
YES = ("y", "yes", "д", "да")
INSTALL = "uv tool install 'amemo[web,embed]' (или pip install 'amemo[embed]')"


def register(sub, shared) -> None:
    _, inner = group(sub, shared, "embed", "смысловой поиск: локальная модель векторов (расширение на выбор)")
    p = add(inner, shared, "enable", "скачать модель, посчитать вектора и включить смысловой поиск (только человек)",
            run_enable)
    p.add_argument("--yes", "-y", action="store_true",
                   help=f"разрешить скачать модель (~{MB} МБ) без вопроса")
    add(inner, shared, "status", "смысловой поиск: модель, покрытие векторами, что сделать", run_status)


# --- окружение ---

def backend() -> str:
    """AMEMO_BACKEND, как его читает embed.get_provider (окружение процесса)."""
    return os.environ.get("AMEMO_BACKEND", "fastembed").strip().lower()


def installed() -> bool:
    """Пакет fastembed есть (без импорта: он тяжёлый)."""
    try:
        return importlib.util.find_spec("fastembed") is not None
    except ValueError:              # модуль уже в sys.modules, но без __spec__
        return sys.modules.get("fastembed") is not None
    except ImportError:
        return False


# --- enable ---

QUESTION = "Скачать модель смыслового поиска {name} (~{mb} МБ) в {folder}? [y/N] "


def _interactive(ctx) -> bool:
    try:
        tty = sys.stdin.isatty()
    except (AttributeError, ValueError, OSError):
        return False
    return tty and not ctx.json and not ctx.env.get("CI", "").strip()


def _allow(ctx, args, name: str, folder) -> None:
    """Разрешение скачать модель: --yes или «да» в интерактивном терминале; иначе код 2."""
    if args.yes:
        return
    hint = "разрешите скачать: amemo embed enable --yes"
    if not _interactive(ctx):
        raise CliError(f"модель {name} (~{MB} МБ) скачивается только с разрешения", exit=USAGE,
                       code="download_not_allowed", hint=hint)
    print(QUESTION.format(name=name, mb=MB, folder=folder), end="", file=ctx.err, flush=True)
    if sys.stdin.readline().strip().lower() not in YES:
        raise CliError("модель не скачана: смысловой поиск не включён", exit=USAGE, code="download_not_allowed",
                       hint=hint)


def _provider(ctx, args, folder):
    """Провайдер модели по умолчанию и скачана ли она сейчас: файлы в folder — без сети и без вопроса."""
    from ... import embed

    local = embed.FastembedProvider(cache_dir=str(folder))
    try:
        local.embed([PROBE])
        return local, False
    except embed.EmbeddingError:
        pass                        # файлов модели нет или они не читаются — скачать заново
    _allow(ctx, args, local.name, folder)
    ctx.note(f"amemo: скачиваю модель {local.name} (~{MB} МБ) в {folder}…")
    remote = embed.FastembedProvider(cache_dir=str(folder), allow_download=True)
    try:
        remote.embed([PROBE])
    except embed.EmbeddingError as e:
        raise CliError(f"модель не скачалась: {e}", exit=ENV, code="embed_download",
                       hint="проверьте сеть и место на диске и повторите: amemo embed enable --yes") from None
    return remote, True


def _person(ctx) -> None:
    if not ctx.is_person:
        from ... import api

        raise api.Forbidden(f"смысловой поиск включает только человек (person:), а не {ctx.agent}: это скачивает "
                            f"модель и меняет установку")


def run_enable(ctx, args) -> int:
    from ... import embed

    _person(ctx)
    chosen = backend()
    if chosen == "none":
        raise CliError("AMEMO_BACKEND=none выключает смысловой поиск", exit=USAGE, code="backend_disabled",
                       hint="уберите AMEMO_BACKEND из окружения (или задайте fastembed) и повторите")
    if chosen != "fastembed":
        raise CliError(f"неизвестный AMEMO_BACKEND {chosen!r}: нужен fastembed или none", exit=USAGE,
                       code="backend_unknown", hint="уберите AMEMO_BACKEND или задайте fastembed")
    if not installed():
        raise CliError("пакет fastembed не установлен: смысловому поиску нужен extra amemo[embed]", exit=ENV,
                       code="fastembed_missing", hint=f"установите: {INSTALL}, затем amemo embed enable")
    conn = ctx.connect()
    folder = embed.models_dir()
    provider, downloaded = _provider(ctx, args, folder)
    model = embed.register_model(conn, provider)
    missing = embed.embedding_coverage(conn, model["id"])
    if missing["missing"]:
        ctx.note(f"amemo: считаю вектора: {missing['missing']} из {missing['total']} документов…")
    embedded = 0
    for attempt in range(ATTEMPTS):
        embedded += embed.sync_embeddings(conn, model["id"], provider)["embedded"]
        try:
            model = embed.activate_model(conn, model["id"])
            break
        except embed.EmbeddingError:
            if attempt == ATTEMPTS - 1:
                raise
    result = {"model": model, "downloaded": downloaded, "models_dir": str(folder), "embedded": embedded,
              "coverage": embed.embedding_coverage(conn, model["id"])}

    def text(r):
        m, c = r["model"], r["coverage"]
        return "\n".join([
            f"модель: {m['name']} v{m['version']} ({m['backend']}, {m['dims']}) — "
            + (f"скачана в {r['models_dir']}" if r["downloaded"] else f"из {r['models_dir']}"),
            f"посчитано векторов: {r['embedded']}; покрытие: {c['covered']} из {c['total']} документов",
            "смысловой поиск включён; новые записи досчитывает повторный amemo embed enable",
        ])
    ctx.emit(result, text)
    return 0


# --- status ---

def state(ctx, conn) -> dict:
    """Состояние смыслового поиска: для amemo embed status и строки amemo doctor."""
    from ... import embed, recipes, search

    provider = ctx.provider()
    found = recipes.availability(conn, provider)
    semantic, reason, error = found["semantic"], found["reason"], None
    if semantic == "used":
        try:
            provider.embed([PROBE])
        except (embed.EmbeddingError, ImportError) as e:
            semantic, reason, error = "unavailable", "embedding_failed", str(e)
    active = search._active_model(conn)
    return {
        "semantic": semantic, "reason": reason, "error": error,
        "backend": backend(), "fastembed": installed(), "models_dir": str(embed.models_dir()),
        "model": embed._model_json(active) if active is not None else None,
        "coverage": embed.embedding_coverage(conn, active[0]) if active is not None else None,
        "documents": conn.execute("SELECT count(*) FROM search_document").fetchone()[0],
    }


def next_step(r: dict) -> str | None:
    """Что сделать, чтобы смысловой поиск заработал (или досчитал вектора); None — делать нечего."""
    reason = r["reason"]
    if r["semantic"] == "used":
        return "досчитать вектора новых записей: amemo embed enable" if r["coverage"]["missing"] else None
    if reason == "backend_disabled" or (reason == "no_active_model" and r["backend"] == "none"):
        return "AMEMO_BACKEND=none выключает его: уберите переменную, затем amemo embed enable"
    if reason == "backend_unknown" or r["backend"] != "fastembed":
        return f"AMEMO_BACKEND {r['backend']!r}: нужен fastembed или none"
    if not r["fastembed"]:
        return f"установите extra amemo[embed]: {INSTALL}, затем amemo embed enable"
    if reason == "no_active_model":
        return f"включить: amemo embed enable (скачает модель ~{MB} МБ)"
    if reason == "provider_mismatch":
        return "активна модель не того провайдера: amemo embed enable включит модель по умолчанию"
    if reason == "embedding_failed":
        return f"файлы модели не читаются из {r['models_dir']}: скачать заново — amemo embed enable"
    return "amemo embed status"


def doctor_line(r: dict) -> tuple[str, str]:
    """Строка doctor «смысловой поиск»: статус и подробность с подсказкой."""
    m, c, step = r["model"], r["coverage"], next_step(r)
    if r["semantic"] == "used":
        detail = f"{m['name']} v{m['version']}: векторов {c['covered']} из {c['total']}"
        return ("warn", f"{detail} — {step}") if step else ("ok", detail)
    return "warn", f"недоступен ({r['reason']}): работают марки и полнотекстовый — {step}"


def run_status(ctx, args) -> int:
    conn = ctx.connect()

    def text(r):
        m, c = r["model"], r["coverage"]
        lines = ["смысловой поиск: " + ("работает" if r["semantic"] == "used" else f"недоступен ({r['reason']})"),
                 f"AMEMO_BACKEND: {r['backend']}; пакет fastembed: {'есть' if r['fastembed'] else 'нет'}; "
                 f"папка модели: {r['models_dir']}",
                 f"модель: {m['name']} v{m['version']} ({m['backend']}, {m['dims']})" if m else "активной модели нет"]
        if c is not None:
            lines.append(f"вектора: {c['covered']} из {c['total']} документов"
                         + (f", не хватает {c['missing']}" if c["missing"] else ""))
        else:
            lines.append(f"документов для векторов: {r['documents']}")
        if r["error"]:
            lines.append(f"ошибка модели: {r['error']}")
        if step := next_step(r):
            lines.append(f"дальше: {step}")
        return "\n".join(lines)
    ctx.emit(state(ctx, conn), text)
    return 0
