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


@pytest.mark.asyncio
async def test_second_tenant_cannot_see_first_tenants_document(
    db_session: Session, clean_queue: None
) -> None:
    token_a = _make_token("tenant-a")
    token_b = _make_token("tenant-b")

    with TestClient(app) as client:
        with open(FIXTURES / "sample.html", "rb") as f:
            upload_response = client.post(
                "/v1/documents",
                files={"file": ("isolated.html", f, "text/html")},
                headers={"Authorization": f"Bearer {token_a}"},
            )
        document_id = upload_response.json()["id"]

        jobs_complete, jobs_failed = await run_worker_burst()
        assert jobs_failed == 0 and jobs_complete >= 1

        # Owning tenant can see it.
        own_status = client.get(
            f"/v1/documents/{document_id}", headers={"Authorization": f"Bearer {token_a}"}
        )
        assert own_status.status_code == 200
        assert own_status.json()["status"] == "PARSED"

        # A different tenant, guessing the same document id, gets 404 — not
        # the document's real status, not even a 403 that would confirm it exists.
        other_status = client.get(
            f"/v1/documents/{document_id}", headers={"Authorization": f"Bearer {token_b}"}
        )
        assert other_status.status_code == 404

    # Defense-in-depth: the repository layer itself enforces the same
    # isolation, independent of the API.
    document_repo = DocumentRepository(db_session)
    assert document_repo.get("tenant-b", document_id) is None
    assert document_repo.get("tenant-a", document_id) is not None

    chunk_repo = ChunkRepository(db_session)
    assert chunk_repo.list_for_document("tenant-b", document_id) == []
    assert len(chunk_repo.list_for_document("tenant-a", document_id)) > 0


@pytest.mark.asyncio
async def test_identical_filename_by_two_tenants_are_independent_documents(
    db_session: Session, clean_queue: None
) -> None:
    token_a = _make_token("tenant-a")
    token_b = _make_token("tenant-b")

    with TestClient(app) as client:
        with open(FIXTURES / "sample.html", "rb") as f:
            response_a = client.post(
                "/v1/documents",
                files={"file": ("shared-name.html", f, "text/html")},
                headers={"Authorization": f"Bearer {token_a}"},
            )
        with open(FIXTURES / "sample.html", "rb") as f:
            response_b = client.post(
                "/v1/documents",
                files={"file": ("shared-name.html", f, "text/html")},
                headers={"Authorization": f"Bearer {token_b}"},
            )

        doc_id_a = response_a.json()["id"]
        doc_id_b = response_b.json()["id"]

        # Same filename, different tenants -> must NOT collide on document id
        # (the id derivation includes tenant_id specifically to prevent this).
        assert doc_id_a != doc_id_b

        jobs_complete, jobs_failed = await run_worker_burst()
        assert jobs_failed == 0 and jobs_complete == 2

        status_a = client.get(
            f"/v1/documents/{doc_id_a}", headers={"Authorization": f"Bearer {token_a}"}
        )
        status_b = client.get(
            f"/v1/documents/{doc_id_b}", headers={"Authorization": f"Bearer {token_b}"}
        )
        assert status_a.json()["status"] == "PARSED"
        assert status_b.json()["status"] == "PARSED"

        # Cross-tenant lookups of each other's id still fail.
        assert client.get(
            f"/v1/documents/{doc_id_a}", headers={"Authorization": f"Bearer {token_b}"}
        ).status_code == 404
        assert client.get(
            f"/v1/documents/{doc_id_b}", headers={"Authorization": f"Bearer {token_a}"}
        ).status_code == 404
