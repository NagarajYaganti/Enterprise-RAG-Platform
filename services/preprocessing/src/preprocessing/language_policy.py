from typing import Any

from core.policy_engine import evaluate_policy

# Matches config/policies/language.yaml's own fallback -- kept here too so
# evaluate_policy still degrades gracefully (per the Adaptive Policy
# Pattern's "never fail the request") even if that file is ever missing.
FALLBACK_OUTCOME = {
    "action": "translate_then_embed",
    "target_language": "en",
    "analyzer": "standard",
}


def compute_language_profile(
    detected_language: str, native_languages: tuple[str, ...] = ("en",)
) -> dict[str, Any]:
    """`native_languages` defaults to ("en",), matching the current default
    embedding model's registered languages (config/models.yaml:
    BAAI/bge-small-en-v1.5 -> languages: ["en"]) -- a sensible default for
    an already-overridable argument, not a hardcoded strategy: the actual
    ACTION decision (embed_natively vs. translate_then_embed + target)
    still lives in config/policies/language.yaml, not in this function.
    """
    return {
        "detected_language": detected_language,
        "supported_natively": detected_language in native_languages,
    }


def decide_language_action(
    detected_language: str,
    native_languages: tuple[str, ...] = ("en",),
    directory: str | None = None,
) -> dict[str, Any]:
    profile = compute_language_profile(detected_language, native_languages)
    decision = evaluate_policy("language", profile, FALLBACK_OUTCOME, directory)
    return decision.outcome
