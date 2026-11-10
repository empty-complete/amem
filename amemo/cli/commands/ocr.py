"""Распознавание сканов PDF (OCR) — расширение на выбор: install, list, remove над папкой языковых данных.

amemo ocr install ЯЗЫК… скачивает .traineddata из репозиториев tesseract-ocr (tessdata_fast — быстрее и меньше,
по умолчанию; tessdata_best — точнее и в несколько раз больше) по HTTPS в ocr_data (AMEMO_OCR_DATA, по умолчанию
~/.local/share/amemo/tessdata). Файл пишется во временный рядом и встаёт на место переименованием; ответ — 200,
не пустой и с заголовком контейнера tessdata (число частей и их смещения), иначе ничего не меняется. Уже
установленный язык без --force не качается. Распознаёт встроенная в PyMuPDF библиотека tesseract: бинарник
tesseract не нужен, только языковые данные.

После install и remove в amemo.toml (как у amemo init: $AMEMO_CONFIG или ~/.config/amemo/amemo.toml) пишутся
ocr = "tesseract" и ocr_languages — языки, которые есть в ocr_data; когда языков не осталось, обе строки
убираются (снова auto: системный tesseract, если он есть). Файл правится целиком через временный и переименование,
чужие ключи и комментарии остаются; --no-config — не трогать amemo.toml (сборка образа: там настройки — окружение).

Ставит и убирает языки только человек: это меняет установку (модель — код 2, как у токенов). list — всем.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import struct
import tomllib
from pathlib import Path

from ...portable import O_BINARY, home as home_
from ..errors import ENV, NOT_FOUND, USAGE, CliError
from . import add, group

QUALITIES = ("fast", "best")
SOURCE = "https://github.com/tesseract-ocr/tessdata_{quality}/raw/main/{lang}.traineddata"
TIMEOUT = 60                       # с на соединение и паузу в ответе
LIMIT = 200 << 20                  # больше байт языковой файл не бывает (best — до ~100 МиБ)
MAX_ENTRIES = 64                   # частей в контейнере tessdata (у tesseract 4–5 — 24)
SUFFIX = ".traineddata"


class DownloadError(Exception):
    """Скачать не удалось; status — HTTP-статус ответа, если он был."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def register(sub, shared) -> None:
    _, inner = group(sub, shared, "ocr", "распознавание сканов PDF: языки tesseract (расширение на выбор)")
    p = add(inner, shared, "install", "скачать языки tesseract и включить OCR (только человек)", run_install)
    p.add_argument("languages", nargs="+", metavar="ЯЗЫК", help="коды tessdata: rus eng deu … (или через запятую)")
    p.add_argument("--quality", choices=QUALITIES, default="fast",
                   help="fast — быстрее и меньше (по умолчанию), best — точнее и крупнее")
    p.add_argument("--force", action="store_true", help="скачать заново, даже если язык уже установлен")
    p.add_argument("--no-config", action="store_true", help="не править amemo.toml (настройки — в окружении)")
    add(inner, shared, "list", "режим OCR, установленные языки и папка данных", run_list)
    p = add(inner, shared, "remove", "удалить языки из папки данных (только человек)", run_remove)
    p.add_argument("languages", nargs="+", metavar="ЯЗЫК", help="коды tessdata: rus eng …")
    p.add_argument("--no-config", action="store_true", help="не править amemo.toml (настройки — в окружении)")


# --- языки и папка ---

def languages_of(values) -> list[str]:
    """Коды языков из аргументов («rus eng» или «rus,eng»); неверный код — код 2."""
    from ... import settings

    found = []
    for value in values:
        for lang in settings.ocr_language_list(value):
            lang = lang.lower()
            if not settings.OCR_LANGUAGE.fullmatch(lang):
                raise CliError(f"язык {lang!r}: нужен код tessdata из строчных латинских букв и «_» (rus, eng, "
                               f"chi_sim)", exit=USAGE, code="usage")
            found.append(lang)
    if not found:
        raise CliError("языки не заданы: amemo ocr install rus eng", exit=USAGE, code="usage")
    return list(dict.fromkeys(found))


def installed(folder: Path) -> list[str]:
    """Языки в папке данных (по именам .traineddata), по алфавиту."""
    from ... import settings

    try:
        names = [p.name[:-len(SUFFIX)] for p in Path(folder).iterdir() if p.name.endswith(SUFFIX) and p.is_file()]
    except (FileNotFoundError, NotADirectoryError):
        return []
    return sorted(n for n in names if settings.OCR_LANGUAGE.fullmatch(n))


def looks_like_traineddata(head: bytes, size: int) -> bool:
    """Заголовок контейнера tessdata: int32 число частей, затем их int64 смещения (-1 — части нет), и первая
    часть начинается сразу за таблицей. Страница ошибки (HTML) или обрывок сюда не проходят."""
    if len(head) < 4:
        return False
    count = struct.unpack("<i", head[:4])[0]
    table = 4 + 8 * count
    if not 1 <= count <= MAX_ENTRIES or len(head) < table or size <= table:
        return False
    offsets = [struct.unpack("<q", head[4 + 8 * i:12 + 8 * i])[0] for i in range(count)]
    present = [o for o in offsets if o != -1]
    return bool(present) and all(table <= o < size for o in present) and min(present) == table


def fetch(url: str, out) -> None:
    """Скачать url в открытый двоичный файл out; ответ не 200 или сбой сети — DownloadError (тесты подменяют)."""
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": "amemo-ocr"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:   # noqa: S310 — адрес https:// выше
            if response.status != 200:
                raise DownloadError(f"{url}: ответ {response.status}", response.status)
            total = 0
            while chunk := response.read(1 << 20):
                total += len(chunk)
                if total > LIMIT:
                    raise DownloadError(f"{url}: больше {LIMIT >> 20} МиБ — это не языковой файл")
                out.write(chunk)
    except urllib.error.HTTPError as e:
        raise DownloadError(f"{url}: ответ {e.code}", e.code) from None
    except (OSError, ValueError) as e:
        raise DownloadError(f"{url}: {getattr(e, 'reason', e)}") from None


def download(lang: str, quality: str, folder: Path) -> int:
    """Скачать язык в folder атомарно; размер файла. Неверный ответ — CliError, прежний файл остаётся."""
    url = SOURCE.format(quality=quality, lang=lang)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".{lang}{SUFFIX}.{secrets.token_hex(6)}.tmp"
    try:
        with open(tmp, "xb") as f:
            try:
                fetch(url, f)
            except DownloadError as e:
                if e.status == 404:
                    raise CliError(f"языка {lang!r} нет в tessdata_{quality}", exit=NOT_FOUND, code="not_found",
                                   hint="коды языков: https://github.com/tesseract-ocr/tessdata_fast") from None
                raise CliError(f"язык {lang}: скачать не удалось — {e}", exit=ENV, code="ocr_download",
                               hint="проверьте сеть и повторите: amemo ocr install " + lang) from None
            f.flush()
            os.fsync(f.fileno())
        size = tmp.stat().st_size
        with open(tmp, "rb") as f:
            head = f.read(4 + 8 * MAX_ENTRIES)
        if not size or not looks_like_traineddata(head, size):
            raise CliError(f"язык {lang}: с {url} пришло не то ({size} байт, не языковые данные tesseract)",
                           exit=ENV, code="ocr_download", hint="повторите позже: amemo ocr install " + lang)
        os.chmod(tmp, 0o644)
        os.replace(tmp, folder / f"{lang}{SUFFIX}")
        return size
    finally:
        tmp.unlink(missing_ok=True)


# --- amemo.toml ---

def config_path(ctx) -> Path:
    """amemo.toml, который читает settings.load: $AMEMO_CONFIG или ~/.config/amemo/amemo.toml (HOME окружения)."""
    from ... import settings

    home = home_(ctx.env)
    explicit = ctx.env.get("AMEMO_CONFIG", "").strip()
    return settings._expand(explicit, home) if explicit else home / ".config" / "amemo" / "amemo.toml"


_KEY = re.compile(r"\s*(ocr|ocr_languages)\s*=")


def set_config(path: Path, values: dict) -> None:
    """Задать (значение) или убрать (None) ключи верхнего уровня amemo.toml, не трогая остального: строки этих
    ключей заменяются, чужие ключи и комментарии остаются; запись — временный файл рядом и переименование.
    Файл-симлинк правится в своей цели."""
    target = Path(os.path.realpath(path)) if path.is_symlink() else path
    if not target.exists() and all(v is None for v in values.values()):
        return                                     # убирать нечего: файла настроек нет
    text = target.read_text(encoding="utf-8") if target.exists() else ""
    try:
        before = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise CliError(f"{target}: не читается как TOML ({e}) — поправьте файл руками", exit=USAGE,
                       code="settings") from None
    lines, skip = [], False
    for line in text.splitlines():
        if skip:                                   # продолжение многострочного списка ocr_languages = [
            skip = "]" not in line
            continue
        if (m := _KEY.match(line)) and m[1] in values:
            skip = line.count("[") > line.count("]")
            continue
        lines.append(line)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        lines.append("# настройки amemo")
    for key, value in values.items():
        if value is not None:
            lines.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
    result = "\n".join(lines) + "\n"
    after = tomllib.loads(result)
    expected = {k: v for k, v in before.items() if k not in values}
    expected.update({k: v for k, v in values.items() if v is not None})
    if after != expected:                         # правка строк задела чужое — не пишем
        raise CliError(f"{target}: не удалось поправить ocr и ocr_languages, не задев остального — впишите "
                       f"их руками: {', '.join(f'{k} = {json.dumps(v, ensure_ascii=False)}' for k, v in values.items() if v is not None)}",
                       exit=USAGE, code="settings")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    mode = (target.stat().st_mode & 0o777) if target.exists() else 0o600   # в amemo.toml бывает пароль DSN
    tmp = target.with_name(f".{target.name}.{secrets.token_hex(6)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_BINARY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(result)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _configure(ctx, folder: Path, args, asked=()) -> str | None:
    """ocr и ocr_languages в amemo.toml по языкам папки — в порядке прежней настройки, затем asked, затем
    остальные; путь файла или None (--no-config)."""
    if getattr(args, "no_config", False):
        return None
    langs = installed(folder)
    order = [x for x in dict.fromkeys([*ctx.settings.ocr_languages, *asked, *langs]) if x in langs]
    path = config_path(ctx)
    shadowed = [var for var in ("AMEMO_OCR", "AMEMO_OCR_LANGUAGES") if ctx.env.get(var, "").strip()]
    if shadowed:
        ctx.note(f"amemo: {', '.join(shadowed)} в окружении перекрывает amemo.toml — поправьте окружение")
    set_config(path, {"ocr": "tesseract", "ocr_languages": order} if order else {"ocr": None, "ocr_languages": None})
    return str(path)


def _person(ctx, what: str) -> None:
    if not ctx.is_person:
        from ... import api

        raise api.Forbidden(f"языки OCR {what} только человек (person:), а не {ctx.agent}: это меняет установку")


# --- команды ---

def install(ctx, langs: list[str], *, quality: str = "fast", force: bool = False, args=None) -> dict:
    """Поставить языки (общая часть amemo ocr install и amemo init --ocr): что скачано и что уже было."""
    _person(ctx, "ставит")
    folder = Path(ctx.settings.ocr_data)
    done, kept = [], []
    for lang in langs:
        if not force and (folder / f"{lang}{SUFFIX}").is_file():
            kept.append(lang)
            continue
        size = download(lang, quality, folder)
        done.append({"language": lang, "bytes": size})
    saved = _configure(ctx, folder, args, langs)
    return {"installed": done, "already": kept, "quality": quality, "data": str(folder), "config_saved": saved}


def run_install(ctx, args) -> int:
    langs = languages_of(args.languages)
    result = install(ctx, langs, quality=args.quality, force=args.force, args=args)

    def text(r):
        lines = [f"{x['language']}: скачан ({x['bytes'] / (1 << 20):.1f} МиБ, {r['quality']})" for x in r["installed"]]
        lines += [f"{x}: уже установлен (заново — --force)" for x in r["already"]]
        lines.append(f"данные: {r['data']}")
        if r["config_saved"]:
            lines.append(f"OCR включён: {r['config_saved']}")
        return "\n".join(lines)
    ctx.emit(result, text)
    return 0


def status(settings) -> dict:
    """Режим OCR, языки и папка (amemo ocr list, amemo doctor)."""
    from ... import sources

    setup = sources.ocr_setup(settings)
    return {"mode": "tesseract" if setup is not None else "none", "setting": settings.ocr,
            "languages": setup.languages.split("+") if setup is not None else [],
            "tessdata": str(setup.tessdata) if setup is not None else None,
            "system": bool(setup is not None and setup.system),
            "data": str(settings.ocr_data), "installed": installed(settings.ocr_data),
            "wanted": list(settings.ocr_languages)}


def run_list(ctx, args) -> int:
    def text(r):
        lines = [f"режим: {r['mode']}" + (f" (ocr = {r['setting']})" if r["setting"] != "auto" else " (auto)")]
        if r["mode"] == "tesseract":
            lines.append(f"языки: {'+'.join(r['languages'])} из {r['tessdata']}"
                         + (" (системный tesseract)" if r["system"] else ""))
        lines.append(f"установлены в {r['data']}: {', '.join(r['installed']) or 'нет'}")
        if r["mode"] == "none" and r["setting"] != "none":
            lines.append("распознать сканы нечем: amemo ocr install rus eng")
        return "\n".join(lines)
    ctx.emit(status(ctx.settings), text)
    return 0


def run_remove(ctx, args) -> int:
    langs = languages_of(args.languages)
    _person(ctx, "удаляет")
    folder = Path(ctx.settings.ocr_data)
    missing = [lang for lang in langs if not (folder / f"{lang}{SUFFIX}").is_file()]
    if missing:
        raise CliError(f"в {folder} нет языков: {', '.join(missing)}", exit=NOT_FOUND, code="not_found",
                       hint="установленные языки: amemo ocr list")
    for lang in langs:
        (folder / f"{lang}{SUFFIX}").unlink()
    saved = _configure(ctx, folder, args)
    result = {"removed": langs, "data": str(folder), "left": installed(folder), "config_saved": saved}
    ctx.emit(result, lambda r: f"удалены: {', '.join(r['removed'])}; осталось: {', '.join(r['left']) or 'нет'}")
    return 0
