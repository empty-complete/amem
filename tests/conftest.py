"""Общие фикстуры: тестовые документы и соединения с тестовыми базами схемы v1."""
import hashlib
import os
from pathlib import Path

import pytest

from amem.embed import EmbeddingProvider
from samples import make_docs


class FakeProvider(EmbeddingProvider):
    """Детерминированные 384-мерные вектора без модели, кэша и сети."""

    name = "fake-text"
    version = "1"
    dims = 384
    backend = "fake"

    def __init__(self):
        self.calls = []

    @staticmethod
    def vector(text: str) -> list[float]:
        known = {
            "alpha": 0,
            "near alpha": 0,
            "beta": 1,
        }
        if text in known:
            index = known[text]
            vector = [0.0] * 384
            vector[index] = 1.0
            if text == "near alpha":
                vector[1] = 0.01
            return vector
        # Для произвольного документа отображение тоже фиксировано между запусками.
        index = hashlib.sha256(text.encode("utf-8")).digest()[0] % 384
        vector = [0.0] * 384
        vector[index] = 1.0
        return vector

    def _embed(self, texts):
        self.calls.append(list(texts))
        return [self.vector(text) for text in texts]


@pytest.fixture(autouse=True)
def _hermetic_backend(monkeypatch):
    """AMEM_BACKEND из окружения разработчика не влияет на тесты: режим none тесты включают сами (monkeypatch).
    Без него выбор — как в CI; fastembed в зависимостях разработки нет, поэтому скрытая загрузка модели упала бы."""
    monkeypatch.delenv("AMEM_BACKEND", raising=False)


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


@pytest.fixture(params=TEST_DSNS, ids=lambda dsn: "pg" + dsn.rsplit(":", 1)[-1].split("/")[0])
def pgdb(request):
    """DSN своей временной базы на тестовом сервере (для pg_dump и pg_restore нужна целая база, а не схема);
    база удаляется после теста, даже если к ней ещё подключены."""
    import uuid

    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    dsn = request.param
    try:
        admin = psycopg.connect(dsn, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as e:
        pytest.fail(f"нет тестовой базы {dsn} — запустите: docker compose --profile test up -d --wait "
                    f"db-test db-test-pg16 ({e})", pytrace=False)
    created = []

    def new_database() -> str:
        name = f"amem_t_{uuid.uuid4().hex[:12]}"
        admin.execute(f'CREATE DATABASE "{name}"')
        created.append(name)
        return make_conninfo(**{**conninfo_to_dict(dsn), "dbname": name})

    try:
        yield new_database
    finally:
        for name in created:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.close()


@pytest.fixture
def store(tmp_path):
    """Хранилище объектов OCFL во временной папке теста (корень создаёт первая запись файла)."""
    from amem.ocfl_store import ObjectStore

    return ObjectStore(tmp_path / "objects")
