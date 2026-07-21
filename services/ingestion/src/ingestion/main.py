from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from core.middleware import TenantContextMiddleware
from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

from ingestion.api import _s3_client, _storage_settings, router, sync_router
from ingestion.queue import get_redis_pool
from ingestion.storage import ensure_bucket


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ensure_bucket(_s3_client, _storage_settings.s3_bucket)
    app.state.redis_pool = await get_redis_pool()
    yield
    await app.state.redis_pool.aclose()


app = FastAPI(title="rag-platform-ingestion", lifespan=lifespan)
app.add_middleware(TenantContextMiddleware)
app.include_router(router)
app.include_router(sync_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
