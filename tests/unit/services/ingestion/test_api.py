import base64
import json
import uuid
from collections.abc import Generator
from pathlib import Path
from typing import Any

import boto3
import pytest
from botocore.config import Config
from connectors.keyword.opensearch_index import OpenSearchIndex, ensure_index
from connectors.postgres.orm import Base
from connectors.postgres.repository import ChunkRepository, DocumentRepository
from connectors.postgres.session import get_engine, get_sessionmaker
from connectors.vectorstores.migrations import ensure_qdrant_collection
from connectors.vectorstores.qdrant_store import QdrantVectorStore
from core.model_registry import get_default_embedding_model
from core.models import Chunk, Document, EmbeddingRecord
from fastapi.testclient import TestClient
from ingestion.main import app
from opensearchpy import OpenSearch
from orchestrator.semantic_cache import SemanticCache
from qdrant_client import QdrantClient
from sqlalchemy.orm import Session

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "documents"
DATABASE_URL = "postgresql+psycopg://rag:rag@localhost:5432/rag_platform"
SYNC_BUCKET = "rag-documents"
CHUNKS_COLLECTION_NAME = "chunks"
CHUNKS_INDEX_NAME = "chunks"
CACHE_COLLECTION_NAME = "semantic_cache"


def _make_token(tenant_id: str) -> str:
    raw = json.dumps({"tenant_id": tenant_id}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


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
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


def test_upload_without_auth_is_rejected(client: TestClient) -> None:
    with open(FIXTURES / "sample.html", "rb") as f:
        response = client.post("/v1/documents", files={"file": ("sample.html", f, "text/html")})

    assert response.status_code == 401


def test_upload_creates_uploaded_document_and_enqueues_job(
    client: TestClient, session: Session
) -> None:
    token = _make_token("tenant-acme")
    with open(FIXTURES / "sample.html", "rb") as f:
        response = client.post(
            "/v1/documents",
            files={"file": ("sample.html", f, "text/html")},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "UPLOADED"
    document_id = body["id"]

    document_repo = DocumentRepository(session)
    document = document_repo.get("tenant-acme", document_id)
    assert document is not None
    assert document.status == "UPLOADED"
    assert document.mime_type == "text/html"


def test_get_status_for_nonexistent_document_is_404(client: TestClient) -> None:
    token = _make_token("tenant-acme")
    response = client.get(
        "/v1/documents/does-not-exist", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404


@pytest.fixture()
def s3_client() -> Generator[Any, None, None]:
    client = boto3.client(
        "s3",
        endpoint_url="http://localhost:9000",
        aws_access_key_id="ragadmin",
        aws_secret_access_key="ragadminsecret",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        region_name="us-east-1",
    )
    try:
        client.create_bucket(Bucket=SYNC_BUCKET)
    except client.exceptions.BucketAlreadyOwnedByYou:
        pass
    for obj in client.list_objects_v2(Bucket=SYNC_BUCKET, Prefix="tenant-sync/").get(
        "Contents", []
    ):
        client.delete_object(Bucket=SYNC_BUCKET, Key=obj["Key"])
    yield client


def test_sync_endpoint_ingests_a_document_dropped_directly_in_the_bucket(
    client: TestClient, session: Session, s3_client: Any
) -> None:
    # Proves POST /v1/sync/blob drives the real, previously-unwired
    # BlobSourceConnector end-to-end through the actual HTTP layer -- a file
    # placed straight in the bucket (as an external source connector would
    # deliver it), never touching the /v1/documents upload endpoint at all.
    s3_client.upload_file(str(FIXTURES / "sample.html"), SYNC_BUCKET, "tenant-sync/sample.html")

    token = _make_token("tenant-sync")
    response = client.post("/v1/sync/blob", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-sync"
    assert body["documents_processed"] == 1
    assert body["documents_deleted"] == 0

    document = DocumentRepository(session).get("tenant-sync", "tenant-sync/sample.html")
    assert document is not None
    assert document.status == "PARSED"
    chunks = ChunkRepository(session).list_for_document("tenant-sync", "tenant-sync/sample.html")
    assert any("Onboarding Runbook" in c.text for c in chunks)


def test_sync_endpoint_rejects_unknown_connector_name(client: TestClient) -> None:
    token = _make_token("tenant-sync")
    response = client.post("/v1/sync/sharepoint", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404


@pytest.fixture()
def erasure_stores() -> Generator[tuple[QdrantClient, OpenSearch], None, None]:
    embedding_model = get_default_embedding_model()
    qdrant_client = QdrantClient(url="http://localhost:6333")
    ensure_qdrant_collection(
        qdrant_client, CHUNKS_COLLECTION_NAME, dimension=embedding_model["dimensions"]
    )
    ensure_qdrant_collection(
        qdrant_client, CACHE_COLLECTION_NAME, dimension=embedding_model["dimensions"]
    )
    opensearch_client = OpenSearch(
        hosts=[{"host": "localhost", "port": 9200}], use_ssl=False, verify_certs=False
    )
    ensure_index(opensearch_client, CHUNKS_INDEX_NAME)
    yield qdrant_client, opensearch_client


def _seed_document_for_erasure(
    session: Session,
    qdrant_client: QdrantClient,
    opensearch_client: OpenSearch,
    tenant_id: str,
    document_id: str,
    chunk_id: str,
) -> None:
    document_repo = DocumentRepository(session)
    chunk_repo = ChunkRepository(session)
    document_repo.upsert(
        Document(
            id=document_id,
            tenant_id=tenant_id,
            source_uri=f"s3://bucket/{document_id}",
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
        text="quarterly compliance report",
        position=0,
        language="en",
        version=1,
        search_analyzer="english",
    )
    chunk_repo.bulk_insert([chunk])
    session.commit()

    vector_id = str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))
    embedding_model = get_default_embedding_model()
    vector = [0.1] * embedding_model["dimensions"]
    QdrantVectorStore(qdrant_client, CHUNKS_COLLECTION_NAME).upsert(
        tenant_id,
        [
            EmbeddingRecord(
                id=vector_id,
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_id=chunk_id,
                vector=vector,
                model_id=embedding_model["id"],
                model_version=embedding_model["version"],
            )
        ],
    )
    OpenSearchIndex(opensearch_client, CHUNKS_INDEX_NAME).upsert(tenant_id, [chunk])

    query_vector = [0.1] * embedding_model["dimensions"]
    SemanticCache(qdrant_client, CACHE_COLLECTION_NAME, 0.95, 3600).put(
        tenant_id,
        principals=["p1"],
        query_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"query:{document_id}")),
        query_vector=query_vector,
        answer_text=f"Cached answer citing [{chunk_id}]",
        document_ids=[document_id],
        cited_chunk_ids=[chunk_id],
        model_id="claude-sonnet-5",
    )


def test_delete_document_removes_it_from_all_four_real_stores(
    client: TestClient,
    session: Session,
    erasure_stores: tuple[QdrantClient, OpenSearch],
) -> None:
    qdrant_client, opensearch_client = erasure_stores
    tenant_id = "tenant-erase"
    document_id = "doc-erase-1"
    chunk_id = "chunk-erase-1"
    _seed_document_for_erasure(
        session, qdrant_client, opensearch_client, tenant_id, document_id, chunk_id
    )

    # sanity check: everything real and present before erasing. Exact
    # point-id retrieval (not a nearest-neighbor query_points search) so
    # unrelated real vectors from other tests sharing this same production
    # collection can never affect this assertion either way.
    vector_id = str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))
    cache_query_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"query:{document_id}"))
    assert DocumentRepository(session).get(tenant_id, document_id) is not None
    assert len(ChunkRepository(session).list_for_document(tenant_id, document_id)) == 1
    assert qdrant_client.retrieve(CHUNKS_COLLECTION_NAME, ids=[vector_id]) != []
    assert qdrant_client.retrieve(CACHE_COLLECTION_NAME, ids=[cache_query_id]) != []

    token = _make_token(tenant_id)
    response = client.delete(
        f"/v1/documents/{document_id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    completed_hooks = set(response.json()["completed_hooks"])
    assert completed_hooks == {"chunks", "vectors", "keyword_index", "semantic_cache", "document"}

    assert DocumentRepository(session).get(tenant_id, document_id) is None
    assert (
        ChunkRepository(session).list_for_document(tenant_id, document_id, active_only=False)
        == []
    )
    assert qdrant_client.retrieve(CHUNKS_COLLECTION_NAME, ids=[vector_id]) == []
    assert qdrant_client.retrieve(CACHE_COLLECTION_NAME, ids=[cache_query_id]) == []
    keyword_hits = opensearch_client.search(
        index=f"{CHUNKS_INDEX_NAME}_*", body={"query": {"term": {"document_id": document_id}}}
    )
    assert keyword_hits["hits"]["hits"] == []


def test_delete_nonexistent_document_is_404(client: TestClient) -> None:
    token = _make_token("tenant-erase")
    response = client.delete(
        "/v1/documents/does-not-exist", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404


def test_delete_enforces_tenant_isolation(
    client: TestClient,
    session: Session,
    erasure_stores: tuple[QdrantClient, OpenSearch],
) -> None:
    qdrant_client, opensearch_client = erasure_stores
    tenant_a = "tenant-erase-a"
    document_id = "doc-erase-2"
    _seed_document_for_erasure(
        session, qdrant_client, opensearch_client, tenant_a, document_id, "chunk-erase-2"
    )

    token_b = _make_token("tenant-erase-b")
    response = client.delete(
        f"/v1/documents/{document_id}", headers={"Authorization": f"Bearer {token_b}"}
    )

    assert response.status_code == 404
    # tenant A's document must survive tenant B's attempt untouched
    assert DocumentRepository(session).get(tenant_a, document_id) is not None


def test_get_status_enforces_tenant_isolation(client: TestClient, session: Session) -> None:
    token_a = _make_token("tenant-a")
    with open(FIXTURES / "sample.html", "rb") as f:
        upload_response = client.post(
            "/v1/documents",
            files={"file": ("sample.html", f, "text/html")},
            headers={"Authorization": f"Bearer {token_a}"},
        )
    document_id = upload_response.json()["id"]

    token_b = _make_token("tenant-b")
    response = client.get(
        f"/v1/documents/{document_id}", headers={"Authorization": f"Bearer {token_b}"}
    )

    assert response.status_code == 404
