import pytest
from orchestrator.settings import OrchestratorSettings


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_MODE_ENABLED", raising=False)
    settings = OrchestratorSettings()

    assert settings.agent_mode_enabled is False
    assert settings.semantic_cache_enabled is True
    assert settings.cache_similarity_threshold == 0.95
    assert settings.cache_ttl_seconds == 3600
    assert settings.complexity_length_threshold == 200
    assert settings.default_budget_cost_per_1k_tokens == 0.01


def test_settings_reads_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_MODE_ENABLED", "true")
    settings = OrchestratorSettings()
    assert settings.agent_mode_enabled is True
