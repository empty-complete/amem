"""Приложение Starlette: create_app(settings) — пул соединений, защита и сессия, problem+json, маршруты.

Библиотека синхронная, поэтому обработчики — обычные функции: Starlette зовёт их в пуле потоков, соединение берётся из
psycopg_pool на запрос (autocommit — как db.connect: каждый conn.transaction() — настоящая транзакция). lifespan
открывает пул и готовит базу (db.prepare — миграции, словари, base_id), при остановке закрывает пул. Секрет cookie
человека — новый на каждый запуск службы. Подборки и загрузки старше суток (AMEM_STATE) lifespan удаляет при запуске
и затем раз в час фоновой задачей. /mcp — Streamable HTTP сервера MCP (amem/service/mcp.py): его менеджер сессий
lifespan запускает и останавливает вместе с пулом.
"""
from __future__ import annotations

import contextlib
import logging
import secrets
import threading

import anyio
from psycopg_pool import ConnectionPool
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from .. import api, db, embed, lang
from ..ocfl_store import ObjectStore
from ..settings import Settings, SettingsError, load_tokens
from . import problems, session

API = "/api/v1"
POOL_MIN, POOL_MAX = 1, 8
POOL_TIMEOUT = 5.0        # с; дольше ждать соединения нет смысла — ответ 503
OPEN_TIMEOUT = 10.0       # с; база не ответила при запуске — служба не стартует
SWEEP_EVERY = 3600.0      # с; подборки и загрузки старше суток удаляются при запуске и раз в час
log = logging.getLogger("amem.service")


def create_app(settings: Settings, *, provider: embed.EmbeddingProvider | None = None) -> Starlette:
    """Служба HTTP по настройкам; provider — эмбеддинги для смыслового канала (None — по AMEM_BACKEND)."""
    if not settings.dsn:
        raise SettingsError("база не задана: задайте AMEM_DSN (или dsn в amem.toml) и выполните amem init")
    tokens = load_tokens(settings.tokens) if settings.tokens is not None else None

    from . import mcp as mcp_

    endpoint = mcp_.HttpMcp(settings)        # /mcp: менеджер сессий SDK — в lifespan

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        pool = ConnectionPool(settings.dsn, kwargs={"autocommit": True}, min_size=POOL_MIN, max_size=POOL_MAX,
                              open=False, timeout=POOL_TIMEOUT, check=ConnectionPool.check_connection,
                              name="amem")
        app.state.base_id = await anyio.to_thread.run_sync(_open, pool)
        app.state.pool = pool
        try:
            await anyio.to_thread.run_sync(_sweep, settings)
            async with endpoint.run(app), anyio.create_task_group() as tasks:
                tasks.start_soon(_sweeper, settings)
                try:
                    yield
                finally:
                    tasks.cancel_scope.cancel()
        finally:
            await anyio.to_thread.run_sync(pool.close)

    from . import http_v1, ui       # маршруты зовут connection() отсюда: импорт — после того, как модуль готов

    app = Starlette(
        routes=[Route("/health", health, methods=["GET"]), *http_v1.ROUTES,
                Route(session.MCP, endpoint, methods=["GET", "POST", "DELETE"]), *ui.ROUTES],
        middleware=[Middleware(session.Guard, settings=settings, secret=secrets.token_urlsafe(32), tokens=tokens)],
        exception_handlers=problems.HANDLERS,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.provider = provider
    app.state.provider_lock = threading.Lock()
    app.state.provider_chosen = provider is not None
    app.state.store = ObjectStore(settings.data)      # только чтение копий: корень создаёт первая запись файла
    app.state.base_id = None
    app.state.mcp = endpoint                          # /mcp: его runtime (задачи клиентов без сессии)
    return app


def _open(pool: ConnectionPool) -> str | None:
    """Открыть пул и подготовить базу; base_id — для журнала запросов (база не меняет его, пока служба жива)."""
    pool.open(wait=True, timeout=OPEN_TIMEOUT)
    try:
        with pool.connection() as conn:
            db.prepare(conn)
            row = conn.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()
    except BaseException:
        pool.close()
        raise
    return row[0] if row else None


def _sweep(settings: Settings) -> None:
    """Подборки и загрузки старше суток — долой (api.bundle_sweep); сбой диска не роняет службу."""
    try:
        removed = api.bundle_sweep(settings.state)
    except OSError as e:
        log.warning("подборки в %s не вычищены: %s", settings.state, e)
        return
    if removed:
        log.info("удалено подборок и загрузок старше суток: %d", removed)


async def _sweeper(settings: Settings) -> None:
    while True:
        await anyio.sleep(SWEEP_EVERY)
        await anyio.to_thread.run_sync(_sweep, settings)


@contextlib.contextmanager
def connection(request: Request):
    """Соединение из пула службы на время запроса: with connection(request) as conn. На то же время — язык вызова
    по Accept-Language (amem.lang.using): подписи ответов операций api — на нём, с заменой на другой слот."""
    language = lang.from_header(request.headers.get("accept-language"))
    with request.app.state.pool.connection() as conn, lang.using(language):
        yield conn


def provider(request: Request) -> embed.EmbeddingProvider | None:
    """provider смыслового канала: явный из create_app или один на запуск службы по AMEM_BACKEND — выбирается при
    первом поиске под замком, поэтому модель fastembed грузится один раз, а не на каждый запрос. AMEM_BACKEND=none
    рецепты проверяют сами при каждом вызове; неизвестный AMEM_BACKEND — None, рецепт назовёт причину."""
    return choose_provider(request.app.state)


def choose_provider(state) -> embed.EmbeddingProvider | None:
    """provider по состоянию приложения (app.state): то же, что provider(request), — для /mcp, у которого запроса
    Starlette в руках нет."""
    if not state.provider_chosen:
        with state.provider_lock:
            if not state.provider_chosen:
                try:
                    state.provider = embed.get_provider(None)
                except embed.EmbeddingError:
                    state.provider = None
                state.provider_chosen = True
    return state.provider


def health(request: Request) -> PlainTextResponse:
    with connection(request) as conn:            # база недоступна — 503, а не «ok»
        conn.execute("SELECT 1")
    return PlainTextResponse("ok")
