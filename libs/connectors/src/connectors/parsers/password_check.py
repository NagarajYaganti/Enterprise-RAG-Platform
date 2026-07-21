from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

_PDF_MIME_TYPE = "application/pdf"


def is_password_protected(path: Path, mime_type: str) -> bool:
    """True if the file is a password-protected/encrypted PDF.

    PDF-only: pypdf.PdfReader(...).is_encrypted is real, verified, installed
    API and gives a reliable, real signal for PDFs. DOCX/PPTX/XLSX
    password-protection needs a different, currently-unverified library --
    explicitly deferred (docs/RETROFIT-AUDIT.md's Phase 1 retrofit plan),
    not silently mis-detected; those formats fall through to FAILED_PARSE
    instead of QUARANTINED, a correct if less specific outcome.
    """
    if mime_type != _PDF_MIME_TYPE:
        return False
    try:
        return bool(PdfReader(path).is_encrypted)
    except PdfReadError:
        # Not a well-formed PDF at all -- that's a corruption case for the
        # caller's own parse attempt to classify as FAILED_PARSE, not a
        # password-protection signal.
        return False
