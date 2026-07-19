from abc import ABC, abstractmethod
from typing import Any


class DocumentParser(ABC):
    @abstractmethod
    def parse(self, file: Any, mime_type: str) -> Any:
        """Parse a raw file into a ParsedDocument."""


class Chunker(ABC):
    @abstractmethod
    def chunk(self, doc: Any, strategy: str) -> list[Any]:
        """Split a parsed document into Chunks using the given strategy."""


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: list[str], model_id: str) -> list[Any]:
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
