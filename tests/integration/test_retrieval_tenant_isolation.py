import base64
import json
from collections.abc import Generator

import pytest
from connectors.embeddings.sentence_transformers_provider import SentenceTransformersProvider
from connectors.keyword.opensearch_index import OpenSearchIndex, ensure_index
from connectors.postgres.repository import ChunkRepository, DocumentRepository
from connectors.vectorstores.qdrant_store import QdrantVectorStore
from core.models import Chunk, Document
from embedding.worker import COLLECTION_NAME, INDEX_NAME, process_embedding_job
from fastapi.testclient import TestClient
from opensearchpy import OpenSearch
from qdrant_client import QdrantClient
from retrieval.main import app
from sqlalchemy.orm import Session

MODEL_ID = "BAAI/bge-small-en-v1.5"


def _make_token(tenant_id: str) -> str:
    raw = json.dumps({"tenant_id": tenant_id}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def embedding_provider() -> SentenceTransformersProvider:
    return SentenceTransformersProvider(MODEL_ID)


def _seed_and_embed(
    db_session: Session,
    embedding_provider: SentenceTransformersProvider,
    tenant_id: str,
    document_id: str,
    text: str,
) -> None:
    doc_repo = DocumentRepository(db_session)
    chunk_repo = ChunkRepository(db_session)
    doc_repo.upsert(
        Document(
            id=document_id,
            tenant_id=tenant_id,
            source_uri=f"iso://{document_id}",
            mime_type="text/plain",
            checksum=document_id,
            version=1,
            status="PARSED",
        )
    )
    chunk_repo.bulk_insert(
        [
            Chunk(
                id=document_id,
                tenant_id=tenant_id,
                document_id=document_id,
                text=text,
                position=0,
                language="en",
                version=1,
                acl_principals=["public"],
            )
        ]
    )
    db_session.commit()

    qdrant_client = QdrantClient(url="http://localhost:6333")
    vector_store = QdrantVectorStore(qdrant_client, COLLECTION_NAME)
    opensearch_client = OpenSearch(
        hosts=[{"host": "localhost", "port": 9200}], use_ssl=False, verify_certs=False
    )
    ensure_index(opensearch_client, INDEX_NAME)
    keyword_index = OpenSearchIndex(opensearch_client, INDEX_NAME)
    process_embedding_job(
        db_session,
        vector_store,
        keyword_index,
        embedding_provider,
        tenant_id,
        document_id,
        MODEL_ID,
        "1",
    )


def test_identical_documents_for_two_tenants_search_returns_own_tenant_only(
    client: TestClient,
    db_session: Session,
    clean_embedding_stores: None,
    embedding_provider: SentenceTransformersProvider,
) -> None:
    # document_id is the table's global primary key (matching real
    # ingestion's uuid5(tenant_id, filename) pattern from Phase 1) — not
    # tenant-scoped, so identical content for two tenants still needs
    # distinct ids, exactly like production would derive them.
    text = "Prescription refill requests are processed within twenty four hours of receipt."
    _seed_and_embed(db_session, embedding_provider, "tenant-iso-a", "doc-iso-1-a", text)
    _seed_and_embed(db_session, embedding_provider, "tenant-iso-b", "doc-iso-1-b", text)

    for tenant_id in ("tenant-iso-a", "tenant-iso-b"):
        token = _make_token(tenant_id)
        response = client.post(
            "/v1/retrieve",
            json={
                "text": "How long does a prescription refill take?",
                "session_id": "s-1",
                "principals": ["public"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["chunks"]) == 1
        expected_suffix = "a" if tenant_id == "tenant-iso-a" else "b"
        assert body["chunks"][0]["document_id"] == f"doc-iso-1-{expected_suffix}"


def test_tenant_a_cannot_retrieve_tenant_bs_chunks(
    client: TestClient,
    db_session: Session,
    clean_embedding_stores: None,
    embedding_provider: SentenceTransformersProvider,
) -> None:
    _seed_and_embed(
        db_session,
        embedding_provider,
        "tenant-iso-only-b",
        "doc-iso-only-b",
        "Claims processing for outpatient procedures takes fourteen business days.",
    )

    token = _make_token("tenant-iso-only-a")
    response = client.post(
        "/v1/retrieve",
        json={
            "text": "How long does outpatient claims processing take?",
            "session_id": "s-1",
            "principals": ["public"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["chunks"] == []
