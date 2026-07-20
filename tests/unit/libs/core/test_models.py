from datetime import datetime, timezone

import pytest
from core.models import (
    ChatTurn,
    Chunk,
    Completion,
    Document,
    EmbeddingRecord,
    Entity,
    KeywordSearchHit,
    ParsedDocument,
    Query,
    Relation,
    RetrievalFilters,
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


def test_chunk_phase3_filter_fields_default_none() -> None:
    chunk = Chunk(
        id="chunk-1",
        tenant_id=TENANT_ID,
        document_id="doc-1",
        text="hello",
        position=0,
        language="en",
        version=1,
    )
    assert chunk.doc_type is None
    assert chunk.department is None
    assert chunk.date is None


def test_chunk_phase3_filter_fields_can_be_set() -> None:
    chunk = Chunk(
        id="chunk-1",
        tenant_id=TENANT_ID,
        document_id="doc-1",
        text="hello",
        position=0,
        language="en",
        version=1,
        doc_type="policy",
        department="lending",
        date="2026-01-01",
    )
    assert chunk.doc_type == "policy"
    assert chunk.department == "lending"
    assert chunk.date == "2026-01-01"


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


def test_embedding_record_phase3_filter_fields_default_empty_or_none() -> None:
    record = EmbeddingRecord(
        id="emb-1",
        tenant_id=TENANT_ID,
        document_id="doc-1",
        chunk_id="chunk-1",
        vector=[0.1, 0.2],
        model_id="bge-small",
        model_version="1",
    )
    assert record.language == ""
    assert record.doc_type is None
    assert record.department is None
    assert record.date is None


def test_embedding_record_phase3_filter_fields_can_be_set() -> None:
    record = EmbeddingRecord(
        id="emb-1",
        tenant_id=TENANT_ID,
        document_id="doc-1",
        chunk_id="chunk-1",
        vector=[0.1, 0.2],
        model_id="bge-small",
        model_version="1",
        language="en",
        doc_type="policy",
        department="lending",
        date="2026-01-01",
    )
    assert record.language == "en"
    assert record.doc_type == "policy"
    assert record.department == "lending"
    assert record.date == "2026-01-01"


def test_query_user_id_defaults_empty_and_can_be_set() -> None:
    query = Query(id="q-1", tenant_id=TENANT_ID, session_id="s-1", text="hi")
    assert query.user_id == ""

    query_with_user = Query(
        id="q-2", tenant_id=TENANT_ID, session_id="s-1", text="hi", user_id="user-1"
    )
    assert query_with_user.user_id == "user-1"


def test_retrieval_filters_all_dimensions_default_to_unconstrained() -> None:
    filters = RetrievalFilters()
    assert filters.language is None
    assert filters.doc_type is None
    assert filters.department is None
    assert filters.date_from is None
    assert filters.date_to is None


def test_retrieval_filters_can_set_each_dimension() -> None:
    filters = RetrievalFilters(
        language="en",
        doc_type="policy",
        department="lending",
        date_from="2026-01-01",
        date_to="2026-12-31",
    )
    assert filters.language == "en"
    assert filters.doc_type == "policy"
    assert filters.department == "lending"
    assert filters.date_from == "2026-01-01"
    assert filters.date_to == "2026-12-31"


def test_chat_turn_requires_tenant_user_and_session() -> None:
    turn = ChatTurn(
        id="turn-1",
        tenant_id=TENANT_ID,
        user_id="user-1",
        session_id="session-1",
        role="user",
        text="what is the deadline?",
        created_at=datetime.now(timezone.utc),
    )
    assert turn.tenant_id == TENANT_ID
    assert turn.user_id == "user-1"
    assert turn.session_id == "session-1"
    with pytest.raises(ValidationError):
        ChatTurn(
            id="turn-1",
            user_id="user-1",
            session_id="session-1",
            role="user",
            text="hi",
            created_at=datetime.now(timezone.utc),
        )  # type: ignore[call-arg]


def test_chat_turn_role_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        ChatTurn(
            id="turn-1",
            tenant_id=TENANT_ID,
            user_id="user-1",
            session_id="session-1",
            role="system",  # type: ignore[arg-type]
            text="hi",
            created_at=datetime.now(timezone.utc),
        )


def test_entity_requires_tenant_id() -> None:
    entity = Entity(
        id="ent-1",
        tenant_id=TENANT_ID,
        document_id="doc-1",
        chunk_id="chunk-1",
        name="Acme Bank",
        label="ORG",
    )
    assert entity.tenant_id == TENANT_ID
    with pytest.raises(ValidationError):
        Entity(
            id="ent-1", document_id="doc-1", chunk_id="chunk-1", name="Acme Bank", label="ORG"
        )  # type: ignore[call-arg]


def test_relation_requires_tenant_id() -> None:
    relation = Relation(
        id="rel-1",
        tenant_id=TENANT_ID,
        subject_entity_id="ent-1",
        predicate="co_occurs_with",
        object_entity_id="ent-2",
        chunk_id="chunk-1",
    )
    assert relation.tenant_id == TENANT_ID
    with pytest.raises(ValidationError):
        Relation(
            id="rel-1",
            subject_entity_id="ent-1",
            predicate="co_occurs_with",
            object_entity_id="ent-2",
            chunk_id="chunk-1",
        )  # type: ignore[call-arg]


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
