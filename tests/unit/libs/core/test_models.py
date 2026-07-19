from datetime import datetime, timezone

import pytest
from core.models import (
    Chunk,
    Completion,
    Document,
    EmbeddingRecord,
    Query,
    RetrievalResult,
    ScoredChunk,
    Tenant,
)
from pydantic import ValidationError

TENANT_ID = "tenant-acme"


def test_tenant_requires_tenant_id() -> None:
    tenant = Tenant(tenant_id=TENANT_ID, name="Acme", created_at=datetime.now(timezone.utc))
    assert tenant.tenant_id == TENANT_ID
    with pytest.raises(ValidationError):
        Tenant(name="Acme", created_at=datetime.now(timezone.utc))  # type: ignore[call-arg]


def test_document_requires_tenant_id() -> None:
    doc = Document(
        id="doc-1",
        tenant_id=TENANT_ID,
        source_uri="s3://bucket/file.pdf",
        mime_type="application/pdf",
        checksum="abc123",
        version=1,
        status="PARSED",
    )
    assert doc.tenant_id == TENANT_ID
    with pytest.raises(ValidationError):
        Document(
            id="doc-1",
            source_uri="s3://bucket/file.pdf",
            mime_type="application/pdf",
            checksum="abc123",
            version=1,
            status="PARSED",
        )  # type: ignore[call-arg]


def test_chunk_requires_tenant_id() -> None:
    chunk = Chunk(
        id="chunk-1", tenant_id=TENANT_ID, document_id="doc-1", text="hello", position=0
    )
    assert chunk.tenant_id == TENANT_ID
    with pytest.raises(ValidationError):
        Chunk(id="chunk-1", document_id="doc-1", text="hello", position=0)  # type: ignore[call-arg]


def test_embedding_record_requires_tenant_id() -> None:
    record = EmbeddingRecord(
        id="emb-1",
        tenant_id=TENANT_ID,
        chunk_id="chunk-1",
        vector=[0.1, 0.2],
        model_id="bge-small",
        model_version="1",
    )
    assert record.tenant_id == TENANT_ID
    with pytest.raises(ValidationError):
        EmbeddingRecord(
            id="emb-1",
            chunk_id="chunk-1",
            vector=[0.1, 0.2],
            model_id="bge-small",
            model_version="1",
        )  # type: ignore[call-arg]


def test_query_requires_tenant_id() -> None:
    query = Query(id="q-1", tenant_id=TENANT_ID, session_id="s-1", text="hi")
    assert query.tenant_id == TENANT_ID
    with pytest.raises(ValidationError):
        Query(id="q-1", session_id="s-1", text="hi")  # type: ignore[call-arg]


def test_retrieval_result_requires_tenant_id() -> None:
    chunk = Chunk(
        id="chunk-1", tenant_id=TENANT_ID, document_id="doc-1", text="hello", position=0
    )
    result = RetrievalResult(
        tenant_id=TENANT_ID,
        query_id="q-1",
        chunks=[ScoredChunk(chunk=chunk, score=0.9)],
    )
    assert result.tenant_id == TENANT_ID
    with pytest.raises(ValidationError):
        RetrievalResult(query_id="q-1", chunks=[])  # type: ignore[call-arg]


def test_completion_requires_tenant_id() -> None:
    completion = Completion(tenant_id=TENANT_ID, model_id="gpt-x", text="answer")
    assert completion.tenant_id == TENANT_ID
    with pytest.raises(ValidationError):
        Completion(model_id="gpt-x", text="answer")  # type: ignore[call-arg]
