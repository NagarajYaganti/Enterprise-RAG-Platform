from collections.abc import Generator
from pathlib import Path

import boto3
import pytest
from botocore.config import Config
from connectors.parser_registry import ParserRegistry
from connectors.sources.blob_connector import BlobSourceConnector

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures" / "documents"
BUCKET = "rag-test-bucket"


@pytest.fixture()
def s3_client() -> Generator[object, None, None]:
    client = boto3.client(
        "s3",
        endpoint_url="http://localhost:9000",
        aws_access_key_id="ragadmin",
        aws_secret_access_key="ragadminsecret",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        region_name="us-east-1",
    )
    try:
        client.create_bucket(Bucket=BUCKET)
    except client.exceptions.BucketAlreadyOwnedByYou:
        pass

    for obj in client.list_objects_v2(Bucket=BUCKET).get("Contents", []):
        client.delete_object(Bucket=BUCKET, Key=obj["Key"])

    client.upload_file(str(FIXTURES / "sample.html"), BUCKET, "docs/sample.html")
    client.upload_file(str(FIXTURES / "sample.eml"), BUCKET, "docs/sample.eml")

    yield client


def test_list_documents_returns_all_when_since_is_none(s3_client: object) -> None:
    registry = ParserRegistry(stt_model_size="tiny")
    connector = BlobSourceConnector(
        s3_client,
        BUCKET,
        "tenant-acme",
        registry,
        known_keys_provider=lambda: set(),
        prefix="docs/",
    )

    refs = connector.list_documents(None)

    assert {ref.key for ref in refs} == {"docs/sample.html", "docs/sample.eml"}


def test_fetch_parses_the_object_content(s3_client: object) -> None:
    registry = ParserRegistry(stt_model_size="tiny")
    connector = BlobSourceConnector(
        s3_client,
        BUCKET,
        "tenant-acme",
        registry,
        known_keys_provider=lambda: set(),
        prefix="docs/",
    )
    refs = {ref.key: ref for ref in connector.list_documents(None)}

    result = connector.fetch(refs["docs/sample.html"])

    assert "Onboarding Runbook" in result.raw_text
    assert result.tenant_id == "tenant-acme"
    assert result.document_id == "docs/sample.html"


def test_list_deletions_detects_removed_keys(s3_client: object) -> None:
    registry = ParserRegistry(stt_model_size="tiny")
    known_keys = {"docs/sample.html", "docs/sample.eml", "docs/already-gone.pdf"}
    connector = BlobSourceConnector(
        s3_client,
        BUCKET,
        "tenant-acme",
        registry,
        known_keys_provider=lambda: known_keys,
        prefix="docs/",
    )

    deletions = connector.list_deletions(None)

    assert deletions == ["docs/already-gone.pdf"]
