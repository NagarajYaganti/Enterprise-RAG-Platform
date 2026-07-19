from pathlib import Path

import pytest
from core.model_registry import ModelNotFoundError, get_default_embedding_model, load_models_config

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
