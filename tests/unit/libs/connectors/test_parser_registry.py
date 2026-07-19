import pytest
from connectors.parser_registry import ParserRegistry, UnsupportedMimeTypeError
from connectors.parsers.email_parser import EmailParser
from connectors.parsers.ocr_tesseract import TesseractOCRParser
from connectors.parsers.unstructured_parser import UnstructuredParser


def test_routes_known_mime_types_to_expected_parser() -> None:
    registry = ParserRegistry(stt_model_size="tiny")

    assert isinstance(registry.for_mime_type("application/pdf"), UnstructuredParser)
    assert isinstance(registry.for_mime_type("text/html"), UnstructuredParser)
    assert isinstance(registry.for_mime_type("image/png"), TesseractOCRParser)
    assert isinstance(registry.for_mime_type("message/rfc822"), EmailParser)


def test_raises_on_unsupported_mime_type() -> None:
    registry = ParserRegistry(stt_model_size="tiny")
    with pytest.raises(UnsupportedMimeTypeError):
        registry.for_mime_type("application/x-not-a-real-type")


def test_stt_parser_is_lazily_constructed_and_cached() -> None:
    registry = ParserRegistry(stt_model_size="tiny")
    assert registry._stt is None

    first = registry.for_mime_type("audio/wav")
    assert registry._stt is not None
    second = registry.for_mime_type("audio/wav")
    assert first is second
