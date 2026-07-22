import pytest
from connectors.vectorstores.client import QdrantSettings, get_qdrant_client


def test_qdrant_settings_defaults_to_localhost() -> None:
    assert QdrantSettings().qdrant_url == "http://localhost:6333"


def test_qdrant_url_env_var_overrides_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QDRANT_URL", "http://qdrant-host:9999")
    assert QdrantSettings().qdrant_url == "http://qdrant-host:9999"


def test_get_qdrant_client_uses_the_env_configured_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QDRANT_URL", "http://qdrant-host:9999")
    client = get_qdrant_client()
    assert client._init_options["url"] == "http://qdrant-host:9999"


def test_get_qdrant_client_explicit_url_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QDRANT_URL", "http://qdrant-host:9999")
    client = get_qdrant_client(url="http://explicit-host:1234")
    assert client._init_options["url"] == "http://explicit-host:1234"
