import logging
from pathlib import Path

from retrieval.rerank_policy import (
    FALLBACK_OUTCOME,
    compute_rerank_profile,
    decide_rerank_action,
)


def test_well_separated_scores_skip_reranking() -> None:
    profile = compute_rerank_profile([0.0328, 0.005, 0.001])
    outcome = decide_rerank_action(profile)
    assert outcome["action"] == "skip"


def test_narrow_margin_scores_still_rerank() -> None:
    profile = compute_rerank_profile([0.0164, 0.0163, 0.010])
    outcome = decide_rerank_action(profile)
    assert outcome["action"] == "rerank"


def test_single_result_has_no_relative_margin_but_does_not_crash() -> None:
    profile = compute_rerank_profile([0.02])
    outcome = decide_rerank_action(profile)
    assert outcome["action"] in ("skip", "rerank")


def test_empty_results_fall_back_to_rerank_default() -> None:
    profile = compute_rerank_profile([])
    outcome = decide_rerank_action(profile)
    assert outcome["action"] == "rerank"


def test_missing_policy_file_falls_back_safely(tmp_path: Path) -> None:
    profile = compute_rerank_profile([0.02, 0.001])
    outcome = decide_rerank_action(profile, directory=str(tmp_path))
    assert outcome == FALLBACK_OUTCOME


def test_a_real_tenant_id_reaches_the_policy_decision_log() -> None:
    target_logger = logging.getLogger("core.policy_engine")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[assignment]
    target_logger.addHandler(handler)
    try:
        profile = compute_rerank_profile([0.02, 0.001])
        decide_rerank_action(profile, tenant_id="tenant-acme")
    finally:
        target_logger.removeHandler(handler)

    decision_records = [r for r in records if r.getMessage() == "policy_engine.decision"]
    assert decision_records[-1].tenant_id == "tenant-acme"  # type: ignore[attr-defined]
