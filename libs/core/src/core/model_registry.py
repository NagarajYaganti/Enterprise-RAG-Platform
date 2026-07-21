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


def get_default_llm_model(path: str | None = None, provider: str = "openai") -> dict[str, Any]:
    """Unlike embeddings/reranking, no viable free local generation model is
    bundled this phase (stated assumption in the Phase 3 plan — a quality
    local instruction-tuned LLM has a footprint out of scope here), so the
    default is the gated OpenAI entry. The adapter itself still refuses to
    run without an API key configured — this function only resolves which
    model_id to use once a key is present.

    Phase-4 addition: provider is now a parameter (default "openai",
    preserving Phase 3's behavior unchanged) so Anthropic can be selected
    explicitly too — a single-provider lookup, same shape as
    get_default_embedding_model/get_default_reranker_model. For comparing
    *among* providers (what ModelRouter needs), see
    get_llm_models_for_task below.
    """
    for entry in load_models_config(path):
        if entry.get("task") == "generation" and entry.get("provider") == provider:
            return entry
    raise ModelNotFoundError(f"no {provider} generation model registered in config/models.yaml")


def get_llm_models_for_task(
    task: str = "generation", path: str | None = None
) -> list[dict[str, Any]]:
    """Phase-4 addition: unlike every get_default_* function above (each
    hardwired to a single provider), ModelRouter must compare *multiple*
    generation-task candidates across providers to route on cost/complexity
    — this returns all of them, unfiltered by provider.
    """
    return [entry for entry in load_models_config(path) if entry.get("task") == task]


def get_model_entry(model_id: str, path: str | None = None) -> dict[str, Any]:
    """Phase-4 addition: the inverse of get_llm_models_for_task's filtering —
    given a model_id ModelRouter.select() already chose, resolve its full
    registry entry (needed for the "provider" field, since orchestrate()
    must pick the matching LLMProvider adapter instance out of a
    dict[str, LLMProvider] keyed by provider name; a single injected
    LLMProvider can't serve a router result that spans multiple providers).
    """
    for entry in load_models_config(path):
        if entry.get("id") == model_id:
            return entry
    raise ModelNotFoundError(f"no model registered with id={model_id!r} in config/models.yaml")
