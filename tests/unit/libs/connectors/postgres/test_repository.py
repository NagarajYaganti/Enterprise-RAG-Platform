from collections.abc import Generator

import pytest
from connectors.postgres.orm import Base
from connectors.postgres.repository import ChunkRepository, DocumentRepository
from connectors.postgres.session import get_engine, get_sessionmaker
from core.models import Chunk, Document
from sqlalchemy.orm import Session

DATABASE_URL = "postgresql+psycopg://rag:rag@localhost:5432/rag_platform"


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


def _make_document(tenant_id: str, doc_id: str, checksum: str, version: int = 1) -> Document:
    return Document(
        id=doc_id,
        tenant_id=tenant_id,
        source_uri=f"s3://bucket/{doc_id}",
        mime_type="application/pdf",
        checksum=checksum,
        version=version,
        status="PARSED",
    )


def _make_chunk(tenant_id: str, doc_id: str, chunk_id: str, version: int = 1) -> Chunk:
    return Chunk(
        id=chunk_id,
        tenant_id=tenant_id,
        document_id=doc_id,
        text="hello world",
        position=0,
        language="en",
        version=version,
    )


def test_document_upsert_and_get(session: Session) -> None:
    repo = DocumentRepository(session)
    doc = _make_document("tenant-a", "doc-1", "checksum-1")

    repo.upsert(doc)
    session.commit()

    fetched = repo.get("tenant-a", "doc-1")
    assert fetched is not None
    assert fetched.checksum == "checksum-1"
    assert fetched.tenant_id == "tenant-a"


def test_document_get_enforces_tenant_scope(session: Session) -> None:
    repo = DocumentRepository(session)
    repo.upsert(_make_document("tenant-a", "doc-1", "checksum-1"))
    session.commit()

    assert repo.get("tenant-b", "doc-1") is None


def test_find_by_checksum_is_tenant_scoped(session: Session) -> None:
    repo = DocumentRepository(session)
    repo.upsert(_make_document("tenant-a", "doc-1", "checksum-shared"))
    session.commit()

    assert repo.find_by_checksum("tenant-a", "checksum-shared") is not None


def test_find_by_source_uri_is_tenant_scoped(session: Session) -> None:
    repo = DocumentRepository(session)
    repo.upsert(_make_document("tenant-a", "doc-1", "checksum-1"))
    session.commit()

    found = repo.find_by_source_uri("tenant-a", "s3://bucket/doc-1")
    assert found is not None
    assert found.id == "doc-1"
    assert repo.find_by_source_uri("tenant-b", "s3://bucket/doc-1") is None
    assert repo.find_by_checksum("tenant-b", "checksum-shared") is None


def test_list_for_tenant_excludes_other_tenants(session: Session) -> None:
    repo = DocumentRepository(session)
    repo.upsert(_make_document("tenant-a", "doc-1", "checksum-1"))
    repo.upsert(_make_document("tenant-b", "doc-2", "checksum-2"))
    session.commit()

    tenant_a_docs = repo.list_for_tenant("tenant-a")
    assert [d.id for d in tenant_a_docs] == ["doc-1"]


def test_chunk_bulk_insert_and_list_for_document(session: Session) -> None:
    chunk_repo = ChunkRepository(session)
    chunks = [_make_chunk("tenant-a", "doc-1", f"chunk-{i}") for i in range(3)]

    chunk_repo.bulk_insert(chunks)
    session.commit()

    listed = chunk_repo.list_for_document("tenant-a", "doc-1")
    assert len(listed) == 3
    assert all(c.status == "active" for c in listed)


def test_chunk_list_for_document_enforces_tenant_scope(session: Session) -> None:
    chunk_repo = ChunkRepository(session)
    chunk_repo.bulk_insert([_make_chunk("tenant-a", "doc-1", "chunk-1")])
    session.commit()

    assert chunk_repo.list_for_document("tenant-b", "doc-1") == []


def test_supersede_for_document_flips_status_and_is_tenant_scoped(session: Session) -> None:
    chunk_repo = ChunkRepository(session)
    chunk_repo.bulk_insert(
        [
            _make_chunk("tenant-a", "doc-1", "chunk-1", version=1),
            _make_chunk("tenant-b", "doc-1", "chunk-2", version=1),
        ]
    )
    session.commit()

    superseded_count = chunk_repo.supersede_for_document("tenant-a", "doc-1")
    session.commit()

    assert superseded_count == 1
    assert chunk_repo.list_for_document("tenant-a", "doc-1", active_only=True) == []
    all_chunks_a = chunk_repo.list_for_document("tenant-a", "doc-1", active_only=False)
    assert all_chunks_a[0].status == "superseded"

    # tenant-b's chunk for the "same" document id must be unaffected
    tenant_b_chunks = chunk_repo.list_for_document("tenant-b", "doc-1")
    assert len(tenant_b_chunks) == 1
    assert tenant_b_chunks[0].status == "active"
