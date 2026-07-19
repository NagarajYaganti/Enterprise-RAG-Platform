import uuid
from collections.abc import Generator

import pytest
from connectors.vectorstores.errors import TenantMismatchError
from connectors.vectorstores.migrations import ensure_pgvector_table
from connectors.vectorstores.pgvector_store import PgvectorStore
from core.models import EmbeddingRecord
from sqlalchemy import Engine, Table, create_engine, text

DATABASE_URL = "postgresql+psycopg://rag:rag@localhost:5432/rag_platform"
TABLE_NAME = "test_pgvector_store_embeddings"


@pytest.fixture()
def engine() -> Engine:
    eng = create_engine(DATABASE_URL)
    with eng.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    return eng


@pytest.fixture()
def table(engine: Engine) -> Generator[Table, None, None]:
    with engine.connect() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {TABLE_NAME}"))
        conn.commit()
    tbl = ensure_pgvector_table(engine, TABLE_NAME, dimension=4)
    yield tbl
    with engine.connect() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {TABLE_NAME}"))
        conn.commit()


def _record(
    tenant_id: str, chunk_id: str, vector: list[float], principals: list[str]
) -> EmbeddingRecord:
    return EmbeddingRecord(
        id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id)),
        tenant_id=tenant_id,
        document_id=f"doc-{chunk_id}",
        chunk_id=chunk_id,
        vector=vector,
        model_id="bge-small",
        model_version="1",
        acl_principals=principals,
    )


def test_upsert_rejects_record_from_a_different_tenant(engine: Engine, table: Table) -> None:
    store = PgvectorStore(engine, table)
    bad_record = _record("tenant-b", "c1", [0.1, 0.2, 0.3, 0.4], ["p1"])

    with pytest.raises(TenantMismatchError):
        store.upsert("tenant-a", [bad_record])


def test_search_is_tenant_isolated(engine: Engine, table: Table) -> None:
    store = PgvectorStore(engine, table)
    store.upsert("tenant-a", [_record("tenant-a", "c1", [0.1, 0.2, 0.3, 0.4], ["p1"])])
    store.upsert("tenant-b", [_record("tenant-b", "c2", [0.1, 0.2, 0.3, 0.41], ["p1"])])

    hits = store.search("tenant-a", [0.1, 0.2, 0.3, 0.4], principals=["p1"], top_k=10)

    assert [h.chunk_id for h in hits] == ["c1"]


def test_search_prefilters_on_acl_principals(engine: Engine, table: Table) -> None:
    store = PgvectorStore(engine, table)
    store.upsert(
        "tenant-a",
        [
            _record("tenant-a", "c3", [0.1, 0.2, 0.3, 0.4], ["p1"]),
            _record("tenant-a", "c4", [0.1, 0.2, 0.3, 0.4], ["p9"]),
        ],
    )

    hits = store.search("tenant-a", [0.1, 0.2, 0.3, 0.4], principals=["p1"], top_k=10)

    assert {h.chunk_id for h in hits} == {"c3"}


def test_upsert_is_idempotent_via_on_conflict_update(engine: Engine, table: Table) -> None:
    store = PgvectorStore(engine, table)
    record = _record("tenant-a", "c5", [0.1, 0.2, 0.3, 0.4], ["p1"])

    store.upsert("tenant-a", [record])
    store.upsert("tenant-a", [record])

    with engine.connect() as conn:
        count = conn.execute(
            text(f"SELECT COUNT(*) FROM {TABLE_NAME} WHERE chunk_id = 'c5'")
        ).scalar()
    assert count == 1


def test_delete_removes_only_the_target_document(engine: Engine, table: Table) -> None:
    store = PgvectorStore(engine, table)
    store.upsert(
        "tenant-a",
        [
            _record("tenant-a", "c6", [0.1, 0.2, 0.3, 0.4], ["p1"]),
            _record("tenant-a", "c7", [0.5, 0.6, 0.7, 0.8], ["p1"]),
        ],
    )

    store.delete("tenant-a", "doc-c6")

    remaining = store.search("tenant-a", [0.1, 0.2, 0.3, 0.4], principals=["p1"], top_k=10)
    assert {h.chunk_id for h in remaining} == {"c7"}


def test_delete_is_tenant_scoped(engine: Engine, table: Table) -> None:
    store = PgvectorStore(engine, table)
    store.upsert("tenant-a", [_record("tenant-a", "c8", [0.1, 0.2, 0.3, 0.4], ["p1"])])
    store.upsert("tenant-b", [_record("tenant-b", "c8dup", [0.1, 0.2, 0.3, 0.4], ["p1"])])

    store.delete("tenant-b", "doc-c8dup")

    remaining_a = store.search("tenant-a", [0.1, 0.2, 0.3, 0.4], principals=["p1"], top_k=10)
    assert {h.chunk_id for h in remaining_a} == {"c8"}
