import mimetypes
import uuid
from collections.abc import Generator
from datetime import datetime, timezone

from connectors.keyword.opensearch_index import OpenSearchIndex, ensure_index
from connectors.parser_registry import ParserRegistry
from connectors.postgres.repository import DocumentRepository
from connectors.postgres.session import get_engine, get_sessionmaker
from connectors.sources.blob_connector import BlobSourceConnector
from connectors.vectorstores.migrations import ensure_qdrant_collection
from connectors.vectorstores.qdrant_store import QdrantVectorStore
from core.model_registry import get_default_embedding_model
from core.models import Document
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from opensearchpy import OpenSearch
from preprocessing.language_detect import LanguageDetector
from qdrant_client import QdrantClient
from sqlalchemy.orm import Session

from ingestion.queue import enqueue_parse_job
from ingestion.storage import StorageSettings, get_s3_client, upload_fileobj
from ingestion.sync import SyncResult, run_sync

# Same collection/index names as services/embedding and services/retrieval
# -- sync-deleted chunks/vectors must be removed from the same real store
# retrieval/embedding read from, not a separate copy.
CHUNKS_COLLECTION_NAME = "chunks"
CHUNKS_INDEX_NAME = "chunks"

router = APIRouter(prefix="/v1/documents")
sync_router = APIRouter(prefix="/v1/sync")

_engine = get_engine()
_session_factory = get_sessionmaker(_engine)
_storage_settings = StorageSettings()
_s3_client = get_s3_client(_storage_settings)
_parser_registry = ParserRegistry(stt_model_size="tiny")
_language_detector = LanguageDetector()


def get_db_session() -> Generator[Session, None, None]:
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


def _require_tenant_id(request: Request) -> str:
    tenant_id: str | None = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        raise HTTPException(status_code=401, detail="missing tenant context")
    return tenant_id


@router.post("")
async def upload_document(
    request: Request,
    file: UploadFile,
    session: Session = Depends(get_db_session),
) -> dict[str, str]:
    tenant_id = _require_tenant_id(request)
    # Deterministic per (tenant, filename) so re-uploading the same filename
    # maps to the same document_id/source_uri — required for the worker's
    # dedupe/version-bump logic to recognize it as a re-upload rather than a
    # brand new document every time.
    document_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{tenant_id}:{file.filename}"))
    key = f"{tenant_id}/{file.filename}"
    mime_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or ""

    upload_fileobj(_s3_client, _storage_settings.s3_bucket, key, file.file)

    document_repo = DocumentRepository(session)
    # Only create the placeholder row for a genuinely new document. For a
    # re-upload, leave the existing row (with its real checksum/version)
    # untouched — the worker's determine_version needs that real checksum
    # to detect the content changed and bump the version. Overwriting it
    # here would erase the very state that comparison depends on.
    if document_repo.get(tenant_id, document_id) is None:
        document_repo.upsert(
            Document(
                id=document_id,
                tenant_id=tenant_id,
                source_uri=f"s3://{_storage_settings.s3_bucket}/{key}",
                mime_type=mime_type,
                checksum="",
                version=1,
                status="UPLOADED",
            )
        )
        session.commit()

    await enqueue_parse_job(
        request.app.state.redis_pool,
        tenant_id,
        document_id,
        _storage_settings.s3_bucket,
        key,
        mime_type,
    )

    return {"id": document_id, "status": "UPLOADED"}


@router.get("/{document_id}")
def get_document_status(
    document_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, str]:
    tenant_id = _require_tenant_id(request)
    document_repo = DocumentRepository(session)
    document = document_repo.get(tenant_id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")
    return {
        "id": document.id,
        "status": document.status,
        "version": str(document.version),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@sync_router.post("/{connector_name}")
def sync_endpoint(
    connector_name: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, int | str]:
    """Drives a SourceConnector's real incremental-sync + deletion-
    propagation methods end-to-end (ingestion.sync.run_sync) --
    SharePointConnector/BlobSourceConnector were built and unit-tested in
    isolation but never called from anywhere in services/ before this
    (docs/RETROFIT-AUDIT.md's Phase 1 finding).

    Only "blob" is wired to an endpoint in this retrofit: SharePoint needs
    real Microsoft Graph credentials/site config this environment doesn't
    have, and inventing plausible-looking config keys for it would violate
    the anti-hallucination rule against guessed configuration surface.
    SharePointConnector itself is unaffected -- it's still fully usable via
    ingestion.sync.run_sync directly once real credentials exist.
    """
    tenant_id = _require_tenant_id(request)
    if connector_name != "blob":
        raise HTTPException(status_code=404, detail=f"unknown connector: {connector_name!r}")

    document_repo = DocumentRepository(session)

    def known_keys() -> set[str]:
        return {doc.id for doc in document_repo.list_for_tenant(tenant_id)}

    connector = BlobSourceConnector(
        _s3_client,
        _storage_settings.s3_bucket,
        tenant_id,
        _parser_registry,
        known_keys_provider=known_keys,
        prefix=f"{tenant_id}/",
    )

    embedding_model = get_default_embedding_model()
    qdrant_client = QdrantClient(url="http://localhost:6333")
    ensure_qdrant_collection(
        qdrant_client, CHUNKS_COLLECTION_NAME, dimension=embedding_model["dimensions"]
    )
    vector_store = QdrantVectorStore(qdrant_client, CHUNKS_COLLECTION_NAME)

    opensearch_client = OpenSearch(
        hosts=[{"host": "localhost", "port": 9200}], use_ssl=False, verify_certs=False
    )
    ensure_index(opensearch_client, CHUNKS_INDEX_NAME)
    keyword_index = OpenSearchIndex(opensearch_client, CHUNKS_INDEX_NAME)

    result: SyncResult = run_sync(
        session, connector, _language_detector, vector_store, keyword_index, tenant_id
    )

    return {
        "tenant_id": result.tenant_id,
        "documents_processed": result.documents_processed,
        "documents_deleted": result.documents_deleted,
    }
