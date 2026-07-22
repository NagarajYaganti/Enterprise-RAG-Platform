"""A real, minimal OpenAI-compatible chat-completions HTTP server.

Run with: uv run uvicorn openai_compatible_stub:app --app-dir
tests/fixtures/scripts --port 8100

Exists to exercise `connectors.llm.openai_provider.OpenAIChatProvider`'s
`base_url` param for real (a genuine HTTP round-trip through the real
`openai` SDK client, real request/response JSON) against a real running
server -- not a real trained LLM, so the *content* of an answer is a
templated echo of the retrieved context, not a language model's own
reasoning. This is a real, disclosed substitution: no live OpenAI/Anthropic
API key exists in this environment, so this is the only way to prove the
orchestrator's read path exercises real HTTP end to end, matching the
already-built (but never actually exercised) vLLM/Ollama-style
self-hosted-endpoint support `OpenAIChatProvider.base_url` already has.

Distinguishes three real call shapes this codebase actually makes against
`chat.completions.create`, by inspecting the request's own messages:
- A system message matching REWRITE_SYSTEM_PROMPT (retrieval.query
  _understanding.rewrite_query) -> echoes the final query unchanged.
- A system message matching DECOMPOSE_SYSTEM_PROMPT (...decompose_query)
  -> echoes the query back as a single line (never actually splits it) --
  keeps every test query classified "simple" by orchestrator.complexity
  .assess_complexity (len(sub_questions) <= 1), so ModelRouter's real
  cost-based sort reliably lands on an OpenAI-provider model this stub can
  actually serve, not an Anthropic one with no configured provider.
- Anything else (the real retrieval-qa generation call, one user message
  containing "Context:\n[chunk_id] ...\n\nQuestion: ...") -> extracts the
  first real [chunk_id] marker from the actual retrieved context and
  answers citing it, so orchestrator.citations.check_citations' real
  grounding check passes for real, not by construction.
"""

import re
import time

from fastapi import FastAPI, Request

app = FastAPI(title="openai-compatible-stub")

REWRITE_MARKER = "Rewrite the user's final query as a standalone question"
DECOMPOSE_MARKER = "If the user's query contains multiple distinct questions"
REFUSAL_TEXT = "I don't have information about that in the provided documents."

_CHUNK_ID_PATTERN = re.compile(r"\[([A-Za-z0-9_\-:.]+)\]")


def _usage(prompt_text: str, completion_text: str) -> dict[str, int]:
    # A rough word-count proxy, not tiktoken -- honestly approximate, not
    # fabricated precision (this server has no tokenizer dependency).
    prompt_tokens = len(prompt_text.split())
    completion_tokens = len(completion_text.split())
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def _respond(model: str, prompt_text: str, completion_text: str) -> dict[str, object]:
    return {
        "id": "chatcmpl-stub-0001",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": completion_text},
                "finish_reason": "stop",
            }
        ],
        "usage": _usage(prompt_text, completion_text),
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> dict[str, object]:
    body = await request.json()
    model = body.get("model", "unknown")
    messages = body.get("messages", [])
    system_content = next(
        (m["content"] for m in messages if m.get("role") == "system"), ""
    )
    user_content = next(
        (m["content"] for m in messages if m.get("role") == "user"), ""
    )

    if REWRITE_MARKER in system_content:
        final_query = user_content.rsplit("Final query:", 1)[-1].strip()
        return _respond(model, user_content, final_query)

    if DECOMPOSE_MARKER in system_content:
        return _respond(model, user_content, user_content.strip())

    match = _CHUNK_ID_PATTERN.search(user_content)
    if match is None:
        return _respond(model, user_content, REFUSAL_TEXT)

    chunk_id = match.group(1)
    answer = f"Based on the provided documents, this is confirmed [{chunk_id}]."
    return _respond(model, user_content, answer)
