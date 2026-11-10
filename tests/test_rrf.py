"""RRF v1: численный эталон, точные марки и стабильные метаданные выдачи."""
import json

import pytest

from amemo import search


def candidate(ref, rank, source_rank=None):
    target, record_id = ref.split(":", 1)
    return {
        "target": "atom" if target == "atm" else "entity",
        "record_id": record_id,
        "revision_id": record_id,
        "ref": ref,
        "rank": rank,
        "source_rank": source_rank,
    }


def by_ref(result):
    return {hit["ref"]: hit for hit in result["hits"]}


def test_rrf_numeric_reference_sums_channels_and_deduplicates_exact_prefix():
    exact_ref = "atm:00000000-0000-0000-0000-000000000001"
    other_ref = "atm:00000000-0000-0000-0000-000000000002"
    channels = {
        "code_exact": [candidate(exact_ref, 1)],
        # Такой дубль не должен появиться после SQL, но чистое слияние тоже его исключает.
        "code_prefix": [candidate(other_ref, 1), candidate(exact_ref, 2)],
        "fts": [candidate(other_ref, 1, 0.8), candidate(exact_ref, 2, 0.2)],
    }
    weights = {"code_exact": 4, "code_prefix": 2, "fts": 1}

    result = search._rrf(channels, weights)

    hits = by_ref(result)
    assert hits[exact_ref]["score"] == pytest.approx(4 / 61 + 1 / 62)
    assert hits[other_ref]["score"] == pytest.approx(2 / 61 + 1 / 61)
    assert hits[exact_ref]["matches"] == [
        {"channel": "code_exact", "rank": 1, "source_rank": None},
        {"channel": "fts", "rank": 2, "source_rank": 0.2},
    ]
    assert hits[other_ref]["matches"] == [
        {"channel": "code_prefix", "rank": 1, "source_rank": None},
        {"channel": "fts", "rank": 1, "source_rank": 0.8},
    ]


def test_rrf_breaks_score_ties_by_canonical_ref_and_applies_limit_last():
    first = "atm:00000000-0000-0000-0000-000000000001"
    second = "ent:00000000-0000-0000-0000-000000000002"
    channels = {
        "fts": [candidate(second, 1, 0.4)],
        "code_prefix": [candidate(first, 1)],
    }
    weights = {"code_prefix": 1, "fts": 1}

    result = search._rrf(channels, weights, limit=1)
    repeated = search._rrf(channels, weights, limit=1)

    assert [hit["ref"] for hit in result["hits"]] == [first]
    assert result["candidate_count"] == 2
    assert result["hits"][0]["score"] == pytest.approx(1 / 61)
    assert json.dumps(result, sort_keys=True) == json.dumps(repeated, sort_keys=True)


@pytest.mark.parametrize("limit", [0, 101, -1, 1.5, True, "10"])
def test_rrf_rejects_limit_outside_1_to_100(limit):
    with pytest.raises(ValueError, match="limit"):
        search._rrf({}, {"fts": 1}, limit=limit)


def test_exact_fact_comparator_puts_exact_group_before_more_popular_candidates():
    exact_ref = "atm:00000000-0000-0000-0000-000000000001"
    popular_ref = "atm:00000000-0000-0000-0000-000000000002"
    channels = {
        "code_exact": [candidate(exact_ref, 50)],
        "code_prefix": [candidate(popular_ref, 1)],
        "fts": [candidate(popular_ref, 1, 0.9)],
    }
    weights = {"code_exact": 4, "code_prefix": 2, "fts": 1}

    ordinary = search._rrf(channels, weights)
    exact_fact = search._rrf(channels, weights, exact_fact=True)

    assert by_ref(ordinary)[popular_ref]["score"] > by_ref(ordinary)[exact_ref]["score"]
    assert [hit["ref"] for hit in ordinary["hits"]] == [popular_ref, exact_ref]
    assert [hit["ref"] for hit in exact_fact["hits"]] == [exact_ref, popular_ref]


def test_rrf_reports_channels_candidate_count_and_durations_without_utility():
    one = "atm:00000000-0000-0000-0000-000000000001"
    two = "atm:00000000-0000-0000-0000-000000000002"
    channels = {
        "code_exact": [candidate(one, 1)],
        "code_prefix": [],
        "fts": [candidate(one, 1, 0.3), candidate(two, 2, 0.1)],
        "vector": None,
    }
    durations = {"code_exact": 1.25, "code_prefix": 0.5, "fts": 2.0}

    result = search._rrf(channels, search.RANKING_V1["recipes"]["exact_fact"],
                         limit=1, durations_ms=durations)

    assert result["ranking_version"] == search.RANKING_V1["version"]
    assert result["used_channels"] == ["code_exact", "code_prefix", "fts"]
    assert result["skipped_channels"] == ["vector"]
    assert result["candidate_count"] == 2
    assert result["durations_ms"] == durations
    assert len(result["hits"]) == 1
    assert set(result) == {
        "hits", "ranking_version", "used_channels", "skipped_channels",
        "candidate_count", "durations_ms",
    }
    assert set(result["hits"][0]) == {
        "target", "record_id", "revision_id", "ref", "score", "matches",
    }


def test_ranking_v1_keeps_k_and_recipe_weights_together():
    assert search.RANKING_V1["k"] == 60
    assert search.RANKING_V1["recipes"] == {
        "exact_fact": {"code_exact": 4, "code_prefix": 2, "fts": 1, "vector": 0.25},
        "similar": {"vector": 2, "fts": 0.5},
    }
