from typing import Literal

from orchestrator.settings import OrchestratorSettings


def assess_complexity(
    query_text: str,
    sub_questions: list[str],
    length_threshold: int | None = None,
) -> Literal["simple", "complex"]:
    """The stated heuristic for ModelRouter.select()'s complexity param
    (Plan v2 §A.6, resolving the fixed ABC's otherwise-undefined
    "complexity: str" contract): more than one decomposed sub-question, or
    the original query text longer than complexity_length_threshold
    characters, is "complex"; otherwise "simple". sub_questions is expected
    to come from retrieval.query_understanding.decompose_query (Phase 3) —
    this function doesn't decompose anything itself, just classifies.
    """
    threshold = (
        length_threshold
        if length_threshold is not None
        else OrchestratorSettings().complexity_length_threshold
    )
    if len(sub_questions) > 1:
        return "complex"
    if len(query_text) > threshold:
        return "complex"
    return "simple"
