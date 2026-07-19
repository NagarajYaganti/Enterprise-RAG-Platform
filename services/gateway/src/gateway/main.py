from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

from gateway.middleware.tenant_context import TenantContextMiddleware

app = FastAPI(title="rag-platform-gateway")
app.add_middleware(TenantContextMiddleware)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
