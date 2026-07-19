from datetime import datetime, timezone
from typing import Any

from core.models import ParsedDocument


def extract_metadata(doc: ParsedDocument, language: str) -> dict[str, Any]:
    return {
        "source_uri": doc.source_uri,
        "mime_type": doc.mime_type,
        "language": language,
        "checksum": doc.checksum,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "element_count": len(doc.structural_elements),
    }
