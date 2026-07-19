import json
import uuid
from typing import Any

from arq.connections import RedisSettings
from connectors.postgres.repository import ChunkRepository, DocumentRepository
from connectors.postgres.session import get_engine, get_sessionmaker
from core.interfaces import EmbeddingProvider, KeywordIndex, VectorStore
from core.models import EmbeddingRecord
from sqlalchemy.orm import Session

from embedding.queue import EMBED_QUEUE_NAME, get_redis_settings

DLQ_KEY = "dlq:embed_chunks"
MAX_TRIES = 3


def process_embedding_job(
    session: Session,
    vector_store: VectorStore,
    keyword_index: KeywordIndex,
    embedding_provider: EmbeddingProvider,
    tenant_id: str,
    document_id: str,
    model_id: str,
    model_version: str,
) -> int:
    """Core idempotent embedding pipeline: embeds every active chunk of a
    document and upserts one EmbeddingRecord per chunk, individually.

    Idempotency: each record's id is a deterministic uuid5 of
    (chunk_id, model_id) — re-running this function (e.g. after a mid-batch
    kill) re-upserts the same ids for already-done chunks (a no-op change,
    not a duplicate) and only adds genuinely new records for the rest.
    Kept independent of arq's ctx mechanism so it's directly testable.
    """
    chunk_repo = ChunkRepository(session)
    doc_repo = DocumentRepository(session)

    document = doc_repo.get(tenant_id, document_id)
    if document is None:
        raise ValueError(f"no document {document_id} for tenant {tenant_id}")

    doc_repo.upsert(document.model_copy(update={"status": "EMBEDDING"}))
    session.commit()

    chunks = chunk_repo.list_for_document(tenant_id, document_id)
    texts = [chunk.text for chunk in chunks]
    vectors = embedding_provider.embed(texts, model_id) if texts else []

    embedded_count = 0
    for chunk, vector in zip(chunks, vectors, strict=True):
        record = EmbeddingRecord(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{chunk.id}:{model_id}")),
            tenant_id=tenant_id,
            document_id=document_id,
            chunk_id=chunk.id,
            vector=vector,
            model_id=model_id,
            model_version=model_version,
            acl_principals=chunk.acl_principals,
        )
        vector_store.upsert(tenant_id, [record])
        keyword_index.upsert(tenant_id, [chunk])
        embedded_count += 1

    doc_repo.upsert(document.model_copy(update={"status": "EMBEDDED"}))
    session.commit()
    return embedded_count


async def embed_chunks(
    ctx: dict[str, Any],
    tenant_id: str,
    document_id: str,
    model_id: str,
    model_version: str,
) -> int:
    session_factory = ctx["session_factory"]
    with session_factory() as session:
        try:
            return process_embedding_job(
                session,
                ctx["vector_store"],
                ctx["keyword_index"],
                ctx["embedding_provider"],
                tenant_id,
                document_id,
                model_id,
                model_version,
            )
        except Exception as exc:
            # arq has no built-in dead-letter queue (verified against the
            # installed version) — hand-built here. Only push to the DLQ on
            # the last allowed try, so transient failures that will still be
            # retried by arq don't get recorded as permanently dead yet.
            if ctx.get("job_try", 1) >= MAX_TRIES:
                redis_pool = ctx["redis"]  # arq auto-populates this
                await redis_pool.lpush(
                    DLQ_KEY,
                    json.dumps(
                        {
                            "tenant_id": tenant_id,
                            "document_id": document_id,
                            "model_id": model_id,
                            "model_version": model_version,
                            "error": str(exc),
                        }
                    ),
                )
            raise


COLLECTION_NAME = "chunks"
INDEX_NAME = "chunks"


async def on_startup(ctx: dict[str, Any]) -> None:
    from connectors.embeddings.sentence_transformers_provider import (
        SentenceTransformersProvider,
    )
    from connectors.keyword.opensearch_index import OpenSearchIndex, ensure_index
    from connectors.vectorstores.migrations import ensure_qdrant_collection
    from connectors.vectorstores.qdrant_store import QdrantVectorStore
    from core.model_registry import get_default_embedding_model
    from opensearchpy import OpenSearch
    from qdrant_client import QdrantClient

    # model_id is never hardcoded here — it comes from config/models.yaml.
    model = get_default_embedding_model()

    engine = get_engine()
    ctx["session_factory"] = get_sessionmaker(engine)

    qdrant_client = QdrantClient(url="http://localhost:6333")
    ensure_qdrant_collection(qdrant_client, COLLECTION_NAME, dimension=model["dimensions"])
    ctx["vector_store"] = QdrantVectorStore(qdrant_client, COLLECTION_NAME)

    opensearch_client = OpenSearch(
        hosts=[{"host": "localhost", "port": 9200}], use_ssl=False, verify_certs=False
    )
    ensure_index(opensearch_client, INDEX_NAME)
    ctx["keyword_index"] = OpenSearchIndex(opensearch_client, INDEX_NAME)

    ctx["embedding_provider"] = SentenceTransformersProvider(model["id"])


class WorkerSettings:
    functions = [embed_chunks]
    on_startup = on_startup
    queue_name = EMBED_QUEUE_NAME
    max_tries = MAX_TRIES
    redis_settings: RedisSettings = get_redis_settings()
