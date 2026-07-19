from pathlib import Path

from core.interfaces import DocumentParser
from core.models import ParsedDocument
from faster_whisper import WhisperModel

from connectors.checksum import sha256_of_bytes

SUPPORTED_MIME_TYPES = frozenset({"audio/wav", "audio/x-wav", "audio/mpeg"})


class FasterWhisperParser(DocumentParser):
    """DocumentParser adapter for audio via faster-whisper (local STT).

    model_size_or_path is never hardcoded here — it must come from
    config/models.yaml (VERIFY BEFORE DEPLOY) per the anti-hallucination rules.
    """

    def __init__(self, model_size_or_path: str, device: str = "cpu", compute_type: str = "int8"):
        self._model = WhisperModel(model_size_or_path, device=device, compute_type=compute_type)

    def parse(
        self, file: Path, mime_type: str, *, tenant_id: str = "", document_id: str = ""
    ) -> ParsedDocument:
        data = file.read_bytes()
        segments, info = self._model.transcribe(str(file))
        text = " ".join(segment.text.strip() for segment in segments)

        return ParsedDocument(
            tenant_id=tenant_id,
            document_id=document_id,
            raw_text=text.strip(),
            structural_elements=[
                {"category": "Transcript", "text": text.strip(), "language": info.language}
            ],
            mime_type=mime_type,
            source_uri=str(file),
            checksum=sha256_of_bytes(data),
        )
