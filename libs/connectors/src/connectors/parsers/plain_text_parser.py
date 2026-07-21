import unicodedata
from pathlib import Path

from charset_normalizer import from_bytes
from core.interfaces import DocumentParser
from core.models import ParsedDocument

from connectors.checksum import sha256_of_bytes

SUPPORTED_MIME_TYPES = frozenset(
    {
        "text/plain",
        "text/markdown",
        "text/csv",
        "application/json",
        "application/xml",
        "text/xml",
    }
)


def _decode(data: bytes) -> str:
    """UTF-8 first (the common case, no guessing needed), then
    charset-normalizer's real detection, then a last-resort lossy decode --
    never raises on encoding. Verified empirically that probabilistic
    charset detection (charset-normalizer, same category of tool as
    chardet) can misdetect short or repetitive byte sequences -- an
    inherent limitation of all statistical detectors, not a defect in this
    usage; real documents are typically long enough for detection to work
    well in practice.
    """
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    best_match = from_bytes(data).best()
    if best_match is not None:
        return str(best_match)
    return data.decode("utf-8", errors="replace")


class PlainTextParser(DocumentParser):
    """DocumentParser adapter for plain text / Markdown / CSV / JSON / XML
    -- named in Section 4 Phase 1's task text but never built (verified: no
    parser existed for any of these mime types before this retrofit).
    """

    def parse(
        self, file: Path, mime_type: str, *, tenant_id: str = "", document_id: str = ""
    ) -> ParsedDocument:
        data = file.read_bytes()
        raw_text = unicodedata.normalize("NFC", _decode(data))

        return ParsedDocument(
            tenant_id=tenant_id,
            document_id=document_id,
            raw_text=raw_text,
            structural_elements=[],
            mime_type=mime_type,
            source_uri=str(file),
            checksum=sha256_of_bytes(data),
        )
