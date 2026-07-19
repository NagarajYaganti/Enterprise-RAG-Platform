from typing import Any

import pytest
from connectors.embeddings.sentence_transformers_provider import SentenceTransformersProvider
from connectors.keyword.opensearch_index import OpenSearchIndex
from connectors.postgres.repository import ChunkRepository, DocumentRepository
from connectors.vectorstores.qdrant_store import QdrantVectorStore
from core.interfaces import VectorStore
from core.models import Chunk, Document
from embedding.queue import enqueue_embed_job, get_redis_pool
from embedding.worker import COLLECTION_NAME, process_embedding_job
from opensearchpy import OpenSearch
from qdrant_client import QdrantClient
from sqlalchemy.orm import Session

from tests.integration.conftest import run_embed_worker_burst

MODEL_ID = "BAAI/bge-small-en-v1.5"


def _count_points_for_document(client: QdrantClient, document_id: str) -> int:
    scroll_result = client.scroll(COLLECTION_NAME, limit=1000)
    return sum(
        1
        for p in scroll_result[0]
        if p.payload and p.payload.get("document_id") == document_id
    )


class _CrashAfterN(VectorStore):
    """Wraps a real VectorStore, raising after N upserts to simulate a
    worker process dying partway through a batch. Unlike relying on arq's
    own exception-based retry (which, verified empirically, immediately
    re-attempts within the same burst call up to max_tries and so isn't a
    faithful stand-in for a real process crash), this directly controls
    exactly how many chunks got persisted before the "crash" — the failure
    point a real process kill would leave behind.
    """

    def __init__(self, real: VectorStore, fail_after: int) -> None:
        self._real = real
        self._fail_after = fail_after
        self.calls = 0

    def upsert(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        if self.calls > self._fail_after:
            raise RuntimeError("simulated worker crash mid-batch")
        return self._real.upsert(tenant_id, *args, **kwargs)

    def search(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
        return self._real.search(tenant_id, *args, **kwargs)

    def delete(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
        return self._real.delete(tenant_id, *args, **kwargs)


@pytest.mark.asyncio
async def test_kill_embed_worker_mid_batch_then_restart_via_real_arq_has_no_dupes_or_losses(
    db_session: Session, clean_queue: None, clean_embedding_stores: None
) -> None:
    tenant_id = "tenant-acme"
    document_id = "doc-idempotency-test"
    doc_repo = DocumentRepository(db_session)
    chunk_repo = ChunkRepository(db_session)
    doc_repo.upsert(
        Document(
            id=document_id,
            tenant_id=tenant_id,
            source_uri=f"s3://bucket/{document_id}",
            mime_type="text/plain",
            checksum="abc123",
            version=1,
            status="PARSED",
        )
    )
    chunk_repo.bulk_insert(
        [
            Chunk(
                id=f"{document_id}-chunk-{i}",
                tenant_id=tenant_id,
                document_id=document_id,
                text=f"quarterly earnings paragraph number {i}",
                position=i,
                language="en",
                version=1,
            )
            for i in range(5)
        ]
    )
    db_session.commit()

    qdrant_client = QdrantClient(url="http://localhost:6333")
    real_vector_store = QdrantVectorStore(qdrant_client, COLLECTION_NAME)

    opensearch_client = OpenSearch(
        hosts=[{"host": "localhost", "port": 9200}], use_ssl=False, verify_certs=False
    )
    keyword_index = OpenSearchIndex(opensearch_client, "chunks")
    provider = SentenceTransformersProvider(MODEL_ID)

    # "Kill mid-batch": a direct call, wrapped to crash after 2 of 5 upserts.
    crashing_store = _CrashAfterN(real_vector_store, fail_after=2)
    with pytest.raises(RuntimeError, match="simulated worker crash mid-batch"):
        process_embedding_job(
            db_session,
            crashing_store,
            keyword_index,
            provider,
            tenant_id,
            document_id,
            MODEL_ID,
            "1",
        )

    partial_count = _count_points_for_document(qdrant_client, document_id)
    assert partial_count == 2

    # "Restart": enqueue and run the REAL arq embed_chunks job end-to-end —
    # this leg is what makes it an integration test, not a repeat of the
    # unit-level idempotency test which calls process_embedding_job directly
    # for both legs.
    redis_pool = await get_redis_pool()
    await enqueue_embed_job(redis_pool, tenant_id, document_id, MODEL_ID, "1")
    await redis_pool.aclose()

    embed_complete, embed_failed = await run_embed_worker_burst()
    assert embed_failed == 0
    assert embed_complete == 1

    final_count = _count_points_for_document(qdrant_client, document_id)
    assert final_count == 5  # all 5 chunks, not 5 + 2 = 7

    all_points = qdrant_client.scroll(COLLECTION_NAME, limit=1000)[0]
    point_ids = [
        p.id for p in all_points if p.payload and p.payload.get("document_id") == document_id
    ]
    assert len(point_ids) == len(set(point_ids))  # no duplicate ids
