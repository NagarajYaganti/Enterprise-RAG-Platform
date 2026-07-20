from core.models import RetrievalFilters


def to_search_kwargs(filters: RetrievalFilters) -> dict[str, str | None]:
    """Translates RetrievalFilters into the keyword arguments QdrantVectorStore
    .search / OpenSearchIndex.search already accept by name. Enforcement
    lives in the adapters (pre-filter, not post-filter) — this is a thin
    mapping layer only. A field left as None here means "unconstrained,"
    matching the adapters' own None-means-unconstrained rule.
    """
    return {
        "language": filters.language,
        "doc_type": filters.doc_type,
        "department": filters.department,
        "date_from": filters.date_from,
        "date_to": filters.date_to,
    }
