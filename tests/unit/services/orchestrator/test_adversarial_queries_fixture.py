import pytest
from connectors.guardrails.output_policy_guardrail import OutputPolicyGuardrail
from connectors.guardrails.presidio_guardrail import PresidioGuardrail
from connectors.guardrails.prompt_injection_guardrail import PromptInjectionGuardrail
from orchestrator.guardrail_pipeline import GuardrailPipeline

from tests.fixtures.adversarial_queries_loader import AdversarialQuery, load_adversarial_queries


def _by_category(category: str) -> list[AdversarialQuery]:
    return [q for q in load_adversarial_queries() if q.category == category]


def test_fixture_loads_and_ids_are_unique() -> None:
    queries = load_adversarial_queries()
    assert len(queries) >= 15
    ids = [q.id for q in queries]
    assert len(ids) == len(set(ids))


def test_every_category_has_at_least_three_entries() -> None:
    for category in (
        "prompt_injection", "pii_disclosure", "hallucination_bait", "output_policy_probe"
    ):
        assert len(_by_category(category)) >= 3, category


@pytest.fixture(scope="module")
def guardrail_pipeline() -> GuardrailPipeline:
    # Real Presidio + real spaCy pipeline — module-scoped, same rationale
    # as every other real-model fixture in this project.
    return GuardrailPipeline(
        pii_guardrail=PresidioGuardrail(),
        injection_guardrail=PromptInjectionGuardrail(),
        output_policy_guardrail=OutputPolicyGuardrail(),
    )


@pytest.mark.parametrize(
    "query", _by_category("prompt_injection"), ids=lambda q: q.id
)
def test_prompt_injection_queries_are_blocked_at_input_by_the_real_pipeline(
    query: AdversarialQuery, guardrail_pipeline: GuardrailPipeline
) -> None:
    result = guardrail_pipeline.check_input(query.text)

    assert result.blocked is True
    assert query.expected_reason_code in [
        code for r in result.results for code in r.reason_codes
    ]


@pytest.mark.parametrize(
    "query", _by_category("pii_disclosure"), ids=lambda q: q.id
)
def test_pii_disclosure_queries_are_redacted_not_blocked_by_the_real_pipeline(
    query: AdversarialQuery, guardrail_pipeline: GuardrailPipeline
) -> None:
    result = guardrail_pipeline.check_input(query.text)

    assert result.blocked is False
    assert result.passed is False
    assert result.text != query.text  # a real redaction actually happened


@pytest.mark.parametrize(
    "query", _by_category("hallucination_bait"), ids=lambda q: q.id
)
def test_hallucination_bait_queries_are_never_blocked_at_input(
    query: AdversarialQuery, guardrail_pipeline: GuardrailPipeline
) -> None:
    """These are meant to test refuse-when-absent (a retrieval/citation
    concern, already proven at the orchestrate()/e2e layer), not guardrails
    — the only thing that matters here is that retrieval still gets a
    chance to run (blocked=False). NOT asserting passed=True: verified
    empirically that Presidio's small spaCy NER model DOES flag proper
    nouns in some of these bait queries as false-positive PII (e.g. "Tokyo"
    -> LOCATION, "Byzantine Empire" -> LOCATION/NRP, "bank" -> ORGANIZATION)
    — a real, disclosed limitation of the small model, not a bug. A
    redaction still isn't a block, so refuse-when-absent is unaffected.
    """
    result = guardrail_pipeline.check_input(query.text)

    assert result.blocked is False


def test_output_policy_probe_queries_are_scoped_to_healthcare_domain() -> None:
    for query in _by_category("output_policy_probe"):
        assert query.domain == "healthcare"
        assert query.expected_reason_code == "OUTPUT_POLICY_VIOLATION"
