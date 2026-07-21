from typing import Any

from core.interfaces import KeywordIndex
from core.models import Chunk, KeywordSearchHit
from opensearchpy import OpenSearch

from connectors.vectorstores.errors import TenantMismatchError

# OpenSearch's real, built-in Lucene language analyzers -- verified
# empirically via the running cluster's own _analyze API (no analysis-icu
# plugin installed, but these ship with OpenSearch core, zero extra
# plugins needed). One real index per analyzer, since analyzer choice is
# an index-level setting OpenSearch cannot change on a live index.
ANALYZERS = [
    "english",
    "spanish",
    "french",
    "german",
    "portuguese",
    "hindi",
    "arabic",
    "cjk",
    "standard",
]

# Mirrors config/policies/language.yaml's `analyzer` outcomes, for the ONE
# place a caller filters search by ISO language code rather than already
# knowing the resolved analyzer (chunk.search_analyzer) -- kept in sync
# manually since libs/connectors cannot import services/preprocessing's
# LanguagePolicy (services must not be a dependency of libs). zh/ja both
# map to cjk, same disclosed limitation as language.yaml (no kuromoji
# plugin installed for real Japanese-specific segmentation).
LANGUAGE_TO_ANALYZER = {
    "en": "english",
    "es": "spanish",
    "fr": "french",
    "de": "german",
    "pt": "portuguese",
    "hi": "hindi",
    "ar": "arabic",
    "zh": "cjk",
    "ja": "cjk",
}


def _index_mapping(analyzer: str) -> dict[str, Any]:
    return {
        "mappings": {
            "properties": {
                "tenant_id": {"type": "keyword"},
                "acl_principals": {"type": "keyword"},
                "document_id": {"type": "keyword"},
                "chunk_id": {"type": "keyword"},
                "text": {"type": "text", "analyzer": analyzer},
                # Phase-3 metadata filter dimensions. Explicit fields, not a
                # generic dict -- verified empirically against the real
                # running OpenSearch 2.19.6 that the `flattened` type is
                # unavailable ("No handler for type [flattened]"), so only
                # these four named dimensions from the phase task text are
                # mapped, matching the equivalent explicit-field design in
                # QdrantVectorStore.
                "language": {"type": "keyword"},
                "doc_type": {"type": "keyword"},
                "department": {"type": "keyword"},
                "date": {"type": "date"},
            }
        }
    }


def ensure_index(client: OpenSearch, index_name: str) -> None:
    """Creates one real index per analyzer (f"{index_name}_{analyzer}") if
    it doesn't already exist -- language-aware analyzers (Phase-2 retrofit)
    mean there is no longer one shared index; `index_name` is now used as a
    prefix. Callers are unaffected: this keeps its exact call signature, so
    every existing call site (services/ingestion, services/embedding,
    services/retrieval, services/orchestrator) needs zero changes.

    Migration note: a pre-existing single `index_name` index from before
    this retrofit (e.g. a long-lived dev volume) is left as-is, not
    migrated/backfilled -- same accepted limitation as Phase 3's Postgres
    schema-drift note. A fresh dev/CI volume gets the new per-language
    indices from scratch.
    """
    for analyzer in ANALYZERS:
        real_index = f"{index_name}_{analyzer}"
        if not client.indices.exists(index=real_index):
            client.indices.create(index=real_index, body=_index_mapping(analyzer))


class OpenSearchIndex(KeywordIndex):
    """KeywordIndex adapter for OpenSearch (BM25). Same tenant-scoping
    guarantee as the VectorStore adapters: tenant_id is always applied as a
    mandatory filter, impossible to query/delete without it.

    `index_name` is a PREFIX (Phase-2 retrofit) -- each chunk's text is
    actually stored in `f"{index_name}_{chunk.search_analyzer}"`, one real
    index per language-appropriate analyzer. Reads/deletes that aren't
    scoped to one specific language span every language index via a
    wildcard pattern, a real, native OpenSearch capability.
    """

    def __init__(self, client: OpenSearch, index_name: str) -> None:
        self._client = client
        self._index_name = index_name

    def _wildcard(self) -> str:
        return f"{self._index_name}_*"

    def upsert(self, tenant_id: str, chunks: list[Chunk]) -> None:
        for chunk in chunks:
            if chunk.tenant_id != tenant_id:
                raise TenantMismatchError(
                    f"chunk {chunk.id} belongs to tenant {chunk.tenant_id}, "
                    f"not the upsert call's tenant_id {tenant_id}"
                )

        for chunk in chunks:
            analyzer = chunk.search_analyzer if chunk.search_analyzer in ANALYZERS else "standard"
            self._client.index(
                index=f"{self._index_name}_{analyzer}",
                id=chunk.id,
                body={
                    "tenant_id": chunk.tenant_id,
                    "document_id": chunk.document_id,
                    "chunk_id": chunk.id,
                    "acl_principals": chunk.acl_principals,
                    "language": chunk.language,
                    "doc_type": chunk.doc_type,
                    "department": chunk.department,
                    "date": chunk.date,
                    "text": chunk.text,
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

        # `language` filter selects which per-analyzer index(es) to search
        # AND still filters on the stored `language` field, so a chunk
        # falling back to a shared analyzer (e.g. "cjk" for both zh/ja)
        # doesn't leak the other language's results.
        if language is not None:
            filters.append({"term": {"language": language}})
            target_index = f"{self._index_name}_{LANGUAGE_TO_ANALYZER.get(language, 'standard')}"
        else:
            target_index = self._wildcard()

        body = {
            "query": {
                "bool": {
                    "must": [{"match": {"text": query}}],
                    "filter": filters,
                }
            },
            "size": top_k,
        }
        response = self._client.search(index=target_index, body=body)
        return [
            KeywordSearchHit(
                chunk_id=hit["_source"]["chunk_id"],
                document_id=hit["_source"]["document_id"],
                score=hit["_score"],
            )
            for hit in response["hits"]["hits"]
        ]

    def delete(self, tenant_id: str, document_id: str) -> None:
        # Always the wildcard: a single document's chunks can span multiple
        # language indices (Phase 1's per-section language detection).
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
            index=self._wildcard(), body=body, params={"refresh": "true"}
        )
