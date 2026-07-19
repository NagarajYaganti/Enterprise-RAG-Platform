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
from ingestion.worker import process_document
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
    return client


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
