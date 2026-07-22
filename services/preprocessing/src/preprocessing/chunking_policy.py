from typing import Any

from core.policy_engine import evaluate_policy

from preprocessing.tokenization import count_tokens

# Matches config/policies/chunking.yaml's own fallback -- kept here too so
# evaluate_policy still degrades gracefully (per the Adaptive Policy
# Pattern's "never fail the request") even if that file is ever missing.
FALLBACK_OUTCOME = {"strategy": "fixed_size", "chunk_size": 500, "overlap_pct": 0.15}


def compute_chunking_profile(
    mime_type: str,
    raw_text: str,
    structural_elements: list[dict[str, Any]],
) -> dict[str, Any]:
    """heading_density = structural elements per 1k tokens (Section 4 Phase
    1's own phrasing) -- a rough proxy for how densely structured a
    document is: many elements packed into a short document (headings,
    tables, etc.) score high; a long, largely unstructured document scores
    low. has_table/is_ocr are stated False, not silently omitted: no
    table-detection or OCR-confidence signal exists yet in this codebase
    (real OCR confidence would need TesseractOCRParser to surface it,
    which it doesn't today) -- a later phase's retrofit can wire these in
    without changing this profile's shape.
    """
    doc_length_tokens = count_tokens(raw_text)
    heading_density = (
        (len(structural_elements) / doc_length_tokens) * 1000 if doc_length_tokens else 0.0
    )
    return {
        "mime_type": mime_type,
        "heading_density": heading_density,
        "has_table": False,
        "is_ocr": False,
        "doc_length_tokens": doc_length_tokens,
    }


def decide_chunking_strategy(
    mime_type: str,
    raw_text: str,
    structural_elements: list[dict[str, Any]],
    directory: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    profile = compute_chunking_profile(mime_type, raw_text, structural_elements)
    decision = evaluate_policy("chunking", profile, FALLBACK_OUTCOME, directory, tenant_id)
    return decision.outcome
