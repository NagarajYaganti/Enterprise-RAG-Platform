import pytest
from connectors.embeddings.sentence_transformers_provider import SentenceTransformersProvider

MODEL_ID = "BAAI/bge-small-en-v1.5"


@pytest.fixture(scope="module")
def provider() -> SentenceTransformersProvider:
    return SentenceTransformersProvider(MODEL_ID)


def test_embed_returns_one_vector_per_text(provider: SentenceTransformersProvider) -> None:
    vectors = provider.embed(["hello world", "quarterly earnings report"], MODEL_ID)

    assert len(vectors) == 2
    assert all(len(v) == 384 for v in vectors)
    assert all(isinstance(x, float) for v in vectors for x in v)


def test_dimension_matches_confirmed_bge_small_size(
    provider: SentenceTransformersProvider,
) -> None:
    assert provider.dimension() == 384


def test_embed_rejects_mismatched_model_id(provider: SentenceTransformersProvider) -> None:
    with pytest.raises(ValueError):
        provider.embed(["hello"], "some-other-model")


def test_similar_texts_have_higher_cosine_similarity_than_dissimilar(
    provider: SentenceTransformersProvider,
) -> None:
    import numpy as np

    a, b, c = provider.embed(
        ["quarterly earnings report", "quarterly earnings summary", "a recipe for pancakes"],
        MODEL_ID,
    )
    sim_ab = np.dot(a, b)
    sim_ac = np.dot(a, c)
    assert sim_ab > sim_ac
