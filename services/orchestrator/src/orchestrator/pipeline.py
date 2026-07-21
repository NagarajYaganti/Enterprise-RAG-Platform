from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from connectors.postgres.repository import TokenUsageRepository
from core.interfaces import EmbeddingProvider, LLMProvider, ModelRouter
from core.model_registry import get_model_entry
from core.models import ChatTurn, GuardrailResult, Query, RetrievalFilters, TokenUsageRecord
from core.prompt_registry import REFUSAL_TEXT, get_prompt_template
from retrieval.pipeline import RetrievalDependencies, retrieve
from retrieval.query_understanding import decompose_query
from retrieval.settings import RetrievalSettings
from sqlalchemy.orm import Session

from orchestrator.citations import check_citations
from orchestrator.complexity import assess_complexity
from orchestrator.guardrail_pipeline import GuardrailPipeline
from orchestrator.semantic_cache import SemanticCache
from orchestrator.settings import OrchestratorSettings

# Distinct from REFUSAL_TEXT ("no info in the documents") — this covers
# guardrail hard-blocks (injection, output policy, an internal guardrail
# failure), which are a different situation from "the docs don't say."
BLOCKED_RESPONSE_TEXT = "This request could not be processed."


class LLMProviderNotConfiguredError(RuntimeError):
    pass


@dataclass
class OrchestrationDependencies:
    """Bundles orchestrate()'s adapters, mirroring RetrievalDependencies'
    dataclass style. llm_providers is keyed by provider name (e.g.
    "openai", "anthropic") rather than being a single LLMProvider — unlike
    retrieval's deps.llm_provider (used only for query rewrite/decompose,
    always the same configured provider), ModelRouter.select can route to
    ANY registered generation model regardless of provider, so orchestrate()
    needs a way to resolve the routed model_id's provider field back to the
    matching adapter instance. cache_embedding_provider/model_id are None-
    able as a pair with semantic_cache: both unset together when the cache
    is disabled.
    """

    retrieval: RetrievalDependencies
    llm_providers: dict[str, LLMProvider]
    model_router: ModelRouter
    guardrail_pipeline: GuardrailPipeline
    semantic_cache: SemanticCache | None
    cache_embedding_provider: EmbeddingProvider | None
    cache_embedding_model_id: str


@dataclass
class OrchestrationResult:
    query_id: str
    rewritten_query: str
    answer_text: str
    cited_chunk_ids: list[str]
    model_id: str | None
    from_cache: bool
    blocked: bool
    blocked_reason: str | None


def _first_reason_code(results: list[GuardrailResult]) -> str | None:
    for result in results:
        if result.reason_codes:
            return result.reason_codes[0]
    return None


def orchestrate(
    session: Session,
    deps: OrchestrationDependencies,
    query: Query,
    principals: list[str],
    filters: RetrievalFilters,
    retrieval_settings: RetrievalSettings,
    orchestrator_settings: OrchestratorSettings,
    chat_history: list[ChatTurn],
    domain: str,
    language: str,
    top_k: int,
    budget: float | None = None,
) -> OrchestrationResult:
    """Mirrors docs/ARCHITECTURE.md's fixed data flow from hybrid_retrieve
    onward: hybrid_retrieve -> rerank (both inside retrieval.pipeline.retrieve)
    -> assemble_prompt -> route_model -> generate -> guardrails -> respond.
    Guardrails actually run TWICE (input and output) per Plan v2 §A.8 — the
    fixed flow names "guardrails" once but doesn't say input-only, and an
    LLM's own output is exactly what OutputPolicyGuardrail/PII-on-output
    exist to catch.

    Zero retrieved chunks short-circuits straight to REFUSAL_TEXT without
    ever calling the LLM — a deterministic guarantee for GAP-MATRIX's
    refuse-when-absent requirement, stronger than trusting the model to
    follow its own refusal instruction when hallucination is exactly the
    failure mode being guarded against.
    """
    input_check = deps.guardrail_pipeline.check_input(query.text)
    if input_check.blocked:
        return OrchestrationResult(
            query_id=query.id,
            rewritten_query=query.text,
            answer_text=BLOCKED_RESPONSE_TEXT,
            cited_chunk_ids=[],
            model_id=None,
            from_cache=False,
            blocked=True,
            blocked_reason=_first_reason_code(input_check.results),
        )

    sanitized_query = query.model_copy(update={"text": input_check.text})

    outcome = retrieve(
        session,
        deps.retrieval,
        sanitized_query,
        principals,
        filters,
        retrieval_settings,
        chat_history,
        top_k,
    )
    retrieved_chunks = outcome.result.chunks
    rewritten_query = outcome.rewritten_query

    if not retrieved_chunks:
        return OrchestrationResult(
            query_id=query.id,
            rewritten_query=rewritten_query,
            answer_text=REFUSAL_TEXT,
            cited_chunk_ids=[],
            model_id=None,
            from_cache=False,
            blocked=False,
            blocked_reason=None,
        )

    resolved_budget = (
        budget if budget is not None else orchestrator_settings.default_budget_cost_per_1k_tokens
    )

    cache_vector: list[float] | None = None
    cache_hit = None
    cache_active = orchestrator_settings.semantic_cache_enabled and deps.semantic_cache is not None
    if cache_active:
        assert deps.cache_embedding_provider is not None  # implied by cache_active
        cache_vector = deps.cache_embedding_provider.embed(
            [rewritten_query], deps.cache_embedding_model_id
        )[0]
        assert deps.semantic_cache is not None
        cache_hit = deps.semantic_cache.get(query.tenant_id, cache_vector)

    # A cache hit is a previously-cached answer that ALREADY passed citation
    # validation and output guardrails before it was stored (see the `put`
    # call below) — it is trusted as-is and returned directly. Re-running
    # citation-check against it would be actively wrong: PII redaction can
    # mangle a `[chunk_id]` marker's brackets (e.g. "[doc-1]" ->
    # "[<ORGANIZATION>-1]"), which would then fail citations.py's character
    # class and falsely look "ungrounded," silently corrupting a valid
    # cached answer into a refusal on every subsequent cache hit.
    if cache_hit is not None:
        return OrchestrationResult(
            query_id=query.id,
            rewritten_query=rewritten_query,
            answer_text=cache_hit.answer_text,
            cited_chunk_ids=cache_hit.cited_chunk_ids,
            model_id=cache_hit.model_id,
            from_cache=True,
            blocked=False,
            blocked_reason=None,
        )

    if deps.retrieval.llm_provider is not None:
        sub_questions = decompose_query(
            rewritten_query, deps.retrieval.llm_provider, deps.retrieval.llm_model_id,
            query.tenant_id,
        )
    else:
        sub_questions = [rewritten_query]
    complexity = assess_complexity(
        rewritten_query, sub_questions, orchestrator_settings.complexity_length_threshold
    )

    model_id = deps.model_router.select(
        task="generation", language=language, complexity=complexity, budget=resolved_budget
    )
    model_entry = get_model_entry(model_id)
    provider = deps.llm_providers.get(model_entry["provider"])
    if provider is None:
        raise LLMProviderNotConfiguredError(
            f"no LLMProvider registered for provider={model_entry['provider']!r} "
            f"(routed to model_id={model_id!r})"
        )

    context_block = "\n\n".join(f"[{sc.chunk.id}] {sc.chunk.text}" for sc in retrieved_chunks)
    template = get_prompt_template(type="retrieval-qa", domain=domain, language=language)
    prompt_text = template.template_text.format(context=context_block, query=rewritten_query)

    completion = provider.generate(
        [{"role": "user", "content": prompt_text}], model_id, {"tenant_id": query.tenant_id}
    )
    answer_text = completion.text

    TokenUsageRepository(session).record(
        TokenUsageRecord(
            id=str(uuid4()),
            tenant_id=query.tenant_id,
            model_id=model_id,
            prompt_tokens=completion.usage.get("prompt_tokens", 0),
            completion_tokens=completion.usage.get("completion_tokens", 0),
            created_at=datetime.now(timezone.utc),
        )
    )

    citation_result = check_citations(answer_text, [sc.chunk for sc in retrieved_chunks])
    if citation_result.is_grounded:
        cited_chunk_ids = citation_result.valid_chunk_ids
    else:
        answer_text = REFUSAL_TEXT
        cited_chunk_ids = []

    output_check = deps.guardrail_pipeline.check_output(answer_text, domain)
    if output_check.blocked:
        return OrchestrationResult(
            query_id=query.id,
            rewritten_query=rewritten_query,
            answer_text=BLOCKED_RESPONSE_TEXT,
            cited_chunk_ids=[],
            model_id=model_id,
            from_cache=False,
            blocked=True,
            blocked_reason=_first_reason_code(output_check.results),
        )
    answer_text = output_check.text

    if answer_text != REFUSAL_TEXT and cache_active:
        assert deps.semantic_cache is not None
        assert cache_vector is not None
        document_ids = sorted(
            {sc.chunk.document_id for sc in retrieved_chunks if sc.chunk.id in cited_chunk_ids}
        )
        deps.semantic_cache.put(
            query.tenant_id, str(uuid4()), cache_vector, answer_text, document_ids,
            cited_chunk_ids, model_id,
        )

    return OrchestrationResult(
        query_id=query.id,
        rewritten_query=rewritten_query,
        answer_text=answer_text,
        cited_chunk_ids=cited_chunk_ids,
        model_id=model_id,
        from_cache=False,
        blocked=False,
        blocked_reason=None,
    )
