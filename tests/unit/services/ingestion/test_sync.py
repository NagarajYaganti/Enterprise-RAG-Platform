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
from connectors.sources.blob_connector import BlobSourceConnector
from core.interfaces import KeywordIndex, SourceConnector, VectorStore
from core.models import ParsedDocument
from ingestion.sync import run_sync
from preprocessing.language_detect import LanguageDetector
from sqlalchemy.orm import Session

DATABASE_URL = "postgresql+psycopg://rag:rag@localhost:5432/rag_platform"
FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "documents"
BUCKET = "rag-sync-test-bucket"
TENANT_ID = "tenant-acme"


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


@pytest.fixture(scope="module")
def language_detector() -> LanguageDetector:
    return LanguageDetector()


class FakeSourceConnector(SourceConnector):
    """Each entry in `docs` doubles as both the "ref" list_documents()
    returns and what fetch() resolves to, since this fake doesn't need a
    separate ref/fetch indirection to prove run_sync's own orchestration.
    """

    def __init__(self, docs: list[ParsedDocument], deletions: list[str]) -> None:
        self._docs = docs
        self._deletions = deletions
        self.fetch_calls: list[str] = []

    def list_documents(self, since: Any) -> list[ParsedDocument]:
        return list(self._docs)

    def fetch(self, ref: Any) -> ParsedDocument:
        parsed: ParsedDocument = ref
        self.fetch_calls.append(parsed.document_id)
        return parsed

    def list_deletions(self, since: Any) -> list[str]:
        return list(self._deletions)


class FakeVectorStore(VectorStore):
    def __init__(self) -> None:
        self.delete_calls: list[tuple[str, str]] = []

    def upsert(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def search(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def delete(self, tenant_id: str, document_id: str) -> None:
        self.delete_calls.append((tenant_id, document_id))


class FakeKeywordIndex(KeywordIndex):
    def __init__(self) -> None:
        self.delete_calls: list[tuple[str, str]] = []

    def upsert(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def search(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def delete(self, tenant_id: str, document_id: str) -> None:
        self.delete_calls.append((tenant_id, document_id))


def _parsed_doc(document_id: str, text: str) -> ParsedDocument:
    return ParsedDocument(
        tenant_id=TENANT_ID,
        document_id=document_id,
        raw_text=text,
        structural_elements=[],
        mime_type="text/plain",
        source_uri=f"fake://{document_id}",
        checksum=f"checksum-{document_id}",
    )


def test_run_sync_processes_every_listed_document(
    session: Session, language_detector: LanguageDetector
) -> None:
    connector = FakeSourceConnector(
        docs=[_parsed_doc("doc-a", "First document body."), _parsed_doc("doc-b", "Second one.")],
        deletions=[],
    )
    vector_store = FakeVectorStore()
    keyword_index = FakeKeywordIndex()

    result = run_sync(
        session, connector, language_detector, vector_store, keyword_index, TENANT_ID
    )

    assert result.documents_processed == 2
    assert result.documents_deleted == 0
    assert connector.fetch_calls == ["doc-a", "doc-b"]

    doc_repo = DocumentRepository(session)
    assert doc_repo.get(TENANT_ID, "doc-a") is not None
    assert doc_repo.get(TENANT_ID, "doc-a").status == "PARSED"  # type: ignore[union-attr]
    chunks = ChunkRepository(session).list_for_document(TENANT_ID, "doc-a")
    assert len(chunks) > 0


def test_run_sync_propagates_deletions_across_chunks_document_and_indexes(
    session: Session, language_detector: LanguageDetector
) -> None:
    # First, sync a document in so there's something real to delete.
    connector = FakeSourceConnector(
        docs=[_parsed_doc("doc-to-delete", "Will be removed.")], deletions=[]
    )
    vector_store = FakeVectorStore()
    keyword_index = FakeKeywordIndex()
    run_sync(session, connector, language_detector, vector_store, keyword_index, TENANT_ID)
    session.commit()

    # Now sync again, this time reporting it as deleted at the source.
    deleting_connector = FakeSourceConnector(docs=[], deletions=["doc-to-delete"])
    result = run_sync(
        session, deleting_connector, language_detector, vector_store, keyword_index, TENANT_ID
    )

    assert result.documents_deleted == 1
    assert (TENANT_ID, "doc-to-delete") in vector_store.delete_calls
    assert (TENANT_ID, "doc-to-delete") in keyword_index.delete_calls
    assert DocumentRepository(session).get(TENANT_ID, "doc-to-delete") is None
    assert ChunkRepository(session).list_for_document(TENANT_ID, "doc-to-delete") == []


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
    for obj in client.list_objects_v2(Bucket=BUCKET).get("Contents", []):
        client.delete_object(Bucket=BUCKET, Key=obj["Key"])
    client.upload_file(str(FIXTURES / "sample.html"), BUCKET, "docs/sample.html")
    return client


def test_run_sync_end_to_end_with_a_real_blob_source_connector(
    session: Session, language_detector: LanguageDetector, s3_client: Any
) -> None:
    # Proves the real, previously-unwired BlobSourceConnector (built and
    # unit-tested in isolation, per docs/RETROFIT-AUDIT.md's finding) now
    # actually gets driven end-to-end through run_sync.
    registry = ParserRegistry(stt_model_size="tiny")
    connector = BlobSourceConnector(
        s3_client,
        BUCKET,
        TENANT_ID,
        registry,
        known_keys_provider=lambda: set(),
        prefix="docs/",
    )
    vector_store = FakeVectorStore()
    keyword_index = FakeKeywordIndex()

    result = run_sync(
        session, connector, language_detector, vector_store, keyword_index, TENANT_ID
    )

    assert result.documents_processed == 1
    document = DocumentRepository(session).get(TENANT_ID, "docs/sample.html")
    assert document is not None
    assert document.status == "PARSED"
    chunks = ChunkRepository(session).list_for_document(TENANT_ID, "docs/sample.html")
    assert any("Onboarding Runbook" in c.text for c in chunks)
