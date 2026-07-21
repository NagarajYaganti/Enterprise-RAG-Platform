import base64
import json
from pathlib import Path

import pytest
from embedding.worker import COLLECTION_NAME, INDEX_NAME
from fastapi.testclient import TestClient
from ingestion.main import app
from opensearchpy import OpenSearch
from qdrant_client import QdrantClient
from sqlalchemy.orm import Session

from tests.integration.conftest import run_embed_worker_burst, run_worker_burst

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"


def _make_token(tenant_id: str) -> str:
    raw = json.dumps({"tenant_id": tenant_id}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.mark.asyncio
async def test_identical_documents_for_two_tenants_search_returns_own_tenant_only(
    db_session: Session, clean_queue: None, clean_embedding_stores: None
) -> None:
    token_a = _make_token("tenant-a")
    token_b = _make_token("tenant-b")

    with TestClient(app) as client:
        for token in (token_a, token_b):
            with open(FIXTURES / "sample.html", "rb") as f:
                response = client.post(
                    "/v1/documents",
                    files={"file": ("sample.html", f, "text/html")},
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert response.status_code == 200

        parse_complete, parse_failed = await run_worker_burst()
        assert parse_failed == 0 and parse_complete == 2

        embed_complete, embed_failed = await run_embed_worker_burst()
        assert embed_failed == 0 and embed_complete == 2

    qdrant_client = QdrantClient(url="http://localhost:6333")
    scroll_result = qdrant_client.scroll(COLLECTION_NAME, limit=100)
    points_by_tenant: dict[str, int] = {}
    for point in scroll_result[0]:
        assert point.payload is not None
        tenant = point.payload["tenant_id"]
        points_by_tenant[tenant] = points_by_tenant.get(tenant, 0) + 1

    assert points_by_tenant.get("tenant-a", 0) > 0
    assert points_by_tenant.get("tenant-b", 0) > 0
    assert points_by_tenant["tenant-a"] == points_by_tenant["tenant-b"]  # identical docs

    opensearch_client = OpenSearch(
        hosts=[{"host": "localhost", "port": 9200}], use_ssl=False, verify_certs=False
    )
    for tenant_id in ("tenant-a", "tenant-b"):
        hits = opensearch_client.search(
            index=f"{INDEX_NAME}_*", body={"query": {"term": {"tenant_id": tenant_id}}}
        )["hits"]["hits"]
        assert len(hits) > 0
        assert all(h["_source"]["tenant_id"] == tenant_id for h in hits)
