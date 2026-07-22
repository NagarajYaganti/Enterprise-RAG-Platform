from core.interfaces import Guardrail
from core.models import GuardrailResult
from pydantic import BaseModel


class GuardrailPipelineResult(BaseModel):
    passed: bool
    blocked: bool
    text: str
    results: list[GuardrailResult]


def _apply(
    result: GuardrailResult, original_text: str, results: list[GuardrailResult]
) -> GuardrailPipelineResult | None:
    """Returns a short-circuiting pipeline result if `result` didn't pass
    cleanly, else None to let the pipeline continue to the next check.
    """
    results.append(result)
    if result.passed:
        return None
    if result.redacted_text is not None:
        # PII case (core.models.GuardrailResult semantics, Plan v2 §A.8):
        # a sanitized substitute is available — continue the pipeline using
        # it, don't hard-block.
        return GuardrailPipelineResult(
            passed=False, blocked=False, text=result.redacted_text, results=results
        )
    # Injection / output-policy / internal-check-failure: no sensible
    # redaction exists, always a hard block. Fail closed.
    return GuardrailPipelineResult(passed=False, blocked=True, text=original_text, results=results)


class GuardrailPipeline:
    """Composes the three Phase-4 Guardrail adapters behind the ABC
    interface (dependency-injected, not imported concretely) so callers
    depend on core.interfaces.Guardrail, not on Presidio/regex specifics —
    tests can substitute fakes without loading spaCy.
    """

    def __init__(
        self,
        pii_guardrail: Guardrail,
        injection_guardrail: Guardrail,
        output_policy_guardrail: Guardrail,
    ) -> None:
        self._pii = pii_guardrail
        self._injection = injection_guardrail
        self._output_policy = output_policy_guardrail

    def check_input(self, text: str, language: str = "en") -> GuardrailPipelineResult:
        results: list[GuardrailResult] = []

        injection_result = self._injection.check(text, policy=f"injection:{language}")
        short_circuit = _apply(injection_result, text, results)
        if short_circuit is not None:
            return short_circuit

        pii_result = self._pii.check(text, policy=f"pii:{language}")
        short_circuit = _apply(pii_result, text, results)
        if short_circuit is not None:
            return short_circuit

        return GuardrailPipelineResult(passed=True, blocked=False, text=text, results=results)

    def check_output(
        self, text: str, domain: str, tenant_id: str, language: str = "en"
    ) -> GuardrailPipelineResult:
        results: list[GuardrailResult] = []

        policy_result = self._output_policy.check(
            text, policy=f"output_policy:{tenant_id}:{domain}"
        )
        short_circuit = _apply(policy_result, text, results)
        if short_circuit is not None:
            return short_circuit

        pii_result = self._pii.check(text, policy=f"pii:{language}")
        short_circuit = _apply(pii_result, text, results)
        if short_circuit is not None:
            return short_circuit

        return GuardrailPipelineResult(passed=True, blocked=False, text=text, results=results)
