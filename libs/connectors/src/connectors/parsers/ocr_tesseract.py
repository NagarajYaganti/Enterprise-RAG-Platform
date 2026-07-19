from pathlib import Path

import pytesseract
from core.interfaces import DocumentParser
from core.models import ParsedDocument
from PIL import Image

from connectors.checksum import sha256_of_bytes

SUPPORTED_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/tiff"})


class TesseractOCRParser(DocumentParser):
    """DocumentParser adapter for images via pytesseract (local Tesseract OCR).

    Cloud OCR adapters are stubbed behind this same DocumentParser interface
    in later phases — this is the one concrete implementation for Phase 1.
    """

    def parse(
        self, file: Path, mime_type: str, *, tenant_id: str = "", document_id: str = ""
    ) -> ParsedDocument:
        data = file.read_bytes()
        image = Image.open(file)
        text = pytesseract.image_to_string(image)

        return ParsedDocument(
            tenant_id=tenant_id,
            document_id=document_id,
            raw_text=text.strip(),
            structural_elements=[{"category": "OCRText", "text": text.strip()}],
            mime_type=mime_type,
            source_uri=str(file),
            checksum=sha256_of_bytes(data),
        )
