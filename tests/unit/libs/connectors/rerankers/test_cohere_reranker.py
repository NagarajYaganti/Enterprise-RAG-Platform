from unittest.mock import MagicMock

import cohere
from connectors.rerankers.cohere_reranker import CohereReranker
from core.models import Chunk, ScoredChunk


def _scored_chunk(chunk_id: str, text: str) -> ScoredChunk:
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
        score=0.0,
    )


def _result_item(index: int, relevance_score: float) -> MagicMock:
    item = MagicMock()
    item.index = index
    item.relevance_score = relevance_score
    return item


def test_rerank_maps_results_back_to_original_candidates_by_index() -> None:
    reranker = CohereReranker(api_key="fake-key", model_id="rerank-v3.5")
    candidates = [_scored_chunk("a", "alpha text"), _scored_chunk("b", "beta text")]

    mock_response = MagicMock()
    # Cohere returns results in relevance order, not input order — index 1
    # (chunk "b") ranked first here, proving we map by .index, not position.
    mock_response.results = [_result_item(1, 0.9), _result_item(0, 0.2)]
    reranker._client.rerank = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    reranked = reranker.rerank("query", candidates, top_k=2)

    assert [c.chunk.id for c in reranked] == ["b", "a"]
    assert [c.score for c in reranked] == [0.9, 0.2]
    reranker._client.rerank.assert_called_once_with(
        model="rerank-v3.5",
        query="query",
        documents=["alpha text", "beta text"],
        top_n=2,
    )


def test_rerank_retries_on_rate_limit_then_succeeds() -> None:
    reranker = CohereReranker(api_key="fake-key", model_id="rerank-v3.5")
    candidates = [_scored_chunk("a", "alpha text")]

    mock_response = MagicMock()
    mock_response.results = [_result_item(0, 0.5)]
    rate_limit_error = cohere.TooManyRequestsError(body={"message": "rate limited"})
    reranker._client.rerank = MagicMock(  # type: ignore[method-assign]
        side_effect=[rate_limit_error, mock_response]
    )

    reranked = reranker.rerank("query", candidates, top_k=1)

    assert [c.chunk.id for c in reranked] == ["a"]
    assert reranker._client.rerank.call_count == 2


def test_rerank_empty_candidates_returns_empty_without_calling_sdk() -> None:
    reranker = CohereReranker(api_key="fake-key", model_id="rerank-v3.5")
    reranker._client.rerank = MagicMock()  # type: ignore[method-assign]

    assert reranker.rerank("anything", [], top_k=5) == []
    reranker._client.rerank.assert_not_called()
