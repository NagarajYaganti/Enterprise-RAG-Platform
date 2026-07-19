import base64
import json
from pathlib import Path

import pytest
from connectors.postgres.repository import ChunkRepository
from fastapi.testclient import TestClient
from ingestion.main import app
from sqlalchemy.orm import Session

from tests.integration.conftest import run_worker_burst

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"

FIXTURE_CASES = [
    ("sample.pdf", "application/pdf"),
    (
        "sample.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    (
        "sample.pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
    (
        "sample.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    ("sample.html", "text/html"),
    ("sample_ocr.png", "image/png"),
    ("sample_audio.wav", "audio/wav"),
    ("sample.eml", "message/rfc822"),
]


def _make_token(tenant_id: str) -> str:
    raw = json.dumps({"tenant_id": tenant_id}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.mark.asyncio
@pytest.mark.parametrize("filename,mime_type", FIXTURE_CASES)
async def test_upload_each_format_reaches_parsed(
    db_session: Session, clean_queue: None, filename: str, mime_type: str
) -> None:
    token = _make_token("tenant-acme")
    with TestClient(app) as client:
        with open(FIXTURES / filename, "rb") as f:
            upload_response = client.post(
                "/v1/documents",
                files={"file": (filename, f, mime_type)},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert upload_response.status_code == 200
        document_id = upload_response.json()["id"]
        assert upload_response.json()["status"] == "UPLOADED"

        jobs_complete, jobs_failed = await run_worker_burst()
        assert jobs_failed == 0, f"{filename}: {jobs_failed} job(s) failed"
        assert jobs_complete >= 1

        status_response = client.get(
            f"/v1/documents/{document_id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "PARSED", (
            f"{filename} did not reach PARSED: {status_response.json()}"
        )

    chunk_repo = ChunkRepository(db_session)
    chunks = chunk_repo.list_for_document("tenant-acme", document_id)
    assert len(chunks) > 0, f"{filename} produced no chunks"
    assert all(c.tenant_id == "tenant-acme" for c in chunks)
    assert all(c.language for c in chunks)
    assert all(c.version == 1 for c in chunks)
    assert all(c.metadata for c in chunks)
