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
                },
                params={"refresh": "true"},
            )

    def search(
        self, tenant_id: str, query: str, principals: list[str], top_k: int = 10
    ) -> list[KeywordSearchHit]:
        body = {
            "query": {
                "bool": {
                    "must": [{"match": {"text": query}}],
                    "filter": [
                        {"term": {"tenant_id": tenant_id}},
                        {"terms": {"acl_principals": principals}},
                    ],
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
