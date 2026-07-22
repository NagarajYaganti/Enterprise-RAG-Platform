import pytest
from connectors.keyword.client import OpenSearchSettings, get_opensearch_client


def test_opensearch_settings_defaults_to_localhost() -> None:
    settings = OpenSearchSettings()
    assert settings.opensearch_host == "localhost"
    assert settings.opensearch_port == 9200


def test_opensearch_env_vars_override_the_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENSEARCH_HOST", "os-host")
    monkeypatch.setenv("OPENSEARCH_PORT", "9999")
    settings = OpenSearchSettings()
    assert settings.opensearch_host == "os-host"
    assert settings.opensearch_port == 9999


def test_get_opensearch_client_uses_the_env_configured_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSEARCH_HOST", "os-host")
    monkeypatch.setenv("OPENSEARCH_PORT", "9999")
    client = get_opensearch_client()
    assert client.transport.hosts == [{"host": "os-host", "port": 9999}]


def test_get_opensearch_client_explicit_args_override_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSEARCH_HOST", "os-host")
    monkeypatch.setenv("OPENSEARCH_PORT", "9999")
    client = get_opensearch_client(host="explicit-host", port=1234)
    assert client.transport.hosts == [{"host": "explicit-host", "port": 1234}]
