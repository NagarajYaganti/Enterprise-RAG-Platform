from pgvector.sqlalchemy import Vector
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from sqlalchemy import Column, Engine, MetaData, String, Table
from sqlalchemy.dialects.postgresql import ARRAY


def ensure_qdrant_collection(
    client: QdrantClient, collection_name: str, dimension: int
) -> None:
    """Create the Qdrant collection if it doesn't already exist, sized to
    the given embedding dimension. A collection created with the wrong
    dimension can't be fixed in place — callers must pick a new collection
    name (e.g. per model_id) when the dimension changes, not reuse this one.
    """
    if not client.collection_exists(collection_name):
        client.create_collection(
            collection_name,
            vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
        )


def build_pgvector_table(metadata: MetaData, table_name: str, dimension: int) -> Table:
    """Defines (but does not create) a pgvector embeddings table sized to
    the given dimension. Different embedding models with different
    dimensions get different table names (e.g. embeddings_384,
    embeddings_1536) — a single fixed-width column can't hold both.
    """
    return Table(
        table_name,
        metadata,
        Column("id", String, primary_key=True),
        Column("tenant_id", String, index=True, nullable=False),
        Column("document_id", String, index=True, nullable=False),
        Column("chunk_id", String, index=True, nullable=False),
        Column("model_id", String, nullable=False),
        Column("model_version", String, nullable=False),
        Column("status", String, nullable=False, default="active"),
        Column("acl_principals", ARRAY(String), nullable=False, default=list),
        Column("embedding", Vector(dimension), nullable=False),
        extend_existing=True,
    )


def ensure_pgvector_table(engine: Engine, table_name: str, dimension: int) -> Table:
    """Create the pgvector embeddings table if it doesn't already exist,
    sized to the given dimension, and return its Table object.
    """
    metadata = MetaData()
    table = build_pgvector_table(metadata, table_name, dimension)
    metadata.create_all(engine, tables=[table])
    return table
