from unittest.mock import MagicMock

import pytest
from connectors.guardrails.presidio_guardrail import PresidioGuardrail


@pytest.fixture(scope="module")
def guardrail() -> PresidioGuardrail:
    # Real Presidio + real en_core_web_sm — loading a spaCy pipeline is
    # expensive, so this is module-scoped like every other real-model
    # fixture in this project (e.g. SentenceTransformersProvider).
    return PresidioGuardrail()


def test_check_passes_clean_text(guardrail: PresidioGuardrail) -> None:
    # Verified empirically against the real analyzer: phrases like "five
    # business days" trigger Presidio's DATE_TIME recognizer (a real,
    # broad-by-design detector, not a bug) — this text has no temporal or
    # identifying language at all, confirmed clean via a real run first.
    result = guardrail.check("Please review the attached document before continuing.")

    assert result.passed is True
    assert result.reason_codes == []
    assert result.redacted_text is None


def test_check_detects_and_redacts_real_pii(guardrail: PresidioGuardrail) -> None:
    result = guardrail.check("Please contact John Smith at john.smith@example.com about this.")

    assert result.passed is False
    assert "PII_DETECTED" in result.reason_codes
    assert result.redacted_text is not None
    assert "john.smith@example.com" not in result.redacted_text


def test_check_uses_default_policy_name(guardrail: PresidioGuardrail) -> None:
    result = guardrail.check("hello world")
    assert result.policy == "pii"


def test_check_accepts_explicit_policy_name(guardrail: PresidioGuardrail) -> None:
    result = guardrail.check("hello world", policy="pii:custom")
    assert result.policy == "pii:custom"


def test_check_fails_closed_when_analyzer_errors() -> None:
    guardrail = PresidioGuardrail()
    guardrail._analyzer.analyze = MagicMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]

    result = guardrail.check("anything")

    assert result.passed is False
    assert result.reason_codes == ["GUARDRAIL_CHECK_FAILED"]
    assert result.redacted_text is None
