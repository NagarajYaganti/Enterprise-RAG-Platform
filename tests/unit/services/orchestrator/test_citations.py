from core.models import Chunk
from core.prompt_registry import REFUSAL_TEXT
from orchestrator.citations import check_citations, extract_cited_chunk_ids

TENANT_ID = "tenant-acme"


def _chunk(chunk_id: str) -> Chunk:
    return Chunk(
        id=chunk_id,
        tenant_id=TENANT_ID,
        document_id="doc-1",
        text="some chunk text",
        position=0,
        language="en",
        version=1,
    )


def test_extract_cited_chunk_ids_finds_bracketed_markers() -> None:
    text = "The refund window is 30 days [chunk-1]. See also [chunk-2] for exceptions."
    assert extract_cited_chunk_ids(text) == ["chunk-1", "chunk-2"]


def test_extract_cited_chunk_ids_dedupes_preserving_first_occurrence_order() -> None:
    text = "As stated [chunk-2], and again [chunk-1], and once more [chunk-2]."
    assert extract_cited_chunk_ids(text) == ["chunk-2", "chunk-1"]


def test_extract_cited_chunk_ids_returns_empty_for_no_markers() -> None:
    assert extract_cited_chunk_ids("No citations in this sentence.") == []


def test_check_citations_grounded_when_all_cited_chunks_were_retrieved() -> None:
    chunks = [_chunk("chunk-1"), _chunk("chunk-2")]
    text = "The refund window is 30 days [chunk-1]."

    result = check_citations(text, chunks)

    assert result.cited_chunk_ids == ["chunk-1"]
    assert result.valid_chunk_ids == ["chunk-1"]
    assert result.hallucinated_chunk_ids == []
    assert result.is_refusal is False
    assert result.is_grounded is True


def test_check_citations_flags_hallucinated_chunk_id_not_in_retrieved_set() -> None:
    chunks = [_chunk("chunk-1")]
    text = "The refund window is 30 days [chunk-99]."

    result = check_citations(text, chunks)

    assert result.valid_chunk_ids == []
    assert result.hallucinated_chunk_ids == ["chunk-99"]
    assert result.is_grounded is False


def test_check_citations_mixed_valid_and_hallucinated_is_not_grounded() -> None:
    chunks = [_chunk("chunk-1")]
    text = "See [chunk-1] and also [chunk-99]."

    result = check_citations(text, chunks)

    assert result.valid_chunk_ids == ["chunk-1"]
    assert result.hallucinated_chunk_ids == ["chunk-99"]
    assert result.is_grounded is False


def test_check_citations_exact_refusal_text_is_grounded_with_no_citations() -> None:
    chunks = [_chunk("chunk-1")]

    result = check_citations(REFUSAL_TEXT, chunks)

    assert result.cited_chunk_ids == []
    assert result.is_refusal is True
    assert result.is_grounded is True


def test_check_citations_answer_with_zero_citations_is_ungrounded() -> None:
    chunks = [_chunk("chunk-1")]
    text = "The refund window is 30 days."

    result = check_citations(text, chunks)

    assert result.cited_chunk_ids == []
    assert result.is_refusal is False
    assert result.is_grounded is False


def test_check_citations_empty_retrieved_set_makes_any_citation_hallucinated() -> None:
    text = "As stated [chunk-1]."

    result = check_citations(text, [])

    assert result.hallucinated_chunk_ids == ["chunk-1"]
    assert result.is_grounded is False
