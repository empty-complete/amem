"""Веб-интерфейс по /ui (спецификация подпроекта 4, разд. 3.4): статика установленного пакета amemo_web.

Папка сборки — amemo_web.static_dir() (index.html и assets/ с хэшами в именах, base /ui/ у сборки). Пакет ищется
при каждом запросе (импорт кэширует sys.modules): без него /ui отвечает 404 с подсказкой pip install 'amemo[web]'.

Отдача:
- файлы assets/ с хэшем сборки в имени — Cache-Control: immutable на год: новая сборка — новые имена. Имя — как
  у vite (build.rollupOptions по умолчанию: assets/[name]-[hash].[ext], хэш — 8 знаков base64url): «имя-хэш.расш»,
  хэш не короче 8 знаков и не из одних строчных букв (иначе это слово: index-template.js). Если в сборке есть
  манифест vite (.vite/manifest.json, build.manifest: true), immutable — только у файлов из него: имя похоже на
  хэш, а файл положили руками — no-cache. Прочие файлы — no-cache;
- index.html — no-cache (свежая сборка видна сразу) и выдача cookie человека по правилам session.grant: только
  запросу со своей страницы (Sec-Fetch-Site: same-origin) или из AMEMO_UI_ORIGINS. При вводе адреса браузер шлёт
  Sec-Fetch-Site: none — тогда cookie не выдаётся, её выдаст первый fetch /api/v1/session интерфейса (same-origin);
- неизвестный путь под /ui/ — index.html (маршруты приложения: /ui/records/…), кроме assets/: отсутствующий
  скрипт или стиль — 404, а не HTML под видом скрипта;
- сегмент, начинающийся с точки (.vite/manifest.json и прочие служебные файлы сборки), — 404;
- путь с «..», «.», «%», «\\» или NUL в сегменте (в том числе закодированный обход — Starlette сопоставляет уже
  раскодированный путь) и путь через символическую ссылку — 404: отдаётся только обычный файл внутри папки сборки,
  по ссылкам служба не ходит, даже по ведущим внутрь;
- у каждого ответа — X-Content-Type-Options: nosniff и CSP приложения: скрипты и запросы — только свои.
/ ведёт на /ui/, если интерфейс установлен; /ui — на /ui/ (относительные пути сборки).
"""
from __future__ import annotations

import functools
import importlib
import json
import re
from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, RedirectResponse, Response
from starlette.routing import Route

from . import problems, session

PACKAGE = "amemo_web"
INDEX = "index.html"
ASSETS = "assets"
# index-BxY3k9aP.js, codemirror-D1x_k2-q.js — имя от сборки vite: имя, «-», хэш (8+ знаков base64url или hex,
# не одни строчные буквы), одно расширение
HASHED = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*-(?=[a-z_-]*[A-Z0-9])[A-Za-z0-9_-]{8,}\.[A-Za-z0-9]+")
MANIFEST = Path(".vite") / "manifest.json"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
       "form-action 'self'")
HEADERS = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": CSP}
IMMUTABLE = "public, max-age=31536000, immutable"
_BAD = ("..", ".", "")


def _missing(detail: str) -> problems.Problem:
    return problems.Problem(404, "not_found", detail)


def static_root() -> Path:
    """Папка сборки веба (без ссылок в пути); нет пакета или сборки — 404 с подсказкой."""
    try:
        package = importlib.import_module(PACKAGE)
    except ModuleNotFoundError as e:
        if e.name != PACKAGE:
            raise
        raise _missing("веб-интерфейс не установлен: pip install 'amemo[web]' (пакет amemo_web), затем перезапустите "
                       "службу; API — по /api/v1") from None
    root = Path(package.static_dir()).resolve()
    if not (root / INDEX).is_file():
        raise _missing(f"в пакете {PACKAGE} нет сборки интерфейса ({INDEX}): переустановите amemo[web]")
    return root


def _file(root: Path, parts: list[str]) -> Path | None:
    """Обычный файл root/parts без символических ссылок по пути; нет его — None."""
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise _missing("нет такого файла интерфейса")
    if not path.is_file():
        return None
    if not path.resolve().is_relative_to(root):          # запасная проверка: путь не ушёл из папки сборки
        raise _missing("нет такого файла интерфейса")
    return path


@functools.lru_cache(maxsize=4)
def _manifest_files(path: Path, mtime_ns: int, size: int) -> frozenset[str]:
    """Файлы сборки из манифеста vite (file, css, assets записей); нечитаемый манифест — пустое множество.
    Кэш — по времени изменения и размеру: новая сборка читается заново."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    files = set()
    for entry in data.values() if isinstance(data, dict) else ():
        if not isinstance(entry, dict):
            continue
        for key in ("css", "assets"):
            files.update(item for item in entry.get(key) or () if isinstance(item, str))
        if isinstance(entry.get("file"), str):
            files.add(entry["file"])
    return frozenset(files)


def built(root: Path, parts: list[str]) -> bool:
    """Файл сборки с хэшем в имени: под assets/, имя как у vite и — если в сборке есть манифест — в манифесте."""
    if len(parts) < 2 or parts[0] != ASSETS or not HASHED.fullmatch(parts[-1]):
        return False
    manifest = root / MANIFEST
    try:
        stat = manifest.stat()
    except OSError:
        return True                 # сборка без манифеста — по имени
    return "/".join(parts) in _manifest_files(manifest, stat.st_mtime_ns, stat.st_size)


def _index(request: Request, root: Path) -> Response:
    session.grant(request)          # cookie человека — только своей странице (Sec-Fetch-Site: same-origin)
    return FileResponse(root / INDEX, media_type="text/html; charset=utf-8",
                        headers={**HEADERS, "Cache-Control": "no-cache"})


def root_of(request: Request) -> Path:
    """Корень сборки этого запуска службы: запомненный при старте (app.state.ui_root; перед обновлением — копия
    прежней сборки), иначе — по пакету сейчас."""
    pinned = getattr(request.app.state, "ui_root", None)
    return pinned if pinned is not None else static_root()


def snapshot(root: Path, target: Path) -> Path:
    """Копия сборки root в target (без символических ссылок): обновление заменит файлы пакета, а открытые вкладки
    до перезапуска грузят прежние assets."""
    import shutil

    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(root, target, symlinks=True, ignore_dangling_symlinks=True)
    return target.resolve()


def ui_file(request: Request) -> Response:
    root = root_of(request)
    rel = request.path_params["path"]
    parts = rel.split("/")
    if parts and parts[-1] == "":
        parts.pop()                 # /ui/records/ — маршрут приложения, как /ui/records
    if any(p in _BAD or p.startswith(".") or "%" in p or "\\" in p or "\x00" in p for p in parts):
        raise _missing("нет такого файла интерфейса")
    if not parts or parts == [INDEX]:
        return _index(request, root)
    path = _file(root, parts)
    if path is None:
        if parts[0] == ASSETS:
            raise _missing("нет такого файла интерфейса: сборка обновилась — перезагрузите страницу")
        return _index(request, root)
    cache = IMMUTABLE if built(root, parts) else "no-cache"
    return FileResponse(path, headers={**HEADERS, "Cache-Control": cache})


def ui_root(request: Request) -> Response:
    root_of(request)
    return RedirectResponse("/ui/", status_code=307, headers={"X-Content-Type-Options": "nosniff"})


ROUTES = [
    Route("/", ui_root, methods=["GET"]),
    Route("/ui", ui_root, methods=["GET"]),
    Route("/ui/{path:path}", ui_file, methods=["GET"]),
]
