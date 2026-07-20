import datetime

from core.interfaces import VectorStore
from core.models import EmbeddingRecord, VectorSearchHit
from qdrant_client import QdrantClient
from qdrant_client.models import (
    DatetimeRange,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
)

from connectors.vectorstores.errors import TenantMismatchError


class QdrantVectorStore(VectorStore):
    """VectorStore adapter for Qdrant. tenant_id is always applied as a
    mandatory filter — impossible to query/delete without it, matching the
    Postgres repository pattern from Phase 1.
    """

    def __init__(self, client: QdrantClient, collection_name: str) -> None:
        self._client = client
        self._collection_name = collection_name

    def upsert(self, tenant_id: str, records: list[EmbeddingRecord]) -> None:
        for record in records:
            if record.tenant_id != tenant_id:
                raise TenantMismatchError(
                    f"record {record.id} belongs to tenant {record.tenant_id}, "
                    f"not the upsert call's tenant_id {tenant_id}"
                )

        points = [
            PointStruct(
                id=record.id,
                vector=record.vector,
                payload={
                    "tenant_id": record.tenant_id,
                    "document_id": record.document_id,
                    "chunk_id": record.chunk_id,
                    "model_id": record.model_id,
                    "model_version": record.model_version,
                    "status": record.status,
                    "acl_principals": record.acl_principals,
                    "language": record.language,
                    "doc_type": record.doc_type,
                    "department": record.department,
                    "date": record.date,
                },
            )
            for record in records
        ]
        self._client.upsert(self._collection_name, points=points)

    def search(
        self,
        tenant_id: str,
        query_vector: list[float],
        principals: list[str],
        top_k: int = 10,
        status: str = "active",
        language: str | None = None,
        doc_type: str | None = None,
        department: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[VectorSearchHit]:
        must: list[FieldCondition] = [
            FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
            FieldCondition(key="status", match=MatchValue(value=status)),
            FieldCondition(key="acl_principals", match=MatchAny(any=principals)),
        ]
        # Metadata filters: a dimension left as None is unconstrained, never
        # translated into a condition — a provided value is an exact/range
        # match that excludes points missing that field. Verified empirically
        # against the real running Qdrant that DatetimeRange filters plain
        # ISO date strings correctly with no special encoding needed.
        if language is not None:
            must.append(FieldCondition(key="language", match=MatchValue(value=language)))
        if doc_type is not None:
            must.append(FieldCondition(key="doc_type", match=MatchValue(value=doc_type)))
        if department is not None:
            must.append(FieldCondition(key="department", match=MatchValue(value=department)))
        if date_from is not None or date_to is not None:
            must.append(
                FieldCondition(
                    key="date",
                    range=DatetimeRange(
                        gte=datetime.date.fromisoformat(date_from) if date_from else None,
                        lte=datetime.date.fromisoformat(date_to) if date_to else None,
                    ),
                )
            )
        query_filter = Filter(must=must)  # type: ignore[arg-type]
        result = self._client.query_points(
            self._collection_name, query=query_vector, query_filter=query_filter, limit=top_k
        )
        return [
            VectorSearchHit(
                chunk_id=point.payload["chunk_id"],  # type: ignore[index]
                document_id=point.payload["document_id"],  # type: ignore[index]
                score=point.score,
                model_id=point.payload["model_id"],  # type: ignore[index]
            )
            for point in result.points
        ]

    def delete(self, tenant_id: str, document_id: str) -> None:
        self._client.delete(
            self._collection_name,
            points_selector=Filter(
                must=[
                    FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                    FieldCondition(key="document_id", match=MatchValue(value=document_id)),
                ]
            ),
        )

    def supersede_by_model(self, tenant_id: str, document_id: str, model_id: str) -> None:
        """Cutover step for re-embedding: flip status=superseded on every
        record for this document that was embedded with the given (old)
        model_id, without deleting them outright. Not part of the fixed
        VectorStore ABC (only Qdrant needs this operation shape) — an
        additive capability on the concrete adapter.
        """
        self._client.set_payload(
            self._collection_name,
            payload={"status": "superseded"},
            points=Filter(
                must=[
                    FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                    FieldCondition(key="document_id", match=MatchValue(value=document_id)),
                    FieldCondition(key="model_id", match=MatchValue(value=model_id)),
                ]
            ),
        )
