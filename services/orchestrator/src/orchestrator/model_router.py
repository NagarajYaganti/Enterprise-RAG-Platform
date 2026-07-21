from typing import Any

from core.interfaces import ModelRouter
from core.model_registry import ModelNotFoundError, get_llm_models_for_task
from observability.logging import get_json_logger

logger = get_json_logger(__name__)


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
    Raises ModelNotFoundError if nothing fits — no silent fallback to a
    hardcoded id.
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
            raise ModelNotFoundError(
                f"no {task} model fits language={language!r}, budget<={budget} "
                "in config/models.yaml"
            )

        # cost_per_1k_tokens is the only capability proxy the registry
        # schema provides: "complex" prefers the most capable (highest-cost)
        # fit within budget, "simple" prefers the cheapest.
        prefer_expensive = complexity == "complex"
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
            },
        )
        return str(chosen["id"])
