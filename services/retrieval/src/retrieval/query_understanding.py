from core.interfaces import LLMProvider
from core.models import ChatTurn

REWRITE_SYSTEM_PROMPT = (
    "Rewrite the user's final query as a standalone question, resolving any "
    "pronouns (it/that/they/etc.) using the conversation history. Reply with "
    "only the rewritten query, nothing else."
)

DECOMPOSE_SYSTEM_PROMPT = (
    "If the user's query contains multiple distinct questions, split it into "
    "separate standalone questions, one per line. If it is already a single "
    "question, reply with just that question unchanged."
)


def rewrite_query(
    query_text: str,
    history: list[ChatTurn],
    llm_provider: LLMProvider | None,
    model_id: str,
    tenant_id: str,
) -> str:
    """Resolve pronouns ("it/that") from conversation history into a
    standalone query, per Section 4 Phase 3 task text. Falls back to the
    query unchanged when llm_provider is None (no OPENAI_API_KEY
    configured) or there's no history to resolve against — a heuristic
    pass-through, not real coreference resolution, stated explicitly per
    the Phase 3 plan's assumption.
    """
    if llm_provider is None or not history:
        return query_text

    history_text = "\n".join(f"{turn.role}: {turn.text}" for turn in history)
    messages = [
        {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Conversation history:\n{history_text}\n\nFinal query: {query_text}",
        },
    ]
    completion = llm_provider.generate(messages, model_id, {"tenant_id": tenant_id})
    rewritten = completion.text.strip()
    return rewritten if rewritten else query_text


def decompose_query(
    query_text: str,
    llm_provider: LLMProvider | None,
    model_id: str,
    tenant_id: str,
) -> list[str]:
    """Split a compound question into sub-queries. Falls back to
    [query_text] unchanged when llm_provider is None.
    """
    if llm_provider is None:
        return [query_text]

    messages = [
        {"role": "system", "content": DECOMPOSE_SYSTEM_PROMPT},
        {"role": "user", "content": query_text},
    ]
    completion = llm_provider.generate(messages, model_id, {"tenant_id": tenant_id})
    lines = [line.strip() for line in completion.text.strip().splitlines() if line.strip()]
    return lines if lines else [query_text]
