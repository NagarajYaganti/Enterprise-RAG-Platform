from core.interfaces import Reranker
from core.models import ScoredChunk
from sentence_transformers import CrossEncoder


class CrossEncoderReranker(Reranker):
    """Local/open Reranker adapter via sentence-transformers' CrossEncoder.
    model_id is never hardcoded — it must come from config/models.yaml.

    predict() returns a raw, uncalibrated relevance score for ordering
    purposes only (verified: CrossEncoder.predict's apply_softmax parameter
    defaults to False for this model family) — never treat it as a
    probability, and never conflate it with a golden eval set's relevance
    grade.
    """

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id
        self._model = CrossEncoder(model_id)

    def rerank(self, query: str, candidates: list[ScoredChunk], top_k: int) -> list[ScoredChunk]:
        if not candidates:
            return []
        pairs = [(query, candidate.chunk.text) for candidate in candidates]
        scores = self._model.predict(pairs)
        rescored = [
            candidate.model_copy(update={"score": float(score)})
            for candidate, score in zip(candidates, scores, strict=True)
        ]
        rescored.sort(key=lambda c: c.score, reverse=True)
        return rescored[:top_k]
