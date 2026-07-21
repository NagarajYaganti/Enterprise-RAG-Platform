import logging
from pathlib import Path

from core.policy_engine import evaluate_policy, load_policy_rules

FIXTURES_DIR = str(Path(__file__).resolve().parents[3] / "fixtures" / "policies")

FALLBACK = {"strategy": "fixed_size", "chunk_size": 500}


def _attach_capture_handler(logger_name: str) -> tuple[logging.Handler, list[logging.LogRecord]]:
    """The engine's logger binds its handler to sys.stderr at import time
    (before pytest's per-test capsys swap ever runs), so capsys can't see
    it — attach a record-capturing handler directly instead, same technique
    already proven in tests/unit/services/orchestrator/test_model_router.py.
    """
    target_logger = logging.getLogger(logger_name)
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[assignment]
    target_logger.addHandler(handler)
    return handler, records


def test_load_policy_rules_returns_none_for_missing_file() -> None:
    assert load_policy_rules("does_not_exist", FIXTURES_DIR) is None


def test_load_policy_rules_returns_parsed_dict_for_a_real_file() -> None:
    content = load_policy_rules("example_policy", FIXTURES_DIR)
    assert content is not None
    assert content["policy"] == "example"
    assert len(content["rules"]) == 5


def test_evaluate_policy_matches_eq_and_gte_rule() -> None:
    decision = evaluate_policy(
        "example_policy",
        profile={"mime_type": "text/html", "heading_density": 1.2},
        fallback=FALLBACK,
        directory=FIXTURES_DIR,
    )
    assert decision.matched_rule == "rule_eq_and_gte"
    assert decision.outcome == {"strategy": "structure_aware"}
    assert decision.is_fallback is False


def test_evaluate_policy_matches_lt_rule() -> None:
    decision = evaluate_policy(
        "example_policy",
        profile={"ocr_confidence": 0.3},
        fallback=FALLBACK,
        directory=FIXTURES_DIR,
    )
    assert decision.matched_rule == "rule_lt"
    assert decision.outcome == {"strategy": "fixed_size", "chunk_size": 500}


def test_evaluate_policy_matches_in_rule() -> None:
    decision = evaluate_policy(
        "example_policy",
        profile={"language": "es"},
        fallback=FALLBACK,
        directory=FIXTURES_DIR,
    )
    assert decision.matched_rule == "rule_in"
    assert decision.outcome == {"strategy": "multilingual_default"}


def test_evaluate_policy_matches_ne_and_not_in_rule() -> None:
    decision = evaluate_policy(
        "example_policy",
        profile={"mime_type": "application/pdf", "doc_type": "report"},
        fallback=FALLBACK,
        directory=FIXTURES_DIR,
    )
    assert decision.matched_rule == "rule_ne_and_not_in"
    assert decision.outcome == {"strategy": "general_default"}


def test_evaluate_policy_matches_lte_and_gt_rule() -> None:
    # mime_type/doc_type are set to values that fail rule_ne_and_not_in's own
    # conditions for real (not just left absent) — see
    # test_negative_comparators_vacuously_pass_when_signal_is_absent below
    # for why leaving them absent would let that earlier rule match instead.
    decision = evaluate_policy(
        "example_policy",
        profile={
            "mime_type": "application/zip",
            "doc_type": "archive",
            "doc_length": 150,
            "score_margin": 0.02,
        },
        fallback=FALLBACK,
        directory=FIXTURES_DIR,
    )
    assert decision.matched_rule == "rule_lte_and_gt"
    assert decision.outcome == {"strategy": "rerank_skip"}


def test_negative_comparators_vacuously_pass_when_signal_is_absent() -> None:
    """Documents a real, intentional (not accidental) characteristic of the
    minimal comparator set: `ne`/`not_in` compare against `None` when a
    signal is absent from the profile, and None never equals/never appears
    in a real expected value — so a rule made ONLY of negative conditions
    acts as a catch-all whenever those signals simply aren't present, not
    just when they're present-but-different. This is why
    test_evaluate_policy_matches_lte_and_gt_rule above must set mime_type/
    doc_type to values that fail for real, not merely omit them.
    """
    decision = evaluate_policy(
        "example_policy",
        profile={"doc_length": 150, "score_margin": 0.02},  # no mime_type/doc_type at all
        fallback=FALLBACK,
        directory=FIXTURES_DIR,
    )
    assert decision.matched_rule == "rule_ne_and_not_in"  # not rule_lte_and_gt


def test_evaluate_policy_falls_back_when_no_rule_matches() -> None:
    decision = evaluate_policy(
        "no_match_policy",
        profile={"anything": "irrelevant"},
        fallback=FALLBACK,
        directory=FIXTURES_DIR,
    )
    assert decision.matched_rule is None
    assert decision.is_fallback is True
    assert decision.outcome == FALLBACK


def test_evaluate_policy_falls_back_when_rules_file_is_missing() -> None:
    decision = evaluate_policy(
        "a_policy_with_no_rules_file_yet",
        profile={"anything": "irrelevant"},
        fallback=FALLBACK,
        directory=FIXTURES_DIR,
    )
    assert decision.matched_rule is None
    assert decision.is_fallback is True
    assert decision.outcome == FALLBACK


def test_evaluate_policy_falls_back_on_malformed_yaml_syntax_never_raises() -> None:
    decision = evaluate_policy(
        "malformed_syntax_policy",
        profile={"anything": "irrelevant"},
        fallback=FALLBACK,
        directory=FIXTURES_DIR,
    )
    assert decision.is_fallback is True
    assert decision.outcome == FALLBACK


def test_evaluate_policy_falls_back_on_unknown_comparator_never_raises() -> None:
    decision = evaluate_policy(
        "malformed_rule_policy",
        profile={"some_signal": 5},
        fallback=FALLBACK,
        directory=FIXTURES_DIR,
    )
    assert decision.is_fallback is True
    assert decision.outcome == FALLBACK


def test_evaluate_policy_logs_a_matched_decision() -> None:
    handler, records = _attach_capture_handler("core.policy_engine")
    try:
        evaluate_policy(
            "example_policy",
            profile={"language": "en"},
            fallback=FALLBACK,
            directory=FIXTURES_DIR,
        )
    finally:
        logging.getLogger("core.policy_engine").removeHandler(handler)

    decision_records = [r for r in records if r.getMessage() == "policy_engine.decision"]
    assert len(decision_records) == 1
    record = decision_records[0]
    assert record.policy_name == "example_policy"  # type: ignore[attr-defined]
    assert record.matched_rule == "rule_in"  # type: ignore[attr-defined]
    assert record.is_fallback is False  # type: ignore[attr-defined]


def test_evaluate_policy_logs_a_fallback_decision() -> None:
    handler, records = _attach_capture_handler("core.policy_engine")
    try:
        evaluate_policy(
            "no_match_policy",
            profile={"anything": "irrelevant"},
            fallback=FALLBACK,
            directory=FIXTURES_DIR,
        )
    finally:
        logging.getLogger("core.policy_engine").removeHandler(handler)

    decision_records = [r for r in records if r.getMessage() == "policy_engine.decision"]
    assert len(decision_records) == 1
    record = decision_records[0]
    assert record.matched_rule is None  # type: ignore[attr-defined]
    assert record.is_fallback is True  # type: ignore[attr-defined]
    assert record.outcome == FALLBACK  # type: ignore[attr-defined]
