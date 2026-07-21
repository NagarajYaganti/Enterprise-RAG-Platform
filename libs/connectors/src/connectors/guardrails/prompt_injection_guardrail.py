import re

from core.interfaces import Guardrail
from core.models import GuardrailResult

# Heuristic, pattern-based prompt-injection screen — NOT an ML classifier.
# Stated limitation (Phase 4 plan §A.7/F): a production system would want a
# more sophisticated classifier. These are well-known, literal jailbreak/
# injection phrasings, not fabricated examples.
INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore (all )?(the )?previous instructions", re.IGNORECASE),
    re.compile(r"disregard (all )?(the )?(previous|prior) instructions", re.IGNORECASE),
    re.compile(r"you are now in (developer|dan) mode", re.IGNORECASE),
    re.compile(r"reveal (your|the) system prompt", re.IGNORECASE),
    re.compile(r"print (your|the) (system )?instructions", re.IGNORECASE),
    re.compile(r"pretend (you have|there are) no (restrictions|rules|limitations)", re.IGNORECASE),
]


class PromptInjectionGuardrail(Guardrail):
    """No sensible redaction exists for an injection attempt — unlike PII,
    passed=False here always means a hard block (redacted_text stays None),
    not a sanitized substitute. Fails closed: an internal error is treated
    as a block, never a silent pass.
    """

    def check(self, payload: str, policy: str = "injection") -> GuardrailResult:
        try:
            matched = any(pattern.search(payload) for pattern in INJECTION_PATTERNS)
        except Exception:
            return GuardrailResult(
                passed=False, policy=policy, reason_codes=["GUARDRAIL_CHECK_FAILED"]
            )

        if matched:
            return GuardrailResult(
                passed=False, policy=policy, reason_codes=["INJECTION_PATTERN_MATCHED"]
            )
        return GuardrailResult(passed=True, policy=policy)
