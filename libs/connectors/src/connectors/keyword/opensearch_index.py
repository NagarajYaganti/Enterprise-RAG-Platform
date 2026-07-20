from core.interfaces import KeywordIndex
from core.models import Chunk, KeywordSearchHit
from opensearchpy import OpenSearch

from connectors.vectorstores.errors import TenantMismatchError

INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "tenant_id": {"type": "keyword"},
            "acl_principals": {"type": "keyword"},
            "document_id": {"type": "keyword"},
            "chunk_id": {"type": "keyword"},
            "text": {"type": "text"},
            # Phase-3 metadata filter dimensions. Explicit fields, not a
            # generic dict — verified empirically against the real running
            # OpenSearch 2.19.6 that the `flattened` type is unavailable
            # ("No handler for type [flattened]"), so only these four named
            # dimensions from the phase task text are mapped, matching the
            # equivalent explicit-field design in QdrantVectorStore.
            "language": {"type": "keyword"},
            "doc_type": {"type": "keyword"},
            "department": {"type": "keyword"},
            "date": {"type": "date"},
        }
    }
}


def ensure_index(client: OpenSearch, index_name: str) -> None:
    """Create the index with an explicit mapping if it doesn't already
    exist. tenant_id/acl_principals/document_id/chunk_id are `keyword`
    (exact match only) — left to dynamic mapping, they could be inferred as
    analyzed `text`, silently breaking exact-match tenant filtering.
    """
    if not client.indices.exists(index=index_name):
        client.indices.create(index=index_name, body=INDEX_MAPPING)


class OpenSearchIndex(KeywordIndex):
    """KeywordIndex adapter for OpenSearch (BM25). Same tenant-scoping
    guarantee as the VectorStore adapters: tenant_id is always applied as a
    mandatory filter, impossible to query/delete without it.
    """

    def __init__(self, client: OpenSearch, index_name: str) -> None:
        self._client = client
        self._index_name = index_name

    def upsert(self, tenant_id: str, chunks: list[Chunk]) -> None:
        for chunk in chunks:
            if chunk.tenant_id != tenant_id:
                raise TenantMismatchError(
                    f"chunk {chunk.id} belongs to tenant {chunk.tenant_id}, "
                    f"not the upsert call's tenant_id {tenant_id}"
                )

        for chunk in chunks:
            self._client.index(
                index=self._index_name,
                id=chunk.id,
                body={
                    "tenant_id": chunk.tenant_id,
                    "document_id": chunk.document_id,
                    "chunk_id": chunk.id,
                    "acl_principals": chunk.acl_principals,
                    "text": chunk.text,
                    "language": chunk.language,
                    "doc_type": chunk.doc_type,
                    "department": chunk.department,
                    "date": chunk.date,
                },
                params={"refresh": "true"},
            )

    def search(
        self,
        tenant_id: str,
        query: str,
        principals: list[str],
        top_k: int = 10,
        language: str | None = None,
        doc_type: str | None = None,
        department: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[KeywordSearchHit]:
        filters: list[dict[str, object]] = [
            {"term": {"tenant_id": tenant_id}},
            {"terms": {"acl_principals": principals}},
        ]
        # Same None-means-unconstrained rule as QdrantVectorStore.search —
        # verified empirically against the real running OpenSearch that a
        # `date`-typed field range-filters plain ISO date strings correctly
        # with no special format configuration needed.
        if language is not None:
            filters.append({"term": {"language": language}})
        if doc_type is not None:
            filters.append({"term": {"doc_type": doc_type}})
        if department is not None:
            filters.append({"term": {"department": department}})
        if date_from is not None or date_to is not None:
            date_range: dict[str, str] = {}
            if date_from is not None:
                date_range["gte"] = date_from
            if date_to is not None:
                date_range["lte"] = date_to
            filters.append({"range": {"date": date_range}})

        body = {
            "query": {
                "bool": {
                    "must": [{"match": {"text": query}}],
                    "filter": filters,
                }
            },
            "size": top_k,
        }
        response = self._client.search(index=self._index_name, body=body)
        return [
            KeywordSearchHit(
                chunk_id=hit["_source"]["chunk_id"],
                document_id=hit["_source"]["document_id"],
                score=hit["_score"],
            )
            for hit in response["hits"]["hits"]
        ]

    def delete(self, tenant_id: str, document_id: str) -> None:
        body = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"tenant_id": tenant_id}},
                        {"term": {"document_id": document_id}},
                    ]
                }
            }
        }
        self._client.delete_by_query(
            index=self._index_name, body=body, params={"refresh": "true"}
        )
