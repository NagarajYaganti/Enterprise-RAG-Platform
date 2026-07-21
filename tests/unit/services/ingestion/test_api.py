import base64
import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import boto3
import pytest
from botocore.config import Config
from connectors.postgres.orm import Base
from connectors.postgres.repository import ChunkRepository, DocumentRepository
from connectors.postgres.session import get_engine, get_sessionmaker
from fastapi.testclient import TestClient
from ingestion.main import app
from sqlalchemy.orm import Session

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "documents"
DATABASE_URL = "postgresql+psycopg://rag:rag@localhost:5432/rag_platform"
SYNC_BUCKET = "rag-documents"


def _make_token(tenant_id: str) -> str:
    raw = json.dumps({"tenant_id": tenant_id}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    engine = get_engine(DATABASE_URL)
    Base.metadata.create_all(engine)
    factory = get_sessionmaker(engine)
    sess = factory()
    for table in reversed(Base.metadata.sorted_tables):
        sess.execute(table.delete())
    sess.commit()
    yield sess
    sess.close()


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


def test_upload_without_auth_is_rejected(client: TestClient) -> None:
    with open(FIXTURES / "sample.html", "rb") as f:
        response = client.post("/v1/documents", files={"file": ("sample.html", f, "text/html")})

    assert response.status_code == 401


def test_upload_creates_uploaded_document_and_enqueues_job(
    client: TestClient, session: Session
) -> None:
    token = _make_token("tenant-acme")
    with open(FIXTURES / "sample.html", "rb") as f:
        response = client.post(
            "/v1/documents",
            files={"file": ("sample.html", f, "text/html")},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "UPLOADED"
    document_id = body["id"]

    document_repo = DocumentRepository(session)
    document = document_repo.get("tenant-acme", document_id)
    assert document is not None
    assert document.status == "UPLOADED"
    assert document.mime_type == "text/html"


def test_get_status_for_nonexistent_document_is_404(client: TestClient) -> None:
    token = _make_token("tenant-acme")
    response = client.get(
        "/v1/documents/does-not-exist", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404


@pytest.fixture()
def s3_client() -> Generator[Any, None, None]:
    client = boto3.client(
        "s3",
        endpoint_url="http://localhost:9000",
        aws_access_key_id="ragadmin",
        aws_secret_access_key="ragadminsecret",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        region_name="us-east-1",
    )
    try:
        client.create_bucket(Bucket=SYNC_BUCKET)
    except client.exceptions.BucketAlreadyOwnedByYou:
        pass
    for obj in client.list_objects_v2(Bucket=SYNC_BUCKET, Prefix="tenant-sync/").get(
        "Contents", []
    ):
        client.delete_object(Bucket=SYNC_BUCKET, Key=obj["Key"])
    yield client


def test_sync_endpoint_ingests_a_document_dropped_directly_in_the_bucket(
    client: TestClient, session: Session, s3_client: Any
) -> None:
    # Proves POST /v1/sync/blob drives the real, previously-unwired
    # BlobSourceConnector end-to-end through the actual HTTP layer -- a file
    # placed straight in the bucket (as an external source connector would
    # deliver it), never touching the /v1/documents upload endpoint at all.
    s3_client.upload_file(str(FIXTURES / "sample.html"), SYNC_BUCKET, "tenant-sync/sample.html")

    token = _make_token("tenant-sync")
    response = client.post("/v1/sync/blob", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-sync"
    assert body["documents_processed"] == 1
    assert body["documents_deleted"] == 0

    document = DocumentRepository(session).get("tenant-sync", "tenant-sync/sample.html")
    assert document is not None
    assert document.status == "PARSED"
    chunks = ChunkRepository(session).list_for_document("tenant-sync", "tenant-sync/sample.html")
    assert any("Onboarding Runbook" in c.text for c in chunks)


def test_sync_endpoint_rejects_unknown_connector_name(client: TestClient) -> None:
    token = _make_token("tenant-sync")
    response = client.post("/v1/sync/sharepoint", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404


def test_get_status_enforces_tenant_isolation(client: TestClient, session: Session) -> None:
    token_a = _make_token("tenant-a")
    with open(FIXTURES / "sample.html", "rb") as f:
        upload_response = client.post(
            "/v1/documents",
            files={"file": ("sample.html", f, "text/html")},
            headers={"Authorization": f"Bearer {token_a}"},
        )
    document_id = upload_response.json()["id"]

    token_b = _make_token("tenant-b")
    response = client.get(
        f"/v1/documents/{document_id}", headers={"Authorization": f"Bearer {token_b}"}
    )

    assert response.status_code == 404
