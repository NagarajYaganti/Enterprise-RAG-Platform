import base64
import json
from pathlib import Path

import pytest
from embedding.queue import EMBED_QUEUE_NAME, get_redis_pool
from fastapi.testclient import TestClient
from ingestion.main import app
from sqlalchemy.orm import Session

from tests.integration.conftest import run_worker_burst

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"


def _make_token(tenant_id: str) -> str:
    raw = json.dumps({"tenant_id": tenant_id}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.mark.asyncio
async def test_embed_chunks_job_is_enqueued_after_a_document_is_parsed(
    db_session: Session, clean_queue: None
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

        # runs the ingestion worker (parse_document), which per this
        # phase's wiring now enqueues embed_chunks onto the embed queue
        jobs_complete, jobs_failed = await run_worker_burst()
        assert jobs_failed == 0 and jobs_complete >= 1

    redis_pool = await get_redis_pool()
    try:
        queued = await redis_pool.queued_jobs(queue_name=EMBED_QUEUE_NAME)
        assert any(job.function == "embed_chunks" for job in queued)
    finally:
        await redis_pool.aclose()
