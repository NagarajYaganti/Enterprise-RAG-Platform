from typing import Any

from core.model_registry import get_default_embedding_model
from core.policy_engine import evaluate_policy

# The one real spreadsheet mime type this codebase's parsers already
# recognize (services/preprocessing/chunking_policy.py's own "spreadsheet"
# rule keys on the same value) -- reused here, not re-derived, so both
# policies agree on what "table" content means.
SPREADSHEET_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def compute_embedding_profile(mime_type: str, language: str) -> dict[str, Any]:
    """`domain` (the third signal Section 4 Phase 2 names: "language,
    content type, domain") has no real signal anywhere in the data model
    yet -- Document/Chunk have no domain field -- so it is honestly left
    out of this profile rather than invented, mirroring Phase 1's
    ChunkingPolicy precedent of stating has_table=False/is_ocr=False for
    signals that don't exist yet rather than silently fabricating one.
    """
    return {
        "mime_type": mime_type,
        "content_type": "table" if mime_type == SPREADSHEET_MIME_TYPE else "prose",
        "language": language,
    }


def decide_embedding_route(
    mime_type: str,
    language: str,
    directory: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Routes a chunk to an embedding model + collection/index pair.

    The fallback is built from get_default_embedding_model() at call time
    (never hardcoded) -- every document type not explicitly routed
    elsewhere by config/policies/embedding.yaml keeps exactly today's real
    default behavior (one model, one "chunks" collection/index), per the
    Adaptive Policy Pattern's "fall back to a safe default, never fail the
    request over strategy selection."
    """
    model = get_default_embedding_model()
    fallback = {
        "model_id": model["id"],
        "model_version": model["version"],
        "collection_name": "chunks",
        "index_name": "chunks",
    }
    profile = compute_embedding_profile(mime_type, language)
    decision = evaluate_policy("embedding", profile, fallback, directory, tenant_id)
    return decision.outcome
