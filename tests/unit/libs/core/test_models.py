from datetime import datetime, timezone

import pytest
from core.models import (
    Chunk,
    Completion,
    Document,
    EmbeddingRecord,
    KeywordSearchHit,
    ParsedDocument,
    Query,
    RetrievalResult,
    ScoredChunk,
    Tenant,
    Vector,
    VectorSearchHit,
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


def test_document_status_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        Document(
            id="doc-1",
            tenant_id=TENANT_ID,
            source_uri="s3://bucket/file.pdf",
            mime_type="application/pdf",
            checksum="abc123",
            version=1,
            status="NOT_A_REAL_STATUS",  # type: ignore[arg-type]
        )


def test_document_acl_principals_defaults_empty_and_can_be_set() -> None:
    doc = Document(
        id="doc-1",
        tenant_id=TENANT_ID,
        source_uri="s3://bucket/file.pdf",
        mime_type="application/pdf",
        checksum="abc123",
        version=1,
        status="UPLOADED",
    )
    assert doc.acl_principals == []

    doc_with_acl = Document(
        id="doc-2",
        tenant_id=TENANT_ID,
        source_uri="s3://bucket/file2.pdf",
        mime_type="application/pdf",
        checksum="def456",
        version=1,
        status="UPLOADED",
        acl_principals=["msgraph:user:abc123"],
    )
    assert doc_with_acl.acl_principals == ["msgraph:user:abc123"]


def test_parsed_document_requires_tenant_id() -> None:
    parsed = ParsedDocument(
        tenant_id=TENANT_ID,
        document_id="doc-1",
        raw_text="hello world",
        structural_elements=[{"category": "Title", "text": "hello"}],
        mime_type="text/html",
        source_uri="s3://bucket/file.html",
        checksum="abc123",
    )
    assert parsed.tenant_id == TENANT_ID
    assert parsed.acl_principals == []
    with pytest.raises(ValidationError):
        ParsedDocument(
            document_id="doc-1",
            raw_text="hello world",
            mime_type="text/html",
            source_uri="s3://bucket/file.html",
            checksum="abc123",
        )  # type: ignore[call-arg]


def test_chunk_requires_tenant_id() -> None:
    chunk = Chunk(
        id="chunk-1",
        tenant_id=TENANT_ID,
        document_id="doc-1",
        text="hello",
        position=0,
        language="en",
        version=1,
    )
    assert chunk.tenant_id == TENANT_ID
    with pytest.raises(ValidationError):
        Chunk(id="chunk-1", document_id="doc-1", text="hello", position=0)  # type: ignore[call-arg]


def test_chunk_defaults_active_status_and_empty_acl() -> None:
    chunk = Chunk(
        id="chunk-1",
        tenant_id=TENANT_ID,
        document_id="doc-1",
        text="hello",
        position=0,
        language="en",
        version=1,
    )
    assert chunk.status == "active"
    assert chunk.acl_principals == []


def test_chunk_status_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        Chunk(
            id="chunk-1",
            tenant_id=TENANT_ID,
            document_id="doc-1",
            text="hello",
            position=0,
            language="en",
            version=1,
            status="not-a-real-status",  # type: ignore[arg-type]
        )


def test_embedding_record_requires_tenant_id() -> None:
    record = EmbeddingRecord(
        id="emb-1",
        tenant_id=TENANT_ID,
        document_id="doc-1",
        chunk_id="chunk-1",
        vector=[0.1, 0.2],
        model_id="bge-small",
        model_version="1",
    )
    assert record.tenant_id == TENANT_ID
    with pytest.raises(ValidationError):
        EmbeddingRecord(
            id="emb-1",
            document_id="doc-1",
            chunk_id="chunk-1",
            vector=[0.1, 0.2],
            model_id="bge-small",
            model_version="1",
        )  # type: ignore[call-arg]


def test_embedding_record_defaults_active_status_and_empty_acl() -> None:
    record = EmbeddingRecord(
        id="emb-1",
        tenant_id=TENANT_ID,
        document_id="doc-1",
        chunk_id="chunk-1",
        vector=[0.1, 0.2],
        model_id="bge-small",
        model_version="1",
    )
    assert record.status == "active"
    assert record.acl_principals == []


def test_embedding_record_status_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        EmbeddingRecord(
            id="emb-1",
            tenant_id=TENANT_ID,
            document_id="doc-1",
            chunk_id="chunk-1",
            vector=[0.1, 0.2],
            model_id="bge-small",
            model_version="1",
            status="not-a-real-status",  # type: ignore[arg-type]
        )


def test_vector_type_alias_is_list_of_float() -> None:
    v: Vector = [0.1, 0.2, 0.3]
    assert v == [0.1, 0.2, 0.3]
    assert Vector == list[float]


def test_vector_search_hit_is_vendor_neutral() -> None:
    hit = VectorSearchHit(chunk_id="chunk-1", document_id="doc-1", score=0.87, model_id="bge-small")
    assert hit.chunk_id == "chunk-1"
    assert hit.score == 0.87


def test_keyword_search_hit_has_no_model_id() -> None:
    hit = KeywordSearchHit(chunk_id="chunk-1", document_id="doc-1", score=4.2)
    assert hit.chunk_id == "chunk-1"
    assert not hasattr(hit, "model_id")


def test_query_requires_tenant_id() -> None:
    query = Query(id="q-1", tenant_id=TENANT_ID, session_id="s-1", text="hi")
    assert query.tenant_id == TENANT_ID
    with pytest.raises(ValidationError):
        Query(id="q-1", session_id="s-1", text="hi")  # type: ignore[call-arg]


def test_retrieval_result_requires_tenant_id() -> None:
    chunk = Chunk(
        id="chunk-1",
        tenant_id=TENANT_ID,
        document_id="doc-1",
        text="hello",
        position=0,
        language="en",
        version=1,
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
