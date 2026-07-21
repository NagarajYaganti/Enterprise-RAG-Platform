import logging

import pytest
from core.model_registry import ModelNotFoundError
from orchestrator.model_router import ConfigModelRouter


def test_selects_cheapest_generation_model_for_simple_complexity() -> None:
    router = ConfigModelRouter()
    model_id = router.select(task="generation", language="en", complexity="simple", budget=0.01)
    assert model_id == "gpt-5.6-luna"


def test_selects_most_capable_within_budget_for_complex_complexity() -> None:
    router = ConfigModelRouter()
    model_id = router.select(task="generation", language="en", complexity="complex", budget=0.01)
    assert model_id == "claude-sonnet-5"


def test_budget_excludes_models_over_the_ceiling() -> None:
    router = ConfigModelRouter()
    model_id = router.select(task="generation", language="en", complexity="complex", budget=0.002)
    assert model_id == "gpt-5.6-luna"


def test_no_model_fits_budget_raises_model_not_found_error() -> None:
    router = ConfigModelRouter()
    with pytest.raises(ModelNotFoundError):
        router.select(task="generation", language="en", complexity="simple", budget=0.0005)


def test_multilingual_entries_match_any_requested_language() -> None:
    router = ConfigModelRouter()
    model_id = router.select(task="generation", language="fr", complexity="simple", budget=0.01)
    assert model_id == "gpt-5.6-luna"


def test_unverified_null_cost_entries_are_excluded_not_treated_as_free() -> None:
    router = ConfigModelRouter()
    model_id = router.select(task="rerank", language="en", complexity="simple", budget=0.01)
    assert model_id == "cross-encoder/ms-marco-MiniLM-L6-v2"


def test_unknown_task_raises_model_not_found_error() -> None:
    router = ConfigModelRouter()
    with pytest.raises(ModelNotFoundError):
        router.select(task="ocr", language="en", complexity="simple", budget=0.01)


def test_select_emits_structured_routing_decision_log() -> None:
    # The router's logger binds its handler to sys.stderr at import time
    # (before pytest's per-test capsys swap ever runs), so capsys can't see
    # it — attach a record-capturing handler directly instead, same as
    # caplog does internally but scoped to this non-propagating logger
    # (get_json_logger sets propagate=False).
    target_logger = logging.getLogger("orchestrator.model_router")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[assignment]
    target_logger.addHandler(handler)
    try:
        router = ConfigModelRouter()
        router.select(task="generation", language="en", complexity="simple", budget=0.01)
    finally:
        target_logger.removeHandler(handler)

    assert len(records) == 1
    record = records[0]
    assert record.getMessage() == "model_router.select"
    assert record.model_id == "gpt-5.6-luna"  # type: ignore[attr-defined]
    assert record.task == "generation"  # type: ignore[attr-defined]
    assert record.language == "en"  # type: ignore[attr-defined]
    assert record.complexity == "simple"  # type: ignore[attr-defined]
    assert record.budget == 0.01  # type: ignore[attr-defined]
    assert "claude-sonnet-5" in record.candidates_considered  # type: ignore[attr-defined]
