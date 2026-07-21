from typing import Any

import openai
from core.interfaces import LLMProvider
from core.models import Completion
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class OpenAIChatProvider(LLMProvider):
    """LLMProvider adapter for OpenAI, gated behind an API key.

    Two-layer retry, same rationale as OpenAIEmbeddingProvider: the SDK
    retries transient errors internally; the outer tenacity retry is a
    separate app-level budget for openai.RateLimitError specifically.

    The fixed LLMProvider ABC's generate(messages, model_id, params)
    signature has no tenant_id slot, but Completion requires one (every
    record in this codebase carries tenant_id from day one) — params must
    include "tenant_id" or this raises, rather than silently defaulting to
    an empty string.

    Phase-4 addition: base_url (optional). vLLM and Ollama both expose an
    OpenAI-compatible /v1/chat/completions route, so the self-hosted/OSS
    path from Section 4 Phase 4's task text is this same class pointed at a
    different base_url, not a new adapter — the wire protocol is identical.
    No local model server is run in this sandbox (real disk-pressure risk,
    documented in Phase 4's plan) — this is proven via a mocked HTTP
    response, same as every other provider this session.
    """

    def __init__(
        self, api_key: str, sdk_max_retries: int = 2, base_url: str | None = None
    ) -> None:
        self._client = openai.OpenAI(
            api_key=api_key, max_retries=sdk_max_retries, base_url=base_url
        )

    @retry(
        retry=retry_if_exception_type(openai.RateLimitError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def generate(
        self, messages: list[dict[str, str]], model_id: str, params: dict[str, Any]
    ) -> Completion:
        if "tenant_id" not in params:
            raise ValueError("params must include tenant_id")

        response = self._client.chat.completions.create(
            messages=messages,  # type: ignore[arg-type]
            model=model_id,
            temperature=params.get("temperature", 0.0),
        )
        text = response.choices[0].message.content or ""
        usage = (
            {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
            if response.usage is not None
            else {}
        )
        return Completion(
            tenant_id=params["tenant_id"],
            model_id=model_id,
            text=text,
            usage=usage,
        )
