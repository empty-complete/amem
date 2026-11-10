"""Публичные рецепты exact_fact/similar: RRF, актуальные вектора и честная деградация."""
import json

import pytest

from amemo import db, embed, ids, lookup, records
from amemo.records import Item, RecordError
from conftest import FakeProvider

AGENT = "model:test"


@pytest.fixture
def kb(pg):
    db.prepare(pg)
    return pg


@pytest.fixture
def provider():
    selected = FakeProvider()
    selected.vector = semantic_vector
    return selected


def semantic_vector(text: str) -> list[float]:
    """Три понятных соседа: near alpha ближе к alpha, beta занимает другую ось."""
    vector = [0.0] * 384
    if "beta" in text:
        vector[1] = 1.0
    else:
        vector[0] = 1.0
        if "near alpha" in text:
            vector[1] = 0.01
    return vector


def atom(key, label, *, codes=None, kind="fact", status=None):
    return Item("atom", {
        "ref": f"@{key}", "kind": kind, "key": key,
        "label": {"ru": label}, "summary_plain": {"ru": label}, "codes": codes or [],
    }, status=status)


def write(kb, *items):
    return records.commit(kb, list(items), agent=AGENT)


def activate(kb, provider):
    model = embed.register_model(kb, provider)
    embed.sync_embeddings(kb, model["id"], provider)
    embed.activate_model(kb, model["id"])
    return model


def by_ref(result):
    return {item["ref"]: item for item in result["items"]}


def test_exact_fact_returns_all_ambiguous_codes_without_hidden_best_answer(kb):
    written = write(kb,
                    atom("second", "Вторая", codes=["ВН–45"]),
                    atom("first", "Первая", codes=["Вн-45"]),
                    atom("prefix", "Префикс", codes=["Вн-45-А"]))

    result = search_recipe(kb, "exact_fact", "ВН - 45")

    exact_refs = {f"atm:{revision.record_id}" for revision in written.revisions[:2]}
    assert {item["ref"] for item in result["items"][:2]} == exact_refs
    assert result["items"][2]["ref"] == f"atm:{written.revisions[2].record_id}"
    assert len(result["items"]) == 3
    assert "answer" not in result and "best" not in result and result["retrieval_id"]
    assert all(set(item) == {
        "ref", "revision", "label", "snippet", "status", "review_state", "score", "matches",
    } for item in result["items"])
    assert all(item["matches"][0]["channel"] == "code_exact" for item in result["items"][:2])
    json.dumps(result)


def search_recipe(kb, name, query, **kwargs):
    from amemo import recipes
    kwargs.setdefault("agent", AGENT)
    return getattr(recipes, name)(kb, query, **kwargs)


def test_exact_fact_empty_result_is_empty_and_reports_missing_model(kb):
    result = search_recipe(kb, "exact_fact", "Нет такой марки")

    assert result["recipe"] == "exact_fact"
    assert result["items"] == []
    assert result["candidate_count"] == 0
    assert result["semantic"] == "unavailable"
    assert result["channels"]["used"] == ["code_exact", "code_prefix", "fts"]
    assert result["channels"]["skipped"] == ["vector"]
    assert result["channels"]["reasons"] == {"vector": "no_active_model"}
    assert result["embedding_coverage"] is None


def test_exact_fact_include_record_uses_lookup_format(kb):
    revision = write(kb, atom("fact", "Карточка", codes=["CRD-1"])).revisions[0]

    compact = search_recipe(kb, "exact_fact", "CRD-1")
    full = search_recipe(kb, "exact_fact", "CRD-1", include_record=True)

    assert "record" not in compact["items"][0]
    assert full["items"][0]["record"] == lookup.get(kb, "atom", revision.record_id)
    assert set(full["items"][0]) == set(compact["items"][0]) | {"record"}


def test_exact_fact_uses_active_model_for_query_embedding(kb, provider):
    write(kb, atom("alpha", "alpha"), atom("beta", "beta"))
    model = activate(kb, provider)
    calls = len(provider.calls)

    result = search_recipe(kb, "exact_fact", "alpha", provider=provider)

    assert result["semantic"] == "used"
    assert result["channels"]["used"] == ["code_exact", "code_prefix", "fts", "vector"]
    assert result["channels"]["skipped"] == []
    assert result["channels"]["reasons"] == {}
    assert result["embedding_coverage"] == {
        "model_id": model["id"], "total": 2, "covered": 2, "missing": 0, "complete": True,
    }
    assert provider.calls[calls:] == [["alpha"]]
    vector_item = next(item for item in result["items"] if any(
        match["channel"] == "vector" for match in item["matches"]))
    match = next(match for match in vector_item["matches"] if match["channel"] == "vector")
    assert isinstance(match["source_rank"], float)


def test_vector_channel_excludes_other_models_old_revisions_and_stale_hashes(kb, provider):
    written = write(kb, atom("alpha", "alpha"), atom("near", "near alpha"), atom("beta", "beta"))
    first = activate(kb, provider)
    other_provider = FakeProvider()
    other_provider.version = "2"
    other_provider.vector = semantic_vector
    second = embed.register_model(kb, other_provider)
    embed.sync_embeddings(kb, second["id"], other_provider)
    embed.activate_model(kb, second["id"])
    stale = records.commit(kb, [Item("atom", {
        "kind": "fact", "key": "alpha", "label": {"ru": "changed"},
        "summary_plain": {"ru": "changed"},
    }, record_id=written.revisions[0].record_id)], agent=AGENT).revisions[0]

    result = search_recipe(kb, "exact_fact", "near alpha", provider=other_provider)

    vector_matches = [(item, match) for item in result["items"] for match in item["matches"]
                      if match["channel"] == "vector"]
    assert vector_matches
    assert all(item["ref"] != f"atm:{stale.record_id}" for item, _ in vector_matches)
    for item, _ in vector_matches:
        row = kb.execute(
            "SELECT e.model_id, e.text_hash, d.document, d.revision_id "
            "FROM search_document d JOIN embedding e ON e.target = d.target "
            "AND e.revision_id = d.revision_id WHERE d.target = 'atom' AND d.record_id = %s "
            "AND e.model_id = %s", (item["record"]["id"] if "record" in item else item["ref"].split(":", 1)[1],
                                    second["id"])).fetchone()
        assert row is not None
        assert str(row[0]) == second["id"] and str(row[0]) != first["id"]
        assert row[1] == embed.text_hash(row[2])


def test_vector_filters_are_applied_before_limit(kb, provider):
    rejected = [atom(f"r{i}", "vector filter", status="rejected") for i in range(51)]
    wanted = atom("wanted", "vector filter", kind="requirement")
    write(kb, *rejected, wanted)
    activate(kb, provider)

    default = search_recipe(kb, "exact_fact", "semantic query", provider=provider, limit=100)
    explicit = search_recipe(kb, "exact_fact", "semantic query", provider=provider,
                             statuses=["rejected"], limit=100)
    wrong_kind = search_recipe(kb, "exact_fact", "semantic query", provider=provider,
                               kind="formula", limit=100)

    assert [item["record"]["key"] if "record" in item else item["ref"] for item in default["items"]] == [
        f"atm:{wanted_payload_id(kb, 'wanted')}"]
    assert len(explicit["items"]) == 50
    assert wrong_kind["items"] == []


def wanted_payload_id(kb, key):
    return kb.execute("SELECT id FROM atom WHERE key = %s", (key,)).fetchone()[0]


def test_similar_text_finds_expected_neighbour_and_logs_only_retrieval(kb, provider):
    written = write(kb, atom("alpha", "alpha"), atom("near", "near alpha"), atom("beta", "beta"))
    activate(kb, provider)
    tables = ("atom", "entity", "changeset", "retrieval", "retrieval_item", "atom_use")
    before = {table: kb.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables}

    result = search_recipe(kb, "similar", "near alpha", provider=provider)

    assert result["recipe"] == "similar" and result["semantic"] == "used"
    assert result["items"][0]["ref"] == f"atm:{written.revisions[1].record_id}"
    assert result["items"][0]["matches"][0]["channel"] == "vector"
    assert result["channels"]["used"] == ["vector", "fts"]
    after = {table: kb.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables}
    atom_items = sum(item["ref"].startswith("atm:") for item in result["items"])
    assert after == {**before, "retrieval": before["retrieval"] + 1,
                     "retrieval_item": before["retrieval_item"] + atom_items}


def test_similar_ref_uses_current_stored_vector_and_excludes_source(kb, provider):
    written = write(kb, atom("alpha", "alpha"), atom("near", "near alpha"), atom("beta", "beta"))
    activate(kb, provider)
    calls = len(provider.calls)
    source = written.revisions[0]

    result = search_recipe(kb, "similar", f"atm:{source.record_id}", provider=provider)

    assert result["semantic"] == "used"
    assert f"atm:{source.record_id}" not in by_ref(result)
    assert result["items"][0]["ref"] == f"atm:{written.revisions[1].record_id}"
    assert provider.calls[calls:] == []
    assert all(match["channel"] in {"vector", "fts"} for item in result["items"] for match in item["matches"])


def test_similar_ref_rejects_missing_record_and_record_without_current_revision(kb):
    missing = ids.uuid7()
    with pytest.raises(RecordError, match="такой записи нет"):
        search_recipe(kb, "similar", f"atm:{missing}")

    record_id = ids.uuid7()
    kb.execute("INSERT INTO atom (id, key, kind, status, created_at, status_changed_at) "
               "VALUES (%s, 'empty', 'fact', 'draft', now(), now())", (record_id,))
    with pytest.raises(RecordError, match="текущей ревизии"):
        search_recipe(kb, "similar", f"atm:{record_id}")
    with pytest.raises(RecordError, match="UUID"):
        search_recipe(kb, "similar", "atm:not-a-uuid")


def test_similar_ref_without_current_fresh_vector_does_not_substitute_old_revision(kb, provider):
    written = write(kb,
                    atom("source", "legacyonly"),
                    atom("old_match", "legacyonly"),
                    atom("current_match", "currentonly"))
    source = written.revisions[0]
    activate(kb, provider)
    revised = records.commit(kb, [Item("atom", {
        "kind": "fact", "key": "source", "label": {"ru": "currentonly"},
        "summary_plain": {"ru": "currentonly"},
    }, record_id=source.record_id)], agent=AGENT).revisions[0]
    assert revised.revision_id != source.revision_id

    class QueryRecorder:
        def __init__(self, conn):
            self.conn = conn
            self.queries = []

        def execute(self, sql, params=None):
            self.queries.append(sql)
            return self.conn.execute(sql, params)

        def __getattr__(self, name):
            return getattr(self.conn, name)

    recorder = QueryRecorder(kb)
    from amemo import recipes
    source_data = recipes._source_document(recorder, f"atm:{source.record_id}")
    assert "currentonly" in source_data[2] and "legacyonly" not in source_data[2]
    result = search_recipe(kb, "similar", f"atm:{source.record_id}", provider=provider)

    assert result["semantic"] == "unavailable"
    assert result["channels"]["skipped"] == ["vector"]
    assert result["channels"]["reasons"] == {"vector": "source_embedding_missing"}
    assert result["items"], "FTS fallback должен найти запись с текстом текущей ревизии"
    assert [item["ref"] for item in result["items"]] == [f"atm:{written.revisions[2].record_id}"]
    assert f"atm:{written.revisions[1].record_id}" not in by_ref(result)
    assert all(match["channel"] == "fts" for item in result["items"] for match in item["matches"])
    assert all(item["matches"] for item in result["items"])
    assert any("d.revision_id = r.id" in query for query in recorder.queries), \
        "документ должен соединяться именно с текущей revision_id"


def test_similar_without_active_model_uses_fts_and_reports_unavailable(kb):
    written = write(kb, atom("wind", "Ветровое давление"), atom("snow", "Снеговая нагрузка"))

    result = search_recipe(kb, "similar", "ветрового давления")

    assert [item["ref"] for item in result["items"]] == [f"atm:{written.revisions[0].record_id}"]
    assert result["semantic"] == "unavailable"
    assert result["channels"]["used"] == ["fts"]
    assert result["channels"]["skipped"] == ["vector"]
    assert result["channels"]["reasons"] == {"vector": "no_active_model"}


def test_backend_none_ignores_old_vectors_and_explicit_provider(kb, provider, monkeypatch):
    written = write(kb, atom("alpha", "alpha"), atom("near", "near alpha"))
    activate(kb, provider)
    monkeypatch.setenv("AMEMO_BACKEND", "none")

    class ExplodingProvider(FakeProvider):
        def _embed(self, texts):
            raise AssertionError("provider вызван при AMEMO_BACKEND=none")

    result = search_recipe(kb, "similar", "alpha", provider=ExplodingProvider())

    assert result["semantic"] == "unavailable"
    assert result["channels"]["used"] == ["fts"]
    assert result["channels"]["skipped"] == ["vector"]
    assert result["channels"]["reasons"] == {"vector": "backend_disabled"}
    assert result["items"]
    assert all(match["channel"] == "fts" for item in result["items"] for match in item["matches"])
    assert f"atm:{written.revisions[0].record_id}" in by_ref(result)


def test_query_provider_must_match_active_model(kb, provider):
    write(kb, atom("alpha", "alpha"))
    activate(kb, provider)
    wrong = FakeProvider()
    wrong.version = "2"
    wrong.vector = semantic_vector

    with pytest.raises(embed.EmbeddingError, match="активной модели"):
        search_recipe(kb, "exact_fact", "alpha", provider=wrong)


def test_availability_reports_why_the_semantic_channel_is_off(kb, provider, monkeypatch):
    """recipes.availability — то же решение, что у поиска по тексту, без счёта векторов."""
    from amemo import recipes

    assert recipes.availability(kb, provider) == {"semantic": "unavailable", "reason": "no_active_model"}
    activate(kb, provider)
    calls = len(provider.calls)
    assert recipes.availability(kb, provider) == {"semantic": "used", "reason": None}
    assert len(provider.calls) == calls                       # вектора не считаются

    wrong = FakeProvider()
    wrong.version = "2"
    assert recipes.availability(kb, wrong) == {"semantic": "unavailable", "reason": "provider_mismatch"}
    with pytest.raises(embed.EmbeddingError):                 # поиск по тексту с этим provider — отказ
        search_recipe(kb, "exact_fact", "alpha", provider=wrong)

    monkeypatch.setenv("AMEMO_BACKEND", "none")
    assert recipes.availability(kb, provider) == {"semantic": "unavailable", "reason": "backend_disabled"}
    monkeypatch.setenv("AMEMO_BACKEND", "nonsense")
    assert recipes.availability(kb) == {"semantic": "unavailable", "reason": "backend_unknown"}


def test_availability_fastembed_model_without_the_package(kb, monkeypatch):
    from amemo import recipes

    class Fastembed(FakeProvider):
        name, version, backend = "intfloat/multilingual-e5-small", "1", "fastembed"

    selected = Fastembed()
    embed.activate_model(kb, embed.register_model(kb, selected)["id"])
    monkeypatch.setattr(recipes.importlib.util, "find_spec", lambda name: None)
    assert recipes.availability(kb, selected) == {"semantic": "unavailable", "reason": "fastembed_missing"}


def test_on_semantic_error_skip_degrades_to_lexical_channels(kb, provider, monkeypatch):
    """on_semantic_error="skip": provider, который не может посчитать вектор запроса, не валит поиск — смысловой
    канал пропускается с причиной; по умолчанию (raise) — EmbeddingError, как раньше. Журнал — одна строка."""
    from amemo import recipes

    written = write(kb, atom("alpha", "alpha"), atom("near", "near alpha"))
    activate(kb, provider)
    alpha = f"atm:{written.revisions[0].record_id}"
    wrong = FakeProvider()
    wrong.version = "2"

    class Broken(FakeProvider):
        def _embed(self, texts):
            raise embed.EmbeddingError("модель не считает вектора")

    class Fastembed(FakeProvider):
        name, version, backend = "fake-fastembed", "1", "fastembed"

    class FastembedBroken(Fastembed, Broken):
        pass

    working = Fastembed()
    model = embed.register_model(kb, working)
    embed.sync_embeddings(kb, model["id"], working)
    monkeypatch.setattr(recipes.importlib.util, "find_spec", lambda name: None)

    cases = [(wrong, "provider_mismatch"), (Broken(), "embedding_failed")]
    for recipe in ("exact_fact", "similar"):
        for selected, reason in cases:
            with pytest.raises(embed.EmbeddingError):
                search_recipe(kb, recipe, "alpha", provider=selected)
            before = kb.execute("SELECT count(*) FROM retrieval").fetchone()[0]
            result = search_recipe(kb, recipe, "alpha", provider=selected, on_semantic_error="skip")
            assert (result["semantic"], result["channels"]["reasons"]) == ("unavailable", {"vector": reason})
            assert "vector" in result["channels"]["skipped"] and alpha in by_ref(result)
            assert kb.execute("SELECT count(*) FROM retrieval").fetchone()[0] == before + 1
    embed.activate_model(kb, model["id"])
    result = search_recipe(kb, "exact_fact", "alpha", provider=FastembedBroken(), on_semantic_error="skip")
    assert result["channels"]["reasons"] == {"vector": "fastembed_missing"}
    monkeypatch.setenv("AMEMO_BACKEND", "nonsense")
    result = search_recipe(kb, "exact_fact", "alpha", on_semantic_error="skip")
    assert result["channels"]["reasons"] == {"vector": "backend_unknown"} and alpha in by_ref(result)
    with pytest.raises(ValueError, match="on_semantic_error"):
        search_recipe(kb, "exact_fact", "alpha", on_semantic_error="ignore")
