from unittest.mock import MagicMock

import httpx
import openai
from connectors.embeddings.openai_provider import OpenAIEmbeddingProvider


def test_embed_returns_vectors_from_response(monkeypatch: object) -> None:
    provider = OpenAIEmbeddingProvider(api_key="fake-key")

    mock_response = MagicMock()
    mock_response.data = [
        MagicMock(embedding=[0.1, 0.2, 0.3]),
        MagicMock(embedding=[0.4, 0.5, 0.6]),
    ]
    provider._client.embeddings.create = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    result = provider.embed(["hello", "world"], "text-embedding-3-small")

    assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    provider._client.embeddings.create.assert_called_once_with(
        input=["hello", "world"], model="text-embedding-3-small"
    )


def test_embed_retries_on_rate_limit_then_succeeds() -> None:
    provider = OpenAIEmbeddingProvider(api_key="fake-key")

    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]

    request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    body = {"error": {"message": "rate limited"}}
    response = httpx.Response(status_code=429, request=request, json=body)
    rate_limit_error = openai.RateLimitError(message="rate limited", response=response, body=body)

    provider._client.embeddings.create = MagicMock(  # type: ignore[method-assign]
        side_effect=[rate_limit_error, mock_response]
    )

    result = provider.embed(["hello"], "text-embedding-3-small")

    assert result == [[0.1, 0.2, 0.3]]
    assert provider._client.embeddings.create.call_count == 2
