from pydantic_settings import BaseSettings, SettingsConfigDict
from qdrant_client import QdrantClient


class QdrantSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    qdrant_url: str = "http://localhost:6333"


def get_qdrant_client(url: str | None = None) -> QdrantClient:
    return QdrantClient(url=url or QdrantSettings().qdrant_url)
