from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

import pytest
from connectors.graph.spacy_extractor import SpacyEntityExtractor
from connectors.postgres.orm import Base
from connectors.postgres.repository import ChunkRepository
from connectors.postgres.session import get_engine, get_sessionmaker
from core.interfaces import EmbeddingProvider, KeywordIndex, LLMProvider, Reranker, VectorStore
from core.models import (
    ChatTurn,
    Chunk,
    Completion,
    KeywordSearchHit,
    Query,
    RetrievalFilters,
    ScoredChunk,
    Vector,
    VectorSearchHit,
)
from retrieval.pipeline import RetrievalDependencies, retrieve
from retrieval.settings import RetrievalSettings
from sqlalchemy.orm import Session

DATABASE_URL = "postgresql+psycopg://rag:rag@localhost:5432/rag_platform"


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    engine = get_engine(DATABASE_URL)
    Base.metadata.create_all(engine)
    factory = get_sessionmaker(engine)
    sess = factory()
    for table in reversed(Base.metadata.sorted_tables):
        sess.execute(table.delete())
    sess.commit()
    yield sess
    sess.close()


class FakeVectorStore(VectorStore):
    def __init__(self, hits: list[VectorSearchHit]) -> None:
        self._hits = hits
        self.search_calls: list[dict[str, Any]] = []

    def upsert(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def search(self, tenant_id: str, *args: Any, **kwargs: Any) -> list[VectorSearchHit]:
        self.search_calls.append({"tenant_id": tenant_id, "args": args, "kwargs": kwargs})
        return self._hits

    def delete(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


class FakeKeywordIndex(KeywordIndex):
    def __init__(self, hits: list[KeywordSearchHit]) -> None:
        self._hits = hits
        self.search_calls: list[dict[str, Any]] = []

    def upsert(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def search(self, tenant_id: str, *args: Any, **kwargs: Any) -> list[KeywordSearchHit]:
        self.search_calls.append({"tenant_id": tenant_id, "args": args, "kwargs": kwargs})
        return self._hits

    def delete(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


class FakeEmbeddingProvider(EmbeddingProvider):
    def embed(self, texts: list[str], model_id: str) -> list[Vector]:
        return [[0.1, 0.2, 0.3] for _ in texts]


class ReversingReranker(Reranker):
    def rerank(self, query: str, candidates: list[ScoredChunk], top_k: int) -> list[ScoredChunk]:
        return list(reversed(candidates))[:top_k]


class FakeLLMProvider(LLMProvider):
    """Returns a fixed multi-line completion regardless of input -- enough
    to prove decompose_query's real sub-questions flow through retrieve(),
    without needing a real LLM call.
    """

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def generate(self, messages: list[Any], model_id: str, params: dict[str, Any]) -> Completion:
        return Completion(
            tenant_id=params.get("tenant_id", ""),
            model_id=model_id,
            text="\n".join(self._lines),
        )


def _chunk(chunk_id: str, tenant_id: str = "tenant-a") -> Chunk:
    return Chunk(
        id=chunk_id,
        tenant_id=tenant_id,
        document_id=f"doc-{chunk_id}",
        text=f"text for {chunk_id}",
        position=0,
        language="en",
        version=1,
    )


def _query(text: str = "what is the deadline?") -> Query:
    return Query(id="q-1", tenant_id="tenant-a", session_id="s-1", text=text)


def _chat_turn(text: str) -> ChatTurn:
    return ChatTurn(
        id="turn-1",
        tenant_id="tenant-a",
        user_id="user-1",
        session_id="s-1",
        role="user",
        text=text,
        created_at=datetime.now(timezone.utc),
    )


def test_retrieve_fuses_and_hydrates_chunks_from_both_backends(session: Session) -> None:
    ChunkRepository(session).bulk_insert([_chunk("c1"), _chunk("c2")])
    session.commit()

    deps = RetrievalDependencies(
        vector_store=FakeVectorStore(
            [VectorSearchHit(chunk_id="c1", document_id="doc-c1", score=0.9, model_id="m")]
        ),
        keyword_index=FakeKeywordIndex(
            [KeywordSearchHit(chunk_id="c2", document_id="doc-c2", score=4.2)]
        ),
        embedding_provider=FakeEmbeddingProvider(),
        embedding_model_id="bge-small",
        reranker=None,
        entity_extractor=None,
        llm_provider=None,
        llm_model_id="",
    )

    outcome = retrieve(
        session, deps, _query(), [], RetrievalFilters(), RetrievalSettings(), [], top_k=10
    )
    result = outcome.result

    assert result.tenant_id == "tenant-a"
    assert result.query_id == "q-1"
    assert {sc.chunk.id for sc in result.chunks} == {"c1", "c2"}


def test_retrieve_without_reranker_truncates_to_top_k(session: Session) -> None:
    ChunkRepository(session).bulk_insert([_chunk("c1"), _chunk("c2"), _chunk("c3")])
    session.commit()

    deps = RetrievalDependencies(
        vector_store=FakeVectorStore(
            [
                VectorSearchHit(chunk_id="c1", document_id="doc-c1", score=0.9, model_id="m"),
                VectorSearchHit(chunk_id="c2", document_id="doc-c2", score=0.8, model_id="m"),
                VectorSearchHit(chunk_id="c3", document_id="doc-c3", score=0.7, model_id="m"),
            ]
        ),
        keyword_index=FakeKeywordIndex([]),
        embedding_provider=FakeEmbeddingProvider(),
        embedding_model_id="bge-small",
        reranker=None,
        entity_extractor=None,
        llm_provider=None,
        llm_model_id="",
    )

    outcome = retrieve(
        session, deps, _query(), [], RetrievalFilters(), RetrievalSettings(), [], top_k=2
    )

    assert len(outcome.result.chunks) == 2


def test_retrieve_with_reranker_uses_its_ordering(session: Session) -> None:
    ChunkRepository(session).bulk_insert([_chunk("c1"), _chunk("c2")])
    session.commit()

    deps = RetrievalDependencies(
        vector_store=FakeVectorStore(
            [
                VectorSearchHit(chunk_id="c1", document_id="doc-c1", score=0.9, model_id="m"),
                VectorSearchHit(chunk_id="c2", document_id="doc-c2", score=0.1, model_id="m"),
            ]
        ),
        keyword_index=FakeKeywordIndex([]),
        embedding_provider=FakeEmbeddingProvider(),
        embedding_model_id="bge-small",
        reranker=ReversingReranker(),
        entity_extractor=None,
        llm_provider=None,
        llm_model_id="",
    )

    outcome = retrieve(
        session, deps, _query(), [], RetrievalFilters(), RetrievalSettings(), [], top_k=10
    )

    # RRF-fused order is [c1, c2] (higher vector score first); the
    # reranker reverses it — proves rerank actually runs, not just fusion.
    assert [sc.chunk.id for sc in outcome.result.chunks] == ["c2", "c1"]


def test_retrieve_passes_filters_to_both_backends(session: Session) -> None:
    vector_store = FakeVectorStore([])
    keyword_index = FakeKeywordIndex([])
    deps = RetrievalDependencies(
        vector_store=vector_store,
        keyword_index=keyword_index,
        embedding_provider=FakeEmbeddingProvider(),
        embedding_model_id="bge-small",
        reranker=None,
        entity_extractor=None,
        llm_provider=None,
        llm_model_id="",
    )
    filters = RetrievalFilters(doc_type="policy", department="lending")

    retrieve(session, deps, _query(), ["p1"], filters, RetrievalSettings(), [], top_k=10)

    assert vector_store.search_calls[0]["kwargs"]["doc_type"] == "policy"
    assert vector_store.search_calls[0]["kwargs"]["department"] == "lending"
    assert keyword_index.search_calls[0]["kwargs"]["doc_type"] == "policy"
    assert keyword_index.search_calls[0]["kwargs"]["department"] == "lending"


def test_retrieve_with_no_results_returns_empty_chunks(session: Session) -> None:
    deps = RetrievalDependencies(
        vector_store=FakeVectorStore([]),
        keyword_index=FakeKeywordIndex([]),
        embedding_provider=FakeEmbeddingProvider(),
        embedding_model_id="bge-small",
        reranker=None,
        entity_extractor=None,
        llm_provider=None,
        llm_model_id="",
    )

    outcome = retrieve(
        session, deps, _query(), [], RetrievalFilters(), RetrievalSettings(), [], top_k=10
    )

    assert outcome.result.chunks == []


def test_retrieve_surfaces_rewritten_query_unchanged_without_llm_provider(
    session: Session,
) -> None:
    deps = RetrievalDependencies(
        vector_store=FakeVectorStore([]),
        keyword_index=FakeKeywordIndex([]),
        embedding_provider=FakeEmbeddingProvider(),
        embedding_model_id="bge-small",
        reranker=None,
        entity_extractor=None,
        llm_provider=None,
        llm_model_id="",
    )

    outcome = retrieve(
        session,
        deps,
        _query("what about it?"),
        [],
        RetrievalFilters(),
        RetrievalSettings(),
        [],
        top_k=10,
    )

    assert outcome.rewritten_query == "what about it?"


def test_retrieve_multi_hop_issues_a_second_search_pass_when_enabled(session: Session) -> None:
    """Proves the multi_hop_enabled branch inside retrieve() itself actually
    runs a second retrieval pass — the standalone extract_expansion_terms()
    unit tests only prove term extraction works in isolation, not that
    pipeline.retrieve() wires it in correctly.

    Phase-3 retrofit: multi-hop now also requires QueryPolicy to agree
    per-query (the global setting is a ceiling, not the sole trigger) — a
    short follow-up query with real chat history is real signal for that,
    not an arbitrary test-only workaround.
    """
    ChunkRepository(session).bulk_insert(
        [
            Chunk(
                id="c1",
                tenant_id="tenant-a",
                document_id="doc-c1",
                text="Acme Bank owns Acme Lending Corp.",
                position=0,
                language="en",
                version=1,
            )
        ]
    )
    session.commit()

    vector_store = FakeVectorStore(
        [VectorSearchHit(chunk_id="c1", document_id="doc-c1", score=0.9, model_id="m")]
    )
    keyword_index = FakeKeywordIndex([])
    deps = RetrievalDependencies(
        vector_store=vector_store,
        keyword_index=keyword_index,
        embedding_provider=FakeEmbeddingProvider(),
        embedding_model_id="bge-small",
        reranker=None,
        entity_extractor=SpacyEntityExtractor("en_core_web_sm"),
        llm_provider=None,
        llm_model_id="",
    )
    settings = RetrievalSettings(multi_hop_enabled=True)
    history = [_chat_turn("Tell me about Acme Bank.")]

    retrieve(
        session,
        deps,
        _query("what about it"),
        [],
        RetrievalFilters(),
        settings,
        history,
        top_k=10,
    )

    # One call for the first pass, a second for the expanded-query pass —
    # only possible if entities were actually extracted from "Acme Bank
    # owns Acme Lending Corp." and used to build a second search.
    assert len(vector_store.search_calls) == 2
    assert len(keyword_index.search_calls) == 2


def test_retrieve_multi_hop_disabled_by_default_issues_only_one_search_pass(
    session: Session,
) -> None:
    ChunkRepository(session).bulk_insert([_chunk("c1")])
    session.commit()

    vector_store = FakeVectorStore(
        [VectorSearchHit(chunk_id="c1", document_id="doc-c1", score=0.9, model_id="m")]
    )
    keyword_index = FakeKeywordIndex([])
    deps = RetrievalDependencies(
        vector_store=vector_store,
        keyword_index=keyword_index,
        embedding_provider=FakeEmbeddingProvider(),
        embedding_model_id="bge-small",
        reranker=None,
        entity_extractor=SpacyEntityExtractor("en_core_web_sm"),
        llm_provider=None,
        llm_model_id="",
    )
    settings = RetrievalSettings()  # multi_hop_enabled defaults to False

    retrieve(session, deps, _query(), [], RetrievalFilters(), settings, [], top_k=10)

    assert len(vector_store.search_calls) == 1
    assert len(keyword_index.search_calls) == 1


def test_retrieve_aggregation_query_never_calls_vector_search(session: Session) -> None:
    # QueryPolicy (Phase-3 retrofit): "aggregations should NOT hit vector
    # search" -- proves retrieve() itself skips the vector call, not just
    # that decide_query_strategy() classifies it correctly in isolation.
    ChunkRepository(session).bulk_insert([_chunk("c1")])
    session.commit()

    vector_store = FakeVectorStore(
        [VectorSearchHit(chunk_id="c1", document_id="doc-c1", score=0.9, model_id="m")]
    )
    keyword_index = FakeKeywordIndex(
        [KeywordSearchHit(chunk_id="c1", document_id="doc-c1", score=1.0)]
    )
    deps = RetrievalDependencies(
        vector_store=vector_store,
        keyword_index=keyword_index,
        embedding_provider=FakeEmbeddingProvider(),
        embedding_model_id="bge-small",
        reranker=None,
        entity_extractor=None,
        llm_provider=None,
        llm_model_id="",
    )

    outcome = retrieve(
        session,
        deps,
        _query("how many loan policies were updated this quarter"),
        [],
        RetrievalFilters(),
        RetrievalSettings(),
        [],
        top_k=10,
    )

    assert outcome.query_intent == "aggregation"
    assert len(vector_store.search_calls) == 0
    assert len(keyword_index.search_calls) == 1
    assert [sc.chunk.id for sc in outcome.result.chunks] == ["c1"]


def test_retrieve_comparison_query_decomposes_and_fuses_sub_question_hits(
    session: Session,
) -> None:
    # QueryPolicy (Phase-3 retrofit): wires the previously-unwired
    # decompose_query() into the real flow -- proves each sub-question's
    # hits actually reach the fused candidate pool, not just that
    # decompose_query() splits text correctly in isolation.
    ChunkRepository(session).bulk_insert([_chunk("c1"), _chunk("c2")])
    session.commit()

    class SubQueryAwareVectorStore(VectorStore):
        def __init__(self) -> None:
            self.search_calls: list[str] = []

        def upsert(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError

        def search(self, tenant_id: str, *args: Any, **kwargs: Any) -> list[VectorSearchHit]:
            return []

        def delete(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError

    class SubQueryAwareKeywordIndex(KeywordIndex):
        def __init__(self) -> None:
            self.queries: list[str] = []

        def upsert(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError

        def search(
            self, tenant_id: str, query: str, *args: Any, **kwargs: Any
        ) -> list[KeywordSearchHit]:
            self.queries.append(query)
            chunk_id = "c1" if "lending" in query else "c2"
            return [KeywordSearchHit(chunk_id=chunk_id, document_id=f"doc-{chunk_id}", score=1.0)]

        def delete(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError

    keyword_index = SubQueryAwareKeywordIndex()
    deps = RetrievalDependencies(
        vector_store=SubQueryAwareVectorStore(),
        keyword_index=keyword_index,
        embedding_provider=FakeEmbeddingProvider(),
        embedding_model_id="bge-small",
        reranker=None,
        entity_extractor=None,
        llm_provider=FakeLLMProvider(
            ["the lending policy", "the compliance policy"]
        ),
        llm_model_id="gpt-5.6-luna",
    )

    outcome = retrieve(
        session,
        deps,
        _query("compare the lending policy and the compliance policy"),
        [],
        RetrievalFilters(),
        RetrievalSettings(),
        [],
        top_k=10,
    )

    assert outcome.query_intent == "comparison"
    assert keyword_index.queries == ["the lending policy", "the compliance policy"]
    assert {sc.chunk.id for sc in outcome.result.chunks} == {"c1", "c2"}


def test_retrieve_skips_reranking_when_scores_are_well_separated(session: Session) -> None:
    # RerankPolicy (Phase-3 retrofit): a chunk both retrievers agree on
    # (rank 1 in both lists) is confidently separated from a chunk only
    # one retriever found at a low rank -- reranking is a wasted cost here.
    ChunkRepository(session).bulk_insert([_chunk("c1"), _chunk("c2")])
    session.commit()

    vector_store = FakeVectorStore(
        [VectorSearchHit(chunk_id="c1", document_id="doc-c1", score=0.9, model_id="m")]
    )
    keyword_index = FakeKeywordIndex(
        [
            KeywordSearchHit(chunk_id="c1", document_id="doc-c1", score=1.0),
            KeywordSearchHit(chunk_id="c2", document_id="doc-c2", score=0.1),
        ]
    )
    deps = RetrievalDependencies(
        vector_store=vector_store,
        keyword_index=keyword_index,
        embedding_provider=FakeEmbeddingProvider(),
        embedding_model_id="bge-small",
        reranker=ReversingReranker(),
        entity_extractor=None,
        llm_provider=None,
        llm_model_id="",
    )

    outcome = retrieve(
        session, deps, _query(), [], RetrievalFilters(), RetrievalSettings(), [], top_k=10
    )

    assert outcome.reranked is False
    # order unchanged from fusion (c1 confidently first) -- the
    # ReversingReranker never ran to flip it.
    assert [sc.chunk.id for sc in outcome.result.chunks][0] == "c1"


def test_retrieve_reranks_when_scores_are_narrowly_separated(session: Session) -> None:
    # Both hits come from the SAME single list (vector-only, adjacent
    # ranks) -- RRF's fused scores for adjacent ranks in one list are
    # always close together (1/(k+1) vs 1/(k+2)), a narrow, non-confident
    # margin that should still trigger reranking.
    ChunkRepository(session).bulk_insert([_chunk("c1"), _chunk("c2")])
    session.commit()

    deps = RetrievalDependencies(
        vector_store=FakeVectorStore(
            [
                VectorSearchHit(chunk_id="c1", document_id="doc-c1", score=0.9, model_id="m"),
                VectorSearchHit(chunk_id="c2", document_id="doc-c2", score=0.1, model_id="m"),
            ]
        ),
        keyword_index=FakeKeywordIndex([]),
        embedding_provider=FakeEmbeddingProvider(),
        embedding_model_id="bge-small",
        reranker=ReversingReranker(),
        entity_extractor=None,
        llm_provider=None,
        llm_model_id="",
    )

    outcome = retrieve(
        session, deps, _query(), [], RetrievalFilters(), RetrievalSettings(), [], top_k=10
    )

    assert outcome.reranked is True
