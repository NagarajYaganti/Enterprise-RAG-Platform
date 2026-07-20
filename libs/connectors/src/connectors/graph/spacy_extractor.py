import uuid

import spacy
from core.models import Chunk, Entity, Relation

RELATION_PREDICATE = "co_occurs_with"


class SpacyEntityExtractor:
    """GraphRAG (optional, flagged OFF by default) entity/relation
    extraction. model_id is never hardcoded — it must come from
    config/models.yaml (core.model_registry.get_default_ner_model).

    Entities: real spaCy NER (PERSON/ORG/GPE/... labels).
    Relations: a coarse first-pass heuristic — any two entities that
    co-occur in the same sentence are linked with a fixed
    "co_occurs_with" predicate. This is NOT real relation classification;
    that would need a per-chunk LLM call, which is exactly the expensive
    option GraphRAG's cost gate exists to guard against. The goal here is
    a cheap local foundation, stated explicitly rather than oversold.
    """

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id
        self._nlp = spacy.load(model_id)

    def extract(self, chunk: Chunk) -> tuple[list[Entity], list[Relation]]:
        doc = self._nlp(chunk.text)

        entities: list[Entity] = []
        entity_spans: list[tuple[int, int, Entity]] = []
        for ent in doc.ents:
            entity = Entity(
                id=str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"{chunk.id}:{ent.start_char}:{ent.end_char}")
                ),
                tenant_id=chunk.tenant_id,
                document_id=chunk.document_id,
                chunk_id=chunk.id,
                name=ent.text,
                label=ent.label_,
            )
            entities.append(entity)
            entity_spans.append((ent.start_char, ent.end_char, entity))

        relations: list[Relation] = []
        for sent in doc.sents:
            sent_entities = [
                entity
                for start, end, entity in entity_spans
                if sent.start_char <= start and end <= sent.end_char
            ]
            for i, subject in enumerate(sent_entities):
                for obj in sent_entities[i + 1 :]:
                    relations.append(
                        Relation(
                            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{subject.id}:{obj.id}")),
                            tenant_id=chunk.tenant_id,
                            subject_entity_id=subject.id,
                            predicate=RELATION_PREDICATE,
                            object_entity_id=obj.id,
                            chunk_id=chunk.id,
                        )
                    )
        return entities, relations
