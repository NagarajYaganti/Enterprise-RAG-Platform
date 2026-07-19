import base64
import json
from pathlib import Path

import pytest
from connectors.postgres.repository import ChunkRepository, DocumentRepository
from fastapi.testclient import TestClient
from ingestion.main import app
from sqlalchemy.orm import Session

from tests.integration.conftest import run_worker_burst

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"


def _make_token(tenant_id: str) -> str:
    raw = json.dumps({"tenant_id": tenant_id}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _upload(client: TestClient, token: str, filename: str, mime_type: str, content: bytes) -> str:
    response = client.post(
        "/v1/documents",
        files={"file": (filename, content, mime_type)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    document_id: str = response.json()["id"]
    return document_id


@pytest.mark.asyncio
async def test_reupload_identical_file_stays_version_one(
    db_session: Session, clean_queue: None
) -> None:
    token = _make_token("tenant-acme")
    content = (FIXTURES / "sample.html").read_bytes()

    with TestClient(app) as client:
        doc_id_1 = _upload(client, token, "versioning.html", "text/html", content)
        jobs_complete, jobs_failed = await run_worker_burst()
        assert jobs_failed == 0 and jobs_complete >= 1

        doc_id_2 = _upload(client, token, "versioning.html", "text/html", content)
        jobs_complete, jobs_failed = await run_worker_burst()
        assert jobs_failed == 0 and jobs_complete >= 1

        assert doc_id_1 == doc_id_2, "re-uploading the same filename should reuse the document id"

        status = client.get(
            f"/v1/documents/{doc_id_1}", headers={"Authorization": f"Bearer {token}"}
        )
        assert status.json()["status"] == "PARSED"
        assert status.json()["version"] == "1"

    chunks = ChunkRepository(db_session).list_for_document("tenant-acme", doc_id_1)
    assert all(c.version == 1 for c in chunks)
    assert all(c.status == "active" for c in chunks)


@pytest.mark.asyncio
async def test_reupload_changed_content_bumps_version_and_supersedes_old_chunks(
    db_session: Session, clean_queue: None
) -> None:
    token = _make_token("tenant-acme")
    original = b"<html><body><h1>Original Title</h1><p>Original body text.</p></body></html>"
    changed = b"<html><body><h1>Revised Title</h1><p>Revised body text.</p></body></html>"

    with TestClient(app) as client:
        doc_id = _upload(client, token, "revision.html", "text/html", original)
        jobs_complete, jobs_failed = await run_worker_burst()
        assert jobs_failed == 0 and jobs_complete >= 1

        status = client.get(
            f"/v1/documents/{doc_id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert status.json()["version"] == "1"

        _upload(client, token, "revision.html", "text/html", changed)
        jobs_complete, jobs_failed = await run_worker_burst()
        assert jobs_failed == 0 and jobs_complete >= 1

        status = client.get(
            f"/v1/documents/{doc_id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert status.json()["status"] == "PARSED"
        assert status.json()["version"] == "2"

    document_repo = DocumentRepository(db_session)
    document = document_repo.get("tenant-acme", doc_id)
    assert document is not None
    assert document.version == 2

    chunk_repo = ChunkRepository(db_session)
    active_chunks = chunk_repo.list_for_document("tenant-acme", doc_id, active_only=True)
    all_chunks = chunk_repo.list_for_document("tenant-acme", doc_id, active_only=False)

    assert any("Revised Title" in c.text for c in active_chunks)
    assert all(c.version == 2 for c in active_chunks)
    assert any(c.status == "superseded" for c in all_chunks)
    assert any("Original Title" in c.text for c in all_chunks if c.status == "superseded")
