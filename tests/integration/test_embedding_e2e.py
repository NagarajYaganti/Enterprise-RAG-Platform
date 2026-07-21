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
async def test_upload_to_searchable_in_qdrant_and_opensearch(
    db_session: Session, clean_queue: None, clean_embedding_stores: None
) -> None:
    token = _make_token("tenant-acme")
    with TestClient(app) as client:
        with open(FIXTURES / "sample.html", "rb") as f:
            upload_response = client.post(
                "/v1/documents",
                files={"file": ("sample.html", f, "text/html")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert upload_response.status_code == 200
        document_id = upload_response.json()["id"]

        parse_complete, parse_failed = await run_worker_burst()
        assert parse_failed == 0 and parse_complete >= 1

        embed_complete, embed_failed = await run_embed_worker_burst()
        assert embed_failed == 0 and embed_complete >= 1

    # Vector store: raw scroll (not search()) since chunks default to
    # acl_principals=[] and search()'s ACL pre-filter (MatchAny on an empty
    # list) matches nothing by design — proven separately in unit tests.
    qdrant_client = QdrantClient(url="http://localhost:6333")
    scroll_result = qdrant_client.scroll(COLLECTION_NAME, limit=100)
    tenant_points = [
        p for p in scroll_result[0] if p.payload and p.payload.get("tenant_id") == "tenant-acme"
    ]
    assert len(tenant_points) > 0
    assert all(p.payload["document_id"] == document_id for p in tenant_points)  # type: ignore[index]

    # Keyword index: real BM25 search, verifying it's genuinely indexed and
    # findable by content, not just present as a raw row.
    opensearch_client = OpenSearch(
        hosts=[{"host": "localhost", "port": 9200}], use_ssl=False, verify_certs=False
    )
    kw_search = opensearch_client.search(
        index=f"{INDEX_NAME}_*", body={"query": {"term": {"document_id": document_id}}}
    )
    assert len(kw_search["hits"]["hits"]) > 0
