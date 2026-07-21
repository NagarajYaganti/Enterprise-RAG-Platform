from pathlib import Path

from connectors.parsers.password_check import is_password_protected

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures" / "documents"


def test_detects_a_real_encrypted_pdf() -> None:
    assert is_password_protected(FIXTURES / "sample_encrypted.pdf", "application/pdf") is True


def test_clean_pdf_is_not_password_protected() -> None:
    assert is_password_protected(FIXTURES / "sample.pdf", "application/pdf") is False


def test_corrupt_pdf_is_not_reported_as_password_protected() -> None:
    # A genuinely corrupt (not-a-real-PDF-at-all) file must not be
    # misreported as password-protected -- that's a corruption case for the
    # caller's parse attempt to classify as FAILED_PARSE, not QUARANTINED.
    assert is_password_protected(FIXTURES / "sample_corrupt.pdf", "application/pdf") is False


def test_non_pdf_mime_type_is_never_password_protected() -> None:
    # No DOCX/PPTX/XLSX password-detection exists yet (explicit scope
    # boundary, docs/RETROFIT-AUDIT.md's Phase 1 retrofit plan) -- a
    # password-protected DOCX would fall through to FAILED_PARSE, a
    # correct if less specific outcome, not silently mis-detected here.
    docx_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert is_password_protected(FIXTURES / "sample.docx", docx_mime) is False
