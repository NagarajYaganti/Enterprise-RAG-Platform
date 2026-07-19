import mimetypes
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.interfaces import SourceConnector
from core.models import ParsedDocument

from connectors.parser_registry import ParserRegistry


@dataclass(frozen=True)
class BlobDocumentRef:
    key: str
    etag: str
    last_modified: datetime


class BlobSourceConnector(SourceConnector):
    """SourceConnector adapter for an S3/MinIO-compatible bucket, with
    incremental sync (via LastModified) and deletion propagation (via a
    caller-supplied set of previously known keys, since object storage has
    no built-in deletion log)."""

    def __init__(
        self,
        s3_client: Any,
        bucket: str,
        tenant_id: str,
        parser_registry: ParserRegistry,
        known_keys_provider: Callable[[], set[str]],
        prefix: str = "",
    ) -> None:
        self._s3 = s3_client
        self._bucket = bucket
        self._tenant_id = tenant_id
        self._parser_registry = parser_registry
        self._known_keys_provider = known_keys_provider
        self._prefix = prefix

    def _list_all_keys(self) -> dict[str, BlobDocumentRef]:
        refs: dict[str, BlobDocumentRef] = {}
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=self._prefix):
            for obj in page.get("Contents", []):
                refs[obj["Key"]] = BlobDocumentRef(
                    key=obj["Key"],
                    etag=obj["ETag"].strip('"'),
                    last_modified=obj["LastModified"],
                )
        return refs

    def list_documents(self, since: datetime | None) -> list[BlobDocumentRef]:
        refs = self._list_all_keys()
        if since is None:
            return list(refs.values())
        return [ref for ref in refs.values() if ref.last_modified > since]

    def fetch(self, ref: Any) -> ParsedDocument:
        blob_ref: BlobDocumentRef = ref
        mime_type, _ = mimetypes.guess_type(blob_ref.key)
        if mime_type is None:
            raise ValueError(f"Could not determine mime type for key: {blob_ref.key}")

        with tempfile.NamedTemporaryFile(suffix=Path(blob_ref.key).suffix) as tmp:
            self._s3.download_fileobj(self._bucket, blob_ref.key, tmp)
            tmp.flush()
            parser = self._parser_registry.for_mime_type(mime_type)
            return parser.parse(
                Path(tmp.name), mime_type, tenant_id=self._tenant_id, document_id=blob_ref.key
            )

    def list_deletions(self, since: datetime | None) -> list[str]:
        current_keys = set(self._list_all_keys().keys())
        known_keys = self._known_keys_provider()
        return sorted(known_keys - current_keys)
