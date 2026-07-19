import json
from collections.abc import Generator

import pytest
import pytest_asyncio
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from connectors.postgres.orm import Base
from connectors.postgres.session import get_engine, get_sessionmaker
from embedding.worker import DLQ_KEY, MAX_TRIES, embed_chunks
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL = "postgresql+psycopg://rag:rag@localhost:5432/rag_platform"


@pytest.fixture()
def session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = get_engine(DATABASE_URL)
    Base.metadata.create_all(engine)
    factory = get_sessionmaker(engine)
    with factory() as sess:
        for table in reversed(Base.metadata.sorted_tables):
            sess.execute(table.delete())
        sess.commit()
    yield factory


@pytest_asyncio.fixture()
async def redis_pool() -> ArqRedis:
    pool = await create_pool(RedisSettings(host="localhost", port=6379))
    await pool.delete(DLQ_KEY)
    return pool


@pytest.mark.asyncio
async def test_embed_chunks_pushes_to_dlq_only_on_final_try(
    session_factory: sessionmaker[Session], redis_pool: ArqRedis
) -> None:
    # tenant/document don't exist -> process_embedding_job raises ValueError
    ctx = {
        "session_factory": session_factory,
        "vector_store": None,
        "keyword_index": None,
        "embedding_provider": None,
        "redis": redis_pool,
        "job_try": 1,  # not the final try yet
    }

    with pytest.raises(ValueError, match="no document"):
        await embed_chunks(ctx, "tenant-a", "doc-does-not-exist", "some-model", "1")

    assert await redis_pool.llen(DLQ_KEY) == 0  # type: ignore[misc]  # not pushed yet


@pytest.mark.asyncio
async def test_embed_chunks_pushes_to_dlq_on_final_try(
    session_factory: sessionmaker[Session], redis_pool: ArqRedis
) -> None:
    ctx = {
        "session_factory": session_factory,
        "vector_store": None,
        "keyword_index": None,
        "embedding_provider": None,
        "redis": redis_pool,
        "job_try": MAX_TRIES,  # final allowed try
    }

    with pytest.raises(ValueError, match="no document"):
        await embed_chunks(ctx, "tenant-a", "doc-does-not-exist", "some-model", "1")

    assert await redis_pool.llen(DLQ_KEY) == 1  # type: ignore[misc]
    raw = await redis_pool.lpop(DLQ_KEY)  # type: ignore[misc]
    entry = json.loads(raw)
    assert entry["tenant_id"] == "tenant-a"
    assert entry["document_id"] == "doc-does-not-exist"
    assert "no document" in entry["error"]
