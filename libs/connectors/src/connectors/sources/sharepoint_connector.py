import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from core.interfaces import SourceConnector
from core.models import ParsedDocument

from connectors.parser_registry import ParserRegistry

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


@dataclass(frozen=True)
class SharePointDocumentRef:
    item_id: str
    name: str
    mime_type: str
    last_modified: datetime | None


def _extract_principals(permission: dict[str, Any]) -> list[str]:
    granted = permission.get("grantedToV2") or {}
    principals = []
    if user := granted.get("user"):
        principals.append(f"msgraph:user:{user['id']}")
    if group := granted.get("group"):
        principals.append(f"msgraph:group:{group['id']}")
    return principals


class SharePointConnector(SourceConnector):
    """SourceConnector adapter for a SharePoint/OneDrive drive via Microsoft
    Graph API. Uses the verified /root/delta endpoint (driveitem-delta) for
    incremental sync + deletion detection, and /permissions
    (driveitem-list-permissions) for ACL capture.

    Auth: takes an already-obtained bearer access_token — token acquisition
    (MSAL / Azure AD app credentials) is a separate concern, out of scope for
    this connector.
    """

    def __init__(
        self,
        http_client: httpx.Client,
        drive_id: str,
        tenant_id: str,
        parser_registry: ParserRegistry,
        access_token: str,
    ) -> None:
        self._http = http_client
        self._drive_id = drive_id
        self._tenant_id = tenant_id
        self._parser_registry = parser_registry
        self._access_token = access_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    def _delta_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        url = f"{GRAPH_BASE_URL}/drives/{self._drive_id}/root/delta"
        while url:
            response = self._http.get(url, headers=self._headers())
            response.raise_for_status()
            payload = response.json()
            items.extend(payload["value"])
            url = payload.get("@odata.nextLink", "")
        return items

    def list_documents(self, since: datetime | None) -> list[SharePointDocumentRef]:
        refs = []
        for item in self._delta_items():
            if "deleted" in item or "file" not in item:
                continue
            last_modified_str = item.get("lastModifiedDateTime")
            last_modified = (
                datetime.fromisoformat(last_modified_str.replace("Z", "+00:00"))
                if last_modified_str
                else None
            )
            if since is not None and last_modified is not None and last_modified <= since:
                continue
            refs.append(
                SharePointDocumentRef(
                    item_id=item["id"],
                    name=item["name"],
                    mime_type=item["file"].get("mimeType", ""),
                    last_modified=last_modified,
                )
            )
        return refs

    def fetch(self, ref: Any) -> ParsedDocument:
        sp_ref: SharePointDocumentRef = ref

        content_url = f"{GRAPH_BASE_URL}/drives/{self._drive_id}/items/{sp_ref.item_id}/content"
        content_response = self._http.get(
            content_url, headers=self._headers(), follow_redirects=True
        )
        content_response.raise_for_status()

        permissions_url = (
            f"{GRAPH_BASE_URL}/drives/{self._drive_id}/items/{sp_ref.item_id}/permissions"
        )
        perm_response = self._http.get(permissions_url, headers=self._headers())
        perm_response.raise_for_status()
        acl_principals = [
            p for perm in perm_response.json()["value"] for p in _extract_principals(perm)
        ]

        with tempfile.NamedTemporaryFile(suffix=Path(sp_ref.name).suffix) as tmp:
            tmp.write(content_response.content)
            tmp.flush()
            parser = self._parser_registry.for_mime_type(sp_ref.mime_type)
            parsed = parser.parse(
                Path(tmp.name),
                sp_ref.mime_type,
                tenant_id=self._tenant_id,
                document_id=sp_ref.item_id,
            )
        return parsed.model_copy(update={"acl_principals": acl_principals})

    def list_deletions(self, since: datetime | None) -> list[str]:
        return [item["id"] for item in self._delta_items() if "deleted" in item]
