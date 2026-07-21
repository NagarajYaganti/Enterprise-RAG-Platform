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
    # Phase-3 addition: same rationale as EmbeddingRecord's matching fields —
    # promoted out of the free-form metadata dict into explicit, indexed/
    # filterable fields, mirroring how `language` already lives here
    # first-class rather than inside metadata. KeywordIndex.upsert receives
    # Chunk objects directly (not EmbeddingRecord), so these must live here
    # too, not only on EmbeddingRecord — EmbeddingRecord's copies are
    # threaded through from these at embed time for Qdrant's payload.
    doc_type: str | None = None
    department: str | None = None
    date: str | None = None


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
    # Phase-3 addition: promoted out of Chunk.metadata into explicit,
    # indexed/filterable fields on the record itself (see VectorStore/
    # KeywordIndex search filter kwargs) — OpenSearch has no generic
    # free-form-dict field type available on the running cluster (verified:
    # `flattened` type unsupported), so only these four named dimensions
    # from the phase task text are promoted, not the whole metadata dict.
    language: str = ""
    doc_type: str | None = None
    department: str | None = None
    date: str | None = None


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
    # Phase-3 addition: ChatSession is keyed by tenant + user + session (per
    # Section 4 Phase 3 task text), so Query needs a user identity alongside
    # the session it belongs to.
    user_id: str = ""


class RetrievalFilters(BaseModel):
    """Phase-3 addition: the four metadata filter dimensions named in the
    task text (date, doc type, department, language). A field left as None
    means "unconstrained" — it is never translated into a filter condition
    by the adapters. A provided value means an exact-match filter, which
    excludes any chunk missing that field.
    """

    language: str | None = None
    doc_type: str | None = None
    department: str | None = None
    date_from: str | None = None
    date_to: str | None = None


class ChatTurn(BaseModel):
    """Phase-3 addition: one turn in a ChatSession, keyed by tenant + user +
    session (per Section 4 Phase 3 task text). Stored as individual rows
    (not a JSON blob) for queryability/audit, mirroring the Chunk/Document
    per-row pattern already established.
    """

    id: str
    tenant_id: str
    user_id: str
    session_id: str
    role: Literal["user", "assistant"]
    text: str
    created_at: datetime


class Entity(BaseModel):
    """Phase-3 addition (GraphRAG, optional/flagged-off): an entity
    extracted from a chunk. label follows spaCy's NER label scheme (e.g.
    ORG, PERSON, GPE) — a first-pass extraction, not a curated ontology.
    """

    id: str
    tenant_id: str
    document_id: str
    chunk_id: str
    name: str
    label: str


class Relation(BaseModel):
    """Phase-3 addition (GraphRAG, optional/flagged-off): a coarse relation
    between two entities co-occurring in the same chunk. predicate is a
    fixed placeholder ("co_occurs_with"), not real relation classification —
    see connectors.graph.spacy_extractor for the caveat.
    """

    id: str
    tenant_id: str
    subject_entity_id: str
    predicate: str
    object_entity_id: str
    chunk_id: str


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


# Phase-4 addition: the closed reason_codes vocabulary each Guardrail
# implementation emits — stated explicitly (Plan v2 §A.8) rather than left
# as an arbitrary string, so tests can assert on specific codes.
GuardrailReasonCode = Literal[
    "PII_DETECTED",
    "INJECTION_PATTERN_MATCHED",
    "OUTPUT_POLICY_VIOLATION",
    "GUARDRAIL_CHECK_FAILED",
]


class GuardrailResult(BaseModel):
    """Phase-4 addition: the fixed Guardrail.check(payload, policy) -> Any
    ABC's concrete return shape. passed=False + GUARDRAIL_CHECK_FAILED means
    the check itself errored — guardrails fail closed (Plan v2 §A.9), never
    silently pass content through because a check broke.
    """

    passed: bool
    policy: str
    reason_codes: list[GuardrailReasonCode] = Field(default_factory=list)
    redacted_text: str | None = None


class PromptTemplate(BaseModel):
    """Phase-4 addition: one entry in the config/prompts/ registry — YAML
    templates, versioned, with a declared variables schema (Section 4 Phase
    4 task text: "prompt template registry... variables schema").
    """

    id: str
    type: Literal["retrieval-qa", "summarization", "reasoning", "structured-output"]
    domain: str
    language: str
    template_text: str
    variables: list[str] = Field(default_factory=list)
    version: str


class AgentStep(BaseModel):
    """Phase-4 addition (agent/tools mode, flagged off by default): one step
    in an agentic tool-use trace. approved_by=None + requires_approval=True
    is the halt state the human-approval gate produces (Plan v2 §A.10) —
    the runtime will not execute this step until a separate resume call
    sets approved_by.
    """

    id: str
    tenant_id: str
    tool_name: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: Any | None = None
    requires_approval: bool = False
    approved_by: str | None = None


class AgentTrace(BaseModel):
    """Phase-4 addition: full trace of an agentic loop run, per Section 4
    Phase 4 task text's "full trace logging" requirement.
    """

    id: str
    tenant_id: str
    query_id: str
    steps: list[AgentStep] = Field(default_factory=list)
    max_iterations: int
    completed: bool = False


class TokenUsageRecord(BaseModel):
    """Phase-4 addition: per-tenant token usage, for the exit checklist's
    "per-tenant token usage recorded in DB" item.
    """

    id: str
    tenant_id: str
    model_id: str
    prompt_tokens: int
    completion_tokens: int
    created_at: datetime
