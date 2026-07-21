from pathlib import Path

import pytest
from connectors.parsers.plain_text_parser import PlainTextParser

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures" / "documents"

CASES = [
    ("sample.txt", "text/plain", "service level agreement"),
    ("sample.md", "text/markdown", "Restart the ingestion worker"),
    ("sample.csv", "text/csv", "widget-b"),
    ("sample.json", "application/json", "refund"),
    ("sample.xml", "application/xml", "refund"),
]


@pytest.mark.parametrize("filename,mime_type,expected_substring", CASES)
def test_parses_expected_text(filename: str, mime_type: str, expected_substring: str) -> None:
    parser = PlainTextParser()
    result = parser.parse(
        FIXTURES / filename, mime_type, tenant_id="tenant-acme", document_id="doc-1"
    )

    assert expected_substring in result.raw_text
    assert result.tenant_id == "tenant-acme"
    assert result.document_id == "doc-1"
    assert result.mime_type == mime_type
    assert len(result.checksum) == 64


def test_checksum_is_stable_across_reparse() -> None:
    parser = PlainTextParser()
    first = parser.parse(FIXTURES / "sample.txt", "text/plain")
    second = parser.parse(FIXTURES / "sample.txt", "text/plain")
    assert first.checksum == second.checksum


def test_decodes_a_real_legacy_encoded_file() -> None:
    # sample_legacy_encoding.txt is genuinely windows-1252 encoded (verified
    # at generation time: it fails plain UTF-8 decoding) -- this exercises
    # the charset-detection fallback path for real, not just the common
    # UTF-8 case.
    parser = PlainTextParser()
    result = parser.parse(FIXTURES / "sample_legacy_encoding.txt", "text/plain")
    assert "délai" in result.raw_text
    assert "remboursement" in result.raw_text


def test_applies_nfc_normalization() -> None:
    # NFC, not NFKC (see cleaning.py's fix earlier in this retrofit) --
    # PlainTextParser normalizes independently since these formats bypass
    # preprocessing.cleaning entirely at the parse stage.
    import unicodedata

    parser = PlainTextParser()
    result = parser.parse(FIXTURES / "sample.txt", "text/plain")
    assert result.raw_text == unicodedata.normalize("NFC", result.raw_text)
