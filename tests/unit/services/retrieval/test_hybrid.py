from core.models import KeywordSearchHit, VectorSearchHit
from retrieval.hybrid import reciprocal_rank_fusion


def _vhit(chunk_id: str, document_id: str = "doc-1") -> VectorSearchHit:
    return VectorSearchHit(chunk_id=chunk_id, document_id=document_id, score=0.0, model_id="m")


def _khit(chunk_id: str, document_id: str = "doc-1") -> KeywordSearchHit:
    return KeywordSearchHit(chunk_id=chunk_id, document_id=document_id, score=0.0)


def test_rrf_formula_matches_the_paper_exactly() -> None:
    # k=1, single hit at rank 1: score = 1 / (k + rank) = 1 / (1 + 1) = 0.5.
    fused = reciprocal_rank_fusion([_vhit("a")], [], k=1)

    assert fused == [("a", "doc-1", 0.5)]


def test_rrf_favors_a_chunk_appearing_in_both_lists_over_a_single_rank1_hit() -> None:
    # Classic RRF property: rank-2-in-both (2/62) outscores rank-1-in-one
    # list only (1/61) — a real fusion effect, not just "union the lists."
    vector_hits = [_vhit("a"), _vhit("b")]
    keyword_hits = [_khit("c"), _khit("b")]

    fused = reciprocal_rank_fusion(vector_hits, keyword_hits, k=60)

    assert fused[0][0] == "b"
    assert fused[0][2] > fused[1][2]
    assert {fused[1][0], fused[2][0]} == {"a", "c"}


def test_rrf_sorts_descending_by_fused_score() -> None:
    vector_hits = [_vhit("a"), _vhit("b"), _vhit("c")]

    fused = reciprocal_rank_fusion(vector_hits, [], k=60)

    scores = [item[2] for item in fused]
    assert scores == sorted(scores, reverse=True)
    assert [item[0] for item in fused] == ["a", "b", "c"]


def test_rrf_with_empty_lists_returns_empty() -> None:
    assert reciprocal_rank_fusion([], [], k=60) == []


def test_rrf_carries_through_document_id() -> None:
    fused = reciprocal_rank_fusion([_vhit("a", document_id="doc-42")], [], k=60)

    assert fused[0][1] == "doc-42"
