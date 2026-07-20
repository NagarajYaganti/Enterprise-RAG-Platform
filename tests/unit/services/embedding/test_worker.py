from collections.abc import Generator
from typing import Any

import pytest
from connectors.embeddings.sentence_transformers_provider import SentenceTransformersProvider
from connectors.keyword.opensearch_index import OpenSearchIndex, ensure_index
from connectors.postgres.orm import Base
from connectors.postgres.repository import ChunkRepository, DocumentRepository
from connectors.postgres.session import get_engine, get_sessionmaker
from connectors.vectorstores.migrations import ensure_qdrant_collection
from connectors.vectorstores.qdrant_store import QdrantVectorStore
from core.interfaces import VectorStore
from core.models import Chunk, Document
from embedding.worker import process_embedding_job
from opensearchpy import OpenSearch
from qdrant_client import QdrantClient
from sqlalchemy.orm import Session

DATABASE_URL = "postgresql+psycopg://rag:rag@localhost:5432/rag_platform"
QDRANT_URL = "http://localhost:6333"
QDRANT_COLLECTION = "test_embedding_worker_collection"
OPENSEARCH_INDEX = "test_embedding_worker_index"
MODEL_ID = "BAAI/bge-small-en-v1.5"


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


@pytest.fixture()
def vector_store() -> Generator[QdrantVectorStore, None, None]:
    client = QdrantClient(url=QDRANT_URL)
    ensure_qdrant_collection(client, QDRANT_COLLECTION, dimension=384)
    yield QdrantVectorStore(client, QDRANT_COLLECTION)
    client.delete_collection(QDRANT_COLLECTION)


@pytest.fixture()
def keyword_index() -> Generator[OpenSearchIndex, None, None]:
    client = OpenSearch(
        hosts=[{"host": "localhost", "port": 9200}], use_ssl=False, verify_certs=False
    )
    client.indices.delete(index=OPENSEARCH_INDEX, ignore=[404])
    ensure_index(client, OPENSEARCH_INDEX)
    yield OpenSearchIndex(client, OPENSEARCH_INDEX)
    client.indices.delete(index=OPENSEARCH_INDEX, ignore=[404])


@pytest.fixture(scope="module")
def embedding_provider() -> SentenceTransformersProvider:
    return SentenceTransformersProvider(MODEL_ID)


def _seed_document_with_chunks(session: Session, tenant_id: str, document_id: str, n: int) -> None:
    doc_repo = DocumentRepository(session)
    chunk_repo = ChunkRepository(session)
    doc_repo.upsert(
        Document(
            id=document_id,
            tenant_id=tenant_id,
            source_uri=f"s3://bucket/{document_id}",
            mime_type="text/plain",
            checksum="abc123",
            version=1,
            status="PARSED",
        )
    )
    chunk_repo.bulk_insert(
        [
            Chunk(
                id=f"{document_id}-chunk-{i}",
                tenant_id=tenant_id,
                document_id=document_id,
                text=f"quarterly earnings paragraph number {i}",
                position=i,
                language="en",
                version=1,
            )
            for i in range(n)
        ]
    )
    session.commit()


def test_process_embedding_job_embeds_all_chunks(
    session: Session,
    vector_store: QdrantVectorStore,
    keyword_index: OpenSearchIndex,
    embedding_provider: SentenceTransformersProvider,
) -> None:
    _seed_document_with_chunks(session, "tenant-a", "doc-1", n=3)

    count = process_embedding_job(
        session, vector_store, keyword_index, embedding_provider, "tenant-a", "doc-1", MODEL_ID, "1"
    )

    assert count == 3
    doc_repo = DocumentRepository(session)
    document = doc_repo.get("tenant-a", "doc-1")
    assert document is not None
    assert document.status == "EMBEDDED"

    # Chunks default to acl_principals=[] — search()'s ACL pre-filter (an
    # empty MatchAny) matches nothing by design, so verify existence via a
    # raw scroll count instead of a principal-gated search here.
    assert _count_vectors_for_document(vector_store, "tenant-a", "doc-1") == 3


def test_process_embedding_job_is_idempotent_across_a_simulated_mid_batch_kill(
    session: Session,
    vector_store: QdrantVectorStore,
    keyword_index: OpenSearchIndex,
    embedding_provider: SentenceTransformersProvider,
) -> None:
    _seed_document_with_chunks(session, "tenant-a", "doc-2", n=5)

    class FlakyVectorStore(VectorStore):
        def __init__(self, real: QdrantVectorStore, fail_after: int) -> None:
            self._real = real
            self._fail_after = fail_after
            self.calls = 0

        def upsert(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
            self.calls += 1
            if self.calls > self._fail_after:
                raise RuntimeError("simulated mid-batch kill")
            return self._real.upsert(tenant_id, *args, **kwargs)

        def search(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
            return self._real.search(tenant_id, *args, **kwargs)

        def delete(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
            return self._real.delete(tenant_id, *args, **kwargs)

    flaky = FlakyVectorStore(vector_store, fail_after=3)

    with pytest.raises(RuntimeError, match="simulated mid-batch kill"):
        process_embedding_job(
            session, flaky, keyword_index, embedding_provider, "tenant-a", "doc-2", MODEL_ID, "1"
        )

    partial_count = _count_vectors_for_document(vector_store, "tenant-a", "doc-2")
    assert partial_count == 3

    # restart: run again with the real (non-failing) store to completion
    count = process_embedding_job(
        session, vector_store, keyword_index, embedding_provider, "tenant-a", "doc-2", MODEL_ID, "1"
    )
    assert count == 5

    final_count = _count_vectors_for_document(vector_store, "tenant-a", "doc-2")
    assert final_count == 5  # not 5 + 3 = 8 — the restart didn't duplicate the first 3


def test_process_embedding_job_populates_phase3_filter_fields_from_chunk(
    session: Session,
    vector_store: QdrantVectorStore,
    keyword_index: OpenSearchIndex,
    embedding_provider: SentenceTransformersProvider,
) -> None:
    doc_repo = DocumentRepository(session)
    chunk_repo = ChunkRepository(session)
    doc_repo.upsert(
        Document(
            id="doc-filters",
            tenant_id="tenant-a",
            source_uri="s3://bucket/doc-filters",
            mime_type="text/plain",
            checksum="abc123",
            version=1,
            status="PARSED",
        )
    )
    chunk_repo.bulk_insert(
        [
            Chunk(
                id="doc-filters-chunk-0",
                tenant_id="tenant-a",
                document_id="doc-filters",
                text="loan policy text",
                position=0,
                language="en",
                version=1,
                doc_type="policy",
                department="lending",
                date="2026-01-01",
            )
        ]
    )
    session.commit()

    process_embedding_job(
        session,
        vector_store,
        keyword_index,
        embedding_provider,
        "tenant-a",
        "doc-filters",
        MODEL_ID,
        "1",
    )

    result = vector_store._client.scroll(
        vector_store._collection_name,
        scroll_filter=None,
        limit=10,
    )
    points = [p for p in result[0] if p.payload and p.payload.get("document_id") == "doc-filters"]
    assert len(points) == 1
    assert points[0].payload is not None
    assert points[0].payload["language"] == "en"
    assert points[0].payload["doc_type"] == "policy"
    assert points[0].payload["department"] == "lending"
    assert points[0].payload["date"] == "2026-01-01"


def test_process_embedding_job_skips_graphrag_when_not_provided(
    session: Session,
    vector_store: QdrantVectorStore,
    keyword_index: OpenSearchIndex,
    embedding_provider: SentenceTransformersProvider,
) -> None:
    """Default call (no knowledge_graph/entity_extractor args) must not
    populate the entities/relations tables at all — proven with real,
    entity-bearing chunk text and a genuine PostgresKnowledgeGraph query
    afterward, not just by omission of a positive assertion.
    """
    from connectors.graph.postgres_knowledge_graph import PostgresKnowledgeGraph

    doc_repo = DocumentRepository(session)
    chunk_repo = ChunkRepository(session)
    doc_repo.upsert(
        Document(
            id="doc-nograph",
            tenant_id="tenant-a",
            source_uri="s3://bucket/doc-nograph",
            mime_type="text/plain",
            checksum="abc123",
            version=1,
            status="PARSED",
        )
    )
    chunk_repo.bulk_insert(
        [
            Chunk(
                id="doc-nograph-chunk-0",
                tenant_id="tenant-a",
                document_id="doc-nograph",
                text="Acme Bank owns Acme Lending Corp.",
                position=0,
                language="en",
                version=1,
            )
        ]
    )
    session.commit()

    count = process_embedding_job(
        session,
        vector_store,
        keyword_index,
        embedding_provider,
        "tenant-a",
        "doc-nograph",
        MODEL_ID,
        "1",
    )
    assert count == 1

    entities, relations = PostgresKnowledgeGraph(session).query_subgraph(
        "tenant-a", ["Acme Bank", "Acme Lending Corp"]
    )
    assert entities == []
    assert relations == []


def test_process_embedding_job_extracts_entities_and_relations_when_graphrag_enabled(
    session: Session,
    vector_store: QdrantVectorStore,
    keyword_index: OpenSearchIndex,
    embedding_provider: SentenceTransformersProvider,
) -> None:
    from connectors.graph.postgres_knowledge_graph import PostgresKnowledgeGraph
    from connectors.graph.spacy_extractor import SpacyEntityExtractor

    doc_repo = DocumentRepository(session)
    chunk_repo = ChunkRepository(session)
    doc_repo.upsert(
        Document(
            id="doc-graph",
            tenant_id="tenant-a",
            source_uri="s3://bucket/doc-graph",
            mime_type="text/plain",
            checksum="abc123",
            version=1,
            status="PARSED",
        )
    )
    chunk_repo.bulk_insert(
        [
            Chunk(
                id="doc-graph-chunk-0",
                tenant_id="tenant-a",
                document_id="doc-graph",
                text="Acme Bank owns Acme Lending Corp.",
                position=0,
                language="en",
                version=1,
            )
        ]
    )
    session.commit()

    knowledge_graph = PostgresKnowledgeGraph(session)
    entity_extractor = SpacyEntityExtractor("en_core_web_sm")

    process_embedding_job(
        session,
        vector_store,
        keyword_index,
        embedding_provider,
        "tenant-a",
        "doc-graph",
        MODEL_ID,
        "1",
        knowledge_graph=knowledge_graph,
        entity_extractor=entity_extractor,
    )
    session.commit()

    # spaCy includes the trailing period in "Acme Lending Corp." here since
    # it's the final token before end-of-sentence — verified empirically,
    # not assumed; the query name must match exactly.
    entities, relations = knowledge_graph.query_subgraph(
        "tenant-a", ["Acme Bank", "Acme Lending Corp."]
    )
    assert {e.name for e in entities} == {"Acme Bank", "Acme Lending Corp."}
    assert len(relations) == 1


def test_graphrag_settings_defaults_to_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from embedding.worker import GraphRAGSettings

    monkeypatch.delenv("GRAPHRAG_ENABLED", raising=False)
    assert GraphRAGSettings().graphrag_enabled is False


def test_graphrag_settings_reads_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    from embedding.worker import GraphRAGSettings

    monkeypatch.setenv("GRAPHRAG_ENABLED", "true")
    assert GraphRAGSettings().graphrag_enabled is True


def _count_vectors_for_document(store: QdrantVectorStore, tenant_id: str, document_id: str) -> int:
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    result = store._client.scroll(
        store._collection_name,
        scroll_filter=Filter(
            must=[
                FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                FieldCondition(key="document_id", match=MatchValue(value=document_id)),
            ]
        ),
        limit=1000,
    )
    return len(result[0])
