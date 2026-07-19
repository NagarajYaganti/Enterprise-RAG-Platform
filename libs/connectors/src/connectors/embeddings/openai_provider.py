import openai
from core.interfaces import EmbeddingProvider
from core.models import Vector
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """EmbeddingProvider adapter for OpenAI, gated behind an API key.

    Two-layer retry: the OpenAI SDK itself retries transient/network errors
    internally (max_retries=2, verified against the installed SDK). The
    outer tenacity retry here is a separate, app-level budget specifically
    for openai.RateLimitError that survives past the SDK's own retries —
    not a duplicate of the SDK's retry logic.
    """

    def __init__(self, api_key: str, sdk_max_retries: int = 2) -> None:
        self._client = openai.OpenAI(api_key=api_key, max_retries=sdk_max_retries)

    @retry(
        retry=retry_if_exception_type(openai.RateLimitError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def embed(self, texts: list[str], model_id: str) -> list[Vector]:
        response = self._client.embeddings.create(input=texts, model=model_id)
        return [item.embedding for item in response.data]
