from pathlib import Path

from connectors.parsers.ocr_tesseract import TesseractOCRParser

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures" / "documents"


def test_ocr_extracts_expected_text() -> None:
    parser = TesseractOCRParser()
    result = parser.parse(
        FIXTURES / "sample_ocr.png", "image/png", tenant_id="tenant-acme", document_id="doc-1"
    )

    assert "INVOICE NUMBER 48213" in result.raw_text
    assert result.tenant_id == "tenant-acme"
    assert result.mime_type == "image/png"
    assert len(result.checksum) == 64
