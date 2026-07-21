import re

from core.interfaces import Guardrail
from core.models import GuardrailResult

# Per-domain forbidden-phrase policies — config-driven per domain, not
# scattered hardcoded checks through the pipeline. Healthcare's "no medical
# advice beyond source documents" instruction (Section 4 Phase 4 task text)
# is enforced here as a pattern check on the OUTPUT, defense-in-depth beyond
# the prompt instruction itself. New domains/patterns extend this dict, not
# the class.
DOMAIN_POLICIES: dict[str, list[re.Pattern[str]]] = {
    "healthcare": [
        re.compile(r"\byou should take\b", re.IGNORECASE),
        re.compile(
            r"\bi recommend (this|the following) (medication|dosage|treatment)\b", re.IGNORECASE
        ),
        re.compile(r"\bdiagnos(e|is)\b", re.IGNORECASE),
    ],
}


class OutputPolicyGuardrail(Guardrail):
    """policy is expected in "output_policy:<domain>" form (e.g.
    "output_policy:healthcare") — the domain segment selects which pattern
    set from DOMAIN_POLICIES applies. Like PromptInjectionGuardrail, a
    violation has no sensible auto-redaction — passed=False is always a
    hard block here. Fails closed on internal errors.
    """

    def check(self, payload: str, policy: str) -> GuardrailResult:
        domain = policy.split(":", 1)[1] if ":" in policy else ""
        patterns = DOMAIN_POLICIES.get(domain, [])

        try:
            matched = any(pattern.search(payload) for pattern in patterns)
        except Exception:
            return GuardrailResult(
                passed=False, policy=policy, reason_codes=["GUARDRAIL_CHECK_FAILED"]
            )

        if matched:
            return GuardrailResult(
                passed=False, policy=policy, reason_codes=["OUTPUT_POLICY_VIOLATION"]
            )
        return GuardrailResult(passed=True, policy=policy)
