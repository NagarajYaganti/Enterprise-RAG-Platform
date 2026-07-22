from pathlib import Path

import pytest
from core.prompt_registry import (
    REFUSAL_TEXT,
    PromptNotFoundError,
    get_prompt_template,
    language_name_for,
    load_prompts_config,
    refusal_text_for,
)

REPO_ROOT_PROMPTS_DIR = "config/prompts"


def test_load_prompts_config_reads_real_registry() -> None:
    entries = load_prompts_config(REPO_ROOT_PROMPTS_DIR)
    assert len(entries) >= 7  # 4 common + bfsi + retail + healthcare retrieval-qa
    assert any(e["domain"] == "common" for e in entries)


def test_load_prompts_config_entries_have_unique_ids() -> None:
    entries = load_prompts_config(REPO_ROOT_PROMPTS_DIR)
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids))


def test_get_prompt_template_returns_common_retrieval_qa() -> None:
    template = get_prompt_template("retrieval-qa", "common", "en", REPO_ROOT_PROMPTS_DIR)
    assert template.id == "retrieval-qa-common-en"
    assert "{context}" in template.template_text
    assert "{query}" in template.template_text
    assert "query" in template.variables
    assert "context" in template.variables


def test_get_prompt_template_returns_domain_specific_variant() -> None:
    healthcare = get_prompt_template("retrieval-qa", "healthcare", "en", REPO_ROOT_PROMPTS_DIR)
    assert healthcare.domain == "healthcare"
    assert "medical advice" in healthcare.template_text.lower()

    bfsi = get_prompt_template("retrieval-qa", "bfsi", "en", REPO_ROOT_PROMPTS_DIR)
    assert bfsi.domain == "bfsi"

    retail = get_prompt_template("retrieval-qa", "retail", "en", REPO_ROOT_PROMPTS_DIR)
    assert retail.domain == "retail"


def test_get_prompt_template_all_common_types_exist() -> None:
    for template_type in ("retrieval-qa", "summarization", "reasoning", "structured-output"):
        template = get_prompt_template(template_type, "common", "en", REPO_ROOT_PROMPTS_DIR)
        assert template.type == template_type


def test_get_prompt_template_refusal_instruction_is_consistent_across_domains() -> None:
    for domain in ("common", "bfsi", "retail", "healthcare"):
        template = get_prompt_template("retrieval-qa", domain, "en", REPO_ROOT_PROMPTS_DIR)
        assert REFUSAL_TEXT in template.template_text


def test_get_prompt_template_raises_when_not_found(tmp_path: Path) -> None:
    with pytest.raises(PromptNotFoundError):
        get_prompt_template("retrieval-qa", "nonexistent-domain", "en", str(tmp_path))


def test_get_prompt_template_target_language_instruction_is_consistent_across_domains() -> None:
    for domain in ("common", "bfsi", "retail", "healthcare"):
        template = get_prompt_template("retrieval-qa", domain, "en", REPO_ROOT_PROMPTS_DIR)
        assert "{target_language}" in template.template_text
        assert "target_language" in template.variables


def test_refusal_text_for_returns_real_translations_for_es_fr_de() -> None:
    assert refusal_text_for("es") == (
        "No tengo información sobre eso en los documentos proporcionados."
    )
    assert refusal_text_for("fr") == (
        "Je n'ai pas d'informations à ce sujet dans les documents fournis."
    )
    assert refusal_text_for("de") == (
        "Ich habe dazu keine Informationen in den bereitgestellten Dokumenten."
    )
    assert refusal_text_for("en") == REFUSAL_TEXT


def test_refusal_text_for_falls_back_to_english_for_an_unconfigured_language() -> None:
    assert refusal_text_for("zh") == REFUSAL_TEXT
    assert refusal_text_for("unknown") == REFUSAL_TEXT


def test_language_name_for_known_and_unknown_codes() -> None:
    assert language_name_for("es") == "Spanish"
    assert language_name_for("fr") == "French"
    assert language_name_for("de") == "German"
    assert language_name_for("en") == "English"
    assert language_name_for("unknown") == "English"
    assert language_name_for("xx") == "English"
