import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from connectors.embeddings.sentence_transformers_provider import SentenceTransformersProvider
from connectors.guardrails.output_policy_guardrail import OutputPolicyGuardrail
from connectors.guardrails.presidio_guardrail import PresidioGuardrail
from connectors.guardrails.prompt_injection_guardrail import PromptInjectionGuardrail
from connectors.keyword.opensearch_index import OpenSearchIndex, ensure_index
from connectors.llm.anthropic_provider import AnthropicProvider
from connectors.llm.openai_provider import OpenAIChatProvider
from connectors.rerankers.cross_encoder_reranker import CrossEncoderReranker
from connectors.vectorstores.migrations import ensure_qdrant_collection
from connectors.vectorstores.qdrant_store import QdrantVectorStore
from core.interfaces import LLMProvider
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
from retrieval.pipeline import RetrievalDependencies
from retrieval.settings import RetrievalSettings

from orchestrator.agent.tool_runtime import ToolRuntime
from orchestrator.api import router
from orchestrator.guardrail_pipeline import GuardrailPipeline
from orchestrator.model_router import ConfigModelRouter
from orchestrator.pipeline import OrchestrationDependencies
from orchestrator.semantic_cache import SemanticCache
from orchestrator.settings import OrchestratorSettings

# Same collection/index names as services/retrieval and services/embedding
# — orchestrator reads what they wrote, never a separate copy.
CHUNKS_COLLECTION_NAME = "chunks"
CHUNKS_INDEX_NAME = "chunks"
CACHE_COLLECTION_NAME = "semantic_cache"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    embedding_model = get_default_embedding_model()
    reranker_model = get_default_reranker_model()
    ner_model = get_default_ner_model()

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

    embedding_provider = SentenceTransformersProvider(embedding_model["id"])
    reranker = CrossEncoderReranker(reranker_model["id"])

    # Query rewriting/decomposition (used internally by retrieval.pipeline
    # .retrieve) degrades to a heuristic pass-through without a key
    # configured — same stated behavior as services/retrieval's own main.py.
    rewrite_llm_provider = None
    rewrite_llm_model_id = ""
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if openai_api_key:
        rewrite_llm_model = get_default_llm_model(provider="openai")
        rewrite_llm_provider = OpenAIChatProvider(api_key=openai_api_key)
        rewrite_llm_model_id = rewrite_llm_model["id"]

    # Generation providers, keyed by provider name — ModelRouter can route
    # to ANY registered generation model regardless of vendor, so every
    # configured provider (not just one) needs an adapter instance ready.
    # A provider with no API key configured is simply absent from this
    # dict; orchestrate() raises LLMProviderNotConfiguredError (mapped to
    # HTTP 503) if ModelRouter ever routes to a model from a missing one.
    llm_providers: dict[str, LLMProvider] = {}
    if openai_api_key:
        llm_providers["openai"] = OpenAIChatProvider(api_key=openai_api_key)
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_api_key:
        llm_providers["anthropic"] = AnthropicProvider(api_key=anthropic_api_key)

    orchestrator_settings = OrchestratorSettings()

    semantic_cache = None
    if orchestrator_settings.semantic_cache_enabled:
        ensure_qdrant_collection(
            qdrant_client, CACHE_COLLECTION_NAME, dimension=embedding_model["dimensions"]
        )
        semantic_cache = SemanticCache(
            qdrant_client,
            CACHE_COLLECTION_NAME,
            orchestrator_settings.cache_similarity_threshold,
            orchestrator_settings.cache_ttl_seconds,
        )

    guardrail_pipeline = GuardrailPipeline(
        pii_guardrail=PresidioGuardrail(model_id=ner_model["id"]),
        injection_guardrail=PromptInjectionGuardrail(),
        output_policy_guardrail=OutputPolicyGuardrail(),
    )

    app.state.retrieval_settings = RetrievalSettings()
    app.state.orchestrator_settings = orchestrator_settings
    app.state.orchestration_dependencies = OrchestrationDependencies(
        retrieval=RetrievalDependencies(
            vector_store=vector_store,
            keyword_index=keyword_index,
            embedding_provider=embedding_provider,
            embedding_model_id=embedding_model["id"],
            reranker=reranker,
            entity_extractor=None,
            llm_provider=rewrite_llm_provider,
            llm_model_id=rewrite_llm_model_id,
        ),
        llm_providers=llm_providers,
        model_router=ConfigModelRouter(),
        guardrail_pipeline=guardrail_pipeline,
        semantic_cache=semantic_cache,
        cache_embedding_provider=embedding_provider,
        cache_embedding_model_id=embedding_model["id"],
    )

    # Agentic RAG: gated behind agent_mode_enabled (Plan v2 §A.11). No
    # concrete Tool adapters exist yet (a stated, deferred limitation — a
    # later phase adds domain-specific tools), so the registry starts
    # empty; every step call 404s/400s until tools are registered. Traces
    # live in-memory on app.state, not persisted — see orchestrator/api.py.
    app.state.tool_runtime = ToolRuntime({})
    app.state.agent_traces = {}

    yield


app = FastAPI(title="rag-platform-orchestrator", lifespan=lifespan)
app.add_middleware(TenantContextMiddleware)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
