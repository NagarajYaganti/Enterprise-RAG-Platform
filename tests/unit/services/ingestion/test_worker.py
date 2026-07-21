from collections.abc import Generator
from pathlib import Path
from typing import Any

import boto3
import pytest
from botocore.config import Config
from connectors.parser_registry import ParserRegistry
from connectors.postgres.orm import Base
from connectors.postgres.repository import ChunkRepository, DocumentRepository
from connectors.postgres.session import get_engine, get_sessionmaker
from core.models import Document
from ingestion.worker import IngestionSettings, process_document
from preprocessing.language_detect import LanguageDetector
from sqlalchemy.orm import Session

DATABASE_URL = "postgresql+psycopg://rag:rag@localhost:5432/rag_platform"
FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "documents"
BUCKET = "rag-worker-test"


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
def s3_client() -> Any:
    client = boto3.client(
        "s3",
        endpoint_url="http://localhost:9000",
        aws_access_key_id="ragadmin",
        aws_secret_access_key="ragadminsecret",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        region_name="us-east-1",
    )
    try:
        client.create_bucket(Bucket=BUCKET)
    except client.exceptions.BucketAlreadyOwnedByYou:
        pass
    client.upload_file(str(FIXTURES / "sample.html"), BUCKET, "sample.html")
    client.upload_file(str(FIXTURES / "sample_corrupt.pdf"), BUCKET, "sample_corrupt.pdf")
    client.upload_file(str(FIXTURES / "sample_encrypted.pdf"), BUCKET, "sample_encrypted.pdf")
    client.upload_file(str(FIXTURES / "sample.txt"), BUCKET, "sample.txt")
    return client


def _seed_uploaded_document(session: Session, tenant_id: str, document_id: str) -> None:
    # Mirrors what ingestion.api's upload endpoint does before enqueueing --
    # process_document's new failure paths update this existing row rather
    # than building a fresh Document (parsed.checksum doesn't exist yet on
    # a parsing-stage failure).
    DocumentRepository(session).upsert(
        Document(
            id=document_id,
            tenant_id=tenant_id,
            source_uri=f"s3://{BUCKET}/{document_id}",
            mime_type="application/octet-stream",
            checksum="",
            version=1,
            status="UPLOADED",
        )
    )
    session.commit()


@pytest.fixture(scope="module")
def parser_registry() -> ParserRegistry:
    return ParserRegistry(stt_model_size="tiny")


@pytest.fixture(scope="module")
def language_detector() -> LanguageDetector:
    return LanguageDetector()


def test_process_document_parses_and_persists(
    session: Session,
    s3_client: Any,
    parser_registry: ParserRegistry,
    language_detector: LanguageDetector,
) -> None:
    document = process_document(
        session,
        s3_client,
        parser_registry,
        language_detector,
        "tenant-acme",
        "doc-1",
        BUCKET,
        "sample.html",
        "text/html",
    )

    assert document.status == "PARSED"
    assert document.version == 1
    assert document.tenant_id == "tenant-acme"

    chunk_repo = ChunkRepository(session)
    chunks = chunk_repo.list_for_document("tenant-acme", "doc-1")
    assert len(chunks) > 0
    assert any("Onboarding Runbook" in c.text for c in chunks)
    assert all(c.language == "en" for c in chunks)
    assert all(c.version == 1 for c in chunks)


def test_process_document_reupload_same_checksum_is_idempotent(
    session: Session,
    s3_client: Any,
    parser_registry: ParserRegistry,
    language_detector: LanguageDetector,
) -> None:
    process_document(
        session,
        s3_client,
        parser_registry,
        language_detector,
        "tenant-acme",
        "doc-2",
        BUCKET,
        "sample.html",
        "text/html",
    )
    first_chunks = ChunkRepository(session).list_for_document("tenant-acme", "doc-2")

    document = process_document(
        session,
        s3_client,
        parser_registry,
        language_detector,
        "tenant-acme",
        "doc-2",
        BUCKET,
        "sample.html",
        "text/html",
    )
    second_chunks = ChunkRepository(session).list_for_document("tenant-acme", "doc-2")

    assert document.version == 1
    assert len(first_chunks) == len(second_chunks)


def test_process_document_reupload_different_content_bumps_version_and_supersedes(
    session: Session,
    s3_client: Any,
    parser_registry: ParserRegistry,
    language_detector: LanguageDetector,
) -> None:
    process_document(
        session,
        s3_client,
        parser_registry,
        language_detector,
        "tenant-acme",
        "doc-3",
        BUCKET,
        "sample.html",
        "text/html",
    )

    modified_html = (
        b"<html><body><h1>Changed Runbook</h1><p>Different content now.</p></body></html>"
    )
    s3_client.put_object(Bucket=BUCKET, Key="sample.html", Body=modified_html)

    document = process_document(
        session,
        s3_client,
        parser_registry,
        language_detector,
        "tenant-acme",
        "doc-3",
        BUCKET,
        "sample.html",
        "text/html",
    )

    assert document.version == 2

    doc_repo = DocumentRepository(session)
    chunk_repo = ChunkRepository(session)
    active_chunks = chunk_repo.list_for_document("tenant-acme", "doc-3", active_only=True)
    all_chunks = chunk_repo.list_for_document("tenant-acme", "doc-3", active_only=False)

    assert any("Changed Runbook" in c.text for c in active_chunks)
    assert any(c.status == "superseded" for c in all_chunks)
    stored_document = doc_repo.get("tenant-acme", "doc-3")
    assert stored_document is not None
    assert stored_document.checksum != ""

    # restore original content for any later test relying on it
    s3_client.upload_file(str(FIXTURES / "sample.html"), BUCKET, "sample.html")


def test_process_document_unsupported_mime_type_reaches_unsupported_status(
    session: Session,
    s3_client: Any,
    parser_registry: ParserRegistry,
    language_detector: LanguageDetector,
) -> None:
    _seed_uploaded_document(session, "tenant-acme", "doc-unsupported")

    document = process_document(
        session,
        s3_client,
        parser_registry,
        language_detector,
        "tenant-acme",
        "doc-unsupported",
        BUCKET,
        "sample.html",
        "application/x-totally-unknown-format",
    )

    assert document.status == "UNSUPPORTED"
    assert document.failure_reason is not None
    assert "application/x-totally-unknown-format" in document.failure_reason


def test_process_document_corrupt_file_reaches_failed_parse_not_stuck_at_uploaded(
    session: Session,
    s3_client: Any,
    parser_registry: ParserRegistry,
    language_detector: LanguageDetector,
) -> None:
    # The real bug found during planning: before this retrofit, an
    # exception during parsing happened before any try/except existed,
    # leaving the document stuck at UPLOADED forever. This proves it now
    # reaches a real terminal status instead.
    _seed_uploaded_document(session, "tenant-acme", "doc-corrupt")

    document = process_document(
        session,
        s3_client,
        parser_registry,
        language_detector,
        "tenant-acme",
        "doc-corrupt",
        BUCKET,
        "sample_corrupt.pdf",
        "application/pdf",
    )

    assert document.status == "FAILED_PARSE"
    assert document.failure_reason is not None


def test_process_document_password_protected_pdf_reaches_quarantined_status(
    session: Session,
    s3_client: Any,
    parser_registry: ParserRegistry,
    language_detector: LanguageDetector,
) -> None:
    _seed_uploaded_document(session, "tenant-acme", "doc-quarantined")

    document = process_document(
        session,
        s3_client,
        parser_registry,
        language_detector,
        "tenant-acme",
        "doc-quarantined",
        BUCKET,
        "sample_encrypted.pdf",
        "application/pdf",
    )

    assert document.status == "QUARANTINED"
    assert document.failure_reason == "password-protected file"


def test_process_document_oversized_file_reaches_unsupported_without_downloading(
    session: Session,
    s3_client: Any,
    parser_registry: ParserRegistry,
    language_detector: LanguageDetector,
) -> None:
    # A real object in MinIO, checked against a deliberately tiny ceiling --
    # proves the pre-flight HEAD-based size check (not a mock) actually
    # rejects it before any download/parse is attempted.
    _seed_uploaded_document(session, "tenant-acme", "doc-oversized")
    real_size = s3_client.head_object(Bucket=BUCKET, Key="sample.html")["ContentLength"]
    tiny_ceiling = IngestionSettings(max_document_size_bytes=real_size - 1)

    document = process_document(
        session,
        s3_client,
        parser_registry,
        language_detector,
        "tenant-acme",
        "doc-oversized",
        BUCKET,
        "sample.html",
        "text/html",
        settings=tiny_ceiling,
    )

    assert document.status == "UNSUPPORTED"
    assert document.failure_reason is not None
    assert "max_document_size_bytes" in document.failure_reason


def test_process_document_routes_low_density_plain_text_through_chunking_policy(
    session: Session,
    s3_client: Any,
    parser_registry: ParserRegistry,
    language_detector: LanguageDetector,
) -> None:
    # Proves worker.py actually CALLS ChunkingPolicy and routes to its
    # outcome, not just that decide_chunking_strategy() works in isolation.
    # sample.txt has no structural_elements at all (PlainTextParser always
    # returns []), so heading_density is 0.0 -> config/policies/chunking
    # .yaml's "plain_or_low_structure" rule -> fixed_size, NOT the
    # previously-hardcoded StructureAwareChunker. FixedSizeChunker's chunks
    # never set a page_number key at all; StructureAwareChunker's always
    # do (even if None) -- a real, observable difference between the two.
    document = process_document(
        session,
        s3_client,
        parser_registry,
        language_detector,
        "tenant-acme",
        "doc-plain-text",
        BUCKET,
        "sample.txt",
        "text/plain",
    )

    assert document.status == "PARSED"
    chunks = ChunkRepository(session).list_for_document("tenant-acme", "doc-plain-text")
    assert len(chunks) > 0
    assert all("page_number" not in c.metadata for c in chunks)
