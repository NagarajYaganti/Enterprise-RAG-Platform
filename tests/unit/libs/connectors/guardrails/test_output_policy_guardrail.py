from unittest.mock import patch

from connectors.guardrails.output_policy_guardrail import OutputPolicyGuardrail


def test_check_passes_clean_healthcare_answer() -> None:
    guardrail = OutputPolicyGuardrail()

    result = guardrail.check(
        "The document states annual wellness checkups are covered in full.",
        policy="output_policy:healthcare",
    )

    assert result.passed is True
    assert result.reason_codes == []


def test_check_detects_medical_advice_in_healthcare_domain() -> None:
    guardrail = OutputPolicyGuardrail()

    result = guardrail.check(
        "You should take 200mg twice daily for this condition.",
        policy="output_policy:healthcare",
    )

    assert result.passed is False
    assert result.reason_codes == ["OUTPUT_POLICY_VIOLATION"]
    assert result.redacted_text is None  # no sensible auto-redaction for a policy violation


def test_check_detects_diagnosis_language() -> None:
    guardrail = OutputPolicyGuardrail()

    result = guardrail.check(
        "Based on your symptoms, I diagnose this as a common cold.",
        policy="output_policy:healthcare",
    )

    assert result.passed is False


def test_check_with_unknown_domain_has_no_patterns_and_passes() -> None:
    guardrail = OutputPolicyGuardrail()

    result = guardrail.check("anything at all", policy="output_policy:unknown_domain")

    assert result.passed is True


def test_check_with_no_domain_segment_passes() -> None:
    guardrail = OutputPolicyGuardrail()

    result = guardrail.check("anything at all", policy="output_policy")

    assert result.passed is True


def test_check_fails_closed_when_pattern_matching_errors() -> None:
    guardrail = OutputPolicyGuardrail()

    with patch(
        "connectors.guardrails.output_policy_guardrail.DOMAIN_POLICIES",
        {"healthcare": [_ExplodingPattern()]},
    ):
        result = guardrail.check("anything", policy="output_policy:healthcare")

    assert result.passed is False
    assert result.reason_codes == ["GUARDRAIL_CHECK_FAILED"]


class _ExplodingPattern:
    def search(self, text: str) -> None:
        raise RuntimeError("boom")
