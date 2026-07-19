from datetime import datetime

import pytest
from core.interfaces import (
    Chunker,
    DocumentParser,
    EmbeddingProvider,
    Guardrail,
    LLMProvider,
    ModelRouter,
    Reranker,
    SourceConnector,
    Translator,
    VectorStore,
)
from core.models import ParsedDocument

ALL_INTERFACES = [
    DocumentParser,
    Chunker,
    EmbeddingProvider,
    VectorStore,
    Reranker,
    LLMProvider,
    ModelRouter,
    Guardrail,
    SourceConnector,
    Translator,
]


@pytest.mark.parametrize("interface", ALL_INTERFACES)
def test_interface_cannot_be_instantiated_directly(interface: type) -> None:
    with pytest.raises(TypeError):
        interface()


def test_minimal_stub_satisfies_document_parser() -> None:
    class StubParser(DocumentParser):
        def parse(
            self, file: object, mime_type: str, *, tenant_id: str = "", document_id: str = ""
        ) -> ParsedDocument:
            return ParsedDocument(
                tenant_id=tenant_id,
                document_id=document_id,
                raw_text="parsed",
                mime_type=mime_type,
                source_uri="stub://file",
                checksum="abc123",
            )

    result = StubParser().parse(b"data", "text/plain")
    assert result.raw_text == "parsed"
    assert result.tenant_id == ""

    stamped = StubParser().parse(
        b"data", "text/plain", tenant_id="tenant-acme", document_id="doc-1"
    )
    assert stamped.tenant_id == "tenant-acme"
    assert stamped.document_id == "doc-1"


def test_minimal_stub_satisfies_source_connector() -> None:
    class StubSourceConnector(SourceConnector):
        def list_documents(self, since: datetime | None) -> list[object]:
            return []

        def fetch(self, ref: object) -> ParsedDocument:
            return ParsedDocument(
                tenant_id="tenant-acme",
                document_id="doc-1",
                raw_text="fetched",
                mime_type="text/plain",
                source_uri="stub://file",
                checksum="abc123",
            )

        def list_deletions(self, since: datetime | None) -> list[str]:
            return []

    connector = StubSourceConnector()
    assert connector.list_documents(None) == []
    assert connector.fetch(object()).raw_text == "fetched"
    assert connector.list_deletions(None) == []


def test_minimal_stub_satisfies_translator() -> None:
    class StubTranslator(Translator):
        def translate(self, text: str, source_lang: str, target_lang: str) -> str:
            return text

    assert StubTranslator().translate("hello", "en", "es") == "hello"


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
