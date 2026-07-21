from core.models import ParsedDocument
from preprocessing.chunkers.fixed_size import FixedSizeChunker
from preprocessing.chunkers.structure_aware import StructureAwareChunker
from preprocessing.language_detect import LanguageDetector
from preprocessing.pipeline import run_pipeline
from preprocessing.translator_stub import StubTranslator


def test_pipeline_detects_language_cleans_and_chunks() -> None:
    doc = ParsedDocument(
        tenant_id="tenant-acme",
        document_id="doc-1",
        # 10 repeats -> 91 tokens (verified via tiktoken cl100k_base),
        # comfortably over chunk_size=50 -- 3 repeats (the old char-based
        # test's value) is only 28 tokens and now fits in a single chunk,
        # since chunk_size means tokens, not characters.
        raw_text="The   quick brown fox jumps over the lazy dog." * 10,
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
    # With no explicit target_language, LanguagePolicy would suggest
    # translate_then_embed for Spanish (not in the default native_languages
    # = ("en",)) -- but StubTranslator's no-op means the text never
    # actually changes, so the safety check in run_pipeline correctly
    # declines to relabel the language, keeping it "es" rather than
    # falsely claiming this untranslated Spanish text is now English.
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
    assert chunks[0].original_text is None  # no translation ran -> not set


def test_pipeline_preserves_original_text_when_translation_runs() -> None:
    original_text = "Hola, este es un texto en español que debe conservarse."
    doc = ParsedDocument(
        tenant_id="tenant-acme",
        document_id="doc-1",
        raw_text=original_text,
        structural_elements=[],
        mime_type="text/plain",
        source_uri="stub://file",
        checksum="abc123",
    )
    chunker = FixedSizeChunker(chunk_size=200, overlap=10)

    # StubTranslator is still a no-op, so chunk.text won't actually read as
    # English -- what this proves is the WIRING: the original is captured
    # and threaded onto the chunk rather than discarded, not translation
    # quality (there is none yet).
    chunks = run_pipeline(
        doc,
        chunker,
        "fixed_size",
        LanguageDetector(),
        StubTranslator(),
        version=1,
        target_language="en",
    )

    assert len(chunks) == 1
    assert chunks[0].language == "en"
    assert chunks[0].original_text == original_text


def test_pipeline_detects_language_per_section_not_per_document() -> None:
    # A real mixed-language document (English section, then an Arabic
    # section) -- detecting once on the whole concatenated text would hide
    # this and tag every chunk with whichever language happens to dominate
    # by character count. Each section must get its OWN detected language.
    english_text = (
        "The quick brown fox jumps over the lazy dog near the riverbank every morning."
    )
    arabic_text = "مرحبا بكم في هذا المستند الذي يحتوي على معلومات مهمة حول السياسة"
    doc = ParsedDocument(
        tenant_id="tenant-acme",
        document_id="doc-1",
        raw_text=f"{english_text}\n{arabic_text}",
        structural_elements=[
            {"category": "Title", "text": "English Section", "page_number": 1},
            {"category": "NarrativeText", "text": english_text, "page_number": 1},
            {"category": "Title", "text": "Arabic Section", "page_number": 2},
            {"category": "NarrativeText", "text": arabic_text, "page_number": 2},
        ],
        mime_type="text/html",
        source_uri="stub://file",
        checksum="abc123",
    )

    chunks = run_pipeline(
        doc,
        StructureAwareChunker(),
        "structure_aware",
        LanguageDetector(),
        StubTranslator(),
        version=1,
    )

    assert len(chunks) == 2
    assert chunks[0].language == "en"
    assert chunks[1].language == "ar"
    # Phase-2 retrofit: each chunk's OpenSearch analyzer must follow its
    # OWN section's language, not the document's majority language.
    assert chunks[0].search_analyzer == "english"
    assert chunks[1].search_analyzer == "arabic"
