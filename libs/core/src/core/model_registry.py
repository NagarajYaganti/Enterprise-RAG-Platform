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


def get_default_reranker_model(path: str | None = None) -> dict[str, Any]:
    """The local cross-encoder (sentence-transformers via huggingface) is
    the default, mirroring get_default_embedding_model's local-first
    rationale — Cohere's reranker is an opt-in, config-gated adapter.
    """
    for entry in load_models_config(path):
        if entry.get("task") == "rerank" and entry.get("provider") == "huggingface":
            return entry
    raise ModelNotFoundError("no huggingface reranker registered in config/models.yaml")


def get_default_ner_model(path: str | None = None) -> dict[str, Any]:
    """GraphRAG's entity extraction uses spaCy NER, not an LLM — a local,
    cheap foundation, matching the phase's cost-gating rationale (real
    per-tenant LLM-based extraction would be the expensive option this
    flag exists to guard against).
    """
    for entry in load_models_config(path):
        if entry.get("task") == "ner" and entry.get("provider") == "spacy":
            return entry
    raise ModelNotFoundError("no spacy ner model registered in config/models.yaml")


def get_default_llm_model(path: str | None = None) -> dict[str, Any]:
    """Unlike embeddings/reranking, no viable free local generation model is
    bundled this phase (stated assumption in the Phase 3 plan — a quality
    local instruction-tuned LLM has a footprint out of scope here), so the
    default is the one gated OpenAI entry. The adapter itself still refuses
    to run without OPENAI_API_KEY configured — this function only resolves
    which model_id to use once a key is present.
    """
    for entry in load_models_config(path):
        if entry.get("task") == "generation" and entry.get("provider") == "openai":
            return entry
    raise ModelNotFoundError("no openai generation model registered in config/models.yaml")
