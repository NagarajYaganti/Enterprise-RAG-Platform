from core.interfaces import Guardrail
from core.model_registry import get_ner_models_by_language
from core.models import GuardrailResult
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine


class PresidioGuardrail(Guardrail):
    """Guardrail adapter for PII detection/redaction via Microsoft Presidio.

    Configured to reuse the small `*_core_*_sm` spaCy models (already
    pinned for GraphRAG/per-locale guardrails) rather than Presidio's
    default en_core_web_lg (400MB) — verified empirically during Phase 4
    planning that AnalyzerEngine()'s default nlp_engine_name/model config
    downloads en_core_web_lg unless overridden via NlpEngineProvider like
    this.

    Semantics: passed=False + redacted_text populated means "PII was
    found, but a sanitized substitute is available" — callers should use
    redacted_text and continue, not hard-block. This differs from
    PromptInjectionGuardrail/OutputPolicyGuardrail, where passed=False has
    no sensible redaction and means a hard block. Fails closed: any
    internal error is GUARDRAIL_CHECK_FAILED, never a silent pass.

    Phase-4 retrofit: `languages` (plural) replaces the old single
    `language`/`model_id` pair, defaulting to `["en"]` — unchanged
    behavior for every existing call site that doesn't opt in to more.
    Per-language model ids are never hardcoded here — they're resolved
    from config/models.yaml via `get_ner_models_by_language()` (same
    registry `en_core_web_sm` already came from), unless a caller passes
    `language_models` explicitly (e.g. for tests).
    `.check(payload, policy)` resolves which of the configured languages
    to analyze with from a "pii:<language>" policy-string suffix (e.g.
    "pii:es"), defaulting to "en" if absent or unrecognized — an
    unrecognized/unconfigured language silently analyzing as English
    is a real, disclosed limitation (a non-Latin-script PII string
    written in an unconfigured language won't be reliably detected),
    not a silent gap.
    """

    def __init__(
        self,
        languages: list[str] | None = None,
        score_threshold: float = 0.5,
        language_models: dict[str, str] | None = None,
    ) -> None:
        languages = languages or ["en"]
        models_by_language = language_models or get_ner_models_by_language()
        nlp_configuration = {
            "nlp_engine_name": "spacy",
            "models": [
                {"lang_code": language, "model_name": models_by_language[language]}
                for language in languages
            ],
        }
        engine = NlpEngineProvider(nlp_configuration=nlp_configuration).create_engine()
        self._analyzer = AnalyzerEngine(nlp_engine=engine, supported_languages=languages)
        self._anonymizer = AnonymizerEngine()  # type: ignore[no-untyped-call]
        self._languages = set(languages)
        self._default_language = languages[0]
        self._score_threshold = score_threshold

    def _resolve_language(self, policy: str) -> str:
        parts = policy.split(":", 1)
        requested = parts[1] if len(parts) == 2 else self._default_language
        return requested if requested in self._languages else self._default_language

    def check(self, payload: str, policy: str = "pii") -> GuardrailResult:
        language = self._resolve_language(policy)
        try:
            results = self._analyzer.analyze(
                text=payload, language=language, score_threshold=self._score_threshold
            )
        except Exception:
            return GuardrailResult(
                passed=False, policy=policy, reason_codes=["GUARDRAIL_CHECK_FAILED"]
            )

        if not results:
            return GuardrailResult(passed=True, policy=policy)

        try:
            anonymized = self._anonymizer.anonymize(
                text=payload, analyzer_results=results  # type: ignore[arg-type]
            )
        except Exception:
            return GuardrailResult(
                passed=False, policy=policy, reason_codes=["GUARDRAIL_CHECK_FAILED"]
            )

        return GuardrailResult(
            passed=False,
            policy=policy,
            reason_codes=["PII_DETECTED"],
            redacted_text=anonymized.text,
        )
