from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from core.models import Chunk, ParsedDocument, Vector


class DocumentParser(ABC):
    @abstractmethod
    def parse(
        self, file: Any, mime_type: str, *, tenant_id: str = "", document_id: str = ""
    ) -> ParsedDocument:
        """Parse a raw file into a ParsedDocument.

        The fixed contract's signature is parse(file, mime_type); tenant_id and
        document_id are additive optional keyword args so callers with that
        context (the ingestion worker) can stamp it directly, without breaking
        the two-positional-arg shape any adapter can still be called with.
        """


class Chunker(ABC):
    @abstractmethod
    def chunk(
        self, doc: ParsedDocument, strategy: str, *, language: str = "unknown", version: int = 1
    ) -> list[Chunk]:
        """Split a parsed document into Chunks using the given strategy.

        tenant_id/document_id come from doc itself (already stamped by the
        time chunking runs). language/version are additive optional keyword
        args, same rationale as DocumentParser.parse's tenant_id/document_id:
        the fixed contract's signature is chunk(doc, strategy).
        """


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: list[str], model_id: str) -> list[Vector]:
        """Embed a batch of texts with the given model into Vectors."""


class VectorStore(ABC):
    @abstractmethod
    def upsert(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
        """Insert or update vector records for a tenant."""

    @abstractmethod
    def search(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
        """Search vector records scoped to a tenant."""

    @abstractmethod
    def delete(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
        """Delete vector records scoped to a tenant."""


class Reranker(ABC):
    @abstractmethod
    def rerank(self, query: str, candidates: list[Any], top_k: int) -> list[Any]:
        """Rerank candidates for a query, returning the top_k ScoredChunks."""


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, messages: list[Any], model_id: str, params: dict[str, Any]) -> Any:
        """Generate a Completion from a list of messages using the given model."""


class ModelRouter(ABC):
    @abstractmethod
    def select(self, task: str, language: str, complexity: str, budget: float) -> str:
        """Select a model_id from the registry given routing constraints."""


class Guardrail(ABC):
    @abstractmethod
    def check(self, payload: Any, policy: str) -> Any:
        """Check input or output against a named policy, returning a GuardrailResult."""


class SourceConnector(ABC):
    """Phase-1 addition (per Section 4 Phase 1 task text): pull-based source
    with incremental sync and deletion propagation. Not one of the original 8
    core interfaces in docs/ARCHITECTURE.md — an explicit, phase-directed
    extension, not a redesign of the fixed contract.
    """

    @abstractmethod
    def list_documents(self, since: datetime | None) -> list[Any]:
        """List document refs changed/added since the given point (or all, if None)."""

    @abstractmethod
    def fetch(self, ref: Any) -> ParsedDocument:
        """Fetch and parse a single document by its source ref."""

    @abstractmethod
    def list_deletions(self, since: datetime | None) -> list[str]:
        """List source-side document ids deleted since the given point."""


class Translator(ABC):
    """Phase-1 addition (per Section 4 Phase 1 task text). Stub-only this
    phase — no real translation provider is wired in yet.
    """

    @abstractmethod
    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        """Translate text from source_lang to target_lang."""


class KeywordIndex(ABC):
    """Phase-2 addition (per Section 4 Phase 2 task text: "Keyword index:
    OpenSearch adapter (BM25) with same tenant enforcement"). Not one of the
    original 8 core interfaces — mirrors VectorStore's shape since both are
    tenant-scoped search backends. A phase-directed extension, not a
    redesign of the fixed contract.
    """

    @abstractmethod
    def upsert(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
        """Insert or update keyword-index entries for a tenant."""

    @abstractmethod
    def search(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
        """BM25 search scoped to a tenant."""

    @abstractmethod
    def delete(self, tenant_id: str, *args: Any, **kwargs: Any) -> Any:
        """Delete keyword-index entries scoped to a tenant."""
