from typing import Any

from core.policy_engine import evaluate_policy

# Matches config/policies/parser.yaml's own fallback -- kept here too so
# evaluate_policy still degrades gracefully (per the Adaptive Policy
# Pattern's "never fail the request") even if that file is ever missing.
# route="unsupported" means the same thing ParserRegistry.for_mime_type's
# UnsupportedMimeTypeError used to mean, but resolved gracefully via the
# policy engine instead of an exception the caller must catch.
FALLBACK_OUTCOME = {"route": "unsupported"}


def decide_parser_route(
    mime_type: str, directory: str | None = None, tenant_id: str | None = None
) -> dict[str, Any]:
    """Routes among the parsers that already exist (ParserRegistry). Does
    NOT add cloud-OCR-fallback-gated-by-residency (an explicit scope
    boundary, docs/RETROFIT-AUDIT.md's Phase 1 retrofit plan): no cloud OCR
    adapter exists in this codebase at all, and building one is out of
    scope for a routing retrofit -- only local Tesseract exists today, so
    there is nothing to gate residency-wise yet.
    """
    profile = {"mime_type": mime_type}
    decision = evaluate_policy("parser", profile, FALLBACK_OUTCOME, directory, tenant_id)
    return decision.outcome
