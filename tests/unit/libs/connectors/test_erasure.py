import uuid
from collections.abc import Generator

import pytest
from connectors.erasure import ErasureError, ErasureService
from connectors.keyword.opensearch_index import OpenSearchIndex, ensure_index
from connectors.postgres.orm import Base
from connectors.postgres.repository import ChunkRepository, DocumentRepository
from connectors.postgres.session import get_engine, get_sessionmaker
from connectors.vectorstores.migrations import ensure_qdrant_collection
from connectors.vectorstores.qdrant_store import QdrantVectorStore
from core.models import Chunk, Document, EmbeddingRecord
from opensearchpy import OpenSearch
from qdrant_client import QdrantClient
from sqlalchemy.orm import Session

DATABASE_URL = "postgresql+psycopg://rag:rag@localhost:5432/rag_platform"
QDRANT_URL = "http://localhost:6333"
QDRANT_COLLECTION = "test_erasure_collection"
OPENSEARCH_INDEX = "test_erasure_index"


def test_erase_document_runs_all_hooks_and_reports_success() -> None:
    service = ErasureService()
    calls: list[tuple[str, str, str]] = []

    service.register("chunks", lambda t, d: calls.append(("chunks", t, d)))
    service.register("vectors", lambda t, d: calls.append(("vectors", t, d)))
    service.register("keyword_index", lambda t, d: calls.append(("keyword_index", t, d)))

    result = service.erase_document("tenant-a", "doc-1")

    assert calls == [
        ("chunks", "tenant-a", "doc-1"),
        ("vectors", "tenant-a", "doc-1"),
        ("keyword_index", "tenant-a", "doc-1"),
    ]
    assert result.completed_hooks == ["chunks", "vectors", "keyword_index"]
    assert result.tenant_id == "tenant-a"
    assert result.document_id == "doc-1"


def test_erase_document_runs_every_hook_even_if_one_fails() -> None:
    service = ErasureService()
    calls: list[str] = []

    service.register("chunks", lambda t, d: calls.append("chunks"))
    service.register("vectors", lambda t, d: (_ for _ in ()).throw(RuntimeError("qdrant down")))
    service.register("keyword_index", lambda t, d: calls.append("keyword_index"))

    with pytest.raises(ErasureError) as exc_info:
        service.erase_document("tenant-a", "doc-1")

    # both the working hooks still ran, despite the middle one failing
    assert calls == ["chunks", "keyword_index"]
    assert len(exc_info.value.failures) == 1
    assert exc_info.value.failures[0].hook_name == "vectors"
    assert "qdrant down" in exc_info.value.failures[0].error


def test_erase_document_collects_multiple_failures() -> None:
    service = ErasureService()

    def failing(t: str, d: str) -> None:
        raise ValueError("boom")

    service.register("a", failing)
    service.register("b", failing)

    with pytest.raises(ErasureError) as exc_info:
        service.erase_document("tenant-a", "doc-1")

    assert len(exc_info.value.failures) == 2
    assert {f.hook_name for f in exc_info.value.failures} == {"a", "b"}


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
def qdrant_client() -> Generator[QdrantClient, None, None]:
    client = QdrantClient(url=QDRANT_URL)
    ensure_qdrant_collection(client, QDRANT_COLLECTION, dimension=4)
    yield client
    client.delete_collection(QDRANT_COLLECTION)


@pytest.fixture()
def opensearch_client() -> Generator[OpenSearch, None, None]:
    client = OpenSearch(
        hosts=[{"host": "localhost", "port": 9200}], use_ssl=False, verify_certs=False
    )
    client.indices.delete(index=f"{OPENSEARCH_INDEX}_*", ignore=[404])
    ensure_index(client, OPENSEARCH_INDEX)
    yield client
    client.indices.delete(index=f"{OPENSEARCH_INDEX}_*", ignore=[404])


def test_erase_document_removes_data_from_all_three_real_stores(
    session: Session, qdrant_client: QdrantClient, opensearch_client: OpenSearch
) -> None:
    tenant_id = "tenant-a"
    document_id = "doc-1"
    chunk_id = "chunk-1"
    vector_id = str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))

    doc_repo = DocumentRepository(session)
    chunk_repo = ChunkRepository(session)
    vector_store = QdrantVectorStore(qdrant_client, QDRANT_COLLECTION)
    keyword_index = OpenSearchIndex(opensearch_client, OPENSEARCH_INDEX)

    doc_repo.upsert(
        Document(
            id=document_id,
            tenant_id=tenant_id,
            source_uri="s3://bucket/doc-1",
            mime_type="text/html",
            checksum="abc123",
            version=1,
            status="PARSED",
        )
    )
    chunk = Chunk(
        id=chunk_id,
        tenant_id=tenant_id,
        document_id=document_id,
        text="quarterly earnings report",
        position=0,
        language="en",
        version=1,
    )
    chunk_repo.bulk_insert([chunk])
    session.commit()

    vector_store.upsert(
        tenant_id,
        [
            EmbeddingRecord(
                id=vector_id,
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_id=chunk_id,
                vector=[0.1, 0.2, 0.3, 0.4],
                model_id="bge-small",
                model_version="1",
            )
        ],
    )
    keyword_index.upsert(tenant_id, [chunk])

    # sanity check: everything is actually there before erasing
    assert doc_repo.get(tenant_id, document_id) is not None
    assert len(chunk_repo.list_for_document(tenant_id, document_id)) == 1
    pre_vector_hits = qdrant_client.query_points(
        QDRANT_COLLECTION, query=[0.1, 0.2, 0.3, 0.4], limit=10
    )
    assert len(pre_vector_hits.points) == 1
    pre_keyword_hits = opensearch_client.search(
        index=f"{OPENSEARCH_INDEX}_*", body={"query": {"match_all": {}}}
    )
    assert len(pre_keyword_hits["hits"]["hits"]) == 1

    def delete_chunks(t: str, d: str) -> None:
        chunk_repo.hard_delete_for_document(t, d)
        session.commit()

    def delete_document(t: str, d: str) -> None:
        doc_repo.hard_delete(t, d)
        session.commit()

    service = ErasureService()
    service.register("chunks", delete_chunks)
    service.register("documents", delete_document)
    service.register("vectors", vector_store.delete)
    service.register("keyword_index", keyword_index.delete)

    result = service.erase_document(tenant_id, document_id)

    assert set(result.completed_hooks) == {"chunks", "documents", "vectors", "keyword_index"}
    assert doc_repo.get(tenant_id, document_id) is None
    assert chunk_repo.list_for_document(tenant_id, document_id, active_only=False) == []

    vector_hits = qdrant_client.query_points(
        QDRANT_COLLECTION, query=[0.1, 0.2, 0.3, 0.4], limit=10
    )
    assert vector_hits.points == []

    keyword_hits = opensearch_client.search(
        index=f"{OPENSEARCH_INDEX}_*", body={"query": {"match_all": {}}}
    )
    assert keyword_hits["hits"]["hits"] == []
