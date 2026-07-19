from preprocessing.translator_stub import StubTranslator


def test_stub_translator_returns_text_unchanged() -> None:
    translator = StubTranslator()
    assert translator.translate("hello world", "en", "es") == "hello world"
