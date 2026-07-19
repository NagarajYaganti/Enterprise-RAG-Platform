import cohere
from core.interfaces import EmbeddingProvider
from core.models import Vector
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class CohereEmbeddingProvider(EmbeddingProvider):
    """EmbeddingProvider adapter for Cohere, gated behind an API key.

    Two-layer retry, same rationale as OpenAIEmbeddingProvider: the SDK
    retries transient errors internally; the outer tenacity retry is a
    separate app-level budget for cohere.TooManyRequestsError specifically.
    """

    def __init__(self, api_key: str, sdk_max_retries: int = 2) -> None:
        self._client = cohere.ClientV2(api_key=api_key, max_retries=sdk_max_retries)

    @retry(
        retry=retry_if_exception_type(cohere.TooManyRequestsError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def embed(self, texts: list[str], model_id: str) -> list[Vector]:
        response = self._client.embed(
            model=model_id,
            texts=texts,
            input_type="search_document",
            embedding_types=["float"],
        )
        floats = response.embeddings.float_
        assert floats is not None
        return list(floats)
