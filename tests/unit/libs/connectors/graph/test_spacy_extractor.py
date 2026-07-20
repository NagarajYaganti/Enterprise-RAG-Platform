from connectors.graph.spacy_extractor import RELATION_PREDICATE, SpacyEntityExtractor
from core.models import Chunk

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


def test_extract_finds_real_entities_via_ner() -> None:
    extractor = SpacyEntityExtractor(MODEL_ID)
    chunk = _chunk("c1", "Acme Bank owns Acme Lending Corp, founded in 2010 in New York.")

    entities, _ = extractor.extract(chunk)

    names = {e.name for e in entities}
    labels = {e.label for e in entities}
    assert "Acme Bank" in names
    assert "ORG" in labels
    assert "GPE" in labels
    for entity in entities:
        assert entity.tenant_id == "tenant-acme"
        assert entity.chunk_id == "c1"
        assert entity.document_id == "doc-1"


def test_extract_links_co_occurring_entities_in_the_same_sentence() -> None:
    extractor = SpacyEntityExtractor(MODEL_ID)
    chunk = _chunk("c2", "Acme Bank owns Acme Lending Corp.")

    entities, relations = extractor.extract(chunk)

    assert len(entities) == 2
    assert len(relations) == 1
    relation = relations[0]
    assert relation.predicate == RELATION_PREDICATE
    entity_ids = {e.id for e in entities}
    assert relation.subject_entity_id in entity_ids
    assert relation.object_entity_id in entity_ids
    assert relation.chunk_id == "c2"


def test_extract_does_not_link_entities_across_sentences() -> None:
    extractor = SpacyEntityExtractor(MODEL_ID)
    # Two distinct sentences, each with exactly one entity — no co-occurrence
    # within either sentence, so no relation should be produced.
    chunk = _chunk("c3", "Acme Bank released its report. New York remained unaffected.")

    entities, relations = extractor.extract(chunk)

    assert len(entities) == 2
    assert relations == []


def test_extract_with_no_entities_returns_empty() -> None:
    extractor = SpacyEntityExtractor(MODEL_ID)
    # Verified empirically against the real model: this sentence produces
    # zero entities (no ORG/PERSON/GPE/DATE/etc.) — earlier drafts of this
    # test used "...nice today", which spaCy correctly tags "today" as DATE.
    chunk = _chunk("c4", "please review the attached document before continuing")

    entities, relations = extractor.extract(chunk)

    assert entities == []
    assert relations == []
