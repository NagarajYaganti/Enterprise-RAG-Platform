from core.interfaces import KnowledgeGraph
from core.models import Entity, Relation
from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.postgres.orm import EntityORM, RelationORM
from connectors.vectorstores.errors import TenantMismatchError


def _entity_to_model(row: EntityORM) -> Entity:
    return Entity(
        id=row.id,
        tenant_id=row.tenant_id,
        document_id=row.document_id,
        chunk_id=row.chunk_id,
        name=row.name,
        label=row.label,
    )


def _relation_to_model(row: RelationORM) -> Relation:
    return Relation(
        id=row.id,
        tenant_id=row.tenant_id,
        subject_entity_id=row.subject_entity_id,
        predicate=row.predicate,
        object_entity_id=row.object_entity_id,
        chunk_id=row.chunk_id,
    )


class PostgresKnowledgeGraph(KnowledgeGraph):
    """KnowledgeGraph adapter backed by Postgres tables, not a graph
    database — docs/ARCHITECTURE.md's fixed local dev stack has none.
    tenant_id is always applied as a mandatory filter, matching every other
    store in this codebase.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_entities(self, tenant_id: str, entities: list[Entity]) -> None:
        for entity in entities:
            if entity.tenant_id != tenant_id:
                raise TenantMismatchError(
                    f"entity {entity.id} belongs to tenant {entity.tenant_id}, "
                    f"not the upsert call's tenant_id {tenant_id}"
                )

        for entity in entities:
            row = self._session.get(EntityORM, entity.id)
            if row is None:
                row = EntityORM(id=entity.id, tenant_id=entity.tenant_id)
                self._session.add(row)
            row.document_id = entity.document_id
            row.chunk_id = entity.chunk_id
            row.name = entity.name
            row.label = entity.label
        self._session.flush()

    def upsert_relations(self, tenant_id: str, relations: list[Relation]) -> None:
        for relation in relations:
            if relation.tenant_id != tenant_id:
                raise TenantMismatchError(
                    f"relation {relation.id} belongs to tenant {relation.tenant_id}, "
                    f"not the upsert call's tenant_id {tenant_id}"
                )

        for relation in relations:
            row = self._session.get(RelationORM, relation.id)
            if row is None:
                row = RelationORM(id=relation.id, tenant_id=relation.tenant_id)
                self._session.add(row)
            row.subject_entity_id = relation.subject_entity_id
            row.predicate = relation.predicate
            row.object_entity_id = relation.object_entity_id
            row.chunk_id = relation.chunk_id
        self._session.flush()

    def query_subgraph(
        self, tenant_id: str, entity_names: list[str]
    ) -> tuple[list[Entity], list[Relation]]:
        entity_stmt = select(EntityORM).where(
            EntityORM.tenant_id == tenant_id, EntityORM.name.in_(entity_names)
        )
        entity_rows = self._session.execute(entity_stmt).scalars().all()
        entities = [_entity_to_model(row) for row in entity_rows]
        entity_ids = {entity.id for entity in entities}
        if not entity_ids:
            return [], []

        relation_stmt = select(RelationORM).where(
            RelationORM.tenant_id == tenant_id,
            (RelationORM.subject_entity_id.in_(entity_ids))
            | (RelationORM.object_entity_id.in_(entity_ids)),
        )
        relation_rows = self._session.execute(relation_stmt).scalars().all()
        relations = [_relation_to_model(row) for row in relation_rows]
        return entities, relations
