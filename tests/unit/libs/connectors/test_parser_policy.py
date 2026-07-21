from pathlib import Path

from connectors.parser_policy import FALLBACK_OUTCOME, decide_parser_route

CASES = [
    ("application/pdf", "unstructured"),
    ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "unstructured"),
    ("text/html", "unstructured"),
    ("image/png", "ocr"),
    ("image/jpeg", "ocr"),
    ("audio/wav", "stt"),
    ("audio/mpeg", "stt"),
    ("message/rfc822", "email"),
    ("text/plain", "plain_text"),
    ("application/json", "plain_text"),
]


def test_routes_each_known_mime_type_to_its_real_parser() -> None:
    for mime_type, expected_route in CASES:
        outcome = decide_parser_route(mime_type)
        assert outcome["route"] == expected_route, mime_type


def test_unknown_mime_type_falls_back_to_unsupported() -> None:
    outcome = decide_parser_route("application/x-totally-unknown-format")
    assert outcome["route"] == "unsupported"


def test_missing_policy_file_falls_back_safely(tmp_path: Path) -> None:
    outcome = decide_parser_route("application/pdf", directory=str(tmp_path))
    assert outcome == FALLBACK_OUTCOME
