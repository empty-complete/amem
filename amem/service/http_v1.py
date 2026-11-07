"""Пути HTTP v1 (docs/api/http-v1.openapi.yaml): тонкий слой над amem/api.py.

Обработчик разбирает путь и строку запроса, берёт соединение из пула службы (app.connection) и зовёт операцию api;
ошибки переводит amem/service/problems.py. Обработчики синхронные: Starlette зовёт их в пуле потоков, и psycopg
не держит цикл событий. Многозначные параметры — повтором (?kind=fact&kind=term), как style: form, explode: true
в контракте; отсутствующий параметр — пустой список, api читает его как «без фильтра».

Файл версии отдаётся FileCopy (FileResponse; Range → 206, неверный Range — problem+json 400, вне файла — 416): типы
из белого списка api.INLINE_TYPES — как есть, остальные — application/octet-stream с Content-Disposition: attachment;
всегда X-Content-Type-Options: nosniff и Content-Security-Policy: sandbox — файл из базы не исполняется как страница
службы.

Пути записи (очередь, submit, папки) читают тело в цикле событий — потоком, с отсечкой на BODY_LIMIT (413 too_large:
Content-Length — только быстрый отказ, ему не верят, chunked ограничен так же; <private> и проверки идут по всему
тексту, и без предела большое тело — отказ в обслуживании), разбирают JSON (не объект, NaN, слишком глубокая
вложенность — 400) и зовут операцию api в пуле потоков. Агент записи — только из сессии (request.state.agent): поле
агента в теле не читается. Маршруты папок — {path:path}: Starlette сопоставляет уже раскодированный путь, и папка
«a/b», пришедшая как a%2Fb, иначе в {path} не попала бы.

Контракт служба отдаёт по /api/v1/openapi.json — копию из пакета (amem/service/http-v1.openapi.yaml).
"""
from __future__ import annotations

import functools
import importlib.resources
import json

import yaml
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, MalformedRangeHeader, RangeNotSatisfiable, Response
from starlette.routing import Route

from .. import api
from . import problems, session
from .app import API, connection, provider

CONTRACT = "http-v1.openapi.yaml"
FILE_HEADERS = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"}
BODY_LIMIT = 1 << 20          # байт JSON-тела записи: пакет submit — сотни атомов; больше — 413 too_large


class FileCopy(FileResponse):
    """FileResponse, у которого неверный или невыполнимый Range — problem+json (400, 416 с Content-Range), а не
    text/plain: разбор диапазона — Starlette, ответ-ошибка — как у всей службы."""

    @classmethod
    def _parse_range_header(cls, http_range: str, file_size: int) -> list[tuple[int, int]]:
        try:
            return super()._parse_range_header(http_range, file_size)
        except MalformedRangeHeader as e:
            raise problems.Problem(400, "bad_request", f"заголовок Range {http_range[:80]!r}: {e.content}",
                                   headers=FILE_HEADERS) from None
        except RangeNotSatisfiable as e:
            raise problems.Problem(416, "range_not_satisfiable", f"диапазон {http_range[:80]!r} вне файла "
                                   f"({e.max_size} байт)", headers={**FILE_HEADERS,
                                                                    "Content-Range": f"bytes */{e.max_size}"}) from None


def _q(request: Request, name: str) -> str | None:
    return request.query_params.get(name)


def _many(request: Request, name: str) -> list[str]:
    """Значения многозначного параметра; пустые (?status=) — как отсутствующие: пустой фильтр — без фильтра."""
    return [value for value in request.query_params.getlist(name) if value != ""]


def get_session(request: Request) -> JSONResponse:
    session.grant(request)
    with connection(request) as conn:
        return JSONResponse(api.session(conn, agent=request.state.agent, can_write=request.state.can_write,
                                        provider=provider(request)))


def search(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.search(conn, _q(request, "q"), agent=request.state.agent, kind=_many(request, "kind"),
                                       status=_many(request, "status"), entity_class=_many(request, "entity_class"),
                                       target=_q(request, "target"), limit=_q(request, "limit"),
                                       provider=provider(request)))


def similar(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.similar(conn, agent=request.state.agent, ref=_q(request, "ref"), q=_q(request, "q"),
                                        limit=_q(request, "limit"), provider=provider(request)))


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
    return FileCopy(content.path, media_type=content.media_type, headers=FILE_HEADERS, filename=content.filename,
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


# --- запись: тело и вызов операции ---

def _too_large() -> problems.Problem:
    return problems.Problem(413, "too_large", f"тело запроса больше {BODY_LIMIT // 1024} КиБ: разбейте пакет на части")


def _constant(name: str):
    raise ValueError(f"{name} — не число JSON")


async def _body(request: Request) -> dict:
    """JSON-объект тела записи; читается потоком до BODY_LIMIT байт, дальше — 413 (не дочитывая)."""
    length = request.headers.get("content-length", "").strip()
    if length.isascii() and length.isdigit() and (len(length) > 18 or int(length) > BODY_LIMIT):
        raise _too_large()                        # быстрый отказ; сам счёт — ниже, по пришедшим байтам
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > BODY_LIMIT:
            raise _too_large()
        chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw.strip():
        raise problems.Problem(400, "bad_request", "нужно тело запроса — JSON-объект")
    try:
        body = json.loads(raw, parse_constant=_constant)
    except RecursionError:
        raise problems.Problem(400, "bad_request", "тело JSON: слишком глубокая вложенность") from None
    except ValueError as e:                       # и UnicodeDecodeError
        raise problems.Problem(400, "bad_request", f"тело — не JSON: {e}") from None
    if not isinstance(body, dict):
        raise problems.Problem(400, "bad_request", f"тело — не JSON-объект, а {type(body).__name__}")
    return body


async def _call(request: Request, operation):
    """operation(conn) в пуле потоков с соединением из пула службы: библиотека синхронная."""
    def run():
        with connection(request) as conn:
            return operation(conn)
    return await run_in_threadpool(run)


# --- очередь проверки ---

def list_review_items(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.review_items(conn, state=_q(request, "state"), reason=_q(request, "reason"),
                                             record=_q(request, "record"), limit=_q(request, "limit")))


def get_review_item(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.review_item(conn, request.path_params["id"]))


async def resolve_review_item(request: Request) -> JSONResponse:
    body = await _body(request)
    return JSONResponse(await _call(request, lambda conn: api.review_resolve(
        conn, request.path_params["id"], agent=request.state.agent, outcome=body.get("outcome"),
        note=body.get("note"), confidence=body.get("confidence"))))


async def enqueue_review(request: Request) -> JSONResponse:
    body = await _body(request)
    return JSONResponse(await _call(request, lambda conn: api.review_enqueue(
        conn, agent=request.state.agent, ref=body.get("ref"), reason=body.get("reason"), note=body.get("note"))))


def get_review_stats(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.review_stats(conn, days=_q(request, "days")))


# --- submit ---

async def submit(request: Request) -> JSONResponse:
    body = await _body(request)
    state = request.app.state
    return JSONResponse(await _call(request, lambda conn: api.submit(
        conn, state.store, state.settings.docs, agent=request.state.agent, proposals=body.get("proposals"),
        links=body.get("links"), reason=body.get("reason"), provider=provider(request))))


# --- папки ---

async def create_folder(request: Request) -> JSONResponse:
    body = await _body(request)
    made = await _call(request, lambda conn: api.folder_create(conn, body.get("path"), agent=request.state.agent))
    return JSONResponse(made, status_code=201)


def delete_folder(request: Request) -> Response:
    with connection(request) as conn:
        api.folder_delete(conn, request.path_params["path"], agent=request.state.agent)
    return Response(status_code=204)


async def rename_folder(request: Request) -> JSONResponse:
    body = await _body(request)
    return JSONResponse(await _call(request, lambda conn: api.folder_rename(
        conn, request.path_params["path"], body.get("path"), agent=request.state.agent)))


async def move_record(request: Request) -> JSONResponse:
    body = await _body(request)
    if "folder" not in body:
        raise problems.Problem(400, "bad_request", "тело: нужно поле folder — путь папки или null (без папки)")
    return JSONResponse(await _call(request, lambda conn: api.record_folder(
        conn, request.path_params["ref"], body["folder"], agent=request.state.agent)))


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
    Route(f"{API}/folders", create_folder, methods=["POST"]),
    Route(f"{API}/folders/{{path:path}}", delete_folder, methods=["DELETE"]),
    Route(f"{API}/folders/{{path:path}}", rename_folder, methods=["PATCH"]),
    Route(f"{API}/records", list_records, methods=["GET"]),
    Route(f"{API}/records/{{ref}}", get_record, methods=["GET"]),
    Route(f"{API}/records/{{ref}}/history", get_history, methods=["GET"]),
    Route(f"{API}/records/{{ref}}/links", get_links, methods=["GET"]),
    Route(f"{API}/records/{{ref}}/folder", move_record, methods=["PATCH"]),
    Route(f"{API}/entities/{{ref}}/card", get_card, methods=["GET"]),
    Route(f"{API}/graph", get_graph, methods=["GET"]),
    Route(f"{API}/changes", get_changes, methods=["GET"]),
    Route(f"{API}/objects/{{id}}", get_object, methods=["GET"]),
    Route(f"{API}/objects/{{id}}/versions/{{n}}/content", get_object_content, methods=["GET"]),
    Route(f"{API}/objects/{{id}}/versions/{{n}}/text", get_object_text, methods=["GET"]),
    Route(f"{API}/objects/{{id}}/versions/{{n}}/sheet", get_object_sheet, methods=["GET"]),
    Route(f"{API}/review/items", list_review_items, methods=["GET"]),
    Route(f"{API}/review/items/{{id}}", get_review_item, methods=["GET"]),
    Route(f"{API}/review/items/{{id}}/resolve", resolve_review_item, methods=["POST"]),
    Route(f"{API}/review/enqueue", enqueue_review, methods=["POST"]),
    Route(f"{API}/review/stats", get_review_stats, methods=["GET"]),
    Route(f"{API}/submit", submit, methods=["POST"]),
    Route(f"{API}/vocab/{{scheme}}", get_vocab, methods=["GET"]),
    Route(f"{API}/base", get_base, methods=["GET"]),
    Route(f"{API}/backups", get_backups, methods=["GET"]),
    Route(f"{API}/openapi.json", get_openapi, methods=["GET"]),
]
