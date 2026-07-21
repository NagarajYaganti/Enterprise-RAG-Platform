from core.interfaces import DocumentParser

from connectors.parsers.email_parser import SUPPORTED_MIME_TYPES as EMAIL_MIME_TYPES
from connectors.parsers.email_parser import EmailParser
from connectors.parsers.ocr_tesseract import SUPPORTED_MIME_TYPES as OCR_MIME_TYPES
from connectors.parsers.ocr_tesseract import TesseractOCRParser
from connectors.parsers.plain_text_parser import SUPPORTED_MIME_TYPES as PLAIN_TEXT_MIME_TYPES
from connectors.parsers.plain_text_parser import PlainTextParser
from connectors.parsers.stt_faster_whisper import SUPPORTED_MIME_TYPES as STT_MIME_TYPES
from connectors.parsers.stt_faster_whisper import FasterWhisperParser
from connectors.parsers.unstructured_parser import SUPPORTED_MIME_TYPES as DOC_MIME_TYPES
from connectors.parsers.unstructured_parser import UnstructuredParser


class UnsupportedMimeTypeError(ValueError):
    pass


class ParserRegistry:
    """Dispatches mime_type -> the DocumentParser adapter that handles it.

    Shared by source connectors and the ingestion worker so mime-type routing
    lives in exactly one place.
    """

    def __init__(self, stt_model_size: str) -> None:
        self._stt_model_size = stt_model_size
        self._unstructured = UnstructuredParser()
        self._ocr = TesseractOCRParser()
        self._email = EmailParser()
        self._plain_text = PlainTextParser()
        self._stt: FasterWhisperParser | None = None

    def for_mime_type(self, mime_type: str) -> DocumentParser:
        if mime_type in DOC_MIME_TYPES:
            return self._unstructured
        if mime_type in OCR_MIME_TYPES:
            return self._ocr
        if mime_type in STT_MIME_TYPES:
            if self._stt is None:
                self._stt = FasterWhisperParser(self._stt_model_size)
            return self._stt
        if mime_type in EMAIL_MIME_TYPES:
            return self._email
        if mime_type in PLAIN_TEXT_MIME_TYPES:
            return self._plain_text
        raise UnsupportedMimeTypeError(f"No parser registered for mime type: {mime_type}")
