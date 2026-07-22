from pathlib import Path

from connectors.guardrails.guardrail_profile import (
    FALLBACK_OUTCOME,
    compiled_patterns,
    decide_guardrail_profile,
)


def test_healthcare_domain_resolves_the_real_migrated_patterns() -> None:
    outcome = decide_guardrail_profile("tenant-acme", "healthcare")

    assert outcome["forbidden_phrase_patterns"] == [
        r"\byou should take\b",
        r"\bi recommend (this|the following) (medication|dosage|treatment)\b",
        r"\bdiagnos(e|is)\b",
    ]


def test_unknown_domain_falls_back_to_no_patterns() -> None:
    outcome = decide_guardrail_profile("tenant-acme", "unknown_domain")

    assert outcome["forbidden_phrase_patterns"] == []


def test_missing_policy_file_falls_back_safely(tmp_path: Path) -> None:
    outcome = decide_guardrail_profile("tenant-acme", "healthcare", directory=str(tmp_path))

    assert outcome == FALLBACK_OUTCOME


def test_compiled_patterns_actually_match_real_text() -> None:
    patterns = compiled_patterns("tenant-acme", "healthcare")

    assert any(p.search("You should take ibuprofen.") for p in patterns)
    assert not any(p.search("The clinic is open until 5pm.") for p in patterns)
