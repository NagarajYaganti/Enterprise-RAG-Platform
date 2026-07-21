from datetime import datetime, timedelta, timezone

from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client.models import (
    DatetimeRange,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
)


class SemanticCacheHit(BaseModel):
    answer_text: str
    document_ids: list[str]
    cited_chunk_ids: list[str]
    model_id: str
    score: float


class SemanticCache:
    """Dedicated Qdrant collection for cached (query embedding -> answer)
    pairs. Deliberately NOT Redis: the pinned redis:8.4 image in
    infra/docker-compose.dev.yml has no RediSearch/vector module (verified
    empirically during Phase 4 planning), so it can't do similarity search.

    Not a VectorStore ABC implementation — its read/write shapes (a single
    best-match lookup returning an answer, not a scored top_k list of
    chunks) genuinely differ from VectorStore's upsert/search/delete
    contract, same rationale as QdrantVectorStore.supersede_by_model being
    an additive capability outside the fixed ABC rather than forced into it.

    Qdrant has no native point TTL, so freshness is enforced by storing
    created_at in the payload and filtering on it at read time
    (DatetimeRange) — an expired point simply stops being returned as a
    hit once past ttl_seconds, it isn't physically deleted by that path.
    """

    def __init__(
        self,
        client: QdrantClient,
        collection_name: str,
        similarity_threshold: float,
        ttl_seconds: int,
    ) -> None:
        self._client = client
        self._collection_name = collection_name
        self._similarity_threshold = similarity_threshold
        self._ttl_seconds = ttl_seconds

    def get(self, tenant_id: str, query_vector: list[float]) -> SemanticCacheHit | None:
        not_before = datetime.now(timezone.utc) - timedelta(seconds=self._ttl_seconds)
        query_filter = Filter(
            must=[
                FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                FieldCondition(key="created_at", range=DatetimeRange(gte=not_before)),
            ]
        )
        result = self._client.query_points(
            self._collection_name, query=query_vector, query_filter=query_filter, limit=1
        )
        if not result.points:
            return None

        point = result.points[0]
        if point.score < self._similarity_threshold:
            return None

        payload = point.payload or {}
        return SemanticCacheHit(
            answer_text=payload["answer_text"],
            document_ids=payload["document_ids"],
            cited_chunk_ids=payload["cited_chunk_ids"],
            model_id=payload["model_id"],
            score=point.score,
        )

    def put(
        self,
        tenant_id: str,
        query_id: str,
        query_vector: list[float],
        answer_text: str,
        document_ids: list[str],
        cited_chunk_ids: list[str],
        model_id: str,
    ) -> None:
        point = PointStruct(
            id=query_id,
            vector=query_vector,
            payload={
                "tenant_id": tenant_id,
                "answer_text": answer_text,
                "document_ids": document_ids,
                "cited_chunk_ids": cited_chunk_ids,
                "model_id": model_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self._client.upsert(self._collection_name, points=[point])

    def invalidate_for_document(self, tenant_id: str, document_id: str) -> None:
        """Delete every cache entry whose answer drew on this document, e.g.
        because it was re-ingested or superseded — mirrors the ACL
        pre-filter pattern (MatchAny against a list-valued payload field)
        used by QdrantVectorStore.search for acl_principals.
        """
        self._client.delete(
            self._collection_name,
            points_selector=Filter(
                must=[
                    FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                    FieldCondition(key="document_ids", match=MatchAny(any=[document_id])),
                ]
            ),
        )
