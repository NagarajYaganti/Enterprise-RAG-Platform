import logging
from datetime import datetime, timezone
from pathlib import Path

from core.models import ChatTurn, RetrievalFilters
from retrieval.query_policy import FALLBACK_OUTCOME, decide_query_strategy, decompose_if_needed


def _chat_turn(text: str) -> ChatTurn:
    return ChatTurn(
        id="turn-1",
        tenant_id="tenant-acme",
        user_id="user-1",
        session_id="session-1",
        role="user",
        text=text,
        created_at=datetime.now(timezone.utc),
    )


def test_aggregation_keyword_routes_to_bm25_only() -> None:
    outcome = decide_query_strategy(
        "how many policies were updated this quarter", RetrievalFilters(), []
    )
    assert outcome["intent"] == "aggregation"
    assert outcome["search_mode"] == "bm25_only"


def test_comparison_keyword_triggers_decompose() -> None:
    outcome = decide_query_strategy(
        "compare the lending policy and the compliance policy", RetrievalFilters(), []
    )
    assert outcome["intent"] == "comparison"
    assert outcome["decompose"] is True


def test_short_query_with_history_triggers_multi_hop() -> None:
    history = [_chat_turn("Tell me about Acme Bank.")]
    outcome = decide_query_strategy("what about it", RetrievalFilters(), history)
    assert outcome["intent"] == "follow_up"
    assert outcome["multi_hop"] is True


def test_plain_factual_query_falls_back_to_todays_default() -> None:
    outcome = decide_query_strategy(
        "what is the minimum credit score for a mortgage", RetrievalFilters(), []
    )
    assert outcome["intent"] == "factual"
    assert outcome["search_mode"] == "hybrid"
    assert outcome["decompose"] is False
    assert outcome["multi_hop"] is False


def test_missing_policy_file_falls_back_safely(tmp_path: Path) -> None:
    outcome = decide_query_strategy(
        "how many loans", RetrievalFilters(), [], directory=str(tmp_path)
    )
    assert outcome == FALLBACK_OUTCOME


def test_decompose_if_needed_returns_single_item_when_policy_says_no() -> None:
    result = decompose_if_needed(
        "what is the deadline", {"decompose": False}, None, "gpt-5.6-luna", "tenant-acme"
    )
    assert result == ["what is the deadline"]


def test_decompose_if_needed_falls_back_without_llm_even_when_policy_says_yes() -> None:
    result = decompose_if_needed(
        "compare a and b", {"decompose": True}, None, "gpt-5.6-luna", "tenant-acme"
    )
    assert result == ["compare a and b"]


def test_a_real_tenant_id_reaches_the_policy_decision_log() -> None:
    target_logger = logging.getLogger("core.policy_engine")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[assignment]
    target_logger.addHandler(handler)
    try:
        decide_query_strategy(
            "what is the refund window", RetrievalFilters(), [], tenant_id="tenant-acme"
        )
    finally:
        target_logger.removeHandler(handler)

    decision_records = [r for r in records if r.getMessage() == "policy_engine.decision"]
    assert decision_records[-1].tenant_id == "tenant-acme"  # type: ignore[attr-defined]
