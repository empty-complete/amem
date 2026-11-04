"""Локальные эмбеддинги: проверка provider, покрытие текущих ревизий и смена модели."""
import json
import math
import sys
import types

import psycopg
import pytest
from pgvector import HalfVector
from pgvector.psycopg import register_vector

from amem import db, embed, ids, records
from amem.records import Item
from conftest import FakeProvider

AGENT = "model:test"


@pytest.fixture
def kb(pg):
    db.prepare(pg)
    return pg


@pytest.fixture
def provider():
    return FakeProvider()


def put_atom(kb, label="Альфа", key="fact"):
    result = records.commit(kb, [Item("atom", {
        "ref": "@fact", "kind": "fact", "key": key,
        "label": {"ru": label}, "summary_plain": {"ru": f"Пояснение: {label}"},
    })], agent=AGENT)
    return result.revisions[0]


def revise_atom(kb, revision, label):
    result = records.commit(kb, [Item("atom", {
        "kind": "fact", "key": "fact", "label": {"ru": label},
        "summary_plain": {"ru": f"Пояснение: {label}"},
    }, record_id=revision.record_id)], agent=AGENT)
    return result.revisions[0]


def test_fake_provider_is_deterministic_and_empty_batch_does_not_call_model(provider):
    first = provider.embed(["alpha", "beta"])
    assert first == provider.embed(["alpha", "beta"])
    assert len(first) == 2 and all(len(vector) == 384 for vector in first)
    calls = len(provider.calls)
    assert provider.embed([]) == []
    assert len(provider.calls) == calls


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_provider_rejects_non_finite_coordinates(provider, value):
    provider.vector = lambda text: [value] * 384
    with pytest.raises(embed.EmbeddingError, match="конеч"):
        provider.embed(["bad"])


def test_provider_rejects_wrong_vector_count(provider):
    provider._embed = lambda texts: []
    with pytest.raises(embed.EmbeddingError, match="число векторов"):
        provider.embed(["one"])


def test_provider_rejects_wrong_dimensions(provider):
    provider.vector = lambda text: [0.0] * 383
    with pytest.raises(embed.EmbeddingError, match="384"):
        provider.embed(["bad"])


def test_register_model_is_idempotent_and_json_compatible(kb, provider):
    model = embed.register_model(kb, provider)
    assert model["name"] == "fake-text" and model["version"] == "1"
    assert model["dims"] == 384 and model["backend"] == "fake" and model["active"] is False
    assert embed.register_model(kb, provider) == model
    assert kb.execute("SELECT count(*) FROM embedding_model").fetchone()[0] == 1
    json.dumps(model)


def test_embed_revision_stores_versioned_document_hash_and_halfvec(kb, provider):
    revision = put_atom(kb)
    model = embed.register_model(kb, provider)
    result = embed.embed_revision(kb, "atom", revision.revision_id, model["id"], provider)
    document = kb.execute("SELECT document FROM search_document").fetchone()[0]
    row = kb.execute("SELECT dims, text_hash, vector_dims(vec) FROM embedding").fetchone()
    assert result["embedded"] is True
    assert result["text_hash"] == embed.text_hash(document)
    assert row == (384, embed.text_hash(document), 384)
    assert str(search_version := embed.SEARCH_TEXT_VERSION) in result["text_hash"]
    assert search_version == 1
    json.dumps(result)


def test_sync_skips_matching_hash_and_new_revision_keeps_old_vector(kb, provider):
    first = put_atom(kb)
    model = embed.register_model(kb, provider)
    assert embed.sync_embeddings(kb, model["id"], provider)["embedded"] == 1
    calls = len(provider.calls)
    assert embed.sync_embeddings(kb, model["id"], provider)["embedded"] == 0
    assert len(provider.calls) == calls

    second = revise_atom(kb, first, "Бета")
    assert embed.embedding_coverage(kb, model["id"])["missing"] == 1
    assert embed.sync_embeddings(kb, model["id"], provider)["embedded"] == 1
    rows = kb.execute("SELECT revision_id, text_hash FROM embedding ORDER BY created_at, revision_id").fetchall()
    assert {str(row[0]) for row in rows} == {str(first.revision_id), str(second.revision_id)}
    assert len({row[1] for row in rows}) == 2
    assert embed.embedding_coverage(kb, model["id"])["complete"] is True


@pytest.mark.parametrize("bad", ["count", "dims", "nan"])
def test_invalid_provider_output_is_rejected_before_insert(kb, provider, bad):
    put_atom(kb)
    model = embed.register_model(kb, provider)
    if bad == "count":
        provider._embed = lambda texts: []
    elif bad == "dims":
        provider.vector = lambda text: [0.0] * 383
    else:
        provider.vector = lambda text: [math.nan] * 384
    with pytest.raises(embed.EmbeddingError):
        embed.sync_embeddings(kb, model["id"], provider)
    assert kb.execute("SELECT count(*) FROM embedding").fetchone()[0] == 0


def test_halfvec_cosine_returns_expected_nearest_neighbour(kb, provider):
    first = put_atom(kb, "Альфа")
    second = put_atom(kb, "Бета", "other")
    model = embed.register_model(kb, provider)
    embed.sync_embeddings(kb, model["id"], provider)
    document = kb.execute("SELECT document FROM search_document WHERE revision_id = %s",
                          (first.revision_id,)).fetchone()[0]
    row = kb.execute(
        "SELECT revision_id, vec <=> %s AS distance FROM embedding "
        "WHERE model_id = %s ORDER BY distance, revision_id LIMIT 1",
        (HalfVector(provider.vector(document)), model["id"])).fetchone()
    assert str(row[0]) == str(first.revision_id)
    assert row[1] == pytest.approx(0.0)
    assert str(row[0]) != str(second.revision_id)


def test_hnsw_1024_exists_and_rejects_384_dimensional_value(kb, provider):
    revision = put_atom(kb)
    index = kb.execute("SELECT pg_get_indexdef('embedding_hnsw_1024'::regclass)").fetchone()[0]
    assert "halfvec(1024)" in index and "USING hnsw" in index
    model_id = ids.uuid7()
    kb.execute("INSERT INTO embedding_model (id, name, version, dims, backend, created_at) "
               "VALUES (%s, 'fake-large', '1', 1024, 'fake', now())", (model_id,))
    register_vector(kb)
    with pytest.raises(psycopg.errors.DataError, match="1024"):
        kb.execute("INSERT INTO embedding (target, revision_id, model_id, dims, text_hash, vec, created_at) "
                   "VALUES ('atom', %s, %s, 1024, 'bad', %s, now())",
                   (revision.revision_id, model_id, HalfVector([0.0] * 384)))
    assert kb.execute("SELECT count(*) FROM embedding").fetchone()[0] == 0


def test_activation_requires_full_coverage_and_switches_atomically(kb, provider):
    revision = put_atom(kb)
    first = embed.register_model(kb, provider)
    other_provider = FakeProvider()
    other_provider.version = "2"
    second = embed.register_model(kb, other_provider)

    with pytest.raises(embed.EmbeddingError, match="1"):
        embed.activate_model(kb, first["id"])
    assert embed.embedding_coverage(kb, first["id"]) == {
        "model_id": first["id"], "total": 1, "covered": 0, "missing": 1, "complete": False,
    }
    embed.sync_embeddings(kb, first["id"], provider)
    assert embed.activate_model(kb, first["id"])["active"] is True
    embed.sync_embeddings(kb, second["id"], other_provider)
    embed.activate_model(kb, second["id"])
    rows = kb.execute("SELECT id, active FROM embedding_model ORDER BY created_at, id").fetchall()
    assert [(str(row[0]), row[1]) for row in rows] == [(first["id"], False), (second["id"], True)]
    assert kb.execute("SELECT count(*) FROM embedding WHERE revision_id = %s",
                      (revision.revision_id,)).fetchone()[0] == 2


def test_empty_database_has_complete_coverage_and_can_activate(kb, provider):
    model = embed.register_model(kb, provider)
    assert embed.embedding_coverage(kb, model["id"]) == {
        "model_id": model["id"], "total": 0, "covered": 0, "missing": 0, "complete": True,
    }
    assert embed.activate_model(kb, model["id"])["active"] is True


def test_backend_none_disables_provider_without_importing_fastembed(kb, provider, monkeypatch):
    put_atom(kb)
    model = embed.register_model(kb, provider)
    calls = len(provider.calls)
    monkeypatch.setenv("AMEM_BACKEND", "none")
    monkeypatch.setitem(sys.modules, "fastembed", None)
    result = embed.sync_embeddings(kb, model["id"])
    assert result["embedded"] == 0 and result["missing"] == 1
    assert len(provider.calls) == calls
    assert embed.get_provider() is None


class ExplodingProvider(FakeProvider):
    def _embed(self, texts):
        raise AssertionError("provider вызван при AMEM_BACKEND=none")


def test_backend_none_overrides_explicit_provider_in_sync(kb, provider, monkeypatch):
    put_atom(kb)
    model = embed.register_model(kb, provider)
    monkeypatch.setenv("AMEM_BACKEND", "none")
    monkeypatch.setitem(sys.modules, "fastembed", None)
    result = embed.sync_embeddings(kb, model["id"], ExplodingProvider())
    assert result["embedded"] == 0 and result["missing"] == 1
    assert kb.execute("SELECT count(*) FROM embedding").fetchone()[0] == 0


def test_backend_none_overrides_explicit_provider_in_embed_revision(kb, provider, monkeypatch):
    revision = put_atom(kb)
    model = embed.register_model(kb, provider)
    monkeypatch.setenv("AMEM_BACKEND", "none")
    monkeypatch.setitem(sys.modules, "fastembed", None)
    result = embed.embed_revision(kb, "atom", revision.revision_id, model["id"], ExplodingProvider())
    assert result["embedded"] is False
    assert kb.execute("SELECT count(*) FROM embedding").fetchone()[0] == 0


def test_fastembed_is_lazy_and_download_requires_explicit_permission(monkeypatch):
    created = []

    class TextEmbedding:
        def __init__(self, **kwargs):
            created.append(kwargs)

        def embed(self, texts):
            return [[0.0] * 384 for _ in texts]

    fake_module = types.SimpleNamespace(TextEmbedding=TextEmbedding)
    monkeypatch.setitem(sys.modules, "fastembed", fake_module)
    provider = embed.FastembedProvider(cache_dir="/unused/test-cache")
    assert created == []
    assert provider.embed([]) == []
    assert created == []
    assert len(provider.embed(["one"])) == 1
    assert created[0]["lazy_load"] is True
    assert created[0]["local_files_only"] is True
    assert created[0]["cache_dir"] == "/unused/test-cache"

    allowed = embed.FastembedProvider(allow_download=True)
    allowed.embed(["one"])
    assert created[1]["local_files_only"] is False


def test_fastembed_preserves_transitive_module_not_found(monkeypatch):
    def missing_dependency(name):
        raise ModuleNotFoundError("No module named 'transitive_dependency'", name="transitive_dependency")

    monkeypatch.setattr(embed.importlib, "import_module", missing_dependency)
    with pytest.raises(ModuleNotFoundError) as caught:
        embed.FastembedProvider().embed(["one"])
    assert caught.value.name == "transitive_dependency"
