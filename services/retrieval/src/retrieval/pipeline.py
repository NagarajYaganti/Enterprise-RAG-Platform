from dataclasses import dataclass

from connectors.graph.spacy_extractor import SpacyEntityExtractor
from connectors.postgres.repository import ChunkRepository
from core.interfaces import EmbeddingProvider, KeywordIndex, LLMProvider, Reranker, VectorStore
from core.models import (
    ChatTurn,
    KeywordSearchHit,
    Query,
    RetrievalFilters,
    RetrievalResult,
    ScoredChunk,
    VectorSearchHit,
)
from sqlalchemy.orm import Session

from retrieval.filters import to_search_kwargs
from retrieval.hybrid import reciprocal_rank_fusion
from retrieval.multi_hop import extract_expansion_terms
from retrieval.query_policy import decide_query_strategy, decompose_if_needed
from retrieval.query_understanding import rewrite_query
from retrieval.rerank_policy import compute_rerank_profile, decide_rerank_action
from retrieval.settings import RetrievalSettings


@dataclass
class RetrievalOutcome:
    """retrieve()'s return shape: the RetrievalResult plus fields surfaced
    for API transparency (per the Phase 3 plan) — callers can show the
    user what query was actually searched against and how it was handled,
    since query/rerank understanding may have changed the flow.
    """

    result: RetrievalResult
    rewritten_query: str
    query_intent: str
    reranked: bool


@dataclass
class RetrievalDependencies:
    """Bundles the adapters retrieve() needs — mirrors the dependency
    injection style already used by services/embedding's worker ctx, kept
    as an explicit dataclass here since retrieve() takes enough of them
    that a flat parameter list would be hard to read. reranker/
    entity_extractor/llm_provider are all optional: None means "not
    configured," and retrieve() degrades gracefully in each case (no
    rerank, no multi-hop, no query rewrite) rather than failing.
    """

    vector_store: VectorStore
    keyword_index: KeywordIndex
    embedding_provider: EmbeddingProvider
    embedding_model_id: str
    reranker: Reranker | None
    entity_extractor: SpacyEntityExtractor | None
    llm_provider: LLMProvider | None
    llm_model_id: str


def _search_one(
    tenant_id: str,
    text: str,
    principals: list[str],
    deps: RetrievalDependencies,
    search_mode: str,
    pool_size: int,
    search_kwargs: dict[str, str | None],
) -> tuple[list[VectorSearchHit], list[KeywordSearchHit]]:
    """One vector+keyword search pass for a single query text. search_mode
    == "bm25_only" skips the vector call entirely -- QueryPolicy's literal
    "aggregations should NOT hit vector search" requirement -- the only
    other real mode is "hybrid" (both). Reused per sub-question when
    QueryPolicy decides to decompose, exactly like the existing multi-hop
    expansion pass already does for its own second search.
    """
    keyword_hits = deps.keyword_index.search(
        tenant_id, text, principals, top_k=pool_size, **search_kwargs
    )
    if search_mode == "bm25_only":
        return [], keyword_hits
    query_vector = deps.embedding_provider.embed([text], deps.embedding_model_id)[0]
    vector_hits = deps.vector_store.search(
        tenant_id, query_vector, principals, top_k=pool_size, **search_kwargs
    )
    return vector_hits, keyword_hits


def retrieve(
    session: Session,
    deps: RetrievalDependencies,
    query: Query,
    principals: list[str],
    filters: RetrievalFilters,
    settings: RetrievalSettings,
    chat_history: list[ChatTurn],
    top_k: int,
) -> RetrievalOutcome:
    """Query understanding -> QueryPolicy (intent -> search mode/decompose/
    multi-hop) -> hybrid retrieve (pre-filtered, tenant/ACL-scoped) ->
    multi-hop (if enabled) -> RerankPolicy -> rerank -> RetrievalResult.
    Mirrors docs/ARCHITECTURE.md's fixed data flow: "authn(tenant) ->
    hybrid_retrieve(vector + keyword, tenant-filtered) -> rerank", with
    query understanding as an internal step before retrieval per Section 4
    Phase 3's task text.
    """
    tenant_id = query.tenant_id
    rewritten_text = rewrite_query(
        query.text, chat_history, deps.llm_provider, deps.llm_model_id, tenant_id
    )

    action = decide_query_strategy(rewritten_text, filters, chat_history)
    search_mode = action["search_mode"]
    pool_size = int(settings.candidate_pool_size * action["candidate_pool_multiplier"])
    search_kwargs = to_search_kwargs(filters)

    # decompose_if_needed returns [rewritten_text] unchanged when the
    # policy didn't ask to decompose, or when no LLM is configured to
    # actually do it -- so this always runs at least one search, matching
    # today's behavior exactly for the common case.
    sub_queries = decompose_if_needed(
        rewritten_text, action, deps.llm_provider, deps.llm_model_id, tenant_id
    )
    vector_hits: list[VectorSearchHit] = []
    keyword_hits: list[KeywordSearchHit] = []
    for sub_query in sub_queries:
        sub_vector_hits, sub_keyword_hits = _search_one(
            tenant_id, sub_query, principals, deps, search_mode, pool_size, search_kwargs
        )
        vector_hits += sub_vector_hits
        keyword_hits += sub_keyword_hits

    chunk_repo = ChunkRepository(session)

    if settings.multi_hop_enabled and action["multi_hop"] and deps.entity_extractor is not None:
        first_pass = reciprocal_rank_fusion(vector_hits, keyword_hits, k=settings.rrf_k)
        first_pass_ids = [chunk_id for chunk_id, _, _ in first_pass[:5]]
        first_pass_chunks = chunk_repo.get_by_ids(tenant_id, first_pass_ids)
        expansion_terms = extract_expansion_terms(first_pass_chunks, deps.entity_extractor)
        if expansion_terms:
            expanded_text = f"{rewritten_text} {' '.join(expansion_terms)}"
            expanded_vector_hits, expanded_keyword_hits = _search_one(
                tenant_id, expanded_text, principals, deps, search_mode, pool_size, search_kwargs
            )
            vector_hits = vector_hits + expanded_vector_hits
            keyword_hits = keyword_hits + expanded_keyword_hits

    fused = reciprocal_rank_fusion(vector_hits, keyword_hits, k=settings.rrf_k)
    fused_chunk_ids = [chunk_id for chunk_id, _, _ in fused]
    chunks_by_id = {chunk.id: chunk for chunk in chunk_repo.get_by_ids(tenant_id, fused_chunk_ids)}
    scored_chunks = [
        ScoredChunk(chunk=chunks_by_id[chunk_id], score=score)
        for chunk_id, _, score in fused
        if chunk_id in chunks_by_id
    ]

    rerank_action = decide_rerank_action(compute_rerank_profile([s.score for s in scored_chunks]))
    reranked = False
    if deps.reranker is not None and rerank_action["action"] == "rerank":
        scored_chunks = deps.reranker.rerank(rewritten_text, scored_chunks, top_k)
        reranked = True
    else:
        scored_chunks = scored_chunks[:top_k]

    result = RetrievalResult(tenant_id=tenant_id, query_id=query.id, chunks=scored_chunks)
    return RetrievalOutcome(
        result=result,
        rewritten_query=rewritten_text,
        query_intent=action["intent"],
        reranked=reranked,
    )
