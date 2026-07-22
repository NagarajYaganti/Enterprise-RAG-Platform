from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from observability.logging import get_json_logger
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.models import PolicyDecision

logger = get_json_logger(__name__)


class PolicyEngineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    policies_config_dir: str = "config/policies"


# Deliberately minimal: AND-within-rule, first-match-wins, no cross-rule OR
# and no priority field. Covers every signal named across Section 4's policy
# descriptions (mime type, heading density, OCR confidence, language, query
# length, score margin, intent, ...) without building a speculative
# general-purpose rule language. Extend this set only when a concrete
# phase's retrofit proves it's needed, per docs/RETROFIT-AUDIT.md's plan.
_COMPARATORS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": lambda actual, expected: bool(actual == expected),
    "ne": lambda actual, expected: bool(actual != expected),
    "in": lambda actual, expected: actual in expected,
    "not_in": lambda actual, expected: actual not in expected,
    "gte": lambda actual, expected: actual is not None and actual >= expected,
    "lte": lambda actual, expected: actual is not None and actual <= expected,
    "gt": lambda actual, expected: actual is not None and actual > expected,
    "lt": lambda actual, expected: actual is not None and actual < expected,
}


def load_policy_rules(policy_name: str, directory: str | None = None) -> dict[str, Any] | None:
    """Returns the parsed YAML for config/policies/<policy_name>.yaml, or
    None if the file doesn't exist yet — a legitimate, expected state (not
    every policy has authored rules yet), never an error by itself.
    """
    settings = PolicyEngineSettings()
    resolved_dir = Path(directory or settings.policies_config_dir)
    rules_path = resolved_dir / f"{policy_name}.yaml"
    if not rules_path.exists():
        return None
    content = yaml.safe_load(rules_path.read_text())
    return content if isinstance(content, dict) else None


def _rule_matches(profile: dict[str, Any], when: dict[str, Any]) -> bool:
    """A rule with no `when` conditions matches unconditionally (a valid,
    intentional catch-all rule shape, not a bug) — every named condition
    must hold (AND) for the rule to match. A signal absent from the profile
    resolves to None, which every comparator here treats as non-matching
    rather than raising, per "fall back on ambiguity."
    """
    for signal_name, condition in when.items():
        signal_value = profile.get(signal_name)
        if not all(
            _COMPARATORS[comparator](signal_value, expected)
            for comparator, expected in condition.items()
        ):
            return False
    return True


def evaluate_policy(
    policy_name: str,
    profile: dict[str, Any],
    fallback: dict[str, Any],
    directory: str | None = None,
    tenant_id: str | None = None,
) -> PolicyDecision:
    """profile -> first matching rule (file order) from
    config/policies/<policy_name>.yaml -> PolicyDecision. A missing rules
    file, malformed YAML, or a malformed rule (bad comparator name, a rule
    missing "name"/"then") all safely resolve to `fallback` rather than
    raising — the Adaptive Policy Pattern's "never fail the request over
    strategy selection" rule (docs/ARCHITECTURE.md). Every call, matched or
    fallback, is logged for auditability.

    `tenant_id` is optional and purely for log correlation — it's surfaced
    as its own top-level `extra` key (which `observability.logging
    .JSONFormatter` already reads on every log line) rather than folded
    into `profile`, since not every caller has a real tenant_id available
    (e.g. eval/tuning tooling) and `profile` is also used for rule matching,
    which tenant_id here is not.
    """
    matched_rule: str | None = None
    outcome = fallback
    is_fallback = True

    try:
        content = load_policy_rules(policy_name, directory)
        if content is not None:
            for rule in content.get("rules", []):
                if _rule_matches(profile, rule.get("when", {})):
                    matched_rule = rule["name"]
                    outcome = rule["then"]
                    is_fallback = False
                    break
    except Exception:
        logger.exception(
            "policy_engine.rule_evaluation_error",
            extra={"policy_name": policy_name, "profile": profile, "tenant_id": tenant_id},
        )
        matched_rule = None
        outcome = fallback
        is_fallback = True

    decision = PolicyDecision(
        policy_name=policy_name,
        profile=profile,
        matched_rule=matched_rule,
        outcome=outcome,
        is_fallback=is_fallback,
    )
    logger.info(
        "policy_engine.decision",
        extra={
            "policy_name": policy_name,
            "profile": profile,
            "matched_rule": matched_rule,
            "outcome": outcome,
            "is_fallback": is_fallback,
            "tenant_id": tenant_id,
        },
    )
    return decision
