from core.interfaces import Guardrail
from core.models import GuardrailResult
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine


class PresidioGuardrail(Guardrail):
    """Guardrail adapter for PII detection/redaction via Microsoft Presidio.

    Configured to reuse en_core_web_sm (already pinned for GraphRAG in
    Phase 3) rather than Presidio's default en_core_web_lg (400MB) —
    verified empirically during Phase 4 planning that AnalyzerEngine()'s
    default nlp_engine_name/model config downloads en_core_web_lg unless
    overridden via NlpEngineProvider like this.

    Semantics: passed=False + redacted_text populated means "PII was
    found, but a sanitized substitute is available" — callers should use
    redacted_text and continue, not hard-block. This differs from
    PromptInjectionGuardrail/OutputPolicyGuardrail, where passed=False has
    no sensible redaction and means a hard block. Fails closed: any
    internal error is GUARDRAIL_CHECK_FAILED, never a silent pass.
    """

    def __init__(
        self, model_id: str = "en_core_web_sm", language: str = "en", score_threshold: float = 0.5
    ) -> None:
        nlp_configuration = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": language, "model_name": model_id}],
        }
        engine = NlpEngineProvider(nlp_configuration=nlp_configuration).create_engine()
        self._analyzer = AnalyzerEngine(nlp_engine=engine, supported_languages=[language])
        self._anonymizer = AnonymizerEngine()  # type: ignore[no-untyped-call]
        self._language = language
        self._score_threshold = score_threshold

    def check(self, payload: str, policy: str = "pii") -> GuardrailResult:
        try:
            results = self._analyzer.analyze(
                text=payload, language=self._language, score_threshold=self._score_threshold
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
