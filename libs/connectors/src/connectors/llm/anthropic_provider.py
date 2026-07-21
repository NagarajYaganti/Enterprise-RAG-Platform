from typing import Any

import anthropic
from core.interfaces import LLMProvider
from core.models import Completion
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class AnthropicProvider(LLMProvider):
    """LLMProvider adapter for Anthropic, gated behind an API key.

    Two-layer retry, same pattern as OpenAIChatProvider: the SDK retries
    transient errors internally; the outer tenacity retry is a separate
    app-level budget for anthropic.RateLimitError specifically.

    Real signature differences from OpenAI (verified against the installed
    SDK, not assumed): max_tokens is REQUIRED (no default — defaulted here
    to a technical constant, not a business decision); system is a
    top-level parameter, not a message with role="system" — a "system"-
    role message in the incoming OpenAI-shaped `messages` list is pulled
    out and passed as `system` here so callers don't need a
    provider-specific message format.
    """

    DEFAULT_MAX_TOKENS = 1024

    def __init__(self, api_key: str, sdk_max_retries: int = 2) -> None:
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=sdk_max_retries)

    @retry(
        retry=retry_if_exception_type(anthropic.RateLimitError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def generate(
        self, messages: list[dict[str, str]], model_id: str, params: dict[str, Any]
    ) -> Completion:
        if "tenant_id" not in params:
            raise ValueError("params must include tenant_id")

        system_text = "\n".join(m["content"] for m in messages if m.get("role") == "system")
        conversation = [m for m in messages if m.get("role") != "system"]

        response = self._client.messages.create(
            model=model_id,
            max_tokens=params.get("max_tokens", self.DEFAULT_MAX_TOKENS),
            messages=conversation,  # type: ignore[arg-type]
            system=system_text,
        )
        text = "".join(
            block.text
            for block in response.content
            if isinstance(block, anthropic.types.TextBlock)
        )
        usage = {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        }
        return Completion(
            tenant_id=params["tenant_id"],
            model_id=model_id,
            text=text,
            usage=usage,
        )
