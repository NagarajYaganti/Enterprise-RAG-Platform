from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

DocumentStatus = Literal[
    "UPLOADED", "PARSING", "PARSED", "EMBEDDING", "EMBEDDED", "FAILED", "SUPERSEDED"
]
ChunkStatus = Literal["active", "superseded"]
EmbeddingStatus = Literal["active", "superseded"]

# The contract's EmbeddingProvider.embed(...) -> list[Vector] names a Vector
# type; a bare float list needs no extra fields, so this is a type alias
# rather than a BaseModel.
Vector = list[float]


class Tenant(BaseModel):
    tenant_id: str
    name: str
    created_at: datetime
    config: dict[str, Any] = Field(default_factory=dict)


class Document(BaseModel):
    id: str
    tenant_id: str
    source_uri: str
    mime_type: str
    checksum: str
    version: int
    status: DocumentStatus
    acl_principals: list[str] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    tenant_id: str
    document_id: str
    raw_text: str
    structural_elements: list[dict[str, Any]] = Field(default_factory=list)
    mime_type: str
    source_uri: str
    checksum: str
    acl_principals: list[str] = Field(default_factory=list)


class Chunk(BaseModel):
    id: str
    tenant_id: str
    document_id: str
    text: str
    position: int
    language: str
    version: int
    status: ChunkStatus = "active"
    acl_principals: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmbeddingRecord(BaseModel):
    id: str
    tenant_id: str
    document_id: str
    chunk_id: str
    vector: list[float]
    model_id: str
    model_version: str
    status: EmbeddingStatus = "active"
    acl_principals: list[str] = Field(default_factory=list)


class VectorSearchHit(BaseModel):
    """Vendor-neutral search result shape shared by every VectorStore
    adapter (Qdrant, pgvector, ...) so callers never need vendor types."""

    chunk_id: str
    document_id: str
    score: float
    model_id: str


class KeywordSearchHit(BaseModel):
    """Search result shape for KeywordIndex (BM25) adapters — no model_id,
    since keyword search doesn't involve an embedding model."""

    chunk_id: str
    document_id: str
    score: float


class Query(BaseModel):
    id: str
    tenant_id: str
    session_id: str
    text: str
    filters: dict[str, Any] = Field(default_factory=dict)


class ScoredChunk(BaseModel):
    chunk: Chunk
    score: float


class RetrievalResult(BaseModel):
    tenant_id: str
    query_id: str
    chunks: list[ScoredChunk] = Field(default_factory=list)


class Completion(BaseModel):
    tenant_id: str
    model_id: str
    text: str
    usage: dict[str, int] = Field(default_factory=dict)
    citations: list[str] = Field(default_factory=list)
