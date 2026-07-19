from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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
    status: str


class Chunk(BaseModel):
    id: str
    tenant_id: str
    document_id: str
    text: str
    position: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmbeddingRecord(BaseModel):
    id: str
    tenant_id: str
    chunk_id: str
    vector: list[float]
    model_id: str
    model_version: str


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
