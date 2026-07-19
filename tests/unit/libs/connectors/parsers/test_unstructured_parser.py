from pathlib import Path

import pytest
from connectors.parsers.unstructured_parser import UnstructuredParser

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures" / "documents"

CASES = [
    ("sample.pdf", "application/pdf", "Quarterly Compliance Report"),
    (
        "sample.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "Lending Policy Overview",
    ),
    (
        "sample.pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "Q3 Retail Sales Summary",
    ),
    (
        "sample.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "widget-a",
    ),
    ("sample.html", "text/html", "Onboarding Runbook"),
]


@pytest.mark.parametrize("filename,mime_type,expected_substring", CASES)
def test_parses_expected_text(filename: str, mime_type: str, expected_substring: str) -> None:
    parser = UnstructuredParser()
    result = parser.parse(
        FIXTURES / filename, mime_type, tenant_id="tenant-acme", document_id="doc-1"
    )

    assert expected_substring in result.raw_text
    assert result.tenant_id == "tenant-acme"
    assert result.document_id == "doc-1"
    assert result.mime_type == mime_type
    assert len(result.checksum) == 64
    assert len(result.structural_elements) > 0


def test_checksum_is_stable_across_reparse() -> None:
    parser = UnstructuredParser()
    first = parser.parse(FIXTURES / "sample.html", "text/html")
    second = parser.parse(FIXTURES / "sample.html", "text/html")
    assert first.checksum == second.checksum
