import time
import uuid
from collections.abc import Generator

import pytest
from connectors.vectorstores.migrations import ensure_qdrant_collection
from orchestrator.semantic_cache import SemanticCache
from qdrant_client import QdrantClient

QDRANT_URL = "http://localhost:6333"
COLLECTION = "test_semantic_cache_collection"


@pytest.fixture()
def client() -> Generator[QdrantClient, None, None]:
    c = QdrantClient(url=QDRANT_URL)
    ensure_qdrant_collection(c, COLLECTION, dimension=4)
    yield c
    c.delete_collection(COLLECTION)


DEFAULT_PRINCIPALS = ["p1"]


def _put(
    cache: SemanticCache,
    tenant_id: str,
    vector: list[float],
    answer_text: str = "The refund window is 30 days.",
    document_ids: list[str] | None = None,
    cited_chunk_ids: list[str] | None = None,
    model_id: str = "gpt-5.6-luna",
    principals: list[str] | None = None,
) -> str:
    query_id = str(uuid.uuid4())
    cache.put(
        tenant_id,
        principals if principals is not None else DEFAULT_PRINCIPALS,
        query_id,
        vector,
        answer_text,
        document_ids or ["doc-1"],
        cited_chunk_ids if cited_chunk_ids is not None else ["doc-1"],
        model_id,
    )
    return query_id


def test_get_returns_none_when_cache_is_empty(client: QdrantClient) -> None:
    cache = SemanticCache(client, COLLECTION, similarity_threshold=0.95, ttl_seconds=3600)

    hit = cache.get("tenant-a", DEFAULT_PRINCIPALS, [0.1, 0.2, 0.3, 0.4])

    assert hit is None


def test_get_returns_a_hit_for_a_near_identical_query_vector(client: QdrantClient) -> None:
    cache = SemanticCache(client, COLLECTION, similarity_threshold=0.95, ttl_seconds=3600)
    _put(
        cache, "tenant-a", [0.1, 0.2, 0.3, 0.4],
        answer_text="30 days.", document_ids=["doc-1"], cited_chunk_ids=["chunk-1"],
    )

    hit = cache.get("tenant-a", DEFAULT_PRINCIPALS, [0.1, 0.2, 0.3, 0.4])

    assert hit is not None
    assert hit.answer_text == "30 days."
    assert hit.document_ids == ["doc-1"]
    assert hit.cited_chunk_ids == ["chunk-1"]
    assert hit.model_id == "gpt-5.6-luna"
    assert hit.score >= 0.95


def test_get_is_tenant_isolated(client: QdrantClient) -> None:
    cache = SemanticCache(client, COLLECTION, similarity_threshold=0.95, ttl_seconds=3600)
    _put(cache, "tenant-a", [0.1, 0.2, 0.3, 0.4])

    hit = cache.get("tenant-b", DEFAULT_PRINCIPALS, [0.1, 0.2, 0.3, 0.4])

    assert hit is None


def test_get_is_principal_isolated(client: QdrantClient) -> None:
    # The literal Phase-4 retrofit bug: two different users in the SAME
    # tenant must not see each other's cached answers, including ones
    # grounded in documents one of them has no access to.
    cache = SemanticCache(client, COLLECTION, similarity_threshold=0.95, ttl_seconds=3600)
    _put(cache, "tenant-a", [0.1, 0.2, 0.3, 0.4], principals=["p1"])

    hit = cache.get("tenant-a", ["p2"], [0.1, 0.2, 0.3, 0.4])

    assert hit is None


def test_get_matches_when_any_shared_principal_overlaps(client: QdrantClient) -> None:
    cache = SemanticCache(client, COLLECTION, similarity_threshold=0.95, ttl_seconds=3600)
    _put(cache, "tenant-a", [0.1, 0.2, 0.3, 0.4], principals=["p1", "p2"])

    hit = cache.get("tenant-a", ["p2", "p3"], [0.1, 0.2, 0.3, 0.4])

    assert hit is not None


def test_get_below_similarity_threshold_is_a_miss(client: QdrantClient) -> None:
    cache = SemanticCache(client, COLLECTION, similarity_threshold=0.999, ttl_seconds=3600)
    _put(cache, "tenant-a", [0.1, 0.2, 0.3, 0.4])

    # A meaningfully different vector under a near-1.0 threshold should miss.
    hit = cache.get("tenant-a", DEFAULT_PRINCIPALS, [0.9, 0.1, 0.0, 0.0])

    assert hit is None


def test_get_excludes_entries_older_than_ttl(client: QdrantClient) -> None:
    cache = SemanticCache(client, COLLECTION, similarity_threshold=0.95, ttl_seconds=1)
    _put(cache, "tenant-a", [0.1, 0.2, 0.3, 0.4])
    time.sleep(1.5)

    hit = cache.get("tenant-a", DEFAULT_PRINCIPALS, [0.1, 0.2, 0.3, 0.4])

    assert hit is None


def test_get_accepts_a_per_call_similarity_threshold_override(client: QdrantClient) -> None:
    # CachePolicy (Phase-4 retrofit): the instance is bound to 0.5 (would
    # match anything), but a per-call override can tighten it back up for
    # this one query without constructing a second SemanticCache instance.
    cache = SemanticCache(client, COLLECTION, similarity_threshold=0.5, ttl_seconds=3600)
    _put(cache, "tenant-a", [0.1, 0.2, 0.3, 0.4])

    hit = cache.get(
        "tenant-a", DEFAULT_PRINCIPALS, [0.9, 0.1, 0.0, 0.0], similarity_threshold=0.999
    )

    assert hit is None


def test_invalidate_for_document_removes_only_entries_citing_it(client: QdrantClient) -> None:
    cache = SemanticCache(client, COLLECTION, similarity_threshold=0.95, ttl_seconds=3600)
    # [0.9, 0.1, 0.0, 0.0] is deliberately low-cosine-similarity to
    # [0.1, 0.2, 0.3, 0.4] (~0.22) so the two entries can't be confused by
    # the nearest-neighbor lookup below the 0.95 threshold — unlike
    # [0.5, 0.6, 0.7, 0.8], which is coincidentally ~0.97 similar to it.
    _put(cache, "tenant-a", [0.1, 0.2, 0.3, 0.4], document_ids=["doc-1"])
    _put(cache, "tenant-a", [0.9, 0.1, 0.0, 0.0], document_ids=["doc-2"])

    cache.invalidate_for_document("tenant-a", "doc-1")

    assert cache.get("tenant-a", DEFAULT_PRINCIPALS, [0.1, 0.2, 0.3, 0.4]) is None
    remaining = cache.get("tenant-a", DEFAULT_PRINCIPALS, [0.9, 0.1, 0.0, 0.0])
    assert remaining is not None
    assert remaining.document_ids == ["doc-2"]


def test_invalidate_for_document_is_tenant_scoped(client: QdrantClient) -> None:
    cache = SemanticCache(client, COLLECTION, similarity_threshold=0.95, ttl_seconds=3600)
    _put(cache, "tenant-a", [0.1, 0.2, 0.3, 0.4], document_ids=["doc-1"])
    _put(cache, "tenant-b", [0.1, 0.2, 0.3, 0.41], document_ids=["doc-1"])

    cache.invalidate_for_document("tenant-b", "doc-1")

    hit = cache.get("tenant-a", DEFAULT_PRINCIPALS, [0.1, 0.2, 0.3, 0.4])
    assert hit is not None
