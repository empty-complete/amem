"""Ошибки службы в application/problem+json (RFC 9457) по таблице разд. 3.2 спецификации подпроекта 4.

Тело: type, title, status, detail, code и, где есть, расширения (issues, by, at, missing…). Исключения библиотеки —
наследники ValueError, поэтому перевод идёт от частного к общему одной цепочкой (to_problem): RecordNotFound раньше
RecordError, коды ReviewError, FolderError и ObjectError раньше «прочего». Необработанная ошибка — 500 internal:
подробности уходят в журнал службы (logger amem.service), в ответе их нет. Недоступная база — 503 без строки
соединения: в тексте ошибки psycopg бывают адрес и порт сервера.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

import psycopg
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from .. import bundle, db, objects, records, review, vocab
from ..check import CheckError
from ..folders import FolderError

MEDIA_TYPE = "application/problem+json"
log = logging.getLogger("amem.service")

# заголовок — короткая фраза для экрана (веб показывает title, если нет detail)
TITLES = {
    400: "Неверный запрос", 401: "Нужен вход", 403: "Запрещено", 404: "Не найдено", 405: "Метод не поддерживается",
    409: "Конфликт", 413: "Слишком много данных", 415: "Неподдерживаемый тип тела", 421: "Чужой адрес службы",
    422: "Отклонено проверкой", 500: "Внутренняя ошибка службы", 501: "Ещё не сделано", 503: "Служба недоступна",
}
CODE_TITLES = {"read_only": "Только чтение", "review_closed": "Уже решено", "bad_origin": "Чужой источник запроса",
               "folder_exists": "Папка уже есть", "folder_not_empty": "Папка не пуста"}
REVIEW = {"closed": (409, "review_closed"), "forbidden": (403, "review_forbidden"),
          "claimed": (403, "review_forbidden"), "stale": (400, "review_bad"), "bad_outcome": (400, "review_bad"),
          "invalid": (400, "review_bad"), "not_found": (404, "not_found")}
FOLDER = {"exists": (409, "folder_exists"), "not_empty": (409, "folder_not_empty"),
          "not_found": (404, "folder_not_found")}
OBJECT = {"too_large": (413, "too_large"), "not_found": (404, "not_found"), "invalid": (400, "bad_request")}
HTTP = {404: "not_found", 405: "method_not_allowed"}


class Problem(Exception):
    """Ответ-ошибка, которую бросает сам слой службы: разбор запроса, 501, отказ проверки с issues."""

    def __init__(self, status: int, code: str, detail: str | None = None, *, headers: dict | None = None, **extra):
        super().__init__(detail or code)
        self.status, self.code, self.detail, self.headers, self.extra = status, code, detail, headers, extra


def response(status: int, code: str, detail: str | None = None, *, headers: dict | None = None,
             **extra) -> JSONResponse:
    body = {"type": "about:blank", "title": CODE_TITLES.get(code) or TITLES.get(status, "Ошибка"), "status": status,
            "code": code}
    if detail:
        body["detail"] = detail
    # расширения — только то, что переводится в JSON: в деталях BundleError бывают произвольные значения
    body.update(json.loads(json.dumps(extra, ensure_ascii=False, default=str)))
    return JSONResponse(body, status_code=status, headers=headers, media_type=MEDIA_TYPE)


def to_problem(exc: BaseException) -> Problem:
    """Исключение → Problem по таблице разд. 3.2; порядок проверок — от частного к общему."""
    message = str(exc)
    if isinstance(exc, Problem):
        return exc
    if isinstance(exc, records.RecordNotFound):
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
    if isinstance(exc, bundle.BundleError):
        return Problem(422, exc.code or "bundle_invalid", message, **exc.details)
    if isinstance(exc, objects.ObjectError):
        status, code = OBJECT.get(exc.code, (400, "bad_request"))
        return Problem(status, code, message)
    if isinstance(exc, (records.RecordError, CheckError, db.BaseNameError, vocab.VocabError)):
        return Problem(400, "bad_request", message)
    if isinstance(exc, psycopg.OperationalError):
        return Problem(503, "db_unavailable", "база недоступна — проверьте, что PostgreSQL запущен и AMEM_DSN верен")
    if isinstance(exc, HTTPException):
        code = HTTP.get(exc.status_code, f"http_{exc.status_code}")
        return Problem(exc.status_code, code, None, headers=exc.headers)
    return Problem(500, "internal", "внутренняя ошибка службы; подробности — в журнале службы")


async def handle(request: Request, exc: Exception) -> JSONResponse:
    problem = to_problem(exc)
    if problem.status == 503:
        log.warning("%s %s: база недоступна: %s", request.method, request.url.path, exc)
    elif problem.status >= 500 and problem is not exc:
        log.error("%s %s: необработанная ошибка", request.method, request.url.path, exc_info=exc)
    return response(problem.status, problem.code, problem.detail, headers=problem.headers, **problem.extra)


# классы, которые ловит ExceptionMiddleware (поиск по MRO исключения); Exception — последний рубеж
# (ServerErrorMiddleware): он отвечает 500 и передаёт исключение серверу дальше
HANDLED = (Problem, records.RecordError, review.ReviewError, FolderError, bundle.BundleError, objects.ObjectError,
           CheckError, db.BaseNameError, vocab.VocabError, psycopg.OperationalError, HTTPException, Exception)
HANDLERS = {cls: handle for cls in HANDLED}
