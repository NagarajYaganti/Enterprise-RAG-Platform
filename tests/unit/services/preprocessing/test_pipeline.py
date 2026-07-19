from core.models import ParsedDocument
from preprocessing.chunkers.fixed_size import FixedSizeChunker
from preprocessing.language_detect import LanguageDetector
from preprocessing.pipeline import run_pipeline
from preprocessing.translator_stub import StubTranslator


def test_pipeline_detects_language_cleans_and_chunks() -> None:
    doc = ParsedDocument(
        tenant_id="tenant-acme",
        document_id="doc-1",
        raw_text="The   quick brown fox jumps over the lazy dog." * 3,
        structural_elements=[],
        mime_type="text/plain",
        source_uri="stub://file",
        checksum="abc123",
    )
    chunker = FixedSizeChunker(chunk_size=50, overlap=5)

    chunks = run_pipeline(
        doc,
        chunker,
        "fixed_size",
        LanguageDetector(),
        StubTranslator(),
        version=1,
    )

    assert len(chunks) > 1
    assert all(c.language == "en" for c in chunks)
    assert all(c.version == 1 for c in chunks)
    assert all("source_uri" in c.metadata for c in chunks)
    # cleaning collapsed the repeated whitespace before chunking
    assert all("   " not in c.text for c in chunks)


def test_pipeline_with_no_target_language_skips_translation() -> None:
    doc = ParsedDocument(
        tenant_id="tenant-acme",
        document_id="doc-1",
        raw_text="Hola, este es un texto en español.",
        structural_elements=[],
        mime_type="text/plain",
        source_uri="stub://file",
        checksum="abc123",
    )
    chunker = FixedSizeChunker(chunk_size=200, overlap=10)

    chunks = run_pipeline(
        doc, chunker, "fixed_size", LanguageDetector(), StubTranslator(), version=1
    )

    assert chunks[0].language == "es"
    assert "español" in chunks[0].text
