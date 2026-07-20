from core.models import KeywordSearchHit, VectorSearchHit


def reciprocal_rank_fusion(
    vector_hits: list[VectorSearchHit],
    keyword_hits: list[KeywordSearchHit],
    k: int = 60,
) -> list[tuple[str, str, float]]:
    """Reciprocal Rank Fusion (Cormack, Clarke & Buettcher, 2009):
    score(chunk) = sum over each ranked list containing it of 1/(k + rank),
    where rank is the 1-indexed position within that list. k=60 is the
    paper's own default, not an invented constant.

    Returns (chunk_id, document_id, fused_score) tuples sorted descending
    by score — a plain tuple, not a shared core model, since this is an
    internal fusion step; chunk_id/document_id are the only routing info
    a caller needs to hydrate full Chunk objects afterward.
    """
    scores: dict[str, float] = {}
    document_ids: dict[str, str] = {}

    for rank, vhit in enumerate(vector_hits, start=1):
        scores[vhit.chunk_id] = scores.get(vhit.chunk_id, 0.0) + 1.0 / (k + rank)
        document_ids[vhit.chunk_id] = vhit.document_id

    for rank, khit in enumerate(keyword_hits, start=1):
        scores[khit.chunk_id] = scores.get(khit.chunk_id, 0.0) + 1.0 / (k + rank)
        document_ids[khit.chunk_id] = khit.document_id

    fused = [
        (chunk_id, document_ids[chunk_id], score) for chunk_id, score in scores.items()
    ]
    fused.sort(key=lambda item: item[2], reverse=True)
    return fused
