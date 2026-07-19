from collections.abc import Generator

import pytest
import pytest_asyncio
from connectors.postgres.orm import Base
from connectors.postgres.session import get_engine, get_sessionmaker
from ingestion.queue import get_redis_pool
from sqlalchemy.orm import Session

DATABASE_URL = "postgresql+psycopg://rag:rag@localhost:5432/rag_platform"


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = get_engine(DATABASE_URL)
    Base.metadata.create_all(engine)
    factory = get_sessionmaker(engine)
    sess = factory()
    for table in reversed(Base.metadata.sorted_tables):
        sess.execute(table.delete())
    sess.commit()
    yield sess
    sess.close()


@pytest_asyncio.fixture()
async def clean_queue() -> None:
    redis_pool = await get_redis_pool()
    await redis_pool.flushdb()
    await redis_pool.aclose()


@pytest.fixture()
def clean_embedding_stores() -> None:
    """Embedding integration tests share the same production Qdrant
    collection / OpenSearch index names the real worker uses (embedding.
    worker.COLLECTION_NAME / INDEX_NAME) — without this, leftover points
    from a previous test run bleed into the next one's assertions (caught
    empirically: a "partial count" assertion saw 5 points instead of 2
    because an earlier test's full 5-point run was never cleaned up).
    """
    from connectors.vectorstores.migrations import ensure_qdrant_collection
    from embedding.worker import COLLECTION_NAME, INDEX_NAME
    from opensearchpy import OpenSearch
    from qdrant_client import QdrantClient

    qdrant_client = QdrantClient(url="http://localhost:6333")
    if qdrant_client.collection_exists(COLLECTION_NAME):
        qdrant_client.delete_collection(COLLECTION_NAME)
    ensure_qdrant_collection(qdrant_client, COLLECTION_NAME, dimension=384)

    opensearch_client = OpenSearch(
        hosts=[{"host": "localhost", "port": 9200}], use_ssl=False, verify_certs=False
    )
    opensearch_client.indices.delete(index=INDEX_NAME, ignore=[404])


async def run_worker_burst() -> tuple[int, int]:
    """Runs the real arq worker (services.ingestion.worker.WorkerSettings)
    in burst mode: processes everything currently queued, then exits. Used
    so integration tests exercise the actual job function via the real
    queue, not a direct function call that bypasses arq entirely.
    """
    from arq.worker import Worker
    from ingestion.queue import get_redis_settings
    from ingestion.worker import on_startup, parse_document

    worker = Worker(
        functions=[parse_document],
        redis_settings=get_redis_settings(),
        on_startup=on_startup,
        burst=True,
        handle_signals=False,
    )
    await worker.async_run()
    jobs_complete, jobs_failed = worker.jobs_complete, worker.jobs_failed
    await worker.close()
    return jobs_complete, jobs_failed


async def run_embed_worker_burst(max_tries: int = 3) -> tuple[int, int]:
    """Same idea as run_worker_burst, for the embedding queue/worker."""
    from arq.worker import Worker
    from embedding.queue import EMBED_QUEUE_NAME
    from embedding.queue import get_redis_settings as get_embed_redis_settings
    from embedding.worker import embed_chunks
    from embedding.worker import on_startup as embed_on_startup

    worker = Worker(
        functions=[embed_chunks],
        redis_settings=get_embed_redis_settings(),
        on_startup=embed_on_startup,
        queue_name=EMBED_QUEUE_NAME,
        max_tries=max_tries,
        burst=True,
        handle_signals=False,
    )
    await worker.async_run()
    jobs_complete, jobs_failed = worker.jobs_complete, worker.jobs_failed
    await worker.close()
    return jobs_complete, jobs_failed
