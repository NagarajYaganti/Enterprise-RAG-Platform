from pathlib import Path

from core.models import Chunk, ScoredChunk
from orchestrator.context_policy import (
    build_context_block,
    compute_context_profile,
    decide_context_strategy,
)

TENANT_ID = "tenant-a"


def _chunk(chunk_id: str, text: str) -> Chunk:
    return Chunk(
        id=chunk_id,
        tenant_id=TENANT_ID,
        document_id=f"doc-{chunk_id}",
        text=text,
        position=0,
        language="en",
        version=1,
    )


def _scored(chunk_id: str, text: str, score: float) -> ScoredChunk:
    return ScoredChunk(chunk=_chunk(chunk_id, text), score=score)


def test_compute_context_profile_resolves_real_context_window_from_config() -> None:
    profile = compute_context_profile("claude-haiku-4-5", [])
    assert profile["model_context_window"] == 200000
    assert profile["chunk_count"] == 0
    assert profile["total_chunk_tokens"] == 0


def test_decide_context_strategy_computes_a_real_token_budget_for_a_known_model() -> None:
    outcome = decide_context_strategy("claude-haiku-4-5", [])

    assert outcome["dedupe"] is True
    assert outcome["token_budget"] == 100000  # 200_000 * 0.5


def test_decide_context_strategy_falls_back_when_context_window_is_unknown() -> None:
    # BAAI/bge-small-en-v1.5 is an embedding model with context_window: null
    # in config/models.yaml — a real, disclosed "unknown window" case, not
    # a fabricated one.
    outcome = decide_context_strategy("BAAI/bge-small-en-v1.5", [])

    assert outcome == {"dedupe": True, "token_budget": None}


def test_decide_context_strategy_falls_back_when_the_policy_file_is_missing(
    tmp_path: Path,
) -> None:
    outcome = decide_context_strategy("claude-haiku-4-5", [], directory=str(tmp_path))

    assert outcome == {"dedupe": True, "token_budget": None}


def test_build_context_block_dedupes_exact_duplicate_chunk_text() -> None:
    chunks = [
        _scored("c1", "Refunds are processed within 30 days.", 0.9),
        _scored("c2", "Refunds are processed within 30 days.", 0.5),  # exact duplicate text
        _scored("c3", "Exchanges take 14 days.", 0.8),
    ]

    result = build_context_block(chunks, {"dedupe": True, "token_budget": None})

    assert "[c1]" in result
    assert "[c2]" not in result  # duplicate dropped, first occurrence kept
    assert "[c3]" in result


def test_build_context_block_keeps_duplicates_when_dedupe_is_off() -> None:
    chunks = [
        _scored("c1", "Refunds are processed within 30 days.", 0.9),
        _scored("c2", "Refunds are processed within 30 days.", 0.5),
    ]

    result = build_context_block(chunks, {"dedupe": False, "token_budget": None})

    assert "[c1]" in result
    assert "[c2]" in result


def test_build_context_block_truncates_lowest_scored_chunks_over_budget() -> None:
    chunks = [
        _scored("high", "alpha beta gamma delta epsilon", 0.9),  # highest score, kept
        _scored("low", "zeta eta theta iota kappa", 0.1),  # lowest score, truncated
    ]
    # A budget that fits exactly one ~5-word chunk's worth of tokens but not two.
    from preprocessing.tokenization import count_tokens

    budget = count_tokens("alpha beta gamma delta epsilon")

    result = build_context_block(chunks, {"dedupe": True, "token_budget": budget})

    assert "[high]" in result
    assert "[low]" not in result


def test_build_context_block_includes_everything_when_budget_is_none() -> None:
    chunks = [_scored(f"c{i}", f"chunk number {i}", 1.0 - i * 0.01) for i in range(20)]

    result = build_context_block(chunks, {"dedupe": True, "token_budget": None})

    for i in range(20):
        assert f"[c{i}]" in result
