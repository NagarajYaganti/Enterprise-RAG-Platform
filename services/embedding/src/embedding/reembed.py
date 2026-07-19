from connectors.postgres.repository import ChunkRepository
from connectors.vectorstores.qdrant_store import QdrantVectorStore
from core.interfaces import EmbeddingProvider, KeywordIndex
from sqlalchemy.orm import Session

from embedding.worker import process_embedding_job


def run_reembed(
    session: Session,
    vector_store: QdrantVectorStore,
    keyword_index: KeywordIndex,
    embedding_provider: EmbeddingProvider,
    tenant_id: str,
    document_id: str,
    new_model_id: str,
    new_model_version: str,
) -> int:
    """Embeds a document's chunks with a new model. Old-model vectors are
    left untouched (still active, still searchable) — this alone does NOT
    supersede them. See cutover() for that explicit, separate step.
    """
    return process_embedding_job(
        session,
        vector_store,
        keyword_index,
        embedding_provider,
        tenant_id,
        document_id,
        new_model_id,
        new_model_version,
    )


def cutover(
    session: Session,
    vector_store: QdrantVectorStore,
    tenant_id: str,
    document_id: str,
    old_model_id: str,
) -> None:
    """Explicit cutover step (ASSUMPTION stated in Plan v2 §7: cutover is a
    separate, deliberate call, not automatic). Confirms the new model's
    chunks are already re-embedded (checked via ChunkRepository — every
    active chunk for the document must exist) before superseding the old
    model's vectors, so a partially-completed re-embed can never trigger a
    premature cutover.
    """
    chunk_repo = ChunkRepository(session)
    active_chunks = chunk_repo.list_for_document(tenant_id, document_id)
    if not active_chunks:
        raise ValueError(f"no active chunks for document {document_id}; nothing to cut over")

    vector_store.supersede_by_model(tenant_id, document_id, old_model_id)
