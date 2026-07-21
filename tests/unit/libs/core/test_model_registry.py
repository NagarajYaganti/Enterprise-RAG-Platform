from pathlib import Path

import pytest
from core.model_registry import (
    ModelNotFoundError,
    get_default_embedding_model,
    get_default_llm_model,
    get_default_ner_model,
    get_default_reranker_model,
    get_llm_models_for_task,
    get_model_entry,
    load_models_config,
)

REPO_ROOT_MODELS_YAML = "config/models.yaml"


def test_load_models_config_reads_real_registry() -> None:
    models = load_models_config(REPO_ROOT_MODELS_YAML)
    assert len(models) >= 1
    assert any(m["task"] == "embedding" for m in models)


def test_get_default_embedding_model_returns_the_local_huggingface_model() -> None:
    model = get_default_embedding_model(REPO_ROOT_MODELS_YAML)
    assert model["provider"] == "huggingface"
    assert model["task"] == "embedding"
    assert model["id"] == "BAAI/bge-small-en-v1.5"
    assert model["verified_before_deploy"] is False


def test_get_default_embedding_model_raises_when_none_registered(tmp_path: Path) -> None:
    empty_config = tmp_path / "empty_models.yaml"
    empty_config.write_text("models: []\n")

    with pytest.raises(ModelNotFoundError):
        get_default_embedding_model(str(empty_config))


def test_get_default_reranker_model_returns_the_local_huggingface_model() -> None:
    model = get_default_reranker_model(REPO_ROOT_MODELS_YAML)
    assert model["provider"] == "huggingface"
    assert model["task"] == "rerank"
    assert model["id"] == "cross-encoder/ms-marco-MiniLM-L6-v2"
    assert model["verified_before_deploy"] is False


def test_get_default_reranker_model_raises_when_none_registered(tmp_path: Path) -> None:
    empty_config = tmp_path / "empty_models.yaml"
    empty_config.write_text("models: []\n")

    with pytest.raises(ModelNotFoundError):
        get_default_reranker_model(str(empty_config))


def test_get_default_llm_model_returns_the_openai_model() -> None:
    model = get_default_llm_model(REPO_ROOT_MODELS_YAML)
    assert model["provider"] == "openai"
    assert model["task"] == "generation"
    assert model["id"] == "gpt-5.6-luna"
    assert model["verified_before_deploy"] is False


def test_get_default_llm_model_raises_when_none_registered(tmp_path: Path) -> None:
    empty_config = tmp_path / "empty_models.yaml"
    empty_config.write_text("models: []\n")

    with pytest.raises(ModelNotFoundError):
        get_default_llm_model(str(empty_config))


def test_get_default_ner_model_returns_the_spacy_model() -> None:
    model = get_default_ner_model(REPO_ROOT_MODELS_YAML)
    assert model["provider"] == "spacy"
    assert model["task"] == "ner"
    assert model["id"] == "en_core_web_sm"
    assert model["verified_before_deploy"] is False


def test_get_default_ner_model_raises_when_none_registered(tmp_path: Path) -> None:
    empty_config = tmp_path / "empty_models.yaml"
    empty_config.write_text("models: []\n")

    with pytest.raises(ModelNotFoundError):
        get_default_ner_model(str(empty_config))


def test_get_default_llm_model_defaults_to_openai_unchanged_from_phase3() -> None:
    model = get_default_llm_model(REPO_ROOT_MODELS_YAML)
    assert model["provider"] == "openai"
    assert model["id"] == "gpt-5.6-luna"


def test_get_default_llm_model_selects_anthropic_when_requested() -> None:
    model = get_default_llm_model(REPO_ROOT_MODELS_YAML, provider="anthropic")
    assert model["provider"] == "anthropic"
    assert model["task"] == "generation"
    assert model["id"] == "claude-sonnet-5"
    assert model["verified_before_deploy"] is False


def test_get_default_llm_model_raises_for_unknown_provider() -> None:
    with pytest.raises(ModelNotFoundError):
        get_default_llm_model(REPO_ROOT_MODELS_YAML, provider="not-a-real-provider")


def test_get_llm_models_for_task_returns_all_generation_entries_across_providers() -> None:
    models = get_llm_models_for_task("generation", REPO_ROOT_MODELS_YAML)
    ids = {m["id"] for m in models}
    providers = {m["provider"] for m in models}

    assert {"gpt-5.6-luna", "claude-sonnet-5", "claude-haiku-4-5"} <= ids
    assert {"openai", "anthropic"} <= providers
    assert all(m["task"] == "generation" for m in models)


def test_get_llm_models_for_task_excludes_non_generation_entries() -> None:
    models = get_llm_models_for_task("generation", REPO_ROOT_MODELS_YAML)
    ids = {m["id"] for m in models}

    assert "BAAI/bge-small-en-v1.5" not in ids  # embedding, not generation
    assert "cross-encoder/ms-marco-MiniLM-L6-v2" not in ids  # rerank, not generation


def test_get_llm_models_for_task_with_empty_config_returns_empty_list(tmp_path: Path) -> None:
    empty_config = tmp_path / "empty_models.yaml"
    empty_config.write_text("models: []\n")

    assert get_llm_models_for_task("generation", str(empty_config)) == []


def test_get_model_entry_resolves_a_known_model_id_to_its_full_entry() -> None:
    entry = get_model_entry("claude-sonnet-5", REPO_ROOT_MODELS_YAML)
    assert entry["provider"] == "anthropic"
    assert entry["task"] == "generation"


def test_get_model_entry_raises_for_unknown_model_id() -> None:
    with pytest.raises(ModelNotFoundError):
        get_model_entry("not-a-real-model-id", REPO_ROOT_MODELS_YAML)
