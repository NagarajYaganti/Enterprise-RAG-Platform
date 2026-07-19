import mimetypes
import uuid
from collections.abc import Generator
from datetime import datetime, timezone

from connectors.postgres.repository import DocumentRepository
from connectors.postgres.session import get_engine, get_sessionmaker
from core.models import Document
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from ingestion.queue import enqueue_parse_job
from ingestion.storage import StorageSettings, get_s3_client, upload_fileobj

router = APIRouter(prefix="/v1/documents")

_engine = get_engine()
_session_factory = get_sessionmaker(_engine)
_storage_settings = StorageSettings()
_s3_client = get_s3_client(_storage_settings)


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
