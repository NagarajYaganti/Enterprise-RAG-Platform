import cohere
from core.interfaces import Reranker
from core.models import ScoredChunk
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class CohereReranker(Reranker):
    """Reranker adapter for Cohere, gated behind an API key.

    Two-layer retry, same rationale as CohereEmbeddingProvider: the SDK
    retries transient errors internally; the outer tenacity retry is a
    separate app-level budget for cohere.TooManyRequestsError specifically.
    """

    def __init__(self, api_key: str, model_id: str, sdk_max_retries: int = 2) -> None:
        # model_id is never hardcoded — bound at construction from
        # config/models.yaml, same rationale as CrossEncoderReranker. The
        # fixed Reranker ABC's rerank(query, candidates, top_k) signature
        # has no model_id slot (unlike EmbeddingProvider.embed), so it must
        # be bound here rather than passed per-call.
        self._model_id = model_id
        self._client = cohere.ClientV2(api_key=api_key, max_retries=sdk_max_retries)

    @retry(
        retry=retry_if_exception_type(cohere.TooManyRequestsError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def rerank(self, query: str, candidates: list[ScoredChunk], top_k: int) -> list[ScoredChunk]:
        if not candidates:
            return []
        response = self._client.rerank(
            model=self._model_id,
            query=query,
            documents=[candidate.chunk.text for candidate in candidates],
            top_n=top_k,
        )
        return [
            candidates[result.index].model_copy(update={"score": result.relevance_score})
            for result in response.results
        ]
