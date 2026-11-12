"""Пути HTTP v1 (docs/api/http-v1.openapi.yaml): тонкий слой над amemo/api.py.

Обработчик разбирает путь и строку запроса, берёт соединение из пула службы (app.connection) и зовёт операцию api;
ошибки переводит amemo/service/problems.py. Обработчики синхронные: Starlette зовёт их в пуле потоков, и psycopg
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

Подборки (/bundles/*) лежат в AMEMO_STATE (api.bundle_export и соседи: владелец, срок хранения — там же). Экспорт —
bundle.export или, с anthology: true, anthology.export; zip отдаётся на скачивание (attachment, FILE_HEADERS), отчёт
антологии — inline в песочнице без скриптов (REPORT_HEADERS). /bundles/inspect принимает multipart/form-data
(Origin обязателен — session.Guard): поле file пишется потоком (python-multipart) во временный файл
AMEMO_STATE/uploads/.<id>.part с отсечкой на UPLOAD_LIMIT (413 too_large, недокачанное удаляется), остальное
в форме — не больше FORM_LIMIT; затем bundle.inspect без базы. Владелец подборки — session.owner (токен или агент).
POST /objects (загрузка файла, разд. 6a.4) идёт тем же разбором: поле file — во временный файл в корне AMEMO_DOCS
(.amemo-upload-<id>.part), поле path — путь в папке документов; затем api.object_upload кладёт файл по пути и принимает
его (objects.upload). Квота AMEMO_STATE_QUOTA не тратится: файл ложится в папку документов, а не в состояние службы.

Медленное тело: следующий кусок тела записи и загрузки служба ждёт не дольше BODY_IDLE, а JSON-тело целиком — не
дольше BODY_TOTAL; дальше — 408 body_timeout (загрузку ограничивает только BODY_IDLE: большой файл по медленной
сети законно идёт долго). Тяжёлые чтения (/graph — обзор неба и окрестность) идут в транзакции с SET LOCAL
statement_timeout = HEAVY_TIMEOUT_MS: превышение база обрывает сама, ответ — 503 timeout, соединение возвращается
в пул без следа настройки. Подборки и загрузки владельца ограничены AMEMO_STATE_QUOTA (api.state_usage): сверх —
507 quota_exceeded, приём загрузки обрывается, как только файл перерос остаток.

Явный поиск (/search, /similar) пишет строку в журнал запросов (amemo/journal.py, AMEMO_QUERY_LOG): ошибка файла
поиск не роняет.

Обновления (/updates, amemo/updates.py): статус и проверка — любому с правом чтения, переключатель и установка — только
человеку с правом записи; установка идёт в фоне (202), отказы, известные заранее, — 409 с кодом.

Контракт служба отдаёт по /api/v1/openapi.json — копию из пакета (amemo/service/http-v1.openapi.yaml).
"""
from __future__ import annotations

import contextlib
import functools
import importlib.resources
import json
import os
import time
from pathlib import Path

import anyio
import python_multipart
import yaml
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, MalformedRangeHeader, RangeNotSatisfiable, Response
from starlette.routing import Route

from .. import api, bundle, journal, private
from . import problems, session
from .app import API, connection, provider

CONTRACT = "http-v1.openapi.yaml"
FILE_HEADERS = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"}
BODY_LIMIT = 1 << 20          # байт JSON-тела записи: пакет submit — сотни атомов; больше — 413 too_large
UPLOAD_LIMIT = bundle.MAX_UNPACKED      # байт файла подборки в /bundles/inspect (4 ГиБ); больше — 413 too_large
FORM_LIMIT = 64 << 10         # байт заголовков и прочих полей формы /bundles/inspect вместе — сверх файла
BODY_IDLE = 30.0              # с без новых байт тела записи или загрузки — 408 body_timeout
BODY_TOTAL = 120.0            # с на всё JSON-тело записи (до 1 МиБ — с запасом и для медленной сети)
HEAVY_TIMEOUT_MS = 15_000     # statement_timeout тяжёлых чтений (/graph); дольше — 503 timeout
# отчёт антологии открывается в новой вкладке как документ без своего источника (sandbox без allow-scripts):
# скрипты не идут, запросы к службе и cookie ему недоступны; стили — встроенные, картинки — только data:
REPORT_HEADERS = {"X-Content-Type-Options": "nosniff", "Content-Disposition": "inline",
                  "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:",
                  "Referrer-Policy": "no-referrer"}


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


def _journal(request: Request, result: dict, query: str, started: float) -> None:
    """Строка журнала запросов о явном поиске (amemo/journal.py): текст после private.strip, без находок."""
    state = request.app.state
    journal.record(state.settings.query_log, recipe=result["recipe"], query=private.strip(query),
                   agent=request.state.agent, base_id=state.base_id, count=len(result["items"]),
                   duration_ms=(time.monotonic() - started) * 1000, retrieval_id=result["retrieval_id"])


def search(request: Request) -> JSONResponse:
    started, q = time.monotonic(), _q(request, "q")
    with connection(request) as conn:
        result = api.search(conn, q, agent=request.state.agent, kind=_many(request, "kind"),
                            status=_many(request, "status"), entity_class=_many(request, "entity_class"),
                            target=_q(request, "target"), limit=_q(request, "limit"), provider=provider(request))
    _journal(request, result, q, started)
    return JSONResponse(result)


def similar(request: Request) -> JSONResponse:
    started, ref, q = time.monotonic(), _q(request, "ref"), _q(request, "q")
    with connection(request) as conn:
        result = api.similar(conn, agent=request.state.agent, ref=ref, q=q, limit=_q(request, "limit"),
                             provider=provider(request))
    _journal(request, result, ref or q, started)
    return JSONResponse(result)


def get_folders(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.folder_tree(conn))


def list_records(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.record_list(conn, folder=_q(request, "folder"), kind=_many(request, "kind"),
                                            status=_many(request, "status"), tag=_many(request, "tag"),
                                            about=_q(request, "about"), limit=_q(request, "limit"),
                                            cursor=_q(request, "cursor"), nested=_q(request, "nested")))


def get_record(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.record(conn, request.path_params["ref"], revision=_q(request, "revision")))


def get_history(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.history(conn, request.path_params["ref"]))


def get_links(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.links(conn, request.path_params["ref"]))


def get_card(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.card(conn, request.path_params["ref"], ancestors=_q(request, "ancestors")))


@contextlib.contextmanager
def _heavy(request: Request):
    """Соединение в транзакции с SET LOCAL statement_timeout: предел действует только до её конца."""
    with connection(request) as conn, conn.transaction():
        conn.execute(f"SET LOCAL statement_timeout = {int(HEAVY_TIMEOUT_MS)}")
        yield conn


def get_graph(request: Request) -> JSONResponse:
    with _heavy(request) as conn:
        return JSONResponse(api.graph(conn, _q(request, "ref"), depth=_q(request, "depth"), limit=_q(request, "limit"),
                                      project=_q(request, "project"), rels=_many(request, "rels"),
                                      status=_many(request, "status"), tag=_many(request, "tag"),
                                      kind=_many(request, "kind"), folder=_q(request, "folder")))


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


def get_tags(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.tag_counts(conn, q=_q(request, "q"), limit=_q(request, "limit")))


def get_suggest(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.suggest(conn, q=_q(request, "q"), target=_q(request, "target"),
                                        limit=_q(request, "limit")))


def get_templates(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.templates(conn, target=_q(request, "target")))


async def put_my_template(request: Request) -> JSONResponse:
    body = await _body(request)
    return JSONResponse(await _call(request, lambda conn: api.template_put(
        conn, request.path_params["code"], body, agent=request.state.agent)))


def delete_my_template(request: Request) -> Response:
    with connection(request) as conn:
        api.template_delete(conn, request.path_params["code"], agent=request.state.agent)
    return Response(status_code=204)


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


def _body_timeout(detail: str) -> problems.Problem:
    return problems.Problem(408, "body_timeout", detail, headers={"Connection": "close"})


async def _stream(request: Request, *, total: float | None = None):
    """Куски тела запроса: следующий ждём не дольше BODY_IDLE, всё тело — не дольше total (None — без общего
    предела); иначе 408 body_timeout. Медленный клиент не держит соединение и разобранное тело сколько угодно."""
    deadline = None if total is None else time.monotonic() + total
    chunks = request.stream().__aiter__()
    while True:
        wait = BODY_IDLE if deadline is None else min(BODY_IDLE, deadline - time.monotonic())
        with anyio.move_on_after(max(wait, 0.0)) as waiting:
            try:
                chunk = await chunks.__anext__()
            except StopAsyncIteration:
                return
        if waiting.cancelled_caught:
            if deadline is not None and time.monotonic() >= deadline:
                raise _body_timeout(f"тело запроса не пришло целиком за {total:g} с")
            raise _body_timeout(f"тело запроса не приходит: {BODY_IDLE:g} с без новых данных")
        yield chunk


async def _body(request: Request) -> dict:
    """JSON-объект тела записи; читается потоком до BODY_LIMIT байт, дальше — 413 (не дочитывая)."""
    length = request.headers.get("content-length", "").strip()
    if length.isascii() and length.isdigit() and (len(length) > 18 or int(length) > BODY_LIMIT):
        raise _too_large()                        # быстрый отказ; сам счёт — ниже, по пришедшим байтам
    chunks, size = [], 0
    async for chunk in _stream(request, total=BODY_TOTAL):
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


# --- задачи агентам ---

def list_tasks(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.task_list(conn, state=_q(request, "state"), object=_q(request, "object")))


async def create_task(request: Request) -> JSONResponse:
    """Поставить задачу (человек или модель; токен только для чтения — 403 у session.Guard): 202 и task_id, и при
    повторе — тот же id незакрытой задачи."""
    body = await _body(request)
    made, _ = await _call(request, lambda conn: api.task_create(
        conn, agent=request.state.agent, kind=body.get("kind"), object=body.get("object"),
        version=body.get("version"), note=body.get("note")))
    return JSONResponse(made, status_code=202)


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


async def move_records(request: Request) -> JSONResponse:
    body = await _body(request)
    if "folder" not in body or "refs" not in body:
        raise problems.Problem(400, "bad_request", "тело: нужны refs — список ссылок и folder — путь папки или null")
    return JSONResponse(await _call(request, lambda conn: api.records_folder(
        conn, body["refs"], body["folder"], agent=request.state.agent)))


# --- подборки ---

def _bundle_links(made: dict) -> dict:
    bid = made["id"]
    return {"id": bid, "summary": made["summary"], "download": f"{API}/bundles/{bid}/download",
            "report": f"{API}/bundles/{bid}/report" if made["has_report"] else None}


async def export_bundle(request: Request) -> JSONResponse:
    body = await _body(request)
    state = request.app.state
    made = await _call(request, lambda conn: api.bundle_export(
        conn, state.store, state.settings.state, agent=request.state.agent, owner=session.owner(request),
        selection=body.get("selection"), with_files=body.get("with_files"), with_packs=body.get("with_packs"),
        anthology=body.get("anthology"), title=body.get("title"), notes_format=body.get("format"),
        notes_lang=body.get("lang"), quota=state.settings.state_quota))
    return JSONResponse(_bundle_links(made))


class HeldFile(FileCopy):
    """Файл, открытый до ответа: очистка по сроку, удалившая его между проверкой и отдачей, ответ не обрывает
    (открытый файл читается и после удаления), а удалённый до открытия — 404 (_hold), а не 500."""

    def __init__(self, handle, **kwargs):
        self._handle = handle
        super().__init__(handle.name, stat_result=os.fstat(handle.fileno()), **kwargs)

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._handle.close()

    @contextlib.asynccontextmanager
    async def _open_file(self):
        self._handle.seek(0)
        yield anyio.wrap_file(self._handle)       # закрывает __call__: диапазоны читают тот же файл


def _hold(path: Path, what: str):
    try:
        return open(path, "rb")
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        raise api.Missing(f"{what} нет: срок хранения — сутки, после него сделайте заново") from None


def download_bundle(request: Request) -> FileResponse:
    found = api.bundle_download(request.app.state.settings.state, request.path_params["id"],
                                owner=session.owner(request))
    return HeldFile(_hold(found.path, "подборки"), media_type="application/zip", headers=FILE_HEADERS,
                    filename=found.filename, content_disposition_type="attachment")


def bundle_report(request: Request) -> FileResponse:
    path = api.bundle_report(request.app.state.settings.state, request.path_params["id"],
                             owner=session.owner(request))
    return HeldFile(_hold(path, "отчёта"), media_type="text/html; charset=utf-8", headers=REPORT_HEADERS)


class _Upload:
    """Приёмник multipart/form-data загрузки (/bundles/inspect, POST /objects): поле file — потоком в файл на диске,
    прочие поля и заголовки частей — не больше FORM_LIMIT байт вместе (текст полей из keep сохраняется в fields);
    файл больше UPLOAD_LIMIT — 413, не дочитывая. filename — имя файла из заголовка части file."""

    def __init__(self, path: Path, room: int | None = None, quota: int | None = None, *, what: str = "подборки",
                 hint: str = "нужно одно поле file с zip подборки", keep: tuple[bytes, ...] = ()):
        self.path, self.out, self.keep = path, None, keep
        self.room, self.quota = room, quota        # остаток места владельца (AMEMO_STATE_QUOTA) и сам предел
        self.what, self.hint = what, hint
        self.size = self.form = 0
        self.field = self.header = b""
        self.disposition = b""
        self.name: bytes | None = None
        self.fields: dict[bytes, bytes] = {}
        self.filename: bytes | None = None
        self.in_file = self.got_file = self.file_done = self.ended = False

    def callbacks(self) -> dict:
        return {"on_part_begin": self.part_begin, "on_header_field": self.header_field,
                "on_header_value": self.header_value, "on_header_end": self.header_end,
                "on_headers_finished": self.headers_finished, "on_part_data": self.part_data,
                "on_part_end": self.part_end, "on_end": self.end}

    def _count_form(self, n: int) -> None:
        self.form += n
        if self.form > FORM_LIMIT:
            raise problems.Problem(413, "too_large", f"поля формы загрузки больше {FORM_LIMIT // 1024} КиБ: "
                                   f"{self.hint}")

    def part_begin(self) -> None:
        self.disposition, self.in_file, self.name = b"", False, None

    def header_field(self, data: bytes, start: int, end: int) -> None:
        self._count_form(end - start)
        self.field += data[start:end]

    def header_value(self, data: bytes, start: int, end: int) -> None:
        self._count_form(end - start)
        self.header += data[start:end]

    def header_end(self) -> None:
        if self.field.lower() == b"content-disposition":
            self.disposition = self.header
        self.field = self.header = b""

    def headers_finished(self) -> None:
        _, options = parse_options_header(self.disposition)
        name = options.get(b"name")
        if name != b"file":
            if name in self.keep:                 # прочие поля читаются (в пределе FORM_LIMIT) и не нужны
                if name in self.fields:
                    raise problems.Problem(400, "bad_request", f"загрузка {self.what}: поле {name.decode()} — одно")
                self.name, self.fields[name] = name, b""
            return
        if self.got_file:
            raise problems.Problem(400, "bad_request", f"загрузка {self.what}: поле file — одно")
        self.got_file = self.in_file = True
        self.filename = options.get(b"filename")
        self.out = open(self.path, "xb")

    def part_data(self, data: bytes, start: int, end: int) -> None:
        if not self.in_file:
            self._count_form(end - start)
            if self.name is not None:
                self.fields[self.name] += data[start:end]
            return
        self.size += end - start
        if self.size > UPLOAD_LIMIT:
            raise _upload_too_large(self.what)
        if self.room is not None and self.size > self.room:
            raise api.quota_exceeded(self.quota - self.room, self.quota, f"загрузка {self.what}")
        self.out.write(data[start:end])

    def part_end(self) -> None:
        self.name = None
        if self.in_file:
            self.out.close()
            self.in_file, self.file_done = False, True

    def end(self) -> None:
        self.ended = True

    def close(self) -> None:
        if self.out is not None:
            self.out.close()

    def text(self, name: bytes) -> str | None:
        """Текст поля формы (UTF-8) или None — поля не было."""
        raw = self.fields.get(name)
        if raw is None:
            return None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            raise problems.Problem(400, "bad_request", f"загрузка {self.what}: поле {name.decode()} — не UTF-8") \
                from None


def _upload_too_large(what: str = "подборки") -> problems.Problem:
    if what == "подборки":
        return problems.Problem(413, "too_large", f"файл подборки больше {UPLOAD_LIMIT // (1 << 20)} МиБ — "
                                f"предел распаковки подборки")
    return problems.Problem(413, "too_large", f"файл больше {UPLOAD_LIMIT // (1 << 20)} МиБ — предел загрузки")


def _boundary(request: Request, what: str) -> bytes:
    """boundary multipart и быстрый отказ по Content-Length (сам счёт — по пришедшим байтам, в _receive)."""
    _, params = parse_options_header(request.headers.get("content-type"))
    boundary = params.get(b"boundary")
    if not boundary:
        raise problems.Problem(400, "bad_request", f"загрузка {what}: в Content-Type нет boundary")
    length = request.headers.get("content-length", "").strip()
    if length.isascii() and length.isdigit() and (len(length) > 18 or int(length) > UPLOAD_LIMIT + FORM_LIMIT):
        raise _upload_too_large(what)
    return boundary


async def _receive(request: Request, boundary: bytes, upload: _Upload) -> None:
    """Тело multipart — в upload потоком; при любой ошибке недокачанный файл удаляется."""
    parser = python_multipart.MultipartParser(boundary, upload.callbacks())
    total = 0
    try:
        try:
            async for chunk in _stream(request):
                await run_in_threadpool(parser.write, chunk)     # запись на диск — не в цикле событий
                if upload.ended:
                    break                         # после финального boundary тело дальше не читается
                # все байты тела до конца формы: пустые части и преамбула — тоже; проверка после разбора куска,
                # чтобы хвост за финальным boundary в том же куске не считался (кусок — не больше буфера сервера)
                total += len(chunk)
                if total > UPLOAD_LIMIT + FORM_LIMIT:
                    raise _upload_too_large(upload.what)
            parser.finalize()
        except MultipartParseError as e:
            raise problems.Problem(400, "bad_request", f"загрузка {upload.what}: тело — не multipart/form-data: "
                                   f"{e}") from None
        finally:
            upload.close()
        if not upload.got_file:
            raise problems.Problem(400, "bad_request", f"загрузка {upload.what}: {upload.hint}")
        if not (upload.file_done and upload.ended):
            raise problems.Problem(400, "bad_request", f"загрузка {upload.what}: тело оборвано до конца файла")
    except BaseException:
        upload.path.unlink(missing_ok=True)
        raise


async def inspect_bundle(request: Request) -> JSONResponse:
    """Загрузка подборки (Origin обязателен — проверяет session.Guard): файл — потоком во временный файл
    в AMEMO_STATE/uploads, сверх UPLOAD_LIMIT — 413 и недокачанное удаляется; затем bundle.inspect без базы.
    Заметки Markdown (.md или zip хранилища Obsidian) — тем же путём: отчёт notes_md.inspect."""
    boundary = _boundary(request, "подборки")
    settings = request.app.state.settings
    state, quota, owner = settings.state, settings.state_quota, session.owner(request)
    room = await run_in_threadpool(api.upload_room, state, owner, quota)
    upload_id, part = await run_in_threadpool(api.upload_begin, state)
    upload = _Upload(part, room, quota)
    await _receive(request, boundary, upload)
    name = (upload.filename or b"").decode("utf-8", "replace") or None
    return JSONResponse(await run_in_threadpool(lambda: api.upload_finish(state, upload_id, part, owner=owner,
                                                                          quota=quota, filename=name)))


async def upload_object(request: Request) -> JSONResponse:
    """Загрузка файла в папку документов (Origin обязателен — session.Guard; разд. 6a.4): поле file — потоком во
    временный файл в корне AMEMO_DOCS (тот же предел UPLOAD_LIMIT, квота AMEMO_STATE_QUOTA не тратится), поле path —
    путь в папке документов (иначе Загрузки/<имя>); затем api.object_upload: 201 — записан, 200 — уже лежал."""
    boundary = _boundary(request, "файла")
    docs = request.app.state.settings.docs
    part = await run_in_threadpool(api.object_upload_begin, docs)
    upload = _Upload(part, what="файла", keep=(b"path",),
                     hint="нужно поле file с файлом (и, если нужно, path — путь в папке документов)")
    await _receive(request, boundary, upload)
    try:
        filename, path = (upload.filename or b"").decode("utf-8", "replace") or None, upload.text(b"path")
    except BaseException:
        part.unlink(missing_ok=True)
        raise

    def run() -> tuple[dict, bool]:
        try:
            with connection(request) as conn:
                return api.object_upload(conn, request.app.state.store, docs, part, filename=filename, path=path,
                                         agent=request.state.agent)
        finally:
            part.unlink(missing_ok=True)          # база недоступна — object_upload не звался, part не убран

    view, created = await run_in_threadpool(run)
    return JSONResponse(view, status_code=201 if created else 200)


def list_objects(request: Request) -> JSONResponse:
    with connection(request) as conn:
        return JSONResponse(api.object_search(conn, q=_q(request, "q"), limit=_q(request, "limit"),
                                              cursor=_q(request, "cursor"), file_type=_q(request, "type")))


async def import_bundle(request: Request) -> JSONResponse:
    body = await _body(request)
    state = request.app.state
    return JSONResponse(await _call(request, lambda conn: api.bundle_import(
        conn, state.store, state.settings.state, body.get("upload_id"), agent=request.state.agent,
        owner=session.owner(request), trust=body.get("trust"), dry_run=body.get("dry_run"),
        can_write=request.state.can_write, docs=state.settings.docs)))


# --- обновления (amemo/updates.py) ---

def _person_writer(request: Request, what: str) -> None:
    """Обновлением управляет только человек с правом записи: модель — 403 forbidden (токен только для чтения
    session.Guard отвергает раньше — 403 read_only)."""
    if not request.state.agent.startswith("person:"):
        raise api.Forbidden(f"{what} только человек (person:), а не {request.state.agent}")
    if not request.state.can_write:
        raise api.ReadOnly(f"вход {request.state.agent} — только для чтения")


def get_updates(request: Request) -> JSONResponse:
    return JSONResponse(request.app.state.updates.status())


async def put_updates(request: Request) -> JSONResponse:
    _person_writer(request, "автообновление включает и выключает")
    body = await _body(request)
    if not isinstance(body.get("auto"), bool) or set(body) != {"auto"}:
        raise problems.Problem(400, "bad_request", "тело: нужно только поле auto — true или false")
    return JSONResponse(await run_in_threadpool(request.app.state.updates.set_auto, body["auto"]))


def check_updates(request: Request) -> JSONResponse:
    return JSONResponse(request.app.state.updates.check(manual=True))


def install_update(request: Request) -> JSONResponse:
    _person_writer(request, "обновление ставит")
    return JSONResponse(request.app.state.updates.start_install(), status_code=202)


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
    Route(f"{API}/records/move", move_records, methods=["POST"]),
    Route(f"{API}/records/{{ref}}", get_record, methods=["GET"]),
    Route(f"{API}/records/{{ref}}/history", get_history, methods=["GET"]),
    Route(f"{API}/records/{{ref}}/links", get_links, methods=["GET"]),
    Route(f"{API}/records/{{ref}}/folder", move_record, methods=["PATCH"]),
    Route(f"{API}/entities/{{ref}}/card", get_card, methods=["GET"]),
    Route(f"{API}/graph", get_graph, methods=["GET"]),
    Route(f"{API}/changes", get_changes, methods=["GET"]),
    Route(f"{API}/objects", list_objects, methods=["GET"]),
    Route(f"{API}/objects", upload_object, methods=["POST"]),
    Route(f"{API}/objects/{{id}}", get_object, methods=["GET"]),
    Route(f"{API}/objects/{{id}}/versions/{{n}}/content", get_object_content, methods=["GET"]),
    Route(f"{API}/objects/{{id}}/versions/{{n}}/text", get_object_text, methods=["GET"]),
    Route(f"{API}/objects/{{id}}/versions/{{n}}/sheet", get_object_sheet, methods=["GET"]),
    Route(f"{API}/review/items", list_review_items, methods=["GET"]),
    Route(f"{API}/review/items/{{id}}", get_review_item, methods=["GET"]),
    Route(f"{API}/review/items/{{id}}/resolve", resolve_review_item, methods=["POST"]),
    Route(f"{API}/review/enqueue", enqueue_review, methods=["POST"]),
    Route(f"{API}/review/stats", get_review_stats, methods=["GET"]),
    Route(f"{API}/tasks", list_tasks, methods=["GET"]),
    Route(f"{API}/tasks", create_task, methods=["POST"]),
    Route(f"{API}/submit", submit, methods=["POST"]),
    Route(f"{API}/vocab/{{scheme}}", get_vocab, methods=["GET"]),
    Route(f"{API}/tags", get_tags, methods=["GET"]),
    Route(f"{API}/suggest", get_suggest, methods=["GET"]),
    Route(f"{API}/templates", get_templates, methods=["GET"]),
    Route(f"{API}/packs/mine/templates/{{code}}", put_my_template, methods=["PUT"]),
    Route(f"{API}/packs/mine/templates/{{code}}", delete_my_template, methods=["DELETE"]),
    Route(f"{API}/base", get_base, methods=["GET"]),
    Route(f"{API}/backups", get_backups, methods=["GET"]),
    Route(f"{API}/updates", get_updates, methods=["GET"]),
    Route(f"{API}/updates", put_updates, methods=["PUT"]),
    Route(f"{API}/updates/check", check_updates, methods=["POST"]),
    Route(f"{API}/updates/install", install_update, methods=["POST"]),
    Route(f"{API}/bundles/export", export_bundle, methods=["POST"]),
    Route(f"{API}/bundles/inspect", inspect_bundle, methods=["POST"]),
    Route(f"{API}/bundles/import", import_bundle, methods=["POST"]),
    Route(f"{API}/bundles/{{id}}/download", download_bundle, methods=["GET"]),
    Route(f"{API}/bundles/{{id}}/report", bundle_report, methods=["GET"]),
    Route(f"{API}/openapi.json", get_openapi, methods=["GET"]),
]
