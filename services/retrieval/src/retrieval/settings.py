from pydantic_settings import BaseSettings, SettingsConfigDict


class RetrievalSettings(BaseSettings):
    """multi_hop_enabled/graphrag_enabled: config flags, off by default per
    Section 4 Phase 3 task text ("config flag, off by default" /
    "optional, flagged OFF"). rrf_k: the Reciprocal Rank Fusion constant
    from Cormack, Clarke & Buettcher (2009) — their own paper's default,
    not an invented number. candidate_pool_size: how many results each of
    vector/keyword search retrieves BEFORE fusion/rerank narrows down to
    default_top_k — must exceed default_top_k or RRF/reranking have
    nothing extra to reorder.
    """

    model_config = SettingsConfigDict(env_prefix="")

    multi_hop_enabled: bool = False
    graphrag_enabled: bool = False
    rrf_k: int = 60
    candidate_pool_size: int = 50
    default_top_k: int = 10
