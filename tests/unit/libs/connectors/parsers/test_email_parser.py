from pathlib import Path

from connectors.parsers.email_parser import EmailParser

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures" / "documents"


def test_parses_subject_and_body() -> None:
    parser = EmailParser()
    result = parser.parse(
        FIXTURES / "sample.eml", "message/rfc822", tenant_id="tenant-acme", document_id="doc-1"
    )

    assert "Contract renewal reminder" in result.raw_text
    assert "review the attached renewal terms" in result.raw_text
    assert result.tenant_id == "tenant-acme"
    assert len(result.checksum) == 64
