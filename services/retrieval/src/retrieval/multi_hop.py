from connectors.graph.spacy_extractor import SpacyEntityExtractor
from core.models import Chunk


def extract_expansion_terms(
    chunks: list[Chunk], extractor: SpacyEntityExtractor, max_terms: int = 5
) -> list[str]:
    """Extracts entity names from first-pass result chunks' text, for an
    optional second (multi-hop) retrieval pass — config-flag-gated in
    RetrievalSettings.multi_hop_enabled, off by default per Section 4
    Phase 3 task text. Reuses the same spaCy pipeline as GraphRAG, no new
    dependency. This function only extracts terms; issuing the actual
    second retrieval call is the pipeline's responsibility.
    """
    terms: list[str] = []
    for chunk in chunks:
        entities, _ = extractor.extract(chunk)
        for entity in entities:
            if entity.name not in terms:
                terms.append(entity.name)
            if len(terms) >= max_terms:
                return terms
    return terms
