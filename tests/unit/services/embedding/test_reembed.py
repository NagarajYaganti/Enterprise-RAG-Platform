import uuid
from collections.abc import Generator

import pytest
from connectors.embeddings.sentence_transformers_provider import SentenceTransformersProvider
from connectors.keyword.opensearch_index import OpenSearchIndex, ensure_index
from connectors.postgres.orm import Base
from connectors.postgres.repository import ChunkRepository, DocumentRepository
from connectors.postgres.session import get_engine, get_sessionmaker
from connectors.vectorstores.migrations import ensure_qdrant_collection
from connectors.vectorstores.qdrant_store import QdrantVectorStore
from core.models import Chunk, Document, EmbeddingRecord
from embedding.reembed import cutover, run_reembed
from opensearchpy import OpenSearch
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy.orm import Session

DATABASE_URL = "postgresql+psycopg://rag:rag@localhost:5432/rag_platform"
QDRANT_URL = "http://localhost:6333"
QDRANT_COLLECTION = "test_reembed_collection"
OPENSEARCH_INDEX = "test_reembed_index"
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
    client.indices.delete(index=f"{OPENSEARCH_INDEX}_*", ignore=[404])
    ensure_index(client, OPENSEARCH_INDEX)
    yield OpenSearchIndex(client, OPENSEARCH_INDEX)
    client.indices.delete(index=f"{OPENSEARCH_INDEX}_*", ignore=[404])


@pytest.fixture(scope="module")
def embedding_provider() -> SentenceTransformersProvider:
    return SentenceTransformersProvider(MODEL_ID)


def _status_counts(store: QdrantVectorStore, tenant_id: str, document_id: str) -> dict[str, int]:
    result = store._client.scroll(
        store._collection_name,
        scroll_filter=Filter(
            must=[
                FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                FieldCondition(key="document_id", match=MatchValue(value=document_id)),
            ]
        ),
        limit=1000,
        with_payload=True,
    )
    counts: dict[str, int] = {}
    for point in result[0]:
        status = point.payload["status"]  # type: ignore[index]
        counts[status] = counts.get(status, 0) + 1
    return counts


def test_reembed_keeps_old_vectors_until_explicit_cutover(
    session: Session,
    vector_store: QdrantVectorStore,
    keyword_index: OpenSearchIndex,
    embedding_provider: SentenceTransformersProvider,
) -> None:
    doc_repo = DocumentRepository(session)
    chunk_repo = ChunkRepository(session)
    doc_repo.upsert(
        Document(
            id="doc-1",
            tenant_id="tenant-a",
            source_uri="s3://bucket/doc-1",
            mime_type="text/plain",
            checksum="abc123",
            version=1,
            status="PARSED",
        )
    )
    chunk_repo.bulk_insert(
        [
            Chunk(
                id="chunk-1",
                tenant_id="tenant-a",
                document_id="doc-1",
                text="quarterly earnings report",
                position=0,
                language="en",
                version=1,
            )
        ]
    )
    session.commit()

    # embed with the "old" model first, via run_reembed itself (proving the
    # thin wrapper actually delegates to process_embedding_job correctly)
    run_reembed(
        session, vector_store, keyword_index, embedding_provider, "tenant-a", "doc-1", MODEL_ID, "1"
    )
    counts_after_old = _status_counts(vector_store, "tenant-a", "doc-1")
    assert counts_after_old == {"active": 1}

    # Simulate "already re-embedded with a new model": upsert a second
    # record tagged with a different model_id directly. A real second
    # provider isn't used here — the embedding provider correctly refuses a
    # model_id it isn't configured for (verified separately), and cutover()
    # itself doesn't care how the new vector got there, only that it exists.
    vector_store.upsert(
        "tenant-a",
        [
            EmbeddingRecord(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, "chunk-1:new-model-id")),
                tenant_id="tenant-a",
                document_id="doc-1",
                chunk_id="chunk-1",
                vector=[0.1] * 384,
                model_id="new-model-id",
                model_version="1",
            )
        ],
    )

    # before cutover: BOTH old and new vectors are active and searchable
    counts_before_cutover = _status_counts(vector_store, "tenant-a", "doc-1")
    assert counts_before_cutover == {"active": 2}

    cutover(session, vector_store, "tenant-a", "doc-1", MODEL_ID)

    # after cutover: old model's vector is superseded, new one is active
    counts_after_cutover = _status_counts(vector_store, "tenant-a", "doc-1")
    assert counts_after_cutover == {"active": 1, "superseded": 1}


def test_cutover_refuses_when_no_active_chunks_exist(
    session: Session, vector_store: QdrantVectorStore
) -> None:
    with pytest.raises(ValueError, match="nothing to cut over"):
        cutover(session, vector_store, "tenant-a", "doc-does-not-exist", MODEL_ID)
