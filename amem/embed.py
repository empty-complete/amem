"""Локальные эмбеддинги текущих ревизий, покрытие модели и её безопасная смена.

Вектор принадлежит ревизии и модели. Синхронизация пересчитывает только текущие документы,
у которых изменился версионированный хэш поискового текста; вектора старых ревизий сохраняются.
fastembed — необязательная зависимость: её модуль и модель загружаются только при первом вызове.
"""
from __future__ import annotations

import hashlib
import importlib
import math
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg
from pgvector import HalfVector
from pgvector.psycopg import register_vector

from .ids import uuid7
from .search import SEARCH_TEXT_VERSION

Target = str


class EmbeddingError(ValueError):
    """Некорректный provider, отсутствующие данные или неполное покрытие модели."""


class EmbeddingProvider:
    """Базовый provider: единая проверка числа, размерности и конечности координат."""

    name: str
    version: str
    dims: int
    backend: str

    def embed(self, texts) -> list[list[float]]:
        values = list(texts)
        if not values:
            return []
        vectors = list(self._embed(values))
        if len(vectors) != len(values):
            raise EmbeddingError(f"provider вернул число векторов {len(vectors)}, ожидалось {len(values)}")
        checked = []
        for i, vector in enumerate(vectors):
            try:
                coordinates = list(vector)
            except TypeError as e:
                raise EmbeddingError(f"вектор {i} не является последовательностью float") from e
            if len(coordinates) != self.dims:
                raise EmbeddingError(f"вектор {i}: размерность {len(coordinates)}, ожидалось {self.dims}")
            try:
                converted = [float(value) for value in coordinates]
            except (TypeError, ValueError, OverflowError) as e:
                raise EmbeddingError(f"вектор {i}: координаты должны быть конечными float") from e
            if not all(math.isfinite(value) for value in converted):
                raise EmbeddingError(f"вектор {i}: координаты должны быть конечными float")
            checked.append(converted)
        return checked

    def _embed(self, texts: list[str]):
        raise NotImplementedError


class FastembedProvider(EmbeddingProvider):
    """Ленивый fastembed; без allow_download разрешены только файлы локального кэша."""

    backend = "fastembed"

    def __init__(self, model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", *,
                 version: str = "1", dims: int = 384, cache_dir: str | None = None,
                 allow_download: bool = False):
        self.name = model_name
        self.version = version
        self.dims = dims
        self.cache_dir = cache_dir
        self.allow_download = allow_download
        self._model = None

    def _embed(self, texts: list[str]):
        if self._model is None:
            try:
                module = importlib.import_module("fastembed")
            except ModuleNotFoundError as e:
                if e.name != "fastembed":
                    raise
                raise EmbeddingError("fastembed не установлен: установите optional extra amem[embed]") from e
            self._model = module.TextEmbedding(
                model_name=self.name,
                cache_dir=self.cache_dir,
                lazy_load=True,
                local_files_only=not self.allow_download,
            )
        return [vector.tolist() if hasattr(vector, "tolist") else vector
                for vector in self._model.embed(texts)]


def get_provider(explicit: EmbeddingProvider | None = None) -> EmbeddingProvider | None:
    """Выбрать provider по AMEM_BACKEND; none имеет приоритет даже над явным аргументом."""
    backend = os.environ.get("AMEM_BACKEND", "fastembed").strip().lower()
    if backend == "none":
        return None
    if explicit is not None:
        return explicit
    if backend == "fastembed":
        return FastembedProvider()
    raise EmbeddingError(f"неизвестный AMEM_BACKEND {backend!r}: нужен fastembed или none")


def text_hash(document: str) -> str:
    """Хэш именно поискового документа; версия текста входит и в метку, и в preimage."""
    preimage = f"amem-search-text\0{SEARCH_TEXT_VERSION}\0{document}".encode("utf-8")
    return f"sha256-s{SEARCH_TEXT_VERSION}:{hashlib.sha256(preimage).hexdigest()}"


def _model_id(value: Any) -> uuid.UUID:
    if isinstance(value, dict):
        value = value.get("id")
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError) as e:
        raise EmbeddingError(f"model_id {value!r}: это не UUID") from e


def _model_row(conn: psycopg.Connection, model_id, *, lock: bool = False):
    row = conn.execute(
        "SELECT id, name, version, dims, backend, active, created_at FROM embedding_model "
        f"WHERE id = %s{' FOR UPDATE' if lock else ''}", (_model_id(model_id),)).fetchone()
    if row is None:
        raise EmbeddingError(f"модель эмбеддингов {model_id} не зарегистрирована")
    return row


def _model_json(row) -> dict:
    return {
        "id": str(row[0]), "name": row[1], "version": row[2], "dims": row[3],
        "backend": row[4], "active": row[5], "created_at": row[6].isoformat(),
    }


def register_model(conn: psycopg.Connection, provider: EmbeddingProvider) -> dict:
    """Идемпотентно зарегистрировать метаданные provider и адаптеры pgvector для соединения."""
    if not all(isinstance(getattr(provider, field, None), str) and getattr(provider, field).strip()
               for field in ("name", "version", "backend")):
        raise EmbeddingError("provider: name, version и backend должны быть непустыми строками")
    if isinstance(provider.dims, bool) or not isinstance(provider.dims, int) or provider.dims <= 0:
        raise EmbeddingError("provider.dims должен быть положительным целым числом")
    register_vector(conn)
    with conn.transaction():
        row = conn.execute(
            "SELECT id, name, version, dims, backend, active, created_at FROM embedding_model "
            "WHERE name = %s AND version = %s AND backend = %s",
            (provider.name, provider.version, provider.backend)).fetchone()
        if row is not None:
            if row[3] != provider.dims:
                raise EmbeddingError(f"модель уже зарегистрирована с размерностью {row[3]}, не {provider.dims}")
            return _model_json(row)
        model_id = uuid7()
        now = datetime.now(timezone.utc)
        conn.execute(
            "INSERT INTO embedding_model (id, name, version, dims, backend, active, created_at) "
            "VALUES (%s, %s, %s, %s, %s, false, %s)",
            (model_id, provider.name, provider.version, provider.dims, provider.backend, now))
    return _model_json(_model_row(conn, model_id))


def _documents_with_embeddings(conn: psycopg.Connection, model_id) -> list[tuple]:
    return conn.execute(
        "SELECT d.target, d.record_id, d.revision_id, d.document, e.text_hash, e.dims "
        "FROM search_document d LEFT JOIN embedding e ON e.target = d.target "
        "AND e.revision_id = d.revision_id AND e.model_id = %s "
        "ORDER BY d.target, d.record_id", (_model_id(model_id),)).fetchall()


def _current(rows: list[tuple], dims: int) -> tuple[list[tuple], list[tuple]]:
    fresh, stale = [], []
    for row in rows:
        expected = text_hash(row[3])
        (fresh if row[4] == expected and row[5] == dims else stale).append(row)
    return fresh, stale


def embedding_coverage(conn: psycopg.Connection, model_id) -> dict:
    """Покрытие именно текущих документов актуальным хэшем; пустая база покрыта полностью."""
    model = _model_row(conn, model_id)
    rows = _documents_with_embeddings(conn, model[0])
    fresh, stale = _current(rows, model[3])
    return {
        "model_id": str(model[0]), "total": len(rows), "covered": len(fresh),
        "missing": len(stale), "complete": not stale,
    }


def _write_embeddings(conn: psycopg.Connection, model, documents: list[tuple],
                      vectors: list[list[float]]) -> None:
    register_vector(conn)
    now = datetime.now(timezone.utc)
    with conn.transaction():
        for row, vector in zip(documents, vectors):
            conn.execute(
                "INSERT INTO embedding (target, revision_id, model_id, dims, text_hash, vec, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (target, revision_id, model_id) DO UPDATE SET "
                "dims = EXCLUDED.dims, text_hash = EXCLUDED.text_hash, vec = EXCLUDED.vec, "
                "created_at = EXCLUDED.created_at",
                (row[0], row[2], model[0], model[3], text_hash(row[3]), HalfVector(vector), now))


def _check_provider(model, provider: EmbeddingProvider) -> None:
    if provider.dims != model[3]:
        raise EmbeddingError(f"размерность provider {provider.dims} не совпадает с моделью {model[3]}")


def sync_embeddings(conn: psycopg.Connection, model_id, provider: EmbeddingProvider | None = None) -> dict:
    """Вычислить недостающие/устаревшие вектора текущих документов одним батчем."""
    model = _model_row(conn, model_id)
    rows = _documents_with_embeddings(conn, model[0])
    _, stale = _current(rows, model[3])
    if not stale:
        return {"embedded": 0, **embedding_coverage(conn, model[0])}
    selected = get_provider(provider)
    if selected is None:
        return {"embedded": 0, **embedding_coverage(conn, model[0])}
    _check_provider(model, selected)
    vectors = selected.embed([row[3] for row in stale])       # вся проверка — до первого INSERT
    _write_embeddings(conn, model, stale, vectors)
    return {"embedded": len(stale), **embedding_coverage(conn, model[0])}


def embed_revision(conn: psycopg.Connection, target: Target, revision_id, model_id,
                   provider: EmbeddingProvider | None = None) -> dict:
    """Вектор одной текущей ревизии; совпадающий хэш повторно provider не вызывает."""
    if target not in ("atom", "entity"):
        raise EmbeddingError(f"неизвестный вид записи {target!r}")
    model = _model_row(conn, model_id)
    row = conn.execute(
        "SELECT d.target, d.record_id, d.revision_id, d.document, e.text_hash, e.dims "
        "FROM search_document d LEFT JOIN embedding e ON e.target = d.target "
        "AND e.revision_id = d.revision_id AND e.model_id = %s "
        "WHERE d.target = %s AND d.revision_id = %s",
        (model[0], target, revision_id)).fetchone()
    if row is None:
        raise EmbeddingError(f"текущая поисковая ревизия {target}:{revision_id} не найдена")
    digest = text_hash(row[3])
    result = {"target": target, "revision_id": str(row[2]), "model_id": str(model[0]),
              "text_hash": digest, "embedded": False}
    if row[4] == digest and row[5] == model[3]:
        return result
    selected = get_provider(provider)
    if selected is None:
        return result
    _check_provider(model, selected)
    vector = selected.embed([row[3]])
    _write_embeddings(conn, model, [row], vector)
    result["embedded"] = True
    return result


def activate_model(conn: psycopg.Connection, model_id) -> dict:
    """Атомарно сделать модель единственной активной; неполное покрытие запрещает смену."""
    with conn.transaction():
        model = _model_row(conn, model_id, lock=True)
        coverage = embedding_coverage(conn, model[0])
        if not coverage["complete"]:
            raise EmbeddingError(f"нельзя активировать модель: не хватает {coverage['missing']} эмбеддингов")
        # UNIQUE на active проверяется после каждой строки: сначала снимаем старый флаг,
        # затем ставим новый. Оба UPDATE остаются неделимыми для других транзакций.
        conn.execute("UPDATE embedding_model SET active = false WHERE active AND id <> %s", (model[0],))
        conn.execute("UPDATE embedding_model SET active = true WHERE id = %s", (model[0],))
        model = _model_row(conn, model[0])
    return _model_json(model)
