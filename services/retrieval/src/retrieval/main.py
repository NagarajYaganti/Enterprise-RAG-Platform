import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from connectors.embeddings.sentence_transformers_provider import SentenceTransformersProvider
from connectors.keyword.opensearch_index import OpenSearchIndex, ensure_index
from connectors.llm.openai_provider import OpenAIChatProvider
from connectors.rerankers.cross_encoder_reranker import CrossEncoderReranker
from connectors.vectorstores.migrations import ensure_qdrant_collection
from connectors.vectorstores.qdrant_store import QdrantVectorStore
from core.middleware import TenantContextMiddleware
from core.model_registry import (
    get_default_embedding_model,
    get_default_llm_model,
    get_default_ner_model,
    get_default_reranker_model,
)
from fastapi import FastAPI, Response
from opensearchpy import OpenSearch
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
from qdrant_client import QdrantClient

from retrieval.api import router
from retrieval.pipeline import RetrievalDependencies
from retrieval.settings import RetrievalSettings

# Same Qdrant collection / OpenSearch index names as services/embedding —
# retrieval reads what embedding wrote, not a separate copy.
COLLECTION_NAME = "chunks"
INDEX_NAME = "chunks"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # No model id is ever hardcoded here — every one comes from
    # config/models.yaml, same discipline as services/embedding's on_startup.
    embedding_model = get_default_embedding_model()
    reranker_model = get_default_reranker_model()

    qdrant_client = QdrantClient(url="http://localhost:6333")
    ensure_qdrant_collection(
        qdrant_client, COLLECTION_NAME, dimension=embedding_model["dimensions"]
    )
    vector_store = QdrantVectorStore(qdrant_client, COLLECTION_NAME)

    opensearch_client = OpenSearch(
        hosts=[{"host": "localhost", "port": 9200}], use_ssl=False, verify_certs=False
    )
    ensure_index(opensearch_client, INDEX_NAME)
    keyword_index = OpenSearchIndex(opensearch_client, INDEX_NAME)

    embedding_provider = SentenceTransformersProvider(embedding_model["id"])
    # Local cross-encoder is the default reranker (free, no key needed),
    # mirroring the embedding provider's local-primary pattern. CohereReranker
    # exists and is tested but isn't wired as the default here — same
    # "implemented, not exercised as primary" scope boundary Phase 2 used
    # for pgvector.
    reranker = CrossEncoderReranker(reranker_model["id"])

    # Query rewriting/decomposition degrades to a heuristic pass-through
    # without a real key configured — stated explicitly in the Phase 3 plan,
    # not a silent failure.
    llm_provider = None
    llm_model_id = ""
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if openai_api_key:
        llm_model = get_default_llm_model()
        llm_provider = OpenAIChatProvider(api_key=openai_api_key)
        llm_model_id = llm_model["id"]

    settings = RetrievalSettings()
    entity_extractor = None
    if settings.multi_hop_enabled:
        from connectors.graph.spacy_extractor import SpacyEntityExtractor

        ner_model = get_default_ner_model()
        entity_extractor = SpacyEntityExtractor(ner_model["id"])

    app.state.retrieval_settings = settings
    app.state.retrieval_dependencies = RetrievalDependencies(
        vector_store=vector_store,
        keyword_index=keyword_index,
        embedding_provider=embedding_provider,
        embedding_model_id=embedding_model["id"],
        reranker=reranker,
        entity_extractor=entity_extractor,
        llm_provider=llm_provider,
        llm_model_id=llm_model_id,
    )
    yield


app = FastAPI(title="rag-platform-retrieval", lifespan=lifespan)
app.add_middleware(TenantContextMiddleware)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
