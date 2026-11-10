"""Ошибки службы в application/problem+json (RFC 9457) по таблице разд. 3.2 спецификации подпроекта 4.

Тело: type, title, status, detail, code и, где есть, расширения (issues, changeset_id и warnings у check_rejected;
by и at у review_closed; missing…); расширение не заменяет пять основных полей. Исключения библиотеки — наследники
ValueError, поэтому перевод идёт от частного к общему одной цепочкой (to_problem): отказ проверки (api.CheckRejected)
и RecordNotFound раньше RecordError (api.Missing — подборки нет — тоже 404; api.Ambiguous — текст указал не на
одну запись — 409 ambiguous с candidates: путей с текстом вместо ссылки у службы нет, перевод — для CLI и MCP),
коды ReviewError, FolderError, MineError, TaskError и ObjectError раньше «прочего», EmbeddingError (503) раньше прочего ValueError —
последней ступени перед 500: так библиотека отвечает на неверный ввод, и ответ — 400 с её сообщением.
Необработанная ошибка — 500 internal: подробности уходят в журнал службы (logger amem.service), в ответе их нет.
Недоступная база — 503 без строки соединения: в тексте ошибки psycopg бывают адрес и порт сервера; значение,
которое база не приняла (psycopg.DataError), — 400 тоже без её текста. Хранилище копий без корня (том не подключён) — 503
store_unavailable, копии версии нет — 404; путь на диске — только в журнале. Тяжёлый запрос, который база оборвала
по statement_timeout (psycopg.errors.QueryCanceled — подкласс OperationalError, поэтому раньше него), — 503 timeout;
подборки владельца сверх предела места (api.QuotaExceeded) — 507 quota_exceeded.
У каждого ответа-ошибки — X-Content-Type-Options: nosniff.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import datetime

import psycopg
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from .. import api, bundle, db, embed, mine, objects, records, review, tasks, vocab
from ..canon import CanonError
from ..check import CheckError
from ..folders import FolderError
from ..packs import PackError

MEDIA_TYPE = "application/problem+json"
log = logging.getLogger("amem.service")

# заголовок — короткая фраза для экрана (веб показывает title, если нет detail)
TITLES = {
    400: "Неверный запрос", 401: "Нужен вход", 403: "Запрещено", 404: "Не найдено", 405: "Метод не поддерживается",
    408: "Тело запроса не дошло", 409: "Конфликт", 413: "Слишком много данных", 415: "Неподдерживаемый тип тела", 416: "Диапазон вне файла",
    421: "Чужой адрес службы", 422: "Отклонено проверкой", 500: "Внутренняя ошибка службы", 501: "Ещё не сделано",
    503: "Служба недоступна", 507: "Нет места",
}
CODE_TITLES = {"read_only": "Только чтение", "review_closed": "Уже решено", "bad_origin": "Чужой источник запроса",
               "forbidden": "Только для человека", "check_rejected": "Отклонено проверкой",
               "folder_exists": "Папка уже есть", "folder_not_empty": "Папка не пуста",
               "semantic_unavailable": "Смысловой поиск недоступен", "db_unavailable": "База недоступна",
               "store_unavailable": "Хранилище копий недоступно", "timeout": "Запрос слишком долгий",
               "body_timeout": "Тело запроса не дошло", "quota_exceeded": "Нет места для подборок",
               "ambiguous": "Неоднозначно", "template_exists": "Код вида занят",
               "template_in_use": "У вида есть записи", "template_invalid": "Вид не прошёл проверку",
               "task_closed": "Задача уже закрыта", "task_claimed": "Задачу держит другой агент"}
RESERVED = frozenset({"type", "title", "status", "code", "detail"})       # расширения их не заменяют
REVIEW = {"closed": (409, "review_closed"), "forbidden": (403, "review_forbidden"),
          "claimed": (403, "review_forbidden"), "stale": (400, "review_bad"), "bad_outcome": (400, "review_bad"),
          "invalid": (400, "review_bad"), "not_found": (404, "not_found")}
FOLDER = {"exists": (409, "folder_exists"), "not_empty": (409, "folder_not_empty"),
          "not_found": (404, "folder_not_found")}
MINE = {"exists": (409, "template_exists"), "in_use": (409, "template_in_use"), "invalid": (422, "template_invalid"),
        "not_found": (404, "not_found"), "forbidden": (403, "forbidden")}
OBJECT = {"too_large": (413, "too_large"), "not_found": (404, "not_found"), "invalid": (400, "bad_request"),
          "path_taken": (409, "object_path_taken"), "docs_unavailable": (503, "docs_unavailable")}
TASK = {"not_found": (404, "not_found"), "closed": (409, "task_closed"), "claimed": (409, "task_claimed"),
        "forbidden": (403, "forbidden"), "invalid": (400, "bad_request")}
HTTP = {404: "not_found", 405: "method_not_allowed"}


class Problem(Exception):
    """Ответ-ошибка, которую бросает сам слой службы: разбор запроса, 501, отказ проверки с issues."""

    def __init__(self, status: int, code: str, detail: str | None = None, *, headers: dict | None = None, **extra):
        super().__init__(detail or code)
        self.status, self.code, self.detail, self.headers, self.extra = status, code, detail, headers, extra


def body(status: int, code: str, detail: str | None = None, *, extra: Mapping | None = None) -> dict:
    """Тело problem+json: пять основных полей и расширения. Его же печатает CLI с --json при ошибке."""
    out = {"type": "about:blank", "title": CODE_TITLES.get(code) or TITLES.get(status, "Ошибка"), "status": status,
           "code": code}
    if detail:
        out["detail"] = detail
    # расширения — только то, что переводится в JSON: в деталях BundleError бывают произвольные значения
    extensions = {str(k): v for k, v in (extra or {}).items() if str(k) not in RESERVED}
    out.update(json.loads(json.dumps(extensions, ensure_ascii=False, default=str)))
    return out


def response(status: int, code: str, detail: str | None = None, *, headers: dict | None = None,
             extra: Mapping | None = None) -> JSONResponse:
    return JSONResponse(body(status, code, detail, extra=extra), status_code=status,
                        headers={"X-Content-Type-Options": "nosniff", **(headers or {})}, media_type=MEDIA_TYPE)


def to_problem(exc: BaseException) -> Problem:
    """Исключение → Problem по таблице разд. 3.2; порядок проверок — от частного к общему."""
    message = str(exc)
    if isinstance(exc, Problem):
        return exc
    if isinstance(exc, api.CheckRejected):
        return Problem(422, "check_rejected", message, issues=exc.issues, changeset_id=exc.changeset_id,
                       warnings=exc.warnings)
    if isinstance(exc, api.Forbidden):
        return Problem(403, "forbidden", message)
    if isinstance(exc, api.ReadOnly):
        return Problem(403, "read_only", message)
    if isinstance(exc, api.Ambiguous):
        return Problem(409, "ambiguous", message, candidates=exc.candidates)
    if isinstance(exc, (records.RecordNotFound, api.Missing)):
        return Problem(404, "not_found", message)
    if isinstance(exc, review.ReviewError):
        status, code = REVIEW.get(exc.code, (400, "review_bad"))
        if exc.code == "closed":
            at = exc.at.isoformat() if isinstance(exc.at, datetime) else None
            who = f"решил {exc.by}" if exc.by else "закрыт без решения"
            return Problem(status, code, f"{message} ({who}{', ' + at if at else ''})", by=exc.by, at=at)
        return Problem(status, code, message)
    if isinstance(exc, FolderError):
        status, code = FOLDER.get(exc.code, (422, "folder_invalid"))
        return Problem(status, code, message)
    if isinstance(exc, mine.MineError):
        status, code = MINE.get(exc.code, (422, "template_invalid"))
        return Problem(status, code, message, **({"issues": exc.issues} if exc.issues else {}))
    if isinstance(exc, tasks.TaskError):
        status, code = TASK.get(exc.code, (400, "bad_request"))
        return Problem(status, code, message)
    if isinstance(exc, bundle.BundleError):
        problem = Problem(422, exc.code or "bundle_invalid", message)
        problem.extra = dict(exc.details)        # ключи деталей — любые, в том числе detail и headers
        return problem
    if isinstance(exc, objects.ObjectError):
        status, code = OBJECT.get(exc.code, (400, "bad_request"))
        return Problem(status, code, message)
    if isinstance(exc, (api.BadRequest, records.RecordError, CheckError, db.BaseNameError, vocab.VocabError,
                        CanonError, PackError)):
        return Problem(400, "bad_request", message)
    if isinstance(exc, embed.EmbeddingError):
        return Problem(503, "semantic_unavailable", f"смысловой поиск недоступен: {message}")
    if isinstance(exc, api.StoreUnavailable):
        return Problem(503, "store_unavailable", message)
    if isinstance(exc, api.QuotaExceeded):
        return Problem(507, "quota_exceeded", message)
    if isinstance(exc, psycopg.errors.QueryCanceled):
        return Problem(503, "timeout", "запрос к базе не уложился в отведённое время: сузьте его (меньше limit, "
                       "depth, фильтр по project или статусам) или повторите позже")
    if isinstance(exc, psycopg.OperationalError):
        return Problem(503, "db_unavailable", "база недоступна — проверьте, что PostgreSQL запущен и AMEM_DSN верен")
    if isinstance(exc, psycopg.DataError):
        return Problem(400, "bad_request", "значение параметра база не принимает (например, знак NUL в строке)")
    if isinstance(exc, HTTPException):
        code = HTTP.get(exc.status_code, f"http_{exc.status_code}")
        return Problem(exc.status_code, code, None, headers=exc.headers)
    if isinstance(exc, ValueError):          # последняя ступень перед 500: неверный ввод, который пропустила служба
        return Problem(400, "bad_request", message)
    return Problem(500, "internal", "внутренняя ошибка службы; подробности — в журнале службы")


async def handle(request: Request, exc: Exception) -> JSONResponse:
    problem = to_problem(exc)
    if problem.code == "db_unavailable":
        log.warning("%s %s: база недоступна: %s", request.method, request.url.path, exc)
    elif problem.code == "timeout":
        log.warning("%s %s: запрос к базе оборван по statement_timeout", request.method, request.url.path)
    elif isinstance(exc, (api.StoreUnavailable, api.CopyMissing)):
        log.warning("%s %s: %s (%s)", request.method, request.url.path, exc, exc.where)
    elif problem.status >= 500 and problem is not exc and problem.code == "internal":
        log.error("%s %s: необработанная ошибка", request.method, request.url.path, exc_info=exc)
    return response(problem.status, problem.code, problem.detail, headers=problem.headers, extra=problem.extra)


# классы, которые ловит ExceptionMiddleware (поиск по MRO исключения); Exception — последний рубеж
# (ServerErrorMiddleware): он отвечает 500 и передаёт исключение серверу дальше
HANDLED = (Problem, api.CheckRejected, api.Ambiguous, api.Forbidden, api.ReadOnly, api.Missing, api.BadRequest,
           records.RecordError, review.ReviewError, FolderError, mine.MineError, tasks.TaskError, bundle.BundleError,
           objects.ObjectError, CheckError,
           db.BaseNameError, vocab.VocabError, CanonError, PackError, embed.EmbeddingError, api.StoreUnavailable,
           api.QuotaExceeded, psycopg.OperationalError, psycopg.DataError, HTTPException, ValueError, Exception)
HANDLERS = {cls: handle for cls in HANDLED}
