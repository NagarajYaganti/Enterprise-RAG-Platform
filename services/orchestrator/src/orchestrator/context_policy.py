from typing import Any

from core.model_registry import get_model_entry
from core.models import ScoredChunk
from core.policy_engine import evaluate_policy
from preprocessing.tokenization import count_tokens

# Today's real, unconstrained behavior: dedupe exact-duplicate chunk text,
# but no token budget (token_budget_fraction: None) -- used whenever no
# rule matches, or the routed model has no known context_window in
# config/models.yaml.
FALLBACK_OUTCOME: dict[str, Any] = {"dedupe": True, "token_budget_fraction": None}


def compute_context_profile(model_id: str, chunks: list[ScoredChunk]) -> dict[str, Any]:
    model_entry = get_model_entry(model_id)
    return {
        "model_context_window": model_entry.get("context_window"),
        "chunk_count": len(chunks),
        "total_chunk_tokens": sum(count_tokens(sc.chunk.text) for sc in chunks),
    }


def decide_context_strategy(
    model_id: str, chunks: list[ScoredChunk], directory: str | None = None
) -> dict[str, Any]:
    """The policy engine decides the one genuine strategy choice --
    token_budget_fraction, how much of the model's real context window to
    reserve for retrieved context vs. the prompt template/expected
    completion -- not the arithmetic itself (same scope boundary already
    established for ModelRouter's sort direction: computing an actual
    token count from a dynamic profile value doesn't fit evaluate_policy's
    profile->fixed-outcome shape). When model_context_window is unknown
    (None) or no token_budget_fraction is configured, the returned
    token_budget is None -- meaning "no budget constraint," today's real
    unconstrained behavior, unchanged for any model without a verified
    context_window.
    """
    profile = compute_context_profile(model_id, chunks)
    decision = evaluate_policy("context", profile, FALLBACK_OUTCOME, directory)
    outcome = decision.outcome

    token_budget: int | None = None
    fraction = outcome.get("token_budget_fraction")
    model_context_window = profile["model_context_window"]
    if model_context_window is not None and fraction is not None:
        token_budget = int(model_context_window * fraction)

    return {"dedupe": outcome.get("dedupe", True), "token_budget": token_budget}


def build_context_block(chunks: list[ScoredChunk], strategy: dict[str, Any]) -> str:
    """Replaces the naive "\\n\\n".join(...) context assembly with a
    dedupe + (optional) token-budget-aware truncation pass. Exact-duplicate
    chunk text is dropped (first occurrence kept, original order
    preserved) whenever strategy["dedupe"] is true. When
    strategy["token_budget"] is a real int, chunks are re-ordered
    highest-scored first and kept greedily until the running token total
    would exceed the budget -- the remaining, lower-scored chunks are
    truncated entirely, matching "truncate lowest-scored chunks first."
    """
    deduped: list[ScoredChunk] = []
    seen_texts: set[str] = set()
    for scored_chunk in chunks:
        if strategy.get("dedupe", True) and scored_chunk.chunk.text in seen_texts:
            continue
        seen_texts.add(scored_chunk.chunk.text)
        deduped.append(scored_chunk)

    token_budget = strategy.get("token_budget")
    if token_budget is None:
        selected = deduped
    else:
        ordered = sorted(deduped, key=lambda scored_chunk: scored_chunk.score, reverse=True)
        selected = []
        running_total = 0
        for scored_chunk in ordered:
            tokens = count_tokens(scored_chunk.chunk.text)
            if running_total + tokens > token_budget:
                break
            selected.append(scored_chunk)
            running_total += tokens

    return "\n\n".join(f"[{sc.chunk.id}] {sc.chunk.text}" for sc in selected)
