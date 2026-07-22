from core.interfaces import Guardrail
from core.models import GuardrailResult

from connectors.guardrails.guardrail_profile import compiled_patterns


def _parse_policy(policy: str) -> tuple[str, str]:
    """policy is "output_policy:<tenant_id>:<domain>" (Phase-4 retrofit,
    GuardrailProfile) -- tolerant of the older 2-segment
    "output_policy:<domain>" form (tenant_id="") and the no-segment
    "output_policy" form (both tenant_id and domain "") so existing
    callers that don't know about tenant scoping yet still resolve to a
    real (tenant-agnostic) domain policy rather than erroring.
    """
    parts = policy.split(":")
    if len(parts) >= 3:
        return parts[1], parts[2]
    if len(parts) == 2:
        return "", parts[1]
    return "", ""


class OutputPolicyGuardrail(Guardrail):
    """policy is expected in "output_policy:<tenant_id>:<domain>" form
    (e.g. "output_policy:tenant-acme:healthcare") -- the domain (and,
    once real per-tenant policy data exists, the tenant) segment selects
    which forbidden-phrase pattern set applies, resolved via
    GuardrailProfile (config/policies/guardrail_profile.yaml) instead of
    a hardcoded DOMAIN_POLICIES dict. Like PromptInjectionGuardrail, a
    violation has no sensible auto-redaction — passed=False is always a
    hard block here. Fails closed on internal errors.
    """

    def check(self, payload: str, policy: str) -> GuardrailResult:
        tenant_id, domain = _parse_policy(policy)

        try:
            patterns = compiled_patterns(tenant_id, domain)
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
