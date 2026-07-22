from typing import Any

from core.policy_engine import evaluate_policy


def compute_cache_profile(query_intent: str) -> dict[str, Any]:
    return {"query_intent": query_intent}


def decide_cache_strategy(
    query_intent: str,
    default_similarity_threshold: float,
    directory: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """default_similarity_threshold is the caller's own
    OrchestratorSettings.cache_similarity_threshold, not a literal
    duplicated here — the fallback for any query_intent with no authored
    rule is "today's real behavior, unchanged" by construction, never a
    second hardcoded copy of that setting.
    """
    fallback: dict[str, Any] = {
        "cache_enabled": True,
        "similarity_threshold": default_similarity_threshold,
    }
    profile = compute_cache_profile(query_intent)
    decision = evaluate_policy("cache", profile, fallback, directory, tenant_id)
    return decision.outcome
