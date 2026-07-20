import math

import pytest
from retrieval.eval import GoldenQuery, mrr, ndcg_at_k, recall_at_k, run_harness


def test_recall_at_k_full_hit() -> None:
    assert recall_at_k(["a", "b", "c"], ["b"], k=3) == 1.0


def test_recall_at_k_miss_outside_k() -> None:
    assert recall_at_k(["a", "b", "c"], ["c"], k=1) == 0.0


def test_recall_at_k_partial_hit_with_multiple_relevant() -> None:
    # one of two relevant chunks retrieved in top-2.
    assert recall_at_k(["a", "x"], ["a", "b"], k=2) == 0.5


def test_recall_at_k_with_no_relevant_chunks_is_zero() -> None:
    assert recall_at_k(["a", "b"], [], k=2) == 0.0


def test_mrr_hit_at_rank_one() -> None:
    assert mrr(["a", "b", "c"], ["a"]) == 1.0


def test_mrr_hit_at_rank_two() -> None:
    assert mrr(["a", "b", "c"], ["b"]) == pytest.approx(0.5)


def test_mrr_no_hit_is_zero() -> None:
    assert mrr(["a", "b", "c"], ["z"]) == 0.0


def test_ndcg_at_k_perfect_ranking_is_one() -> None:
    # both relevant chunks retrieved in the ideal order (best case == DCG).
    assert ndcg_at_k(["a", "b"], ["a", "b"], k=2) == pytest.approx(1.0)


def test_ndcg_at_k_matches_hand_computed_value() -> None:
    # retrieved=[c, a], relevant={a}: DCG = 0 (rank1 miss) + 1/log2(3) (rank2 hit).
    # IDCG (best case: one relevant chunk in rank1) = 1/log2(2) = 1.0.
    expected = (1.0 / math.log2(3)) / 1.0
    assert ndcg_at_k(["c", "a"], ["a"], k=2) == pytest.approx(expected)


def test_ndcg_at_k_no_relevant_in_top_k_is_zero() -> None:
    assert ndcg_at_k(["x", "y"], ["a"], k=2) == 0.0


def test_run_harness_averages_metrics_across_queries() -> None:
    golden = [
        GoldenQuery(query="q1", relevant_chunk_ids=["a"]),
        GoldenQuery(query="q2", relevant_chunk_ids=["z"]),
    ]

    def fake_retrieve(query: str) -> list[str]:
        # q1's relevant chunk "a" is found at rank 1 (perfect);
        # q2's relevant chunk "z" is never retrieved (miss).
        return ["a", "b", "c"] if query == "q1" else ["x", "y"]

    metrics = run_harness(golden, fake_retrieve, k=3)

    assert metrics["recall@3"] == pytest.approx(0.5)  # (1.0 + 0.0) / 2
    assert metrics["mrr"] == pytest.approx(0.5)  # (1.0 + 0.0) / 2
    assert metrics["ndcg@3"] == pytest.approx(0.5)  # (1.0 + 0.0) / 2


def test_run_harness_with_no_queries_returns_zeros() -> None:
    metrics = run_harness([], lambda q: [], k=5)

    assert metrics == {"recall@5": 0.0, "mrr": 0.0, "ndcg@5": 0.0}
