from pathlib import Path

from core.interfaces import DocumentParser
from core.models import ParsedDocument
from unstructured.partition.auto import partition

from connectors.checksum import sha256_of_bytes

SUPPORTED_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/html",
    }
)


class UnstructuredParser(DocumentParser):
    """DocumentParser adapter for PDF/DOCX/PPTX/XLSX/HTML via the `unstructured` library."""

    def parse(
        self, file: Path, mime_type: str, *, tenant_id: str = "", document_id: str = ""
    ) -> ParsedDocument:
        data = file.read_bytes()
        elements = partition(filename=str(file), content_type=mime_type)

        structural_elements = [
            {
                "category": el.category,
                "text": el.text,
                "filetype": el.metadata.filetype,
            }
            for el in elements
        ]
        raw_text = "\n".join(el.text for el in elements if el.text)

        return ParsedDocument(
            tenant_id=tenant_id,
            document_id=document_id,
            raw_text=raw_text,
            structural_elements=structural_elements,
            mime_type=mime_type,
            source_uri=str(file),
            checksum=sha256_of_bytes(data),
        )
