from typing import Any

from core.policy_engine import evaluate_policy

# Today's real default: always rerank when a reranker is configured
# (pipeline.retrieve() handles "no reranker configured" separately, before
# ever consulting this policy).
FALLBACK_OUTCOME: dict[str, Any] = {"action": "rerank"}


def compute_rerank_profile(fused_scores: list[float]) -> dict[str, Any]:
    """`margin` = top1 - top2 (both already RRF-fused scores, k=60 -- a
    single rank-1 hit contributes at most 1/(60+1) ~= 0.0164 per list). With
    fewer than 2 results there's nothing to be confident RELATIVE TO, so
    margin falls back to top1 itself -- reranking a single/empty result is
    moot either way, and this keeps the comparator well-defined rather than
    raising on a short list.
    """
    top1 = fused_scores[0] if fused_scores else 0.0
    top2 = fused_scores[1] if len(fused_scores) > 1 else 0.0
    margin = top1 - top2 if len(fused_scores) > 1 else top1
    return {"top1_score": top1, "margin": margin}


def decide_rerank_action(
    profile: dict[str, Any], directory: str | None = None, tenant_id: str | None = None
) -> dict[str, Any]:
    decision = evaluate_policy("rerank", profile, FALLBACK_OUTCOME, directory, tenant_id)
    return decision.outcome
