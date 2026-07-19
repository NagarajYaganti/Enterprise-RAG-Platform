from collections.abc import Generator

import pytest
from connectors.postgres.orm import Base
from connectors.postgres.repository import DocumentRepository
from connectors.postgres.session import get_engine, get_sessionmaker
from core.models import Document
from ingestion.dedupe import determine_version
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


def test_new_source_uri_gets_version_one(session: Session) -> None:
    repo = DocumentRepository(session)

    decision = determine_version(repo, "tenant-a", "s3://bucket/new-doc.pdf", "checksum-1")

    assert decision.version == 1
    assert decision.is_exact_duplicate is False


def test_reupload_with_same_checksum_is_exact_duplicate(session: Session) -> None:
    repo = DocumentRepository(session)
    repo.upsert(
        Document(
            id="doc-1",
            tenant_id="tenant-a",
            source_uri="s3://bucket/doc.pdf",
            mime_type="application/pdf",
            checksum="checksum-1",
            version=1,
            status="PARSED",
        )
    )
    session.commit()

    decision = determine_version(repo, "tenant-a", "s3://bucket/doc.pdf", "checksum-1")

    assert decision.version == 1
    assert decision.is_exact_duplicate is True


def test_reupload_with_different_checksum_bumps_version(session: Session) -> None:
    repo = DocumentRepository(session)
    repo.upsert(
        Document(
            id="doc-1",
            tenant_id="tenant-a",
            source_uri="s3://bucket/doc.pdf",
            mime_type="application/pdf",
            checksum="checksum-1",
            version=1,
            status="PARSED",
        )
    )
    session.commit()

    decision = determine_version(repo, "tenant-a", "s3://bucket/doc.pdf", "checksum-2")

    assert decision.version == 2
    assert decision.is_exact_duplicate is False


def test_reupload_is_tenant_scoped(session: Session) -> None:
    repo = DocumentRepository(session)
    repo.upsert(
        Document(
            id="doc-1",
            tenant_id="tenant-a",
            source_uri="s3://bucket/doc.pdf",
            mime_type="application/pdf",
            checksum="checksum-1",
            version=1,
            status="PARSED",
        )
    )
    session.commit()

    decision = determine_version(repo, "tenant-b", "s3://bucket/doc.pdf", "checksum-1")

    assert decision.version == 1
    assert decision.is_exact_duplicate is False
