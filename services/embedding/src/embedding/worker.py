import json
import uuid
from typing import TYPE_CHECKING, Any

from arq.connections import RedisSettings
from connectors.graph.postgres_knowledge_graph import PostgresKnowledgeGraph
from connectors.keyword.opensearch_index import OpenSearchIndex, ensure_index
from connectors.postgres.repository import ChunkRepository, DocumentRepository
from connectors.postgres.session import get_engine, get_sessionmaker
from connectors.vectorstores.migrations import ensure_qdrant_collection
from connectors.vectorstores.qdrant_store import QdrantVectorStore
from core.interfaces import EmbeddingProvider, KeywordIndex, KnowledgeGraph, VectorStore
from core.models import EmbeddingRecord
from observability.logging import get_json_logger
from opensearchpy import OpenSearch
from pydantic_settings import BaseSettings, SettingsConfigDict
from qdrant_client import QdrantClient
from sqlalchemy.orm import Session

from embedding.embedding_policy import decide_embedding_route
from embedding.queue import EMBED_QUEUE_NAME, get_redis_settings

if TYPE_CHECKING:
    from connectors.graph.spacy_extractor import SpacyEntityExtractor

logger = get_json_logger(__name__)

DLQ_KEY = "dlq:embed_chunks"
MAX_TRIES = 3


def _resolve_embedding_target(
    document_mime_type: str,
    chunk_language: str,
    bound_model_id: str,
    embedding_dimension: int,
    default_vector_store: VectorStore,
    default_keyword_index: KeywordIndex,
    qdrant_client: "QdrantClient | None",
    opensearch_client: "OpenSearch | None",
    alt_stores: dict[tuple[str, str], tuple[VectorStore, KeywordIndex]],
) -> tuple[VectorStore, KeywordIndex]:
    """EmbeddingPolicy (Phase-2 retrofit) routes a chunk to a
    collection/index pair, but this worker process is bound to exactly one
    embedding_provider (one model_id, loaded once at startup). If the
    policy routes to a DIFFERENT model than this worker is configured to
    serve (e.g. a live vendor model this worker isn't running), fall back
    to the bound default rather than crash the job over a strategy choice
    it can't fulfill -- the Adaptive Policy Pattern's "never fail the
    request over strategy selection," mirroring the same defensive-
    backstop pattern Phase 1 used for ParserPolicy/ParserRegistry drift.

    Explicit, disclosed limitation: services/retrieval and
    services/orchestrator still only search the default "chunks"
    collection -- a chunk routed elsewhere here is embedded and stored
    correctly but not yet reachable via retrieval until those services'
    own retrofit loops wire in multi-collection search.
    """
    outcome = decide_embedding_route(document_mime_type, chunk_language)
    route_model_id = outcome["model_id"]
    collection_name = outcome["collection_name"]
    index_name = outcome["index_name"]

    if route_model_id != bound_model_id:
        logger.warning(
            "embedding_policy.model_mismatch_fallback",
            extra={
                "routed_model_id": route_model_id,
                "bound_model_id": bound_model_id,
                "collection_name": collection_name,
                "index_name": index_name,
            },
        )
        return default_vector_store, default_keyword_index

    if collection_name == COLLECTION_NAME and index_name == INDEX_NAME:
        return default_vector_store, default_keyword_index

    key = (collection_name, index_name)
    if key in alt_stores:
        return alt_stores[key]

    if qdrant_client is None or opensearch_client is None:
        # No real clients available to construct an alternate store with
        # (e.g. a direct unit-level call that only passed the default
        # store/index) -- fall back rather than crash.
        logger.warning(
            "embedding_policy.no_client_for_alt_collection_fallback",
            extra={"collection_name": collection_name, "index_name": index_name},
        )
        return default_vector_store, default_keyword_index

    ensure_qdrant_collection(qdrant_client, collection_name, dimension=embedding_dimension)
    ensure_index(opensearch_client, index_name)
    alt_store = (
        QdrantVectorStore(qdrant_client, collection_name),
        OpenSearchIndex(opensearch_client, index_name),
    )
    alt_stores[key] = alt_store
    return alt_store


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
    qdrant_client: "QdrantClient | None" = None,
    opensearch_client: "OpenSearch | None" = None,
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

    EmbeddingPolicy (Phase-2 retrofit): each chunk is routed independently
    via decide_embedding_route(document.mime_type, chunk.language) to a
    (collection_name, index_name) pair -- most chunks resolve to today's
    real default ("chunks"/"chunks"), matching this function's pre-
    retrofit behavior exactly; qdrant_client/opensearch_client are only
    consulted for the rare chunk routed elsewhere (e.g. spreadsheet
    content). This is why the SAME model_id/model_version arguments still
    apply to the whole batch's embedding call below -- only STORAGE
    routing varies per chunk in this pass, not which model actually
    generates the vector (see _resolve_embedding_target's docstring for
    the disclosed model-mismatch fallback).
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

    alt_stores: dict[tuple[str, str], tuple[VectorStore, KeywordIndex]] = {}
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
        target_vector_store, target_keyword_index = _resolve_embedding_target(
            document.mime_type,
            chunk.language,
            model_id,
            len(vector),
            vector_store,
            keyword_index,
            qdrant_client,
            opensearch_client,
            alt_stores,
        )
        target_vector_store.upsert(tenant_id, [record])
        target_keyword_index.upsert(tenant_id, [chunk])

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
                qdrant_client=ctx.get("qdrant_client"),
                opensearch_client=ctx.get("opensearch_client"),
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
    from core.model_registry import get_default_embedding_model

    # model_id is never hardcoded here — it comes from config/models.yaml.
    model = get_default_embedding_model()

    engine = get_engine()
    ctx["session_factory"] = get_sessionmaker(engine)

    qdrant_client = QdrantClient(url="http://localhost:6333")
    ensure_qdrant_collection(qdrant_client, COLLECTION_NAME, dimension=model["dimensions"])
    ctx["vector_store"] = QdrantVectorStore(qdrant_client, COLLECTION_NAME)
    # Raw client also kept in ctx (Phase-2 retrofit) so process_embedding_job
    # can construct alternate collections on demand for chunks EmbeddingPolicy
    # routes elsewhere -- the bound vector_store above stays the default path.
    ctx["qdrant_client"] = qdrant_client

    opensearch_client = OpenSearch(
        hosts=[{"host": "localhost", "port": 9200}], use_ssl=False, verify_certs=False
    )
    ensure_index(opensearch_client, INDEX_NAME)
    ctx["keyword_index"] = OpenSearchIndex(opensearch_client, INDEX_NAME)
    ctx["opensearch_client"] = opensearch_client

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
