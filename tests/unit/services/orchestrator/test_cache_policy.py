from pathlib import Path

from orchestrator.cache_policy import decide_cache_strategy


def test_factual_intent_uses_a_tighter_threshold() -> None:
    outcome = decide_cache_strategy("factual", default_similarity_threshold=0.95)

    assert outcome == {"cache_enabled": True, "similarity_threshold": 0.97}


def test_comparison_intent_disables_the_cache() -> None:
    outcome = decide_cache_strategy("comparison", default_similarity_threshold=0.95)

    assert outcome["cache_enabled"] is False


def test_unmatched_intent_falls_back_to_the_callers_default_threshold() -> None:
    outcome = decide_cache_strategy("aggregation", default_similarity_threshold=0.83)

    assert outcome == {"cache_enabled": True, "similarity_threshold": 0.83}


def test_missing_policy_file_falls_back_to_the_callers_default_threshold(
    tmp_path: Path,
) -> None:
    outcome = decide_cache_strategy(
        "factual", default_similarity_threshold=0.42, directory=str(tmp_path)
    )

    assert outcome == {"cache_enabled": True, "similarity_threshold": 0.42}
