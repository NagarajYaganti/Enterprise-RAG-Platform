from dataclasses import dataclass

from connectors.graph.spacy_extractor import SpacyEntityExtractor
from connectors.postgres.repository import ChunkRepository
from core.interfaces import EmbeddingProvider, KeywordIndex, LLMProvider, Reranker, VectorStore
from core.models import ChatTurn, Query, RetrievalFilters, RetrievalResult, ScoredChunk
from sqlalchemy.orm import Session

from retrieval.filters import to_search_kwargs
from retrieval.hybrid import reciprocal_rank_fusion
from retrieval.multi_hop import extract_expansion_terms
from retrieval.query_understanding import rewrite_query
from retrieval.settings import RetrievalSettings


@dataclass
class RetrievalOutcome:
    """retrieve()'s return shape: the RetrievalResult plus the rewritten
    query text, surfaced separately for API transparency (per the Phase 3
    plan) — callers can show the user what query was actually searched
    against, since query understanding may have changed it.
    """

    result: RetrievalResult
    rewritten_query: str


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
    """Query understanding -> hybrid retrieve (pre-filtered, tenant/ACL-
    scoped) -> multi-hop (if enabled) -> rerank -> RetrievalResult. Mirrors
    docs/ARCHITECTURE.md's fixed data flow:
    "authn(tenant) -> hybrid_retrieve(vector + keyword, tenant-filtered) ->
    rerank", with query understanding as an internal step before retrieval
    per Section 4 Phase 3's task text.
    """
    tenant_id = query.tenant_id
    rewritten_text = rewrite_query(
        query.text, chat_history, deps.llm_provider, deps.llm_model_id, tenant_id
    )

    search_kwargs = to_search_kwargs(filters)
    query_vector = deps.embedding_provider.embed([rewritten_text], deps.embedding_model_id)[0]
    vector_hits = deps.vector_store.search(
        tenant_id,
        query_vector,
        principals,
        top_k=settings.candidate_pool_size,
        **search_kwargs,
    )
    keyword_hits = deps.keyword_index.search(
        tenant_id,
        rewritten_text,
        principals,
        top_k=settings.candidate_pool_size,
        **search_kwargs,
    )

    chunk_repo = ChunkRepository(session)

    if settings.multi_hop_enabled and deps.entity_extractor is not None:
        first_pass = reciprocal_rank_fusion(vector_hits, keyword_hits, k=settings.rrf_k)
        first_pass_ids = [chunk_id for chunk_id, _, _ in first_pass[:5]]
        first_pass_chunks = chunk_repo.get_by_ids(tenant_id, first_pass_ids)
        expansion_terms = extract_expansion_terms(first_pass_chunks, deps.entity_extractor)
        if expansion_terms:
            expanded_text = f"{rewritten_text} {' '.join(expansion_terms)}"
            expanded_vector = deps.embedding_provider.embed(
                [expanded_text], deps.embedding_model_id
            )[0]
            vector_hits = vector_hits + deps.vector_store.search(
                tenant_id,
                expanded_vector,
                principals,
                top_k=settings.candidate_pool_size,
                **search_kwargs,
            )
            keyword_hits = keyword_hits + deps.keyword_index.search(
                tenant_id,
                expanded_text,
                principals,
                top_k=settings.candidate_pool_size,
                **search_kwargs,
            )

    fused = reciprocal_rank_fusion(vector_hits, keyword_hits, k=settings.rrf_k)
    fused_chunk_ids = [chunk_id for chunk_id, _, _ in fused]
    chunks_by_id = {chunk.id: chunk for chunk in chunk_repo.get_by_ids(tenant_id, fused_chunk_ids)}
    scored_chunks = [
        ScoredChunk(chunk=chunks_by_id[chunk_id], score=score)
        for chunk_id, _, score in fused
        if chunk_id in chunks_by_id
    ]

    if deps.reranker is not None:
        scored_chunks = deps.reranker.rerank(rewritten_text, scored_chunks, top_k)
    else:
        scored_chunks = scored_chunks[:top_k]

    result = RetrievalResult(tenant_id=tenant_id, query_id=query.id, chunks=scored_chunks)
    return RetrievalOutcome(result=result, rewritten_query=rewritten_text)
