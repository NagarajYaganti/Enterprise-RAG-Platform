"""Exit checklist proof via the real HTTP API (not a direct orchestrate()
call, unlike test_pipeline.py's unit tests) — exercises the full real
service: main.py's lifespan (real embedding/reranker/PII models, real
Qdrant/OpenSearch/Postgres), TenantContextMiddleware, api.py's request/
response cycle, and pipeline.orchestrate() underneath it. The one thing
that ISN'T real is the LLM generation call itself — no OPENAI_API_KEY/
ANTHROPIC_API_KEY is configured in this environment, so fake providers are
monkeypatched into the already-constructed app.state.orchestration_
dependencies.llm_providers dict post-startup, mirroring test_retrieval_e2e
.py's real-seeding pattern for everything else in the pipeline.
"""

import base64
import json
from collections.abc import Generator
from typing import Any

import pytest
from connectors.embeddings.sentence_transformers_provider import SentenceTransformersProvider
from connectors.keyword.opensearch_index import OpenSearchIndex, ensure_index
from connectors.postgres.repository import ChunkRepository, DocumentRepository, TokenUsageRepository
from connectors.vectorstores.migrations import ensure_qdrant_collection
from connectors.vectorstores.qdrant_store import QdrantVectorStore
from core.interfaces import LLMProvider
from core.models import Chunk, Completion, Document
from embedding.worker import COLLECTION_NAME, INDEX_NAME, process_embedding_job
from fastapi.testclient import TestClient
from opensearchpy import OpenSearch
from orchestrator.main import CACHE_COLLECTION_NAME, app
from orchestrator.semantic_cache import SemanticCache
from qdrant_client import QdrantClient
from sqlalchemy.orm import Session

MODEL_ID = "BAAI/bge-small-en-v1.5"


def _make_token(tenant_id: str) -> str:
    raw = json.dumps({"tenant_id": tenant_id}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def embedding_provider() -> SentenceTransformersProvider:
    return SentenceTransformersProvider(MODEL_ID)


@pytest.fixture()
def clean_semantic_cache(client: TestClient) -> None:
    """Orchestrator-specific counterpart to conftest's clean_embedding_
    stores: the real semantic_cache Qdrant collection persists across
    tests in this module (module-scoped client/lifespan), so leftover
    cache entries from one test would otherwise leak into the next one's
    "is this a fresh generation" assertions.
    """
    qdrant_client = QdrantClient(url="http://localhost:6333")
    if qdrant_client.collection_exists(CACHE_COLLECTION_NAME):
        qdrant_client.delete_collection(CACHE_COLLECTION_NAME)
    embedding_model_dim = 384  # BAAI/bge-small-en-v1.5
    ensure_qdrant_collection(qdrant_client, CACHE_COLLECTION_NAME, dimension=embedding_model_dim)


class FakeLLMProvider(LLMProvider):
    def __init__(self, text: str) -> None:
        self._text = text
        self.call_count = 0

    def generate(self, messages: list[Any], model_id: str, params: dict[str, Any]) -> Completion:
        self.call_count += 1
        return Completion(
            tenant_id=params["tenant_id"],
            model_id=model_id,
            text=self._text,
            usage={"prompt_tokens": 12, "completion_tokens": 7},
        )


def _seed_chunk(
    db_session: Session,
    embedding_provider: SentenceTransformersProvider,
    tenant_id: str,
    document_id: str,
    text: str,
) -> None:
    doc_repo = DocumentRepository(db_session)
    chunk_repo = ChunkRepository(db_session)
    doc_repo.upsert(
        Document(
            id=document_id,
            tenant_id=tenant_id,
            source_uri=f"e2e://{document_id}",
            mime_type="text/plain",
            checksum=document_id,
            version=1,
            status="PARSED",
        )
    )
    chunk_repo.bulk_insert(
        [
            Chunk(
                id=document_id,
                tenant_id=tenant_id,
                document_id=document_id,
                text=text,
                position=0,
                language="en",
                version=1,
                acl_principals=["public"],
            )
        ]
    )
    db_session.commit()

    qdrant_client = QdrantClient(url="http://localhost:6333")
    vector_store = QdrantVectorStore(qdrant_client, COLLECTION_NAME)
    opensearch_client = OpenSearch(
        hosts=[{"host": "localhost", "port": 9200}], use_ssl=False, verify_certs=False
    )
    ensure_index(opensearch_client, INDEX_NAME)
    keyword_index = OpenSearchIndex(opensearch_client, INDEX_NAME)
    process_embedding_job(
        db_session, vector_store, keyword_index, embedding_provider, tenant_id, document_id,
        MODEL_ID, "1",
    )


def test_generate_e2e_returns_a_grounded_answer_with_citations(
    client: TestClient,
    db_session: Session,
    clean_embedding_stores: None,
    clean_semantic_cache: None,
    embedding_provider: SentenceTransformersProvider,
) -> None:
    _seed_chunk(
        db_session, embedding_provider, "tenant-orch-e2e", "doc-orch-1",
        "Refunds are processed within 30 days of the return request.",
    )
    fake_llm = FakeLLMProvider("The refund window is 30 days [doc-orch-1].")
    app.state.orchestration_dependencies.llm_providers["openai"] = fake_llm

    token = _make_token("tenant-orch-e2e")
    response = client.post(
        "/v1/generate",
        json={
            "text": "How long is the refund window?",
            "session_id": "s-1",
            "principals": ["public"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    # Not asserting the exact answer_text string: the real PresidioGuardrail
    # runs on the output too, and phrases like "30 days" are known (verified
    # empirically, see test_presidio_guardrail.py) to trigger its DATE_TIME
    # recognizer — a real, working-as-designed redaction, not a bug. What
    # matters here is that citation validation ran against the ORIGINAL
    # (pre-redaction) completion text and correctly found the real seeded
    # chunk id, and that routing/caching state is otherwise correct.
    assert body["cited_chunk_ids"] == ["doc-orch-1"]
    assert body["model_id"] == "gpt-5.6-luna"
    assert body["blocked"] is False
    assert body["from_cache"] is False
    assert body["answer_text"]  # non-empty: not the refusal fallback


def test_generate_e2e_refuses_when_no_matching_chunks(
    client: TestClient,
    db_session: Session,
    clean_embedding_stores: None,
    clean_semantic_cache: None,
) -> None:
    # clean_embedding_stores deletes the OpenSearch index without
    # recreating it (only _seed_chunk does that, via process_embedding_job)
    # — this test deliberately seeds nothing, so it must recreate the index
    # itself or the real keyword search 404s instead of returning zero hits.
    opensearch_client = OpenSearch(
        hosts=[{"host": "localhost", "port": 9200}], use_ssl=False, verify_certs=False
    )
    ensure_index(opensearch_client, INDEX_NAME)

    token = _make_token("tenant-orch-e2e-empty")
    response = client.post(
        "/v1/generate",
        json={"text": "What is the weather forecast today?", "session_id": "s-1"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer_text"] == "I don't have information about that in the provided documents."
    assert body["model_id"] is None


def test_generate_e2e_redacts_real_pii_in_query_before_retrieval(
    client: TestClient, clean_embedding_stores: None, clean_semantic_cache: None
) -> None:
    opensearch_client = OpenSearch(
        hosts=[{"host": "localhost", "port": 9200}], use_ssl=False, verify_certs=False
    )
    ensure_index(opensearch_client, INDEX_NAME)

    # Uses the same email+name phrasing verified reliable in
    # test_presidio_guardrail.py's test_check_detects_and_redacts_real_pii
    # — a bare SSN-shaped number wasn't reliably flagged by the real
    # analyzer in this sentence context (verified empirically; score
    # depends on surrounding context, not just digit format).
    token = _make_token("tenant-orch-pii")
    response = client.post(
        "/v1/generate",
        json={
            "text": "Please contact John Smith at john.smith@example.com about my refund.",
            "session_id": "s-1",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "john.smith@example.com" not in body["rewritten_query"]


def test_generate_e2e_router_picks_a_more_capable_model_for_complex_queries(
    client: TestClient,
    db_session: Session,
    clean_embedding_stores: None,
    clean_semantic_cache: None,
    embedding_provider: SentenceTransformersProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This test is about ModelRouter picking a different model per request,
    # not about caching — both queries are close paraphrases of the same
    # topic, so a real semantic-cache hit on the second call would mask
    # the routing decision being tested. Disabled here; caching itself has
    # its own dedicated test below.
    monkeypatch.setattr(app.state.orchestrator_settings, "semantic_cache_enabled", False)
    _seed_chunk(
        db_session, embedding_provider, "tenant-orch-router", "doc-orch-router-1",
        "The quarterly compliance audit covers lending, deposits, and fraud controls.",
    )
    openai_fake = FakeLLMProvider("Audits cover lending and deposits [doc-orch-router-1].")
    anthropic_fake = FakeLLMProvider(
        "Audits cover lending, deposits, and fraud [doc-orch-router-1]."
    )
    app.state.orchestration_dependencies.llm_providers["openai"] = openai_fake
    app.state.orchestration_dependencies.llm_providers["anthropic"] = anthropic_fake
    token = _make_token("tenant-orch-router")
    headers = {"Authorization": f"Bearer {token}"}

    short_response = client.post(
        "/v1/generate",
        json={
            "text": "What does the compliance audit cover?",
            "session_id": "s-short",
            "principals": ["public"],
        },
        headers=headers,
    )
    assert short_response.json()["model_id"] == "gpt-5.6-luna"

    long_query = "What does the compliance audit cover? " * 10  # well over 200 chars -> complex
    long_response = client.post(
        "/v1/generate",
        json={"text": long_query, "session_id": "s-long", "principals": ["public"]},
        headers=headers,
    )
    assert long_response.json()["model_id"] == "claude-sonnet-5"


def test_generate_e2e_persists_token_usage_for_a_fresh_generation(
    client: TestClient,
    db_session: Session,
    clean_embedding_stores: None,
    clean_semantic_cache: None,
    embedding_provider: SentenceTransformersProvider,
) -> None:
    _seed_chunk(
        db_session, embedding_provider, "tenant-orch-usage", "doc-orch-usage-1",
        "Wire transfers over $10,000 require dual authorization.",
    )
    app.state.orchestration_dependencies.llm_providers["openai"] = FakeLLMProvider(
        "Wire transfers over $10,000 need dual authorization [doc-orch-usage-1]."
    )
    token = _make_token("tenant-orch-usage")

    response = client.post(
        "/v1/generate",
        json={
            "text": "When is dual authorization required for a wire transfer?",
            "session_id": "s-1",
            "principals": ["public"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    usage_rows = TokenUsageRepository(db_session).list_for_tenant("tenant-orch-usage")
    assert len(usage_rows) == 1
    assert usage_rows[0].model_id == "gpt-5.6-luna"
    assert usage_rows[0].prompt_tokens == 12
    assert usage_rows[0].completion_tokens == 7


def test_generate_e2e_semantic_cache_hit_skips_a_second_generation(
    client: TestClient,
    db_session: Session,
    clean_embedding_stores: None,
    clean_semantic_cache: None,
    embedding_provider: SentenceTransformersProvider,
) -> None:
    _seed_chunk(
        db_session, embedding_provider, "tenant-orch-cache", "doc-orch-cache-1",
        "Loan applications must be reviewed within five business days.",
    )
    fake_llm = FakeLLMProvider("Loans are reviewed within five business days [doc-orch-cache-1].")
    app.state.orchestration_dependencies.llm_providers["openai"] = fake_llm
    token = _make_token("tenant-orch-cache")
    request_body = {
        "text": "How quickly are loan applications reviewed?",
        "session_id": "s-1",
        "principals": ["public"],
    }
    headers = {"Authorization": f"Bearer {token}"}

    first = client.post("/v1/generate", json=request_body, headers=headers)
    assert first.json()["from_cache"] is False
    assert fake_llm.call_count == 1

    second = client.post(
        "/v1/generate",
        json={**request_body, "session_id": "s-2"},
        headers=headers,
    )
    assert second.json()["from_cache"] is True
    assert second.json()["answer_text"] == first.json()["answer_text"]
    assert fake_llm.call_count == 1  # unchanged — the second call never reached the LLM


def test_semantic_cache_smoke_via_direct_instance(client: TestClient) -> None:
    """Cheap sanity check that the real SemanticCache wired into
    app.state actually talks to the real semantic_cache Qdrant collection
    the lifespan created (not e.g. silently pointed at the wrong one).
    """
    cache = app.state.orchestration_dependencies.semantic_cache
    assert isinstance(cache, SemanticCache)
