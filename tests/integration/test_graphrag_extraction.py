"""GraphRAG (optional, flagged OFF by default per Section 4 Phase 3 task
text): proves the GRAPHRAG_ENABLED env var genuinely gates entity/relation
extraction through the REAL arq embedding worker (not just at the
process_embedding_job unit level, already covered in
tests/unit/services/embedding/test_worker.py) — with the flag unset, the
worker never touches the entities/relations tables; with it set, it does.
"""

import pytest
from connectors.graph.postgres_knowledge_graph import PostgresKnowledgeGraph
from connectors.postgres.repository import ChunkRepository, DocumentRepository
from core.models import Chunk, Document
from embedding.queue import enqueue_embed_job, get_redis_pool
from sqlalchemy.orm import Session

from tests.integration.conftest import run_embed_worker_burst

MODEL_ID = "BAAI/bge-small-en-v1.5"


def _seed_document(session: Session, tenant_id: str, document_id: str, text: str) -> None:
    doc_repo = DocumentRepository(session)
    chunk_repo = ChunkRepository(session)
    doc_repo.upsert(
        Document(
            id=document_id,
            tenant_id=tenant_id,
            source_uri=f"graphrag://{document_id}",
            mime_type="text/plain",
            checksum=document_id,
            version=1,
            status="PARSED",
        )
    )
    chunk_repo.bulk_insert(
        [
            Chunk(
                id=f"{document_id}-chunk-0",
                tenant_id=tenant_id,
                document_id=document_id,
                text=text,
                position=0,
                language="en",
                version=1,
            )
        ]
    )
    session.commit()


@pytest.mark.asyncio
async def test_graphrag_disabled_by_default_extracts_no_entities(
    db_session: Session,
    clean_queue: None,
    clean_embedding_stores: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GRAPHRAG_ENABLED", raising=False)
    tenant_id = "tenant-graphrag-off"
    document_id = "doc-graphrag-off"
    _seed_document(db_session, tenant_id, document_id, "Acme Bank owns Acme Lending Corp.")

    redis_pool = await get_redis_pool()
    await enqueue_embed_job(redis_pool, tenant_id, document_id, MODEL_ID, "1")
    await redis_pool.aclose()

    embed_complete, embed_failed = await run_embed_worker_burst()
    assert embed_failed == 0 and embed_complete == 1

    entities, relations = PostgresKnowledgeGraph(db_session).query_subgraph(
        tenant_id, ["Acme Bank", "Acme Lending Corp."]
    )
    assert entities == []
    assert relations == []


@pytest.mark.asyncio
async def test_graphrag_enabled_extracts_entities_and_relations(
    db_session: Session,
    clean_queue: None,
    clean_embedding_stores: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GRAPHRAG_ENABLED", "true")
    tenant_id = "tenant-graphrag-on"
    document_id = "doc-graphrag-on"
    _seed_document(db_session, tenant_id, document_id, "Acme Bank owns Acme Lending Corp.")

    redis_pool = await get_redis_pool()
    await enqueue_embed_job(redis_pool, tenant_id, document_id, MODEL_ID, "1")
    await redis_pool.aclose()

    embed_complete, embed_failed = await run_embed_worker_burst()
    assert embed_failed == 0 and embed_complete == 1

    entities, relations = PostgresKnowledgeGraph(db_session).query_subgraph(
        tenant_id, ["Acme Bank", "Acme Lending Corp."]
    )
    assert {e.name for e in entities} == {"Acme Bank", "Acme Lending Corp."}
    assert len(relations) == 1
