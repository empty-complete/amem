"""Пути HTTP v1 (docs/api/http-v1.openapi.yaml): тонкий слой над amem/api.py.

Обработчик разбирает путь и строку запроса, берёт соединение из пула службы (app.connection) и зовёт операцию api;
ошибки переводит amem/service/problems.py. Обработчики синхронные: Starlette зовёт их в пуле потоков, и psycopg
не держит цикл событий. Многозначные параметры — повтором (?kind=fact&kind=term), как style: form, explode: true
в контракте; отсутствующий параметр — пустой список, api читает его как «без фильтра».

Файл версии отдаётся FileResponse (Range → 206): типы из белого списка api.INLINE_TYPES — как есть, остальные —
application/octet-stream с Content-Disposition: attachment; всегда X-Content-Type-Options: nosniff
и Content-Security-Policy: sandbox — файл из базы не исполняется как страница службы.

Контракт служба отдаёт по /api/v1/openapi.json — копию из пакета (amem/service/http-v1.openapi.yaml).
"""
from __future__ import annotations

import functools
import importlib.resources

import yaml
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from .. import api
from . import session
from .app import API, connection

CONTRACT = "http-v1.openapi.yaml"
FILE_HEADERS = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"}


def _q(request: Request, name: str) -> str | None:
    return request.query_params.get(name)


def _many(request: Request, name: str) -> list[str]:
    """Значения многозначного параметра; пустые (?status=) — как отсутствующие: пустой фильтр — без фильтра."""
    return [value for value in request.query_params.getlist(name) if value != ""]


def get_session(request: Request) -> JSONResponse:
    session.grant(request)
    with connection(request) as conn:
        return JSONResponse(api.session(conn, agent=request.state.agent, can_write=request.state.can_write,
                                        provider=request.app.state.provider))


def search(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.search(conn, _q(request, "q"), agent=request.state.agent, kind=_many(request, "kind"),
                                       status=_many(request, "status"), entity_class=_many(request, "entity_class"),
                                       target=_q(request, "target"), limit=_q(request, "limit"),
                                       provider=request.app.state.provider))


def similar(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.similar(conn, agent=request.state.agent, ref=_q(request, "ref"), q=_q(request, "q"),
                                        limit=_q(request, "limit"), provider=request.app.state.provider))


def get_folders(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.folder_tree(conn))


def list_records(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.record_list(conn, folder=_q(request, "folder"), kind=_many(request, "kind"),
                                            status=_many(request, "status"), tag=_q(request, "tag"),
                                            about=_q(request, "about"), limit=_q(request, "limit"),
                                            cursor=_q(request, "cursor")))


def get_record(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.record(conn, request.path_params["ref"]))


def get_history(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.history(conn, request.path_params["ref"]))


def get_links(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.links(conn, request.path_params["ref"]))


def get_card(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.card(conn, request.path_params["ref"], ancestors=_q(request, "ancestors")))


def get_graph(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.graph(conn, _q(request, "ref"), depth=_q(request, "depth"),
                                      rels=_many(request, "rels"), status=_many(request, "status")))


def get_changes(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.changes(conn, since=_q(request, "since"), until=_q(request, "until"),
                                        who=_q(request, "who"), limit=_q(request, "limit")))


def get_object(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.object_view(conn, request.path_params["id"]))


def get_object_content(request: Request) -> FileResponse:
    with connection(request) as conn:
        content = api.object_content(conn, request.app.state.store, request.path_params["id"],
                                     request.path_params["n"])
    return FileResponse(content.path, media_type=content.media_type, headers=FILE_HEADERS, filename=content.filename,
                        content_disposition_type="inline" if content.inline else "attachment")


def get_object_text(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.object_text(conn, request.app.state.store, request.path_params["id"],
                                            request.path_params["n"], page=_q(request, "page")))


def get_object_sheet(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.object_sheet(conn, request.app.state.store, request.path_params["id"],
                                             request.path_params["n"], name=_q(request, "name"),
                                             cell_range=_q(request, "range")))


def get_vocab(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.vocab_entries(conn, request.path_params["scheme"]))


def get_base(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.base(conn))


def get_backups(request: Request) -> JSONResponse:
    return JSONResponse(api.backup_list(request.app.state.settings.backups))


@functools.cache
def contract() -> dict:
    """Контракт из пакета как JSON-объект (YAML читается один раз)."""
    return yaml.safe_load(importlib.resources.files(__package__).joinpath(CONTRACT).read_text(encoding="utf-8"))


def get_openapi(request: Request) -> JSONResponse:
    return JSONResponse(contract())


ROUTES = [
    Route(f"{API}/session", get_session, methods=["GET"]),
    Route(f"{API}/search", search, methods=["GET"]),
    Route(f"{API}/similar", similar, methods=["GET"]),
    Route(f"{API}/folders", get_folders, methods=["GET"]),
    Route(f"{API}/records", list_records, methods=["GET"]),
    Route(f"{API}/records/{{ref}}", get_record, methods=["GET"]),
    Route(f"{API}/records/{{ref}}/history", get_history, methods=["GET"]),
    Route(f"{API}/records/{{ref}}/links", get_links, methods=["GET"]),
    Route(f"{API}/entities/{{ref}}/card", get_card, methods=["GET"]),
    Route(f"{API}/graph", get_graph, methods=["GET"]),
    Route(f"{API}/changes", get_changes, methods=["GET"]),
    Route(f"{API}/objects/{{id}}", get_object, methods=["GET"]),
    Route(f"{API}/objects/{{id}}/versions/{{n}}/content", get_object_content, methods=["GET"]),
    Route(f"{API}/objects/{{id}}/versions/{{n}}/text", get_object_text, methods=["GET"]),
    Route(f"{API}/objects/{{id}}/versions/{{n}}/sheet", get_object_sheet, methods=["GET"]),
    Route(f"{API}/vocab/{{scheme}}", get_vocab, methods=["GET"]),
    Route(f"{API}/base", get_base, methods=["GET"]),
    Route(f"{API}/backups", get_backups, methods=["GET"]),
    Route(f"{API}/openapi.json", get_openapi, methods=["GET"]),
]
