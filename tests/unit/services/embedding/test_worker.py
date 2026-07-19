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
