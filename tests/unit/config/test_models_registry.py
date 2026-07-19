from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
MODELS_YAML = REPO_ROOT / "config" / "models.yaml"

REQUIRED_FIELDS = {
    "id",
    "provider",
    "task",
    "version",
    "dimensions",
    "cost_per_1k_tokens",
    "latency_class",
    "languages",
    "verified_before_deploy",
    "verified_date",
    "verified_by",
}


def test_models_yaml_parses() -> None:
    content = yaml.safe_load(MODELS_YAML.read_text())
    assert "models" in content
    assert isinstance(content["models"], list)


def test_every_model_entry_matches_schema_and_is_unverified() -> None:
    content = yaml.safe_load(MODELS_YAML.read_text())
    for entry in content["models"]:
        assert REQUIRED_FIELDS <= entry.keys()
        # No entry may claim to be deploy-verified without a human having
        # actually done so — this repo has no automated verification step.
        assert entry["verified_before_deploy"] is False


def test_every_embedding_entry_has_a_dimension() -> None:
    content = yaml.safe_load(MODELS_YAML.read_text())
    embedding_entries = [e for e in content["models"] if e["task"] == "embedding"]
    assert len(embedding_entries) >= 1
    for entry in embedding_entries:
        assert isinstance(entry["dimensions"], int)
        assert entry["dimensions"] > 0
