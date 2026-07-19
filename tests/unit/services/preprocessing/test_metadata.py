from core.models import ParsedDocument
from preprocessing.metadata import extract_metadata


def test_extract_metadata_includes_expected_fields() -> None:
    doc = ParsedDocument(
        tenant_id="tenant-acme",
        document_id="doc-1",
        raw_text="hello",
        structural_elements=[{"category": "Title", "text": "hello"}],
        mime_type="text/html",
        source_uri="s3://bucket/file.html",
        checksum="abc123",
    )

    metadata = extract_metadata(doc, language="en")

    assert metadata["source_uri"] == "s3://bucket/file.html"
    assert metadata["mime_type"] == "text/html"
    assert metadata["language"] == "en"
    assert metadata["checksum"] == "abc123"
    assert metadata["element_count"] == 1
    assert "ingested_at" in metadata
