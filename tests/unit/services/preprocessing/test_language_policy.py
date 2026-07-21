from pathlib import Path

from preprocessing.language_policy import FALLBACK_OUTCOME, decide_language_action


def test_english_is_supported_natively() -> None:
    outcome = decide_language_action("en")
    assert outcome["action"] == "embed_natively"


def test_non_english_falls_back_to_translate_then_embed() -> None:
    outcome = decide_language_action("ar")
    assert outcome["action"] == "translate_then_embed"
    assert outcome["target_language"] == "en"


def test_custom_native_languages_override() -> None:
    outcome = decide_language_action("es", native_languages=("es", "en"))
    assert outcome["action"] == "embed_natively"


def test_missing_policy_file_falls_back_safely(tmp_path: Path) -> None:
    outcome = decide_language_action("ar", directory=str(tmp_path))
    assert outcome == FALLBACK_OUTCOME
