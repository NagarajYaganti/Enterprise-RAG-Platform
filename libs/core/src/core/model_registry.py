from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelRegistrySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    models_config_path: str = "config/models.yaml"


class ModelNotFoundError(ValueError):
    pass


def load_models_config(path: str | None = None) -> list[dict[str, Any]]:
    settings = ModelRegistrySettings()
    resolved_path = Path(path or settings.models_config_path)
    content = yaml.safe_load(resolved_path.read_text())
    models: list[dict[str, Any]] = content.get("models", [])
    return models


def get_default_embedding_model(path: str | None = None) -> dict[str, Any]:
    """The local/open model (sentence-transformers via huggingface) is the
    default per the Phase 2 task text: "one local/open model ... plus
    OpenAI and Cohere adapters gated behind API-key config" — local is
    primary, the cloud providers are opt-in. model_id is never hardcoded in
    business logic; this is the one place that reads it from config.
    """
    for entry in load_models_config(path):
        if entry.get("task") == "embedding" and entry.get("provider") == "huggingface":
            return entry
    raise ModelNotFoundError("no huggingface embedding model registered in config/models.yaml")
