from pathlib import Path

import pytest
from connectors.parsers.stt_faster_whisper import FasterWhisperParser

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures" / "documents"


@pytest.fixture(scope="module")
def parser() -> FasterWhisperParser:
    # "tiny" is the smallest whisper model, fine for a fast CI smoke test;
    # it is imprecise, so tests assert on keyword substrings, not exact text.
    return FasterWhisperParser("tiny", device="cpu", compute_type="int8")


def test_transcribes_expected_keywords(parser: FasterWhisperParser) -> None:
    result = parser.parse(
        FIXTURES / "sample_audio.wav",
        "audio/wav",
        tenant_id="tenant-acme",
        document_id="doc-1",
    )

    lowered = result.raw_text.lower()
    assert "quarterly" in lowered
    assert "earnings call" in lowered
    assert result.tenant_id == "tenant-acme"
    assert len(result.checksum) == 64
