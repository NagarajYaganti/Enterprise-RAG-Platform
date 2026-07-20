from collections.abc import Generator

import pytest
from connectors.graph.postgres_knowledge_graph import PostgresKnowledgeGraph
from connectors.postgres.orm import Base
from connectors.postgres.session import get_engine, get_sessionmaker
from connectors.vectorstores.errors import TenantMismatchError
from core.models import Entity, Relation
from sqlalchemy.orm import Session

DATABASE_URL = "postgresql+psycopg://rag:rag@localhost:5432/rag_platform"


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    engine = get_engine(DATABASE_URL)
    Base.metadata.create_all(engine)
    factory = get_sessionmaker(engine)
    sess = factory()
    for table in reversed(Base.metadata.sorted_tables):
        sess.execute(table.delete())
    sess.commit()
    yield sess
    sess.close()


def _entity(tenant_id: str, entity_id: str, name: str, label: str = "ORG") -> Entity:
    return Entity(
        id=entity_id,
        tenant_id=tenant_id,
        document_id="doc-1",
        chunk_id="chunk-1",
        name=name,
        label=label,
    )


def _relation(tenant_id: str, relation_id: str, subject_id: str, object_id: str) -> Relation:
    return Relation(
        id=relation_id,
        tenant_id=tenant_id,
        subject_entity_id=subject_id,
        predicate="co_occurs_with",
        object_entity_id=object_id,
        chunk_id="chunk-1",
    )


def test_upsert_entities_rejects_entity_from_a_different_tenant(session: Session) -> None:
    graph = PostgresKnowledgeGraph(session)
    bad_entity = _entity("tenant-b", "e1", "Acme Bank")

    with pytest.raises(TenantMismatchError):
        graph.upsert_entities("tenant-a", [bad_entity])


def test_upsert_relations_rejects_relation_from_a_different_tenant(session: Session) -> None:
    graph = PostgresKnowledgeGraph(session)
    bad_relation = _relation("tenant-b", "r1", "e1", "e2")

    with pytest.raises(TenantMismatchError):
        graph.upsert_relations("tenant-a", [bad_relation])


def test_query_subgraph_returns_matching_entities_and_their_relations(session: Session) -> None:
    graph = PostgresKnowledgeGraph(session)
    graph.upsert_entities(
        "tenant-a",
        [
            _entity("tenant-a", "e1", "Acme Bank"),
            _entity("tenant-a", "e2", "Acme Lending Corp"),
            _entity("tenant-a", "e3", "Unrelated Co"),
        ],
    )
    graph.upsert_relations("tenant-a", [_relation("tenant-a", "r1", "e1", "e2")])
    session.commit()

    entities, relations = graph.query_subgraph("tenant-a", ["Acme Bank", "Acme Lending Corp"])

    assert {e.id for e in entities} == {"e1", "e2"}
    assert len(relations) == 1
    assert relations[0].id == "r1"


def test_query_subgraph_is_tenant_scoped(session: Session) -> None:
    graph = PostgresKnowledgeGraph(session)
    graph.upsert_entities("tenant-a", [_entity("tenant-a", "e1", "Acme Bank")])
    session.commit()

    entities, relations = graph.query_subgraph("tenant-b", ["Acme Bank"])

    assert entities == []
    assert relations == []


def test_query_subgraph_with_no_matching_entities_returns_empty(session: Session) -> None:
    graph = PostgresKnowledgeGraph(session)

    entities, relations = graph.query_subgraph("tenant-a", ["Nonexistent Corp"])

    assert entities == []
    assert relations == []


def test_upsert_entities_is_idempotent(session: Session) -> None:
    graph = PostgresKnowledgeGraph(session)
    entity = _entity("tenant-a", "e1", "Acme Bank")

    graph.upsert_entities("tenant-a", [entity])
    graph.upsert_entities("tenant-a", [entity])
    session.commit()

    entities, _ = graph.query_subgraph("tenant-a", ["Acme Bank"])
    assert len(entities) == 1
