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
