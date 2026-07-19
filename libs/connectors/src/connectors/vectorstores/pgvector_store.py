from core.interfaces import VectorStore
from core.models import EmbeddingRecord, VectorSearchHit
from sqlalchemy import Engine, Table, delete, select
from sqlalchemy.dialects.postgresql import insert

from connectors.vectorstores.errors import TenantMismatchError


class PgvectorStore(VectorStore):
    """VectorStore fallback adapter for pgvector. Same tenant-scoping
    guarantee as QdrantVectorStore: tenant_id is always applied as a
    mandatory filter, impossible to query/delete without it.
    """

    def __init__(self, engine: Engine, table: Table) -> None:
        self._engine = engine
        self._table = table

    def upsert(self, tenant_id: str, records: list[EmbeddingRecord]) -> None:
        for record in records:
            if record.tenant_id != tenant_id:
                raise TenantMismatchError(
                    f"record {record.id} belongs to tenant {record.tenant_id}, "
                    f"not the upsert call's tenant_id {tenant_id}"
                )

        with self._engine.begin() as conn:
            for record in records:
                values = {
                    "id": record.id,
                    "tenant_id": record.tenant_id,
                    "document_id": record.document_id,
                    "chunk_id": record.chunk_id,
                    "model_id": record.model_id,
                    "model_version": record.model_version,
                    "status": record.status,
                    "acl_principals": record.acl_principals,
                    "embedding": record.vector,
                }
                stmt = insert(self._table).values(**values)
                update_cols = {k: v for k, v in values.items() if k != "id"}
                stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=update_cols)
                conn.execute(stmt)

    def search(
        self,
        tenant_id: str,
        query_vector: list[float],
        principals: list[str],
        top_k: int = 10,
        status: str = "active",
    ) -> list[VectorSearchHit]:
        distance = self._table.c.embedding.cosine_distance(query_vector)
        stmt = (
            select(
                self._table.c.chunk_id,
                self._table.c.document_id,
                self._table.c.model_id,
                distance.label("distance"),
            )
            .where(
                self._table.c.tenant_id == tenant_id,
                self._table.c.status == status,
                self._table.c.acl_principals.overlap(principals),
            )
            .order_by(distance)
            .limit(top_k)
        )
        with self._engine.connect() as conn:
            rows = conn.execute(stmt).all()

        return [
            VectorSearchHit(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                score=1.0 - row.distance,
                model_id=row.model_id,
            )
            for row in rows
        ]

    def delete(self, tenant_id: str, document_id: str) -> None:
        stmt = delete(self._table).where(
            self._table.c.tenant_id == tenant_id,
            self._table.c.document_id == document_id,
        )
        with self._engine.begin() as conn:
            conn.execute(stmt)
