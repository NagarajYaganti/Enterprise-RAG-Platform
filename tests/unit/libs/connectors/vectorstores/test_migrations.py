from collections.abc import Generator

import pytest
from connectors.vectorstores.migrations import ensure_pgvector_table, ensure_qdrant_collection
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams
from sqlalchemy import create_engine, inspect, text

QDRANT_URL = "http://localhost:6333"
DATABASE_URL = "postgresql+psycopg://rag:rag@localhost:5432/rag_platform"


@pytest.fixture()
def qdrant_client() -> Generator[QdrantClient, None, None]:
    client = QdrantClient(url=QDRANT_URL)
    yield client
    for name in ["test_migrations_collection"]:
        if client.collection_exists(name):
            client.delete_collection(name)


def _vector_size(info: object) -> int:
    vectors = info.config.params.vectors  # type: ignore[attr-defined]
    assert isinstance(vectors, VectorParams)
    assert vectors.size is not None
    return vectors.size


def test_ensure_qdrant_collection_creates_with_correct_dimension(
    qdrant_client: QdrantClient,
) -> None:
    ensure_qdrant_collection(qdrant_client, "test_migrations_collection", dimension=384)

    info = qdrant_client.get_collection("test_migrations_collection")
    assert _vector_size(info) == 384


def test_ensure_qdrant_collection_is_idempotent(qdrant_client: QdrantClient) -> None:
    ensure_qdrant_collection(qdrant_client, "test_migrations_collection", dimension=384)
    ensure_qdrant_collection(qdrant_client, "test_migrations_collection", dimension=384)

    info = qdrant_client.get_collection("test_migrations_collection")
    assert _vector_size(info) == 384


def test_ensure_pgvector_table_creates_with_correct_dimension() -> None:
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("DROP TABLE IF EXISTS test_migrations_embeddings"))
        conn.commit()

    ensure_pgvector_table(engine, "test_migrations_embeddings", dimension=384)

    inspector = inspect(engine)
    columns = {c["name"]: c for c in inspector.get_columns("test_migrations_embeddings")}
    assert "embedding" in columns
    assert "tenant_id" in columns

    with engine.connect() as conn:
        conn.execute(text("DROP TABLE test_migrations_embeddings"))
        conn.commit()


def test_ensure_pgvector_table_is_idempotent() -> None:
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("DROP TABLE IF EXISTS test_migrations_embeddings_2"))
        conn.commit()

    ensure_pgvector_table(engine, "test_migrations_embeddings_2", dimension=384)
    ensure_pgvector_table(engine, "test_migrations_embeddings_2", dimension=384)

    inspector = inspect(engine)
    assert "test_migrations_embeddings_2" in inspector.get_table_names()

    with engine.connect() as conn:
        conn.execute(text("DROP TABLE test_migrations_embeddings_2"))
        conn.commit()
