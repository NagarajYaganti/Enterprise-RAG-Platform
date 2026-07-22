from opensearchpy import OpenSearch
from pydantic_settings import BaseSettings, SettingsConfigDict


class OpenSearchSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    opensearch_host: str = "localhost"
    opensearch_port: int = 9200


def get_opensearch_client(host: str | None = None, port: int | None = None) -> OpenSearch:
    settings = OpenSearchSettings()
    resolved_host = host or settings.opensearch_host
    resolved_port = port or settings.opensearch_port
    return OpenSearch(
        hosts=[{"host": resolved_host, "port": resolved_port}], use_ssl=False, verify_certs=False
    )
