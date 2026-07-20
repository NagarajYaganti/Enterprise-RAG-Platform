import math
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class GoldenQuery:
    """One human-authored eval-set entry: a query and the chunk ids a human
    judged relevant to it. Binary relevance (relevant or not), per Section
    4 Phase 3's "queries + relevant chunk ids, human-authored" task text.
    """

    query: str
    relevant_chunk_ids: list[str]


def recall_at_k(retrieved_chunk_ids: list[str], relevant_chunk_ids: list[str], k: int) -> float:
    if not relevant_chunk_ids:
        return 0.0
    relevant_set = set(relevant_chunk_ids)
    hit_count = len(set(retrieved_chunk_ids[:k]) & relevant_set)
    return hit_count / len(relevant_set)


def mrr(retrieved_chunk_ids: list[str], relevant_chunk_ids: list[str]) -> float:
    relevant_set = set(relevant_chunk_ids)
    for rank, chunk_id in enumerate(retrieved_chunk_ids, start=1):
        if chunk_id in relevant_set:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved_chunk_ids: list[str], relevant_chunk_ids: list[str], k: int) -> float:
    """Standard nDCG@k with binary relevance. IDCG is the DCG of the ideal
    ranking (all relevant chunks first, up to k) — the only ceiling that
    makes nDCG a 0..1 normalized score.
    """
    relevant_set = set(relevant_chunk_ids)
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, chunk_id in enumerate(retrieved_chunk_ids[:k], start=1)
        if chunk_id in relevant_set
    )
    ideal_hits = min(len(relevant_set), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


def run_harness(
    golden_queries: list[GoldenQuery],
    retrieve_fn: Callable[[str], list[str]],
    k: int = 5,
) -> dict[str, float]:
    """retrieve_fn(query_text) -> ranked list of chunk_ids from a real
    retrieval pipeline. Averages recall@k, MRR, nDCG@k across every golden
    query. THESE NUMBERS COME FROM RUNNING THIS FUNCTION — never hardcode
    or report metrics that weren't actually computed here, per CLAUDE.md.
    """
    recalls: list[float] = []
    mrrs: list[float] = []
    ndcgs: list[float] = []
    for golden_query in golden_queries:
        retrieved = retrieve_fn(golden_query.query)
        recalls.append(recall_at_k(retrieved, golden_query.relevant_chunk_ids, k))
        mrrs.append(mrr(retrieved, golden_query.relevant_chunk_ids))
        ndcgs.append(ndcg_at_k(retrieved, golden_query.relevant_chunk_ids, k))

    n = len(golden_queries)
    return {
        f"recall@{k}": sum(recalls) / n if n else 0.0,
        "mrr": sum(mrrs) / n if n else 0.0,
        f"ndcg@{k}": sum(ndcgs) / n if n else 0.0,
    }
