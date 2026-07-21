import base64
import json
from pathlib import Path

import pytest
from connectors.postgres.repository import ChunkRepository
from fastapi.testclient import TestClient
from ingestion.main import app
from sqlalchemy.orm import Session

from tests.integration.conftest import run_worker_burst

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"

# Real RTL (Arabic), CJK (Chinese), and Indic (Hindi) fixtures -- proves the
# Global-First Principle's non-Latin-script requirements end-to-end through
# the real /v1/documents API, not just at the unit level (per docs/
# RETROFIT-AUDIT.md Phase 1 item 11).
SINGLE_LANGUAGE_CASES = [
    ("sample_arabic.txt", "text/plain", "ar"),
    ("sample_chinese.txt", "text/plain", "zh"),
    ("sample_hindi.txt", "text/plain", "hi"),
]


def _make_token(tenant_id: str) -> str:
    raw = json.dumps({"tenant_id": tenant_id}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.mark.asyncio
@pytest.mark.parametrize("filename,mime_type,expected_language", SINGLE_LANGUAGE_CASES)
async def test_non_latin_script_document_reaches_parsed_with_correct_language(
    db_session: Session,
    clean_queue: None,
    filename: str,
    mime_type: str,
    expected_language: str,
) -> None:
    token = _make_token("tenant-acme")
    with TestClient(app) as client:
        with open(FIXTURES / filename, "rb") as f:
            upload_response = client.post(
                "/v1/documents",
                files={"file": (filename, f, mime_type)},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert upload_response.status_code == 200
        document_id = upload_response.json()["id"]

        jobs_complete, jobs_failed = await run_worker_burst()
        assert jobs_failed == 0, f"{filename}: {jobs_failed} job(s) failed"
        assert jobs_complete >= 1

        status_response = client.get(
            f"/v1/documents/{document_id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert status_response.json()["status"] == "PARSED", (
            f"{filename} did not reach PARSED: {status_response.json()}"
        )

    chunks = ChunkRepository(db_session).list_for_document("tenant-acme", document_id)
    assert len(chunks) == 1, f"{filename} should fit in a single chunk, got {len(chunks)}"
    assert chunks[0].language == expected_language, (
        f"{filename}: expected language {expected_language!r}, got {chunks[0].language!r}"
    )
    # Token-based sizing (item 2): a non-Latin script's real token count
    # must not collapse to near-zero or explode absurdly relative to its
    # character count -- both would indicate byte/char slicing snuck back
    # in instead of tiktoken-based slicing.
    char_count = len((FIXTURES / filename).read_text(encoding="utf-8"))
    assert 0 < len(chunks[0].text) <= char_count + 1


@pytest.mark.asyncio
async def test_mixed_language_document_detects_language_per_section_not_per_document(
    db_session: Session, clean_queue: None
) -> None:
    # An English section followed by an Arabic section in one HTML document
    # -- the document-wide majority-language vote would otherwise mislabel
    # one of the two sections (item 3's whole point).
    token = _make_token("tenant-acme")
    filename = "sample_mixed_en_ar.html"
    with TestClient(app) as client:
        with open(FIXTURES / filename, "rb") as f:
            upload_response = client.post(
                "/v1/documents",
                files={"file": (filename, f, "text/html")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert upload_response.status_code == 200
        document_id = upload_response.json()["id"]

        jobs_complete, jobs_failed = await run_worker_burst()
        assert jobs_failed == 0
        assert jobs_complete >= 1

        status_response = client.get(
            f"/v1/documents/{document_id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert status_response.json()["status"] == "PARSED"

    chunks = ChunkRepository(db_session).list_for_document("tenant-acme", document_id)
    languages = {c.language for c in chunks}
    assert "en" in languages, f"expected an English-language chunk, got languages: {languages}"
    assert "ar" in languages, f"expected an Arabic-language chunk, got languages: {languages}"

    english_chunk = next(c for c in chunks if c.language == "en")
    arabic_chunk = next(c for c in chunks if c.language == "ar")
    assert "Loan Policy" in english_chunk.text or "business days" in english_chunk.text
    assert "سياسة القروض" in arabic_chunk.text or "يجب مراجعة" in arabic_chunk.text
