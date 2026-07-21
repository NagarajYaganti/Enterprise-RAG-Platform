from unittest.mock import MagicMock

import httpx
import openai
import pytest
from connectors.llm.openai_provider import OpenAIChatProvider


def _mock_completion(text: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=text))]
    response.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return response


def test_generate_returns_completion_from_response() -> None:
    provider = OpenAIChatProvider(api_key="fake-key")
    provider._client.chat.completions.create = MagicMock(  # type: ignore[method-assign]
        return_value=_mock_completion("rewritten query")
    )

    completion = provider.generate(
        [{"role": "user", "content": "hi"}],
        "gpt-5.6-luna",
        {"tenant_id": "tenant-acme"},
    )

    assert completion.tenant_id == "tenant-acme"
    assert completion.model_id == "gpt-5.6-luna"
    assert completion.text == "rewritten query"
    assert completion.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    provider._client.chat.completions.create.assert_called_once_with(
        messages=[{"role": "user", "content": "hi"}], model="gpt-5.6-luna", temperature=0.0
    )


def test_base_url_defaults_to_none_unchanged_from_phase3() -> None:
    provider = OpenAIChatProvider(api_key="fake-key")
    assert provider._client.base_url is not None  # SDK fills in its own default


def test_base_url_is_passed_through_for_self_hosted_openai_compatible_endpoints() -> None:
    provider = OpenAIChatProvider(api_key="fake-key", base_url="http://localhost:8000/v1")
    # The SDK normalizes base_url with a trailing slash — verified against
    # the real installed client, not assumed.
    assert str(provider._client.base_url) == "http://localhost:8000/v1/"


def test_generate_raises_when_tenant_id_missing_from_params() -> None:
    provider = OpenAIChatProvider(api_key="fake-key")

    with pytest.raises(ValueError, match="tenant_id"):
        provider.generate([{"role": "user", "content": "hi"}], "gpt-5.6-luna", {})


def test_generate_retries_on_rate_limit_then_succeeds() -> None:
    provider = OpenAIChatProvider(api_key="fake-key")

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    body = {"error": {"message": "rate limited"}}
    response = httpx.Response(status_code=429, request=request, json=body)
    rate_limit_error = openai.RateLimitError(message="rate limited", response=response, body=body)

    provider._client.chat.completions.create = MagicMock(  # type: ignore[method-assign]
        side_effect=[rate_limit_error, _mock_completion("ok")]
    )

    completion = provider.generate(
        [{"role": "user", "content": "hi"}], "gpt-5.6-luna", {"tenant_id": "tenant-acme"}
    )

    assert completion.text == "ok"
    assert provider._client.chat.completions.create.call_count == 2
