from pydantic_settings import BaseSettings, SettingsConfigDict


class OrchestratorSettings(BaseSettings):
    """agent_mode_enabled: global flag gating whether the agent runtime is
    even constructed (Plan v2 §A.11) — availability, not per-call use; a
    request must also explicitly opt in with use_agent=True. semantic_cache
    _enabled: on by default (a pure latency/cost optimization, not a
    correctness risk, given the tenant+principal pre-filter discipline in
    semantic_cache.py). cache_ttl_seconds: enforced via a stored created_at
    payload field and a DatetimeRange filter at lookup — Qdrant has no
    native point-TTL feature (verified, not invented). complexity_length
    _threshold: the stated heuristic constant for assess_complexity (Plan
    v2 §A.6) — a query longer than this, or with more than one decomposed
    sub-question, is "complex".
    """

    model_config = SettingsConfigDict(env_prefix="")

    agent_mode_enabled: bool = False
    semantic_cache_enabled: bool = True
    cache_similarity_threshold: float = 0.95
    cache_ttl_seconds: int = 3600
    complexity_length_threshold: int = 200
    # Phase-4 addition: default ModelRouter budget ceiling
    # (cost_per_1k_tokens) when a caller/tenant doesn't specify one — set
    # above gpt-5.6-luna/claude-haiku-4-5 (0.001) but below claude-sonnet-5
    # (0.003) is NOT assumed; 0.01 simply admits every currently-registered
    # generation model so routing degrades to pure complexity-based choice
    # by default, per the Plan v2 §A.7 "budget ceiling" design.
    default_budget_cost_per_1k_tokens: float = 0.01
