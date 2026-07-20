import json
import uuid
from typing import TYPE_CHECKING, Any

from arq.connections import RedisSettings
from connectors.graph.postgres_knowledge_graph import PostgresKnowledgeGraph
from connectors.postgres.repository import ChunkRepository, DocumentRepository
from connectors.postgres.session import get_engine, get_sessionmaker
from core.interfaces import EmbeddingProvider, KeywordIndex, KnowledgeGraph, VectorStore
from core.models import EmbeddingRecord
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.orm import Session

from embedding.queue import EMBED_QUEUE_NAME, get_redis_settings

if TYPE_CHECKING:
    from connectors.graph.spacy_extractor import SpacyEntityExtractor

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
    knowledge_graph: KnowledgeGraph | None = None,
    entity_extractor: "SpacyEntityExtractor | None" = None,
) -> int:
    """Core idempotent embedding pipeline: embeds every active chunk of a
    document and upserts one EmbeddingRecord per chunk, individually.

    Idempotency: each record's id is a deterministic uuid5 of
    (chunk_id, model_id) — re-running this function (e.g. after a mid-batch
    kill) re-upserts the same ids for already-done chunks (a no-op change,
    not a duplicate) and only adds genuinely new records for the rest.
    Kept independent of arq's ctx mechanism so it's directly testable.

    GraphRAG (optional, flagged OFF by default): knowledge_graph and
    entity_extractor are both None unless GraphRAGSettings.enabled is true
    at worker startup — their None-ness IS the flag, so a disabled worker
    never imports spaCy/extracts anything, no separate boolean threaded
    through. When both are provided, entity/relation extraction runs per
    chunk after that chunk's embedding upsert.
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
            language=chunk.language,
            doc_type=chunk.doc_type,
            department=chunk.department,
            date=chunk.date,
        )
        vector_store.upsert(tenant_id, [record])
        keyword_index.upsert(tenant_id, [chunk])

        if knowledge_graph is not None and entity_extractor is not None:
            entities, relations = entity_extractor.extract(chunk)
            if entities:
                knowledge_graph.upsert_entities(tenant_id, entities)
            if relations:
                knowledge_graph.upsert_relations(tenant_id, relations)

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
            entity_extractor = ctx.get("entity_extractor")
            # Constructed per-job from this job's own session (not cached in
            # ctx) so entity/relation upserts share the same transaction as
            # the document/chunk repositories below — see on_startup's note.
            knowledge_graph = (
                PostgresKnowledgeGraph(session) if entity_extractor is not None else None
            )
            return process_embedding_job(
                session,
                ctx["vector_store"],
                ctx["keyword_index"],
                ctx["embedding_provider"],
                tenant_id,
                document_id,
                model_id,
                model_version,
                knowledge_graph=knowledge_graph,
                entity_extractor=entity_extractor,
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


class GraphRAGSettings(BaseSettings):
    """GraphRAG (optional, flagged OFF by default per Section 4 Phase 3
    task text). env var: GRAPHRAG_ENABLED. When false (default), on_startup
    never imports spaCy or constructs a KnowledgeGraph — extraction is a
    real per-tenant cost this flag exists to gate, not just a no-op toggle.
    """

    model_config = SettingsConfigDict(env_prefix="")

    graphrag_enabled: bool = False


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

    if GraphRAGSettings().graphrag_enabled:
        from connectors.graph.spacy_extractor import SpacyEntityExtractor
        from core.model_registry import get_default_ner_model

        # Only the extractor (expensive to load — a real spaCy model) is
        # cached here for the worker's lifetime. PostgresKnowledgeGraph is
        # NOT constructed here: it must share the same per-job session as
        # process_embedding_job's other repositories (see embed_chunks) so
        # entity/relation upserts commit atomically with everything else,
        # not via a separate session left open for the worker's whole life.
        ner_model = get_default_ner_model()
        ctx["entity_extractor"] = SpacyEntityExtractor(ner_model["id"])


class WorkerSettings:
    functions = [embed_chunks]
    on_startup = on_startup
    queue_name = EMBED_QUEUE_NAME
    max_tries = MAX_TRIES
    redis_settings: RedisSettings = get_redis_settings()
