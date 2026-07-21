from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.models import PromptTemplate


class PromptRegistrySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    prompts_config_dir: str = "config/prompts"


class PromptNotFoundError(ValueError):
    pass


# The exact refusal-when-absent sentence every retrieval-qa/reasoning
# template instructs the model to emit verbatim (GAP-MATRIX's primary
# hallucination control). Defined once here so callers checking for it
# (e.g. orchestrator's citations.py) compare against a single source of
# truth instead of a duplicated literal — a prior YAML line-wrapping bug
# already proved duplicated copies of this string can silently drift.
REFUSAL_TEXT = "I don't have information about that in the provided documents."


def load_prompts_config(directory: str | None = None) -> list[dict[str, Any]]:
    """Unlike model_registry's single models.yaml (one file, many entries),
    each prompt template is its own YAML file under config/prompts/<domain>/
    — one file = one template, mirroring the "domain packs as folders of
    templates" task text and keeping templates individually diffable/
    reviewable.
    """
    settings = PromptRegistrySettings()
    resolved_dir = Path(directory or settings.prompts_config_dir)
    entries: list[dict[str, Any]] = []
    for yaml_file in sorted(resolved_dir.rglob("*.yaml")):
        content = yaml.safe_load(yaml_file.read_text())
        if content:
            entries.append(content)
    return entries


def get_prompt_template(
    type: str, domain: str, language: str, directory: str | None = None
) -> PromptTemplate:
    for entry in load_prompts_config(directory):
        if (
            entry.get("type") == type
            and entry.get("domain") == domain
            and entry.get("language") == language
        ):
            return PromptTemplate(**entry)
    raise PromptNotFoundError(
        f"no prompt template for type={type!r} domain={domain!r} language={language!r}"
    )
