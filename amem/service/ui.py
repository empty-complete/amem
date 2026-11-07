"""Веб-интерфейс по /ui (спецификация подпроекта 4, разд. 3.4): статика установленного пакета amem_web.

Папка сборки — amem_web.static_dir() (index.html и assets/ с хэшами в именах, base /ui/ у сборки). Пакет ищется
при каждом запросе (импорт кэширует sys.modules): без него /ui отвечает 404 с подсказкой pip install 'amem[web]'.

Отдача:
- файлы assets/ с хэшем в имени — Cache-Control: immutable на год: новая сборка — новые имена;
- index.html — no-cache (свежая сборка видна сразу) и выдача cookie человека по правилам session.grant: только
  запросу со своей страницы (Sec-Fetch-Site: same-origin) или из AMEM_UI_ORIGINS. При вводе адреса браузер шлёт
  Sec-Fetch-Site: none — тогда cookie не выдаётся, её выдаст первый fetch /api/v1/session интерфейса (same-origin);
- неизвестный путь под /ui/ — index.html (маршруты приложения: /ui/records/…), кроме assets/: отсутствующий
  скрипт или стиль — 404, а не HTML под видом скрипта;
- путь с «..», «.», «%», «\\» или NUL в сегменте (в том числе закодированный обход — Starlette сопоставляет уже
  раскодированный путь) и путь через символическую ссылку — 404: отдаётся только обычный файл внутри папки сборки,
  по ссылкам служба не ходит, даже по ведущим внутрь;
- у каждого ответа — X-Content-Type-Options: nosniff и CSP приложения: скрипты и запросы — только свои.
/ ведёт на /ui/, если интерфейс установлен; /ui — на /ui/ (относительные пути сборки).
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, RedirectResponse, Response
from starlette.routing import Route

from . import problems, session

PACKAGE = "amem_web"
INDEX = "index.html"
ASSETS = "assets"
HASHED = re.compile(r".+[.-][A-Za-z0-9_-]{8,}\.[A-Za-z0-9]+")     # index-BxY3k9aP.js — имя от сборки vite
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
        raise _missing("веб-интерфейс не установлен: pip install 'amem[web]' (пакет amem_web), затем перезапустите "
                       "службу; API — по /api/v1") from None
    root = Path(package.static_dir()).resolve()
    if not (root / INDEX).is_file():
        raise _missing(f"в пакете {PACKAGE} нет сборки интерфейса ({INDEX}): переустановите amem[web]")
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


def _index(request: Request, root: Path) -> Response:
    session.grant(request)          # cookie человека — только своей странице (Sec-Fetch-Site: same-origin)
    return FileResponse(root / INDEX, media_type="text/html; charset=utf-8",
                        headers={**HEADERS, "Cache-Control": "no-cache"})


def ui_file(request: Request) -> Response:
    root = static_root()
    rel = request.path_params["path"]
    parts = rel.split("/")
    if parts and parts[-1] == "":
        parts.pop()                 # /ui/records/ — маршрут приложения, как /ui/records
    if any(p in _BAD or "%" in p or "\\" in p or "\x00" in p for p in parts):
        raise _missing("нет такого файла интерфейса")
    if not parts or parts == [INDEX]:
        return _index(request, root)
    path = _file(root, parts)
    if path is None:
        if parts[0] == ASSETS:
            raise _missing("нет такого файла интерфейса: сборка обновилась — перезагрузите страницу")
        return _index(request, root)
    cache = IMMUTABLE if parts[0] == ASSETS and HASHED.fullmatch(parts[-1]) else "no-cache"
    return FileResponse(path, headers={**HEADERS, "Cache-Control": cache})


def ui_root(request: Request) -> Response:
    static_root()
    return RedirectResponse("/ui/", status_code=307, headers={"X-Content-Type-Options": "nosniff"})


ROUTES = [
    Route("/", ui_root, methods=["GET"]),
    Route("/ui", ui_root, methods=["GET"]),
    Route("/ui/{path:path}", ui_file, methods=["GET"]),
]
