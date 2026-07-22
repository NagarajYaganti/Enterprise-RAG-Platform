import logging
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


def test_english_resolves_to_english_analyzer() -> None:
    assert decide_language_action("en")["analyzer"] == "english"


def test_arabic_resolves_to_arabic_analyzer() -> None:
    outcome = decide_language_action("ar")
    assert outcome["action"] == "translate_then_embed"
    assert outcome["analyzer"] == "arabic"


def test_chinese_and_japanese_both_resolve_to_cjk_analyzer() -> None:
    assert decide_language_action("zh")["analyzer"] == "cjk"
    assert decide_language_action("ja")["analyzer"] == "cjk"


def test_hindi_resolves_to_hindi_analyzer() -> None:
    assert decide_language_action("hi")["analyzer"] == "hindi"


def test_custom_native_languages_override_still_gets_its_own_analyzer() -> None:
    # Proves analyzer selection stays per-language-specific even on the
    # embed_natively branch, not just the translate_then_embed branch.
    outcome = decide_language_action("es", native_languages=("es", "en"))
    assert outcome["action"] == "embed_natively"
    assert outcome["analyzer"] == "spanish"


def test_unknown_language_falls_back_to_standard_analyzer() -> None:
    outcome = decide_language_action("unknown")
    assert outcome["analyzer"] == "standard"


def test_a_real_tenant_id_reaches_the_policy_decision_log() -> None:
    target_logger = logging.getLogger("core.policy_engine")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[assignment]
    target_logger.addHandler(handler)
    try:
        decide_language_action("en", tenant_id="tenant-acme")
    finally:
        target_logger.removeHandler(handler)

    decision_records = [r for r in records if r.getMessage() == "policy_engine.decision"]
    assert decision_records[-1].tenant_id == "tenant-acme"  # type: ignore[attr-defined]
