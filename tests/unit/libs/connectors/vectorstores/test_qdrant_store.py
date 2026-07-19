import uuid
from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from connectors.vectorstores.errors import TenantMismatchError
from connectors.vectorstores.migrations import ensure_qdrant_collection
from connectors.vectorstores.qdrant_store import QdrantVectorStore
from core.models import EmbeddingRecord
from qdrant_client import QdrantClient

QDRANT_URL = "http://localhost:6333"
COLLECTION = "test_qdrant_store_collection"


@pytest.fixture()
def client() -> Generator[QdrantClient, None, None]:
    c = QdrantClient(url=QDRANT_URL)
    ensure_qdrant_collection(c, COLLECTION, dimension=4)
    yield c
    c.delete_collection(COLLECTION)


def _record(
    tenant_id: str,
    chunk_id: str,
    vector: list[float],
    principals: list[str],
    model_id: str = "bge-small",
) -> EmbeddingRecord:
    # Qdrant point IDs must be an unsigned int or a UUID (verified against the
    # real API) — id and chunk_id are deliberately different here: id is a
    # UUID5 derived from chunk_id+model_id so tests stay readable while
    # satisfying that constraint, matching how production ids are real UUIDs
    # already (and matching the worker's own deterministic-id scheme).
    return EmbeddingRecord(
        id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{chunk_id}:{model_id}")),
        tenant_id=tenant_id,
        document_id=f"doc-{chunk_id}",
        chunk_id=chunk_id,
        vector=vector,
        model_id=model_id,
        model_version="1",
        acl_principals=principals,
    )


def test_upsert_rejects_record_from_a_different_tenant(client: QdrantClient) -> None:
    store = QdrantVectorStore(client, COLLECTION)
    bad_record = _record("tenant-b", "c1", [0.1, 0.2, 0.3, 0.4], ["p1"])

    with pytest.raises(TenantMismatchError):
        store.upsert("tenant-a", [bad_record])


def test_search_is_tenant_isolated(client: QdrantClient) -> None:
    store = QdrantVectorStore(client, COLLECTION)
    store.upsert(
        "tenant-a", [_record("tenant-a", "c1", [0.1, 0.2, 0.3, 0.4], ["p1"])]
    )
    store.upsert(
        "tenant-b", [_record("tenant-b", "c2", [0.1, 0.2, 0.3, 0.41], ["p1"])]
    )

    hits = store.search("tenant-a", [0.1, 0.2, 0.3, 0.4], principals=["p1"], top_k=10)

    assert [h.chunk_id for h in hits] == ["c1"]


def test_search_prefilters_on_acl_principals(client: QdrantClient) -> None:
    store = QdrantVectorStore(client, COLLECTION)
    store.upsert(
        "tenant-a",
        [
            _record("tenant-a", "c3", [0.1, 0.2, 0.3, 0.4], ["p1"]),
            _record("tenant-a", "c4", [0.1, 0.2, 0.3, 0.4], ["p9"]),
        ],
    )

    hits = store.search("tenant-a", [0.1, 0.2, 0.3, 0.4], principals=["p1"], top_k=10)

    assert {h.chunk_id for h in hits} == {"c3"}


def test_search_delegates_filter_to_qdrant_not_post_filtering() -> None:
    """Proves the adapter passes a query_filter into query_points (server-
    side pre-filter), not that it fetches broadly and filters in Python —
    the distinction GAP-MATRIX warns matters for ACL leak prevention.
    """
    mock_client = MagicMock(spec=QdrantClient)
    mock_client.query_points.return_value = MagicMock(points=[])
    store = QdrantVectorStore(mock_client, COLLECTION)

    store.search("tenant-a", [0.1, 0.2, 0.3, 0.4], principals=["p1"], top_k=5)

    assert mock_client.query_points.called
    _, call_kwargs = mock_client.query_points.call_args
    assert call_kwargs["query_filter"] is not None
    filter_str = str(call_kwargs["query_filter"])
    assert "tenant_id" in filter_str
    assert "acl_principals" in filter_str


def test_delete_removes_only_the_target_document(client: QdrantClient) -> None:
    store = QdrantVectorStore(client, COLLECTION)
    store.upsert(
        "tenant-a",
        [
            _record("tenant-a", "c5", [0.1, 0.2, 0.3, 0.4], ["p1"]),
            _record("tenant-a", "c6", [0.5, 0.6, 0.7, 0.8], ["p1"]),
        ],
    )

    store.delete("tenant-a", "doc-c5")

    remaining = store.search("tenant-a", [0.1, 0.2, 0.3, 0.4], principals=["p1"], top_k=10)
    assert {h.chunk_id for h in remaining} == {"c6"}


def test_delete_is_tenant_scoped(client: QdrantClient) -> None:
    store = QdrantVectorStore(client, COLLECTION)
    store.upsert(
        "tenant-a", [_record("tenant-a", "c7", [0.1, 0.2, 0.3, 0.4], ["p1"])]
    )
    store.upsert(
        "tenant-b", [_record("tenant-b", "c7dup", [0.1, 0.2, 0.3, 0.4], ["p1"])]
    )

    store.delete("tenant-b", "doc-c7dup")

    remaining_a = store.search("tenant-a", [0.1, 0.2, 0.3, 0.4], principals=["p1"], top_k=10)
    assert {h.chunk_id for h in remaining_a} == {"c7"}


def test_supersede_by_model_flips_status_for_matching_model_only(client: QdrantClient) -> None:
    store = QdrantVectorStore(client, COLLECTION)
    store.upsert(
        "tenant-a",
        [
            _record("tenant-a", "c8", [0.1, 0.2, 0.3, 0.4], ["p1"], model_id="old-model"),
        ],
    )
    store.upsert(
        "tenant-a",
        [
            _record("tenant-a", "c8", [0.1, 0.2, 0.3, 0.4], ["p1"], model_id="new-model"),
        ],
    )

    store.supersede_by_model("tenant-a", "doc-c8", "old-model")

    active_hits = store.search("tenant-a", [0.1, 0.2, 0.3, 0.4], principals=["p1"], top_k=10)
    assert {h.model_id for h in active_hits} == {"new-model"}

    superseded_hits = store.search(
        "tenant-a", [0.1, 0.2, 0.3, 0.4], principals=["p1"], top_k=10, status="superseded"
    )
    assert {h.model_id for h in superseded_hits} == {"old-model"}
