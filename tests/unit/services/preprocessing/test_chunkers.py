import pytest
from core.models import ParsedDocument
from preprocessing.chunkers.fixed_size import FixedSizeChunker
from preprocessing.chunkers.structure_aware import StructureAwareChunker


def _make_doc(
    raw_text: str, structural_elements: list[dict[str, object]] | None = None
) -> ParsedDocument:
    return ParsedDocument(
        tenant_id="tenant-acme",
        document_id="doc-1",
        raw_text=raw_text,
        structural_elements=structural_elements or [],
        mime_type="text/plain",
        source_uri="stub://file",
        checksum="abc123",
    )


class TestFixedSizeChunker:
    def test_rejects_overlap_ge_chunk_size(self) -> None:
        with pytest.raises(ValueError):
            FixedSizeChunker(chunk_size=100, overlap=100)

    def test_produces_overlapping_windows(self) -> None:
        # 21 tokens (verified via tiktoken.get_encoding("cl100k_base")) --
        # chunk_size=10/overlap=2 tokens (step=8) -> windows at token
        # offsets 0, 8, 16, i.e. 3 chunks, matching real BPE token counts,
        # not character counts.
        text = (
            "the quick brown fox jumps over the lazy dog and then runs "
            "away quickly into the deep dark forest at night"
        )
        chunker = FixedSizeChunker(chunk_size=10, overlap=2)
        doc = _make_doc(text)

        chunks = chunker.chunk(doc, "fixed_size", language="en", version=1)

        assert len(chunks) == 3
        assert all(c.tenant_id == "tenant-acme" for c in chunks)
        assert all(c.document_id == "doc-1" for c in chunks)
        assert all(c.language == "en" for c in chunks)
        assert all(c.version == 1 for c in chunks)

    def test_skips_blank_pieces(self) -> None:
        # "hello world" is 2 tokens -- with chunk_size=5/overlap=1 (step=4),
        # only one window (offset 0) ever starts before the token count is
        # exhausted, so this must produce exactly one chunk with the whole
        # text, not a second, blank one.
        chunker = FixedSizeChunker(chunk_size=5, overlap=1)
        doc = _make_doc("hello world")

        chunks = chunker.chunk(doc, "fixed_size")

        assert len(chunks) == 1
        assert chunks[0].text == "hello world"

    def test_cjk_text_produces_more_chunks_than_equal_length_english(self) -> None:
        # The literal scenario the spec names: 500 characters of Chinese
        # text is NOT equivalent to 500 characters of English -- CJK text
        # encodes to far more tokens per character (verified empirically:
        # the same character count produced 84 tokens for Chinese vs. 7 for
        # English), so character-based sizing under-chunks CJK content
        # relative to English. Token-based sizing must NOT treat them the
        # same.
        zh_text = "快速的棕色狐狸跳过了懒狗然后迅速跑开进入了黑暗的森林" * 2
        en_text = "a" * len(zh_text)  # identical character count
        chunker = FixedSizeChunker(chunk_size=20, overlap=2)

        zh_chunks = chunker.chunk(_make_doc(zh_text), "fixed_size")
        en_chunks = chunker.chunk(_make_doc(en_text), "fixed_size")

        assert len(zh_text) == len(en_text)  # same character count, by construction
        assert len(zh_chunks) > len(en_chunks)


class TestStructureAwareChunker:
    def test_splits_on_headings(self) -> None:
        chunker = StructureAwareChunker()
        elements = [
            {"category": "Title", "text": "Section One", "page_number": 1},
            {"category": "NarrativeText", "text": "Body of section one.", "page_number": 1},
            {"category": "Title", "text": "Section Two", "page_number": 2},
            {"category": "NarrativeText", "text": "Body of section two.", "page_number": 2},
        ]
        doc = _make_doc("ignored", structural_elements=elements)

        chunks = chunker.chunk(doc, "structure_aware", language="en", version=1)

        assert len(chunks) == 2
        assert "Section One" in chunks[0].text
        assert "Body of section one" in chunks[0].text
        assert chunks[0].metadata["page_number"] == 1
        assert "Section Two" in chunks[1].text
        assert chunks[1].metadata["page_number"] == 2

    def test_no_elements_produces_no_chunks(self) -> None:
        chunker = StructureAwareChunker()
        doc = _make_doc("ignored", structural_elements=[])

        assert chunker.chunk(doc, "structure_aware") == []

    def test_no_heading_produces_single_section(self) -> None:
        chunker = StructureAwareChunker()
        elements = [{"category": "NarrativeText", "text": "just body text", "page_number": 1}]
        doc = _make_doc("ignored", structural_elements=elements)

        chunks = chunker.chunk(doc, "structure_aware")

        assert len(chunks) == 1
        assert chunks[0].text == "just body text"
