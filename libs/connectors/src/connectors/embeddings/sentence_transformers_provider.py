from core.interfaces import EmbeddingProvider
from core.models import Vector
from sentence_transformers import SentenceTransformer


class SentenceTransformersProvider(EmbeddingProvider):
    """Local/open EmbeddingProvider adapter via sentence-transformers.
    model_id is never hardcoded — it must come from config/models.yaml.
    """

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id
        self._model = SentenceTransformer(model_id)

    def dimension(self) -> int:
        return int(self._model.get_embedding_dimension())

    def embed(self, texts: list[str], model_id: str) -> list[Vector]:
        if model_id != self._model_id:
            raise ValueError(
                f"provider configured for model_id={self._model_id!r}, got {model_id!r}"
            )
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return [embedding.tolist() for embedding in embeddings]
