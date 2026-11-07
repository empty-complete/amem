"""Приложение Starlette: create_app(settings) — пул соединений, защита и сессия, problem+json, маршруты.

Библиотека синхронная, поэтому обработчики — обычные функции: Starlette зовёт их в пуле потоков, соединение берётся из
psycopg_pool на запрос (autocommit — как db.connect: каждый conn.transaction() — настоящая транзакция). lifespan
открывает пул и готовит базу (db.prepare — миграции, словари, base_id), при остановке закрывает пул. Секрет cookie
человека — новый на каждый запуск службы.
"""
from __future__ import annotations

import contextlib
import secrets

import anyio
from psycopg_pool import ConnectionPool
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from .. import db, embed
from ..ocfl_store import ObjectStore
from ..settings import Settings, SettingsError, load_tokens
from . import problems, session

API = "/api/v1"
POOL_MIN, POOL_MAX = 1, 8
POOL_TIMEOUT = 5.0        # с; дольше ждать соединения нет смысла — ответ 503
OPEN_TIMEOUT = 10.0       # с; база не ответила при запуске — служба не стартует


def create_app(settings: Settings, *, provider: embed.EmbeddingProvider | None = None) -> Starlette:
    """Служба HTTP по настройкам; provider — эмбеддинги для смыслового канала (None — по AMEM_BACKEND)."""
    if not settings.dsn:
        raise SettingsError("база не задана: задайте AMEM_DSN (или dsn в amem.toml) и выполните amem init")
    tokens = load_tokens(settings.tokens) if settings.tokens is not None else None

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        pool = ConnectionPool(settings.dsn, kwargs={"autocommit": True}, min_size=POOL_MIN, max_size=POOL_MAX,
                              open=False, timeout=POOL_TIMEOUT, check=ConnectionPool.check_connection,
                              name="amem")
        await anyio.to_thread.run_sync(_open, pool)
        app.state.pool = pool
        try:
            yield
        finally:
            await anyio.to_thread.run_sync(pool.close)

    from . import http_v1           # маршруты зовут connection() отсюда: импорт — после того, как модуль готов

    app = Starlette(
        routes=[Route("/health", health, methods=["GET"]), *http_v1.ROUTES],
        middleware=[Middleware(session.Guard, settings=settings, secret=secrets.token_urlsafe(32), tokens=tokens)],
        exception_handlers=problems.HANDLERS,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.provider = provider
    app.state.store = ObjectStore(settings.data)      # только чтение копий: корень создаёт первая запись файла
    return app


def _open(pool: ConnectionPool) -> None:
    pool.open(wait=True, timeout=OPEN_TIMEOUT)
    try:
        with pool.connection() as conn:
            db.prepare(conn)
    except BaseException:
        pool.close()
        raise


def connection(request: Request):
    """Соединение из пула службы на время запроса: with connection(request) as conn."""
    return request.app.state.pool.connection()


def health(request: Request) -> PlainTextResponse:
    with connection(request) as conn:            # база недоступна — 503, а не «ok»
        conn.execute("SELECT 1")
    return PlainTextResponse("ok")
