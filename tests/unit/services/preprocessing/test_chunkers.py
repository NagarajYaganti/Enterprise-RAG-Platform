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
        chunker = FixedSizeChunker(chunk_size=10, overlap=2)
        doc = _make_doc("a" * 25)

        chunks = chunker.chunk(doc, "fixed_size", language="en", version=1)

        assert len(chunks) > 1
        assert all(c.tenant_id == "tenant-acme" for c in chunks)
        assert all(c.document_id == "doc-1" for c in chunks)
        assert all(c.language == "en" for c in chunks)
        assert all(c.version == 1 for c in chunks)
        # consecutive chunks overlap by `overlap` characters
        assert chunks[0].text[-2:] == chunks[1].text[:2]

    def test_skips_blank_pieces(self) -> None:
        chunker = FixedSizeChunker(chunk_size=5, overlap=1)
        doc = _make_doc("ab")

        chunks = chunker.chunk(doc, "fixed_size")

        assert len(chunks) == 1
        assert chunks[0].text == "ab"


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
