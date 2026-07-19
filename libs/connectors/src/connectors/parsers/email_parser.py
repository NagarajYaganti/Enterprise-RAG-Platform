from email import policy
from email.parser import BytesParser
from pathlib import Path

from core.interfaces import DocumentParser
from core.models import ParsedDocument

from connectors.checksum import sha256_of_bytes

SUPPORTED_MIME_TYPES = frozenset({"message/rfc822"})

# .msg (OLE compound format) is deferred: no credible script-based
# fixture-generation path exists for it (extract-msg only reads .msg, it
# cannot author one), so it's out of scope for this phase's golden-file
# tests. .eml is plain MIME text, both readable and generatable via stdlib.


class EmailParser(DocumentParser):
    """DocumentParser adapter for .eml (stdlib `email` module). .msg deferred."""

    def parse(
        self, file: Path, mime_type: str, *, tenant_id: str = "", document_id: str = ""
    ) -> ParsedDocument:
        data = file.read_bytes()
        message = BytesParser(policy=policy.default).parsebytes(data)

        body = message.get_body(preferencelist=("plain",))
        body_text = body.get_content().strip() if body is not None else ""
        subject = message.get("Subject", "")
        raw_text = f"{subject}\n\n{body_text}".strip()

        return ParsedDocument(
            tenant_id=tenant_id,
            document_id=document_id,
            raw_text=raw_text,
            structural_elements=[
                {"category": "Subject", "text": str(subject)},
                {"category": "Body", "text": body_text},
            ],
            mime_type=mime_type,
            source_uri=str(file),
            checksum=sha256_of_bytes(data),
        )
