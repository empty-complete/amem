"""Общие фикстуры: тестовые документы и соединения с тестовыми базами схемы v1."""
import os
from pathlib import Path

import pytest

from samples import make_docs


@pytest.fixture
def docs(tmp_path) -> Path:
    return make_docs(tmp_path / "docs")


# Тестовые базы схемы v1 — PostgreSQL 18 и 16 (проверка совместимости).
# Запуск: docker compose --profile test up -d --wait db-test db-test-pg16
TEST_DSNS = os.environ.get(
    "AMEM_TEST_DSNS",
    "postgresql://test:test@localhost:5433/test,postgresql://test:test@localhost:5434/test").split(",")


@pytest.fixture(params=TEST_DSNS, ids=lambda dsn: "pg" + dsn.rsplit(":", 1)[-1].split("/")[0])
def pg(request):
    """Соединение со своей чистой схемой в тестовой базе; схема удаляется после теста.

    Базы недоступны — тест падает с подсказкой, а не пропускается: без них хранилище не проверено."""
    import uuid

    import psycopg

    dsn = request.param
    try:
        admin = psycopg.connect(dsn, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as e:
        pytest.fail(f"нет тестовой базы {dsn} — запустите: docker compose --profile test up -d --wait "
                    f"db-test db-test-pg16 ({e})", pytrace=False)
    schema = f"t_{uuid.uuid4().hex[:12]}"
    admin.execute(f'CREATE SCHEMA "{schema}"')
    # расширения ставятся на всю базу, в public; миграция повторяет CREATE EXTENSION IF NOT EXISTS
    admin.execute("CREATE EXTENSION IF NOT EXISTS btree_gist SCHEMA public")
    admin.execute("CREATE EXTENSION IF NOT EXISTS vector SCHEMA public")
    # autocommit — как у сервера (db.connect): каждый conn.transaction() — настоящая транзакция
    conn = psycopg.connect(dsn, autocommit=True, options=f"-c search_path={schema},public")
    try:
        yield conn
    finally:
        conn.close()
        admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        admin.close()
