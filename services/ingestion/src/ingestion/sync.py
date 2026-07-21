from dataclasses import dataclass
from datetime import datetime

from connectors.erasure import ErasureService
from connectors.postgres.repository import ChunkRepository, DocumentRepository
from core.interfaces import KeywordIndex, SourceConnector, VectorStore
from preprocessing.language_detect import LanguageDetector
from sqlalchemy.orm import Session

from ingestion.worker import process_parsed_document


@dataclass
class SyncResult:
    tenant_id: str
    documents_processed: int
    documents_deleted: int


def run_sync(
    session: Session,
    connector: SourceConnector,
    language_detector: LanguageDetector,
    vector_store: VectorStore,
    keyword_index: KeywordIndex,
    tenant_id: str,
    since: datetime | None = None,
) -> SyncResult:
    """Drives a SourceConnector's real, already-tested incremental-sync +
    deletion-propagation methods end-to-end -- SharePointConnector/
    BlobSourceConnector were built and unit-tested in isolation but never
    called from anywhere in services/ before this (docs/RETROFIT-AUDIT.md's
    Phase 1 finding). Synchronous, matching the connectors themselves and
    process_document -- kept independent of arq so it's directly callable
    from tests and a plain HTTP endpoint without a live worker process.

    connector.fetch(ref) already parses via the connector's OWN internal
    parser_registry (an external source, not our own S3 bucket, so there's
    no download-from-our-bucket step to run first) -- this reuses
    _process_parsed_document, the same chunking-policy/persistence logic
    ingestion.worker.process_document uses for uploads, rather than
    duplicating it.
    """
    document_repo = DocumentRepository(session)
    chunk_repo = ChunkRepository(session)

    processed = 0
    for ref in connector.list_documents(since):
        parsed = connector.fetch(ref)
        process_parsed_document(
            session,
            language_detector,
            tenant_id,
            parsed.document_id,
            parsed.mime_type,
            parsed.source_uri,
            parsed,
        )
        processed += 1

    # Phase-2 retrofit: reuses the same ErasureService hard-delete
    # orchestrator services/ingestion's DELETE /v1/documents/{id} endpoint
    # now uses, rather than maintaining two independent copies of this
    # exact 4-step deletion sequence (chunks, vectors, keyword-index,
    # document row). No session.commit() inside the hooks, matching this
    # function's prior behavior -- callers control the session's commit
    # boundary, same as process_parsed_document's dedupe/persist path.
    def delete_chunks(t: str, d: str) -> None:
        chunk_repo.hard_delete_for_document(t, d)

    erasure_service = ErasureService()
    erasure_service.register("chunks", delete_chunks)
    erasure_service.register("vectors", vector_store.delete)
    erasure_service.register("keyword_index", keyword_index.delete)
    erasure_service.register("document", document_repo.hard_delete)

    deleted = 0
    for document_id in connector.list_deletions(since):
        erasure_service.erase_document(tenant_id, document_id)
        deleted += 1

    return SyncResult(tenant_id=tenant_id, documents_processed=processed, documents_deleted=deleted)
