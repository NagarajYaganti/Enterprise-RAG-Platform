import pytest
from core.interfaces import (
    Chunker,
    DocumentParser,
    EmbeddingProvider,
    Guardrail,
    LLMProvider,
    ModelRouter,
    Reranker,
    VectorStore,
)

ALL_INTERFACES = [
    DocumentParser,
    Chunker,
    EmbeddingProvider,
    VectorStore,
    Reranker,
    LLMProvider,
    ModelRouter,
    Guardrail,
]


@pytest.mark.parametrize("interface", ALL_INTERFACES)
def test_interface_cannot_be_instantiated_directly(interface: type) -> None:
    with pytest.raises(TypeError):
        interface()


def test_minimal_stub_satisfies_document_parser() -> None:
    class StubParser(DocumentParser):
        def parse(self, file: object, mime_type: str) -> str:
            return "parsed"

    assert StubParser().parse(b"data", "text/plain") == "parsed"


def test_minimal_stub_satisfies_vector_store() -> None:
    class StubVectorStore(VectorStore):
        def upsert(self, tenant_id: str, *args: object, **kwargs: object) -> str:
            return f"upserted:{tenant_id}"

        def search(self, tenant_id: str, *args: object, **kwargs: object) -> list[object]:
            return []

        def delete(self, tenant_id: str, *args: object, **kwargs: object) -> bool:
            return True

    store = StubVectorStore()
    assert store.upsert("tenant-acme") == "upserted:tenant-acme"
    assert store.search("tenant-acme") == []
    assert store.delete("tenant-acme") is True
