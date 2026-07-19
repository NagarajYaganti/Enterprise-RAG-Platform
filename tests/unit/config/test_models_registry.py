from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
MODELS_YAML = REPO_ROOT / "config" / "models.yaml"


def test_models_yaml_parses_and_starts_empty() -> None:
    content = yaml.safe_load(MODELS_YAML.read_text())
    assert content == {"models": []}
