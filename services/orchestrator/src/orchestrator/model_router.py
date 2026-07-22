from typing import Any

from core.interfaces import ModelRouter
from core.model_registry import ModelNotFoundError, get_default_llm_model, get_llm_models_for_task
from core.policy_engine import evaluate_policy
from observability.logging import get_json_logger

logger = get_json_logger(__name__)

# Today's real default: "simple" (and any other complexity value) prefers
# the cheapest fit within budget -- matches config/policies/model_router
# .yaml's own fallback, kept here too so evaluate_policy still degrades
# gracefully if that file is ever missing.
_SORT_FALLBACK = {"sort": "cost_asc"}


def _language_matches(entry: dict[str, Any], language: str) -> bool:
    languages = entry.get("languages", [])
    return language in languages or "multilingual" in languages


def _within_budget(entry: dict[str, Any], budget: float) -> bool:
    cost = entry.get("cost_per_1k_tokens")
    if cost is None:
        # Unverified/ASSUMPTION-marked cost (e.g. rerank-v3.5's null in
        # config/models.yaml) — never silently treat an unknown cost as
        # "free" or "within budget". Excluded, not included by default.
        return False
    return bool(cost <= budget)


class ConfigModelRouter(ModelRouter):
    """Rules engine over config/models.yaml (Section 4 Phase 4 task text) —
    no model id is ever hardcoded here; every candidate comes from
    get_llm_models_for_task(). budget is a cost_per_1k_tokens ceiling (Plan
    v2 §A.7), directly comparable to the registry field — not an absolute
    per-request dollar amount, which isn't knowable before generation.

    Phase-4 retrofit: candidate filtering (language match + budget
    ceiling) stays real Python operating on the dynamic, config-sourced
    candidate list — filtering an arbitrary-length list doesn't fit
    core.policy_engine's profile-to-fixed-outcome shape, stated explicitly
    rather than silently left alone. The one genuine STRATEGY choice this
    class makes (which direction to sort by cost) now comes from
    config/policies/model_router.yaml via evaluate_policy, logged like
    every other named policy. When nothing fits, falls back to the real
    configured default model (get_default_llm_model()) instead of raising
    — the Adaptive Policy Pattern's "never fail the request over strategy
    selection," and the exact violation docs/RETROFIT-AUDIT.md named.

    That fallback is only safe for task="generation": get_default_llm_model
    is itself hardcoded to look up a generation-task entry (there is no
    generic "default model for any task" resolver), so falling back to it
    for e.g. task="rerank"/"ocr" would silently return a generation
    model_id mislabeled as a reranker/OCR choice — a worse bug than
    raising. Every other task still raises ModelNotFoundError when nothing
    fits, a real, stated scope boundary rather than a silent gap.
    """

    def __init__(self, path: str | None = None) -> None:
        self._path = path

    def select(self, task: str, language: str, complexity: str, budget: float) -> str:
        candidates = [
            entry
            for entry in get_llm_models_for_task(task, self._path)
            if _language_matches(entry, language) and _within_budget(entry, budget)
        ]

        if not candidates:
            if task != "generation":
                raise ModelNotFoundError(
                    f"no {task} model fits language={language!r}, budget<={budget} "
                    "in config/models.yaml (no safe default exists for a non-generation task)"
                )
            fallback_model = get_default_llm_model(self._path)
            logger.info(
                "model_router.select",
                extra={
                    "model_id": fallback_model["id"],
                    "task": task,
                    "language": language,
                    "complexity": complexity,
                    "budget": budget,
                    "candidates_considered": [],
                    "is_fallback": True,
                },
            )
            return str(fallback_model["id"])

        # Note: self._path (if overridden) points at a models.yaml file, a
        # different config root from evaluate_policy's own policies
        # directory (config/policies/ by default) -- never conflate the two.
        decision = evaluate_policy("model_router", {"complexity": complexity}, _SORT_FALLBACK)
        prefer_expensive = decision.outcome["sort"] == "cost_desc"
        chosen = sorted(
            candidates,
            key=lambda entry: entry["cost_per_1k_tokens"],
            reverse=prefer_expensive,
        )[0]

        logger.info(
            "model_router.select",
            extra={
                "model_id": chosen["id"],
                "task": task,
                "language": language,
                "complexity": complexity,
                "budget": budget,
                "candidates_considered": [c["id"] for c in candidates],
                "is_fallback": False,
            },
        )
        return str(chosen["id"])
