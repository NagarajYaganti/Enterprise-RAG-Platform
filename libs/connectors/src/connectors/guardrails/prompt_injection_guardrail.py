import re

from core.interfaces import Guardrail
from core.models import GuardrailResult

# Heuristic, pattern-based prompt-injection screen — NOT an ML classifier.
# Stated limitation (Phase 4 plan §A.7/F): a production system would want a
# more sophisticated classifier. These are well-known, literal jailbreak/
# injection phrasings, not fabricated examples.
INJECTION_PATTERNS_EN: list[re.Pattern[str]] = [
    re.compile(r"ignore (all )?(the )?previous instructions", re.IGNORECASE),
    re.compile(r"disregard (all )?(the )?(previous|prior) instructions", re.IGNORECASE),
    re.compile(r"you are now in (developer|dan) mode", re.IGNORECASE),
    re.compile(r"reveal (your|the) system prompt", re.IGNORECASE),
    re.compile(r"print (your|the) (system )?instructions", re.IGNORECASE),
    re.compile(r"pretend (you have|there are) no (restrictions|rules|limitations)", re.IGNORECASE),
]

# Phase-4 retrofit (per-locale guardrails): real, hand-verified Spanish/
# French/German translations of the 6 English phrasings above — not
# machine-translated filler. An unconfigured/unrecognized language falls
# back to the English set (patterns_for_language below), a disclosed
# limitation: an injection attempt phrased in that language's own wording
# won't match.
INJECTION_PATTERNS_ES: list[re.Pattern[str]] = [
    re.compile(r"ignora(r)? (todas )?(las )?instrucciones anteriores", re.IGNORECASE),
    re.compile(r"descart(a|ar) (todas )?(las )?instrucciones (anteriores|previas)", re.IGNORECASE),
    re.compile(r"ahora est[aá]s en modo (desarrollador|dan)", re.IGNORECASE),
    re.compile(r"revela (tu|el) (mensaje del sistema|prompt del sistema)", re.IGNORECASE),
    re.compile(r"imprime (tus|las) instrucciones( del sistema)?", re.IGNORECASE),
    re.compile(r"finge que no (tienes|hay) (restricciones|reglas|limitaciones)", re.IGNORECASE),
]

INJECTION_PATTERNS_FR: list[re.Pattern[str]] = [
    re.compile(r"ignore(z)? (toutes )?(les )?instructions pr[ée]c[ée]dentes", re.IGNORECASE),
    re.compile(
        r"fait(es|s)? abstraction des instructions (pr[ée]c[ée]dentes|ant[ée]rieures)",
        re.IGNORECASE,
    ),
    re.compile(r"vous [êe]tes maintenant en mode (d[ée]veloppeur|dan)", re.IGNORECASE),
    re.compile(r"r[ée]v[èe]le(z)? (votre|le) (prompt syst[èe]me|invite syst[èe]me)", re.IGNORECASE),
    re.compile(r"imprime(z)? (tes|vos|les) instructions( syst[èe]me)?", re.IGNORECASE),
    re.compile(
        r"fait(es|s)? semblant (que tu n'as|qu'il n'y a) aucune "
        r"(restriction|r[èe]gle|limitation)",
        re.IGNORECASE,
    ),
]

INJECTION_PATTERNS_DE: list[re.Pattern[str]] = [
    re.compile(r"ignorier(e|en sie) (alle )?(die )?vorherigen anweisungen", re.IGNORECASE),
    re.compile(
        r"missachte(n sie)? (alle )?(die )?(vorherigen|fr[üu]heren) anweisungen", re.IGNORECASE
    ),
    re.compile(r"du bist jetzt im (entwickler|dan)-?modus", re.IGNORECASE),
    re.compile(r"enth[üu]lle(n sie)? (deinen|den|ihren) system-?prompt", re.IGNORECASE),
    re.compile(r"gib(t| sie)? (deine|die|ihre) (system-)?anweisungen aus", re.IGNORECASE),
    re.compile(
        r"tu(n sie)? so.{0,4}als ob (du keine|es keine|sie keine) "
        r"(einschr[äa]nkungen|regeln|beschr[äa]nkungen)",
        re.IGNORECASE,
    ),
]

INJECTION_PATTERNS_BY_LANGUAGE: dict[str, list[re.Pattern[str]]] = {
    "en": INJECTION_PATTERNS_EN,
    "es": INJECTION_PATTERNS_ES,
    "fr": INJECTION_PATTERNS_FR,
    "de": INJECTION_PATTERNS_DE,
}


def patterns_for_language(language: str) -> list[re.Pattern[str]]:
    return INJECTION_PATTERNS_BY_LANGUAGE.get(language, INJECTION_PATTERNS_EN)


def _resolve_language(policy: str) -> str:
    parts = policy.split(":", 1)
    return parts[1] if len(parts) == 2 else "en"


class PromptInjectionGuardrail(Guardrail):
    """No sensible redaction exists for an injection attempt — unlike PII,
    passed=False here always means a hard block (redacted_text stays None),
    not a sanitized substitute. Fails closed: an internal error is treated
    as a block, never a silent pass.

    Phase-4 retrofit: `.check(payload, policy)` resolves which language's
    pattern set to use from a "injection:<language>" policy-string suffix
    (mirroring PresidioGuardrail's "pii:<language>" convention), defaulting
    to "en" if absent or unrecognized.
    """

    def check(self, payload: str, policy: str = "injection") -> GuardrailResult:
        language = _resolve_language(policy)
        patterns = patterns_for_language(language)
        try:
            matched = any(pattern.search(payload) for pattern in patterns)
        except Exception:
            return GuardrailResult(
                passed=False, policy=policy, reason_codes=["GUARDRAIL_CHECK_FAILED"]
            )

        if matched:
            return GuardrailResult(
                passed=False, policy=policy, reason_codes=["INJECTION_PATTERN_MATCHED"]
            )
        return GuardrailResult(passed=True, policy=policy)
