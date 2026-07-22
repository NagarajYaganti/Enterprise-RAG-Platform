from typing import Any

from core.interfaces import LLMProvider
from core.models import ChatTurn, RetrievalFilters
from core.policy_engine import evaluate_policy
from preprocessing.language_detect import LanguageDetector

# Cheap, fixed keyword signals (per Section 4 Phase 3's "cheap signals
# first") -- not an ML classifier. Extend only when eval-harness evidence
# justifies it, per the Adaptive Policy Pattern's own rule 5.
AGGREGATION_KEYWORDS = ("how many", "count", "total", "average", "sum")
COMPARISON_KEYWORDS = ("compare", "versus", " vs ", "difference between")

FALLBACK_OUTCOME: dict[str, Any] = {
    "intent": "factual",
    "search_mode": "hybrid",
    "candidate_pool_multiplier": 1.0,
    "decompose": False,
    "multi_hop": False,
}

_language_detector = LanguageDetector()


def compute_query_profile(
    query_text: str,
    filters: RetrievalFilters,
    chat_history: list[ChatTurn],
) -> dict[str, Any]:
    lowered = query_text.lower()
    return {
        "query_length": len(query_text.split()),
        "has_aggregation_keywords": any(kw in lowered for kw in AGGREGATION_KEYWORDS),
        "has_comparison_keywords": any(kw in lowered for kw in COMPARISON_KEYWORDS),
        "has_filters": filters != RetrievalFilters(),
        "has_history": len(chat_history) > 0,
        "detected_language": _language_detector.detect(query_text),
    }


def decide_query_strategy(
    query_text: str,
    filters: RetrievalFilters,
    chat_history: list[ChatTurn],
    directory: str | None = None,
) -> dict[str, Any]:
    profile = compute_query_profile(query_text, filters, chat_history)
    decision = evaluate_policy("query", profile, FALLBACK_OUTCOME, directory)
    return decision.outcome


def decompose_if_needed(
    query_text: str,
    action: dict[str, Any],
    llm_provider: LLMProvider | None,
    model_id: str,
    tenant_id: str,
) -> list[str]:
    """Wires the previously-unwired retrieval.query_understanding
    .decompose_query() into the real flow -- built and unit-tested in
    isolation since Phase 3's original build, never called from
    pipeline.retrieve() before this retrofit. Only invoked when
    QueryPolicy actually decided to decompose; degrades to [query_text]
    with no LLM configured, matching decompose_query's own fallback.
    """
    from retrieval.query_understanding import decompose_query

    if not action.get("decompose", False):
        return [query_text]
    return decompose_query(query_text, llm_provider, model_id, tenant_id)
