from connectors.rerankers.cross_encoder_reranker import CrossEncoderReranker
from core.models import Chunk, ScoredChunk

MODEL_ID = "cross-encoder/ms-marco-MiniLM-L6-v2"


def _scored_chunk(chunk_id: str, text: str, score: float) -> ScoredChunk:
    return ScoredChunk(
        chunk=Chunk(
            id=chunk_id,
            tenant_id="tenant-acme",
            document_id="doc-1",
            text=text,
            position=0,
            language="en",
            version=1,
        ),
        score=score,
    )


def test_rerank_reorders_candidates_by_relevance() -> None:
    reranker = CrossEncoderReranker(MODEL_ID)
    # Deliberately give the relevant candidate a lower initial score than
    # the irrelevant one, so a passing test proves the reranker actually
    # reordered by real relevance rather than just preserving input order.
    candidates = [
        _scored_chunk("irrelevant", "The weather in Paris is sunny today.", score=0.9),
        _scored_chunk(
            "relevant", "Loan applications must be reviewed within five business days.", score=0.1
        ),
    ]

    reranked = reranker.rerank(
        "What is the deadline for reviewing loan applications?", candidates, top_k=2
    )

    assert reranked[0].chunk.id == "relevant"


def test_rerank_respects_top_k() -> None:
    reranker = CrossEncoderReranker(MODEL_ID)
    candidates = [
        _scored_chunk("a", "Revenue grew twelve percent quarter over quarter.", score=0.5),
        _scored_chunk("b", "Follow these steps to onboard a new enterprise tenant.", score=0.5),
        _scored_chunk("c", "Invoice number 48213 was issued last week.", score=0.5),
    ]

    reranked = reranker.rerank("revenue growth", candidates, top_k=1)

    assert len(reranked) == 1


def test_rerank_empty_candidates_returns_empty() -> None:
    reranker = CrossEncoderReranker(MODEL_ID)

    assert reranker.rerank("anything", [], top_k=5) == []
