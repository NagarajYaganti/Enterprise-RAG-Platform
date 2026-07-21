from unittest.mock import MagicMock

import anthropic
import httpx
import pytest
from anthropic.types import TextBlock
from connectors.llm.anthropic_provider import AnthropicProvider


def _mock_message(text: str) -> MagicMock:
    # A real TextBlock (not a MagicMock stand-in) — the adapter narrows
    # response.content's block-type union via isinstance(TextBlock), which
    # only a genuine instance satisfies.
    text_block = TextBlock(type="text", text=text, citations=None)
    response = MagicMock()
    response.content = [text_block]
    response.usage = MagicMock(input_tokens=10, output_tokens=5)
    return response


def test_generate_returns_completion_from_response() -> None:
    provider = AnthropicProvider(api_key="fake-key")
    provider._client.messages.create = MagicMock(  # type: ignore[method-assign]
        return_value=_mock_message("hello from claude")
    )

    completion = provider.generate(
        [{"role": "user", "content": "hi"}],
        "claude-sonnet-5",
        {"tenant_id": "tenant-acme"},
    )

    assert completion.tenant_id == "tenant-acme"
    assert completion.model_id == "claude-sonnet-5"
    assert completion.text == "hello from claude"
    assert completion.usage == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }
    provider._client.messages.create.assert_called_once_with(
        model="claude-sonnet-5",
        max_tokens=AnthropicProvider.DEFAULT_MAX_TOKENS,
        messages=[{"role": "user", "content": "hi"}],
        system="",
    )


def test_generate_extracts_system_message_as_top_level_param() -> None:
    """Anthropic's real API takes `system` as a separate parameter, not a
    message with role="system" — verified against the installed SDK.
    """
    provider = AnthropicProvider(api_key="fake-key")
    provider._client.messages.create = MagicMock(  # type: ignore[method-assign]
        return_value=_mock_message("ok")
    )

    provider.generate(
        [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "hi"},
        ],
        "claude-sonnet-5",
        {"tenant_id": "tenant-acme"},
    )

    _, call_kwargs = provider._client.messages.create.call_args
    assert call_kwargs["system"] == "You are a helpful assistant."
    assert call_kwargs["messages"] == [{"role": "user", "content": "hi"}]


def test_generate_respects_custom_max_tokens() -> None:
    provider = AnthropicProvider(api_key="fake-key")
    provider._client.messages.create = MagicMock(  # type: ignore[method-assign]
        return_value=_mock_message("ok")
    )

    provider.generate(
        [{"role": "user", "content": "hi"}],
        "claude-sonnet-5",
        {"tenant_id": "tenant-acme", "max_tokens": 200},
    )

    _, call_kwargs = provider._client.messages.create.call_args
    assert call_kwargs["max_tokens"] == 200


def test_generate_raises_when_tenant_id_missing_from_params() -> None:
    provider = AnthropicProvider(api_key="fake-key")

    with pytest.raises(ValueError, match="tenant_id"):
        provider.generate([{"role": "user", "content": "hi"}], "claude-sonnet-5", {})


def test_generate_retries_on_rate_limit_then_succeeds() -> None:
    provider = AnthropicProvider(api_key="fake-key")

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    body = {"error": {"message": "rate limited"}}
    response = httpx.Response(status_code=429, request=request, json=body)
    rate_limit_error = anthropic.RateLimitError(
        message="rate limited", response=response, body=body
    )

    provider._client.messages.create = MagicMock(  # type: ignore[method-assign]
        side_effect=[rate_limit_error, _mock_message("ok")]
    )

    completion = provider.generate(
        [{"role": "user", "content": "hi"}], "claude-sonnet-5", {"tenant_id": "tenant-acme"}
    )

    assert completion.text == "ok"
    assert provider._client.messages.create.call_count == 2
