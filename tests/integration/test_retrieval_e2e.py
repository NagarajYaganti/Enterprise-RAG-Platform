"""Exit checklist proof via the real HTTP API (not a direct pipeline.retrieve()
call, unlike test_retrieval_eval_harness.py) — exercises the full real
service: main.py's lifespan, TenantContextMiddleware, api.py's request/
response cycle, and pipeline.retrieve() underneath it.
"""

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
    principals: list[str],
    **fields: str | None,
) -> None:
    doc_repo = DocumentRepository(db_session)
    chunk_repo = ChunkRepository(db_session)
    doc_repo.upsert(
        Document(
            id=document_id,
            tenant_id=tenant_id,
            source_uri=f"e2e://{document_id}",
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
                acl_principals=principals,
                **fields,  # type: ignore[arg-type]
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


def test_retrieve_via_real_api_finds_the_seeded_chunk(
    client: TestClient,
    db_session: Session,
    clean_embedding_stores: None,
    embedding_provider: SentenceTransformersProvider,
) -> None:
    _seed_and_embed(
        db_session,
        embedding_provider,
        "tenant-e2e",
        "doc-e2e-1",
        "Loan applications must be reviewed within five business days.",
        ["public"],
    )

    token = _make_token("tenant-e2e")
    response = client.post(
        "/v1/retrieve",
        json={
            "text": "How quickly are loan applications reviewed?",
            "session_id": "s-1",
            "principals": ["public"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["chunks"]) >= 1
    assert body["chunks"][0]["chunk_id"] == "doc-e2e-1"
    expected_text = "Loan applications must be reviewed within five business days."
    assert body["chunks"][0]["text"] == expected_text


def test_retrieve_via_real_api_returns_no_chunks_without_matching_principals(
    client: TestClient,
    db_session: Session,
    clean_embedding_stores: None,
    embedding_provider: SentenceTransformersProvider,
) -> None:
    _seed_and_embed(
        db_session,
        embedding_provider,
        "tenant-e2e",
        "doc-e2e-2",
        "Revenue grew twelve percent quarter over quarter.",
        ["restricted-group"],
    )

    token = _make_token("tenant-e2e")
    response = client.post(
        "/v1/retrieve",
        json={
            "text": "How much did revenue grow?",
            "session_id": "s-2",
            "principals": ["some-other-group"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["chunks"] == []
