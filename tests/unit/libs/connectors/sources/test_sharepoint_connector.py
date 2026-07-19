from pathlib import Path

import httpx
from connectors.parser_registry import ParserRegistry
from connectors.sources.sharepoint_connector import SharePointConnector

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures" / "documents"
DRIVE_ID = "drive-1"

# Response shapes verified against Microsoft Graph API docs:
# https://learn.microsoft.com/en-us/graph/api/driveitem-delta
# https://learn.microsoft.com/en-us/graph/api/driveitem-list-permissions
DELTA_RESPONSE = {
    "value": [
        {
            "id": "item-1",
            "name": "sample.html",
            "file": {"mimeType": "text/html"},
            "lastModifiedDateTime": "2026-07-01T00:00:00Z",
        },
        {
            "id": "item-2",
            "name": "deleted-file.pdf",
            "deleted": {},
        },
    ]
}

PERMISSIONS_RESPONSE = {
    "value": [
        {
            "id": "1",
            "roles": ["read"],
            "grantedToV2": {"user": {"id": "user-abc-123", "displayName": "Robin Danielsen"}},
        }
    ]
}


def _make_client(html_bytes: bytes) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/root/delta"):
            return httpx.Response(200, json=DELTA_RESPONSE)
        if request.url.path.endswith("/permissions"):
            return httpx.Response(200, json=PERMISSIONS_RESPONSE)
        if request.url.path.endswith("/content"):
            return httpx.Response(200, content=html_bytes)
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_list_documents_excludes_deleted_items() -> None:
    html_bytes = (FIXTURES / "sample.html").read_bytes()
    client = _make_client(html_bytes)
    registry = ParserRegistry(stt_model_size="tiny")
    connector = SharePointConnector(client, DRIVE_ID, "tenant-acme", registry, "fake-token")

    refs = connector.list_documents(None)

    assert len(refs) == 1
    assert refs[0].item_id == "item-1"
    assert refs[0].mime_type == "text/html"


def test_list_deletions_returns_deleted_item_ids() -> None:
    client = _make_client(b"")
    registry = ParserRegistry(stt_model_size="tiny")
    connector = SharePointConnector(client, DRIVE_ID, "tenant-acme", registry, "fake-token")

    deletions = connector.list_deletions(None)

    assert deletions == ["item-2"]


def test_fetch_parses_content_and_captures_acl() -> None:
    html_bytes = (FIXTURES / "sample.html").read_bytes()
    client = _make_client(html_bytes)
    registry = ParserRegistry(stt_model_size="tiny")
    connector = SharePointConnector(client, DRIVE_ID, "tenant-acme", registry, "fake-token")
    ref = connector.list_documents(None)[0]

    result = connector.fetch(ref)

    assert "Onboarding Runbook" in result.raw_text
    assert result.tenant_id == "tenant-acme"
    assert result.document_id == "item-1"
    assert result.acl_principals == ["msgraph:user:user-abc-123"]
