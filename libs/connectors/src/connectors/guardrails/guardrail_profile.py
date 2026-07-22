import re
from typing import Any

from core.policy_engine import evaluate_policy

# Today's real behavior for any domain with no authored rule: nothing is
# blocked (matches the old DOMAIN_POLICIES.get(domain, []) default).
FALLBACK_OUTCOME: dict[str, Any] = {"forbidden_phrase_patterns": []}

_compiled_cache: dict[tuple[str, ...], list["re.Pattern[str]"]] = {}


def compute_guardrail_profile(tenant_id: str, domain: str) -> dict[str, Any]:
    return {"tenant_id": tenant_id, "domain": domain}


def decide_guardrail_profile(
    tenant_id: str, domain: str, directory: str | None = None
) -> dict[str, Any]:
    profile = compute_guardrail_profile(tenant_id, domain)
    decision = evaluate_policy("guardrail_profile", profile, FALLBACK_OUTCOME, directory)
    return decision.outcome


def compiled_patterns(tenant_id: str, domain: str, directory: str | None = None) -> list[Any]:
    """Resolves the real forbidden-phrase regex patterns for this
    tenant/domain via GuardrailProfile, compiling raw pattern strings from
    the config outcome (YAML can't store a compiled re.Pattern object) --
    cached by the pattern tuple so repeated calls with the same outcome
    don't recompile every time.
    """
    outcome = decide_guardrail_profile(tenant_id, domain, directory)
    raw_patterns = tuple(outcome.get("forbidden_phrase_patterns", []))
    if raw_patterns not in _compiled_cache:
        _compiled_cache[raw_patterns] = [
            re.compile(pattern, re.IGNORECASE) for pattern in raw_patterns
        ]
    return _compiled_cache[raw_patterns]
