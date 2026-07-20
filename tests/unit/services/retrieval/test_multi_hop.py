from connectors.graph.spacy_extractor import SpacyEntityExtractor
from core.models import Chunk
from retrieval.multi_hop import extract_expansion_terms

MODEL_ID = "en_core_web_sm"


def _chunk(chunk_id: str, text: str) -> Chunk:
    return Chunk(
        id=chunk_id,
        tenant_id="tenant-acme",
        document_id="doc-1",
        text=text,
        position=0,
        language="en",
        version=1,
    )


def test_extract_expansion_terms_pulls_entity_names_from_chunks() -> None:
    extractor = SpacyEntityExtractor(MODEL_ID)
    chunks = [_chunk("c1", "Acme Bank owns Acme Lending Corp.")]

    terms = extract_expansion_terms(chunks, extractor)

    assert "Acme Bank" in terms


def test_extract_expansion_terms_deduplicates_across_chunks() -> None:
    extractor = SpacyEntityExtractor(MODEL_ID)
    chunks = [
        _chunk("c1", "Acme Bank released its report."),
        _chunk("c2", "Acme Bank also released a statement."),
    ]

    terms = extract_expansion_terms(chunks, extractor)

    assert terms.count("Acme Bank") == 1


def test_extract_expansion_terms_respects_max_terms() -> None:
    extractor = SpacyEntityExtractor(MODEL_ID)
    chunks = [
        _chunk(
            "c1",
            "Acme Bank, Beta Corp, Gamma LLC, Delta Inc, and Epsilon Group all "
            "attended the conference in New York.",
        )
    ]

    terms = extract_expansion_terms(chunks, extractor, max_terms=2)

    assert len(terms) == 2


def test_extract_expansion_terms_with_no_entities_returns_empty() -> None:
    extractor = SpacyEntityExtractor(MODEL_ID)
    chunks = [_chunk("c1", "please review the attached document before continuing")]

    terms = extract_expansion_terms(chunks, extractor)

    assert terms == []
