from preprocessing.cleaning import clean_text


def test_collapses_repeated_whitespace() -> None:
    assert clean_text("hello    world") == "hello world"


def test_collapses_excess_newlines() -> None:
    assert clean_text("para one\n\n\n\n\npara two") == "para one\n\npara two"


def test_strips_control_characters() -> None:
    assert clean_text("hello\x00\x01world") == "helloworld"


def test_strips_leading_and_trailing_whitespace() -> None:
    assert clean_text("   hello   ") == "hello"


def test_uses_nfc_not_nfkc_normalization() -> None:
    # Full-width digits are a real, verified case where NFC and NFKC
    # disagree: NFKC's compatibility folding rewrites them to ASCII
    # ("１２３" -> "123"), silently altering the source text. NFC preserves
    # them, matching the Global-First citation-fidelity requirement.
    assert clean_text("１２３") == "１２３"
