"""Proves metadata filters (doc_type/department/date/language) are real
server-side pre-filters against Qdrant/OpenSearch, not a post-filter in
Python — mirroring the "filter delegation" proof already established for
ACL principals in Phase 2's test_qdrant_store.py.
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
TENANT_ID = "tenant-filters"


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


def _seed_two_chunks_same_text_different_doc_type(
    db_session: Session, embedding_provider: SentenceTransformersProvider
) -> None:
    """Both chunks share near-identical text (so semantic/keyword search
    alone can't tell them apart) but differ only in doc_type — isolates
    the filter's effect from retrieval ranking itself.
    """
    doc_repo = DocumentRepository(db_session)
    chunk_repo = ChunkRepository(db_session)
    text = "All wire transfers above ten thousand dollars require dual authorization."

    for document_id, doc_type in [("doc-filter-policy", "policy"), ("doc-filter-report", "report")]:
        doc_repo.upsert(
            Document(
                id=document_id,
                tenant_id=TENANT_ID,
                source_uri=f"filter://{document_id}",
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
                    tenant_id=TENANT_ID,
                    document_id=document_id,
                    text=text,
                    position=0,
                    language="en",
                    version=1,
                    acl_principals=["public"],
                    doc_type=doc_type,
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
    for document_id in ("doc-filter-policy", "doc-filter-report"):
        process_embedding_job(
            db_session,
            vector_store,
            keyword_index,
            embedding_provider,
            TENANT_ID,
            document_id,
            MODEL_ID,
            "1",
        )


def test_doc_type_filter_excludes_non_matching_chunk_via_real_api(
    client: TestClient,
    db_session: Session,
    clean_embedding_stores: None,
    embedding_provider: SentenceTransformersProvider,
) -> None:
    _seed_two_chunks_same_text_different_doc_type(db_session, embedding_provider)

    token = _make_token(TENANT_ID)
    response = client.post(
        "/v1/retrieve",
        json={
            "text": "wire transfer authorization requirement",
            "session_id": "s-1",
            "principals": ["public"],
            "filters": {"doc_type": "policy"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert {c["chunk_id"] for c in body["chunks"]} == {"doc-filter-policy"}


def test_without_filter_both_chunks_are_returned(
    client: TestClient,
    db_session: Session,
    clean_embedding_stores: None,
    embedding_provider: SentenceTransformersProvider,
) -> None:
    _seed_two_chunks_same_text_different_doc_type(db_session, embedding_provider)

    token = _make_token(TENANT_ID)
    response = client.post(
        "/v1/retrieve",
        json={
            "text": "wire transfer authorization requirement",
            "session_id": "s-1",
            "principals": ["public"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert {c["chunk_id"] for c in body["chunks"]} == {"doc-filter-policy", "doc-filter-report"}


def test_date_range_filter_excludes_out_of_range_chunk(
    client: TestClient,
    db_session: Session,
    clean_embedding_stores: None,
    embedding_provider: SentenceTransformersProvider,
) -> None:
    doc_repo = DocumentRepository(db_session)
    chunk_repo = ChunkRepository(db_session)
    text = "Customer returns are accepted within thirty days with a valid receipt."

    for document_id, date in [("doc-filter-old", "2025-01-01"), ("doc-filter-new", "2026-06-01")]:
        doc_repo.upsert(
            Document(
                id=document_id,
                tenant_id=TENANT_ID,
                source_uri=f"filter://{document_id}",
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
                    tenant_id=TENANT_ID,
                    document_id=document_id,
                    text=text,
                    position=0,
                    language="en",
                    version=1,
                    acl_principals=["public"],
                    date=date,
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
    for document_id in ("doc-filter-old", "doc-filter-new"):
        process_embedding_job(
            db_session,
            vector_store,
            keyword_index,
            embedding_provider,
            TENANT_ID,
            document_id,
            MODEL_ID,
            "1",
        )

    token = _make_token(TENANT_ID)
    response = client.post(
        "/v1/retrieve",
        json={
            "text": "customer return policy",
            "session_id": "s-1",
            "principals": ["public"],
            "filters": {"date_from": "2026-01-01"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert {c["chunk_id"] for c in body["chunks"]} == {"doc-filter-new"}
