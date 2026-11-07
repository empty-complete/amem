"""Защита запросов и сессия (спецификация подпроекта 4, разд. 3.1) — промежуточный слой ASGI перед маршрутами.

Для каждого запроса, в любом режиме:
- Host — 127.0.0.1, localhost, [::1] или адрес из настроек (--host); чужой — 421 (DNS rebinding);
- Origin, если пришёл, — свой источник или один из AMEM_UI_ORIGINS; чужой — 403. Запасная проверка — запрос без
  Origin, но с Sec-Fetch-Site: cross-site или same-site: так браузер помечает запрос с чужой страницы, даже если
  Origin не прислал (<img>, <script>, переход по форме), — 403 у любой записи и у любого запроса к /api/v1, кроме
  /health: иначе чужая страница картинкой с /api/v1/search писала бы строки в журнал выдачи и засоряла полезность;
- запись (POST, PUT, PATCH, DELETE) с телом — только application/json, иначе 415. Запись без тела (DELETE папки)
  проверять нечего: межсайтовый запрос без тела всё равно несёт Origin и упирается в проверку выше.
  Исключение — /bundles/inspect: multipart/form-data, и Origin для него обязателен.

Кто пишет — request.state.agent и request.state.can_write:
- локальная служба: запрос с cookie amem_session этого запуска — человек (AMEM_AGENT), без неё — модель
  (AMEM_MODEL_AGENT); писать вправе оба, записи модели идут через проверку;
- общая служба (AMEM_TOKENS): Authorization: Bearer <токен>; без верного токена — 401, токен без права записи — 403
  на запись. Cookie в этом режиме не выдаётся и не читается.

Cookie выдаёт обработчик вызовом grant(request) — GET /api/v1/session и /ui/index.html, — если запрос пришёл со своей
страницы (Sec-Fetch-Site: same-origin) или с источника из AMEM_UI_ORIGINS. Сама выдача — здесь, в заголовке ответа:
секрет не выходит из промежуточного слоя. Записи GET-ом служба не делает, поэтому проверки записи — по методу.
"""
from __future__ import annotations

import hmac
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import HTTPConnection, Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .. import settings as settings_
from . import problems

COOKIE = "amem_session"
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
FOREIGN_SITES = frozenset({"cross-site", "same-site"})       # Sec-Fetch-Site запроса с чужой страницы
LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")
WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", "[::]", ""})      # адрес «на всех интерфейсах» — не имя службы
API_PREFIX = "/api/v1/"
INSPECT = "/api/v1/bundles/inspect"
PUBLIC = frozenset({"/health"})          # без входа и в общей службе: проверка живости для compose и мониторинга


def allowed_hosts(host: str) -> frozenset[str]:
    """Имена в заголовке Host, на которые служба отвечает: локальные и адрес из настроек (IPv6 — в скобках)."""
    own = host.strip().lower()
    if ":" in own and not own.startswith("["):
        own = f"[{own}]"
    return frozenset(LOCAL_HOSTS) | ({own} - WILDCARD_HOSTS)


def hostname(host: str) -> str:
    """Имя из заголовка Host без порта: «[::1]:8767» → «[::1]», «Localhost:8767» → «localhost»."""
    host = host.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        return host[:end + 1] if end > 0 else host
    return host.partition(":")[0]


def grant(request: Request) -> bool:
    """Выдать cookie человека в ответе на этот запрос, если он пришёл со своей страницы или из AMEM_UI_ORIGINS.
    Тогда и сам запрос — уже человек: интерфейс узнаёт это из первого же ответа /session."""
    person = getattr(request.state, "grant_agent", None)
    if person is None:
        return False
    request.state.grant = True
    request.state.agent = person
    request.state.can_write = True
    return True


class Guard:
    """Промежуточный слой: защита Host/Origin/тела записи, затем агент запроса в scope["state"]."""

    def __init__(self, app: ASGIApp, *, settings: settings_.Settings, secret: str,
                 tokens: tuple[settings_.Token, ...] | None) -> None:
        self.app = app
        self.settings = settings
        self.secret = secret
        self.tokens = tokens
        self.hosts = allowed_hosts(settings.host)
        self.origins = frozenset(settings.ui_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":          # веб-сокетов у службы нет: рукопожатие отклоняется сразу
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":               # lifespan
            await self.app(scope, receive, send)
            return
        refusal = self._refusal(scope)
        if refusal is not None:
            await refusal(scope, receive, send)
            return
        state = scope["state"]

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start" and state.get("grant"):
                headers = MutableHeaders(scope=message)
                headers.append("set-cookie", f"{COOKIE}={self.secret}; HttpOnly; Path=/; SameSite=Strict")
            await send(message)

        await self.app(scope, receive, send_with_cookie)

    def _refusal(self, scope: Scope):
        """Ответ-отказ или None; при None агент запроса уже записан в scope["state"]."""
        headers = Headers(scope=scope)
        method, path = scope["method"], scope["path"]
        host = headers.get("host")
        if host is None or hostname(host) not in self.hosts:
            return problems.response(421, "bad_host", f"служба не отвечает на адрес {host!r}: допустимы "
                                     f"{', '.join(sorted(self.hosts))} (защита от подмены DNS)")
        origin = headers.get("origin")
        if origin is not None and not self._own_origin(origin, scope, host):
            return problems.response(403, "bad_origin", f"запрос со страницы {origin!r}: служба принимает только свой "
                                     f"источник и AMEM_UI_ORIGINS")
        site = headers.get("sec-fetch-site", "").strip().lower()
        if origin is None and site in FOREIGN_SITES and path not in PUBLIC \
                and (method in WRITE_METHODS or path.startswith(API_PREFIX)):
            return problems.response(403, "bad_origin", f"запрос с чужой страницы (Sec-Fetch-Site: {site}) без Origin: "
                                     "служба отвечает только своей странице и AMEM_UI_ORIGINS")
        if method in WRITE_METHODS:
            media = headers.get("content-type", "").partition(";")[0].strip().lower()
            if path == INSPECT:
                if origin is None:
                    return problems.response(403, "bad_origin", "загрузка подборки: нужен заголовок Origin "
                                             "(запрос со страницы интерфейса)")
                if media != "multipart/form-data":
                    return problems.response(415, "unsupported_media_type",
                                             "загрузка подборки: нужен multipart/form-data")
            elif (media or _has_body(headers)) and media != "application/json":
                return problems.response(415, "unsupported_media_type",
                                         f"запись принимает только application/json, а не {media or 'тело без типа'}")
        state = scope.setdefault("state", {})
        if self.tokens is not None:
            if path in PUBLIC:
                state.update(agent=self.settings.model_agent, can_write=False, grant_agent=None)
                return None
            scheme, _, token = headers.get("authorization", "").partition(" ")
            entry = settings_.match_token(self.tokens, token.strip()) if scheme.lower() == "bearer" and token else None
            if entry is None:
                detail = "нужен вход: заголовок Authorization: Bearer <токен>" if not token else "токен не подошёл"
                return problems.response(401, "auth_required", detail, headers={"WWW-Authenticate": "Bearer"})
            if method in WRITE_METHODS and not entry.write:
                return problems.response(403, "read_only", f"токен {entry.agent} — только для чтения")
            state.update(agent=entry.agent, can_write=entry.write, grant_agent=None)
            return None
        cookie = HTTPConnection(scope).cookies.get(COOKIE)
        person = cookie is not None and hmac.compare_digest(cookie.encode(), self.secret.encode())
        own_page = site == "same-origin" or _origin(origin) in self.origins
        state.update(agent=self.settings.agent if person else self.settings.model_agent, can_write=True,
                     grant_agent=self.settings.agent if own_page else None)
        return None

    def _own_origin(self, origin: str, scope: Scope, host: str) -> bool:
        value = _origin(origin)
        return value in self.origins or value == f"{scope['scheme']}://{host.strip().lower()}"


def _origin(origin: str | None) -> str | None:
    if origin is None:
        return None
    value = origin.strip().rstrip("/").lower()
    parts = urlsplit(value)
    return value if parts.scheme and parts.netloc else None        # «null» и мусор не равны ничему


def _has_body(headers: Headers) -> bool:
    return headers.get("content-length", "0").strip() != "0" or "transfer-encoding" in headers
