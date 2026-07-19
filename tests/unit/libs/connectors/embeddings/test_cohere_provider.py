from unittest.mock import MagicMock

import cohere
from connectors.embeddings.cohere_provider import CohereEmbeddingProvider


def test_embed_returns_vectors_from_response() -> None:
    provider = CohereEmbeddingProvider(api_key="fake-key")

    mock_response = MagicMock()
    mock_response.embeddings.float_ = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    provider._client.embed = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    result = provider.embed(["hello", "world"], "embed-v4.0")

    assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    provider._client.embed.assert_called_once_with(
        model="embed-v4.0",
        texts=["hello", "world"],
        input_type="search_document",
        embedding_types=["float"],
    )


def test_embed_retries_on_rate_limit_then_succeeds() -> None:
    provider = CohereEmbeddingProvider(api_key="fake-key")

    mock_response = MagicMock()
    mock_response.embeddings.float_ = [[0.1, 0.2, 0.3]]

    rate_limit_error = cohere.TooManyRequestsError(body={"message": "rate limited"})

    provider._client.embed = MagicMock(  # type: ignore[method-assign]
        side_effect=[rate_limit_error, mock_response]
    )

    result = provider.embed(["hello"], "embed-v4.0")

    assert result == [[0.1, 0.2, 0.3]]
    assert provider._client.embed.call_count == 2
