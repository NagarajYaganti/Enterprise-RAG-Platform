from preprocessing.cleaning import clean_text


def test_collapses_repeated_whitespace() -> None:
    assert clean_text("hello    world") == "hello world"


def test_collapses_excess_newlines() -> None:
    assert clean_text("para one\n\n\n\n\npara two") == "para one\n\npara two"


def test_strips_control_characters() -> None:
    assert clean_text("hello\x00\x01world") == "helloworld"


def test_strips_leading_and_trailing_whitespace() -> None:
    assert clean_text("   hello   ") == "hello"
