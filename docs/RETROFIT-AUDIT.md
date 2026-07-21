# Retrofit Audit — Phases 0–4 vs. the updated master spec

**Date:** 2026-07-21
**Scope:** Read-only audit. No code changed. Every "current state" cell below is
backed by a real file/module reference verified in this pass (`grep`/`Read`
against the actual repo), not inferred from memory or from what Phase 4's own
`docs/PROGRESS.md` claimed at merge time — a few of those claims are
contradicted by what's actually shipped (see Phase 4 rows, especially the
semantic-cache keying and NFC-normalization findings).

**Headline finding:** the two platform-wide principles added to
`docs/ARCHITECTURE.md` — the **Adaptive Policy Pattern** and the
**Global-First Principle** — are almost entirely unimplemented. `config/policies/`
does not exist. Not one of the eleven named policies (`ParserPolicy`,
`ChunkingPolicy`, `EmbeddingPolicy`, `LanguagePolicy`, `QueryPolicy`,
`RerankPolicy`, `CachePolicy`, `ContextPolicy`, `PromptPolicy`, `ModelRouter`,
`GuardrailProfile`) exists as a config-driven engine. `ModelRouter` is the
closest thing to compliant — and even it hardcodes its rules in Python and
hard-fails instead of falling back to a safe default. This is not a set of
small gaps; it is a missing structural layer that phases 0–4 were built
without, because it didn't exist in the spec version this repo was built
against.

A second, narrower but security-critical finding: **the semantic cache
(Phase 4) is keyed by `tenant_id` only, not `tenant_id` + `principals`** —
exactly the cross-user leak channel `docs/GAP-MATRIX.md`'s own row for this
capability warns about by name. This is real, already-merged, already-in-`main`
behavior, not a hypothetical.

---

## Phase 0 — Repo scaffold & foundations

| Requirement (updated spec) | Current state | Severity | Retrofit / Rewrite |
|---|---|---|---|
| 8 core interfaces (`DocumentParser`, `Chunker`, `EmbeddingProvider`, `VectorStore`, `Reranker`, `LLMProvider`, `ModelRouter`, `Guardrail`) | Present, unchanged. `libs/core/src/core/interfaces.py` | — (DONE) | — |
| Pydantic models carry `tenant_id` | Present. `libs/core/src/core/models.py` | — (DONE) | — |
| `TenantContext` middleware | Present, but its own docstring says **"INSECURE STUB... Replaced by real OIDC/JWT validation in Phase 5."** `libs/core/src/core/middleware.py` | MINOR (already tracked, explicitly scoped to Phase 5, not a new gap) | Retrofit — deferred to Phase 5 by design |
| docker-compose dev stack, CI (lint/typecheck/test) | Present and green. `infra/docker-compose.dev.yml`, `.github/workflows/ci.yml` | — (DONE) | — |
| **NEW: structural scaffolding for the Adaptive Policy Pattern** (a shared "compute profile → evaluate config rules → log decision → fallback" mechanism; a `config/policies/` directory) | ~~**ABSENT.**~~ **CLOSED (retrofit/phase-0, 2026-07-21).** `libs/core/src/core/policy_engine.py`'s `evaluate_policy()`/`load_policy_rules()` (function-based, mirroring `model_registry.py`'s idiom, not a new ABC — a policy is pure computation, not a stateful adapter). 8 comparators, AND-within-rule, first-match-wins, never raises (missing file / malformed YAML / unknown comparator all safely fall back), every call logs a structured `policy_engine.decision` line. `libs/core/src/core/models.py`'s `PolicyDecision` is the fixed output shape. `config/policies/README.md` documents the schema. 17 tests, `tests/unit/libs/core/test_policy_engine.py` + 3 in `test_models.py`. No concrete named policy (ChunkingPolicy, etc.) was built here — those remain their own phases' retrofit items, now unblocked. | **BLOCKER → CLOSED** | Done |
| `config/tenants/` per-tenant config schema | Directory exists but is **empty** — no schema files, no per-tenant policy overrides possible yet | MAJOR (blocks `GuardrailProfile`'s "per tenant" requirement and Phase 5's jurisdiction profiles) | Retrofit, but naturally lands with Phase 5 — **not part of the Phase 0 retrofit**, unchanged |

---

## Phase 1 — Ingestion & preprocessing

| Requirement (updated spec) | Current state | Severity | Retrofit / Rewrite |
|---|---|---|---|
| **ParserPolicy** (adaptive): probe text-layer/DPI/script/size, route to native-extract / local OCR / cloud-OCR-gated-by-residency, log decision | ~~**ABSENT.** Parser selection in `services/ingestion` is a static mime-type dispatch~~ **CLOSED (retrofit/phase-1, 2026-07-21).** New `libs/connectors/src/connectors/parser_policy.py` (`decide_parser_route`) + `config/policies/parser.yaml`, consulted by `worker.process_document` before `ParserRegistry.for_mime_type`. **Scope note, stated not silently dropped**: routes among parsers that already exist (unstructured/ocr/stt/email/plain_text); no cloud-OCR-gated-by-residency adapter exists in this codebase at all, so there is nothing to gate residency-wise yet. | **BLOCKER → CLOSED** | Done |
| **ChunkingPolicy** (adaptive): profile documents, rules-engine-select strategy+size+overlap, log decision, fallback to fixed-size | ~~**ABSENT.** `worker.py:74` hardcodes `chunker = StructureAwareChunker()` for every document~~ **CLOSED (retrofit/phase-1, 2026-07-21).** New `services/preprocessing/src/preprocessing/chunking_policy.py` + `config/policies/chunking.yaml`; `worker._build_chunker` now routes via the policy's outcome, proven end-to-end via an observable chunk-metadata difference between the two chunkers. | **BLOCKER → CLOSED** | Done |
| Chunk sizes **token-based**, never character-based | ~~**WRONG.** `FixedSizeChunker.chunk()` slices by character count~~ **CLOSED (retrofit/phase-1, 2026-07-21).** `FixedSizeChunker` now slices via `tiktoken`'s `cl100k_base` encoding (new shared `preprocessing.tokenization` module). Verified empirically: Arabic/Hindi/Chinese fixtures show markedly higher tokens-per-character than English, correctly reflecting the density difference the spec names. Stated assumption: `tiktoken`'s vocabulary isn't identical to `BAAI/bge-small-en-v1.5`'s own tokenizer — a practical proxy, not an exact match. | **BLOCKER → CLOSED** | Done |
| **LanguagePolicy**: per-**section** language detection (documents mix languages), not per-file | ~~**WRONG granularity.** `pipeline.py:21` detects once on the whole document~~ **CLOSED (retrofit/phase-1, 2026-07-21).** `pipeline.run_pipeline` now detects language per structural element; `structure_aware.py`'s section grouping uses a length-weighted vote so a short heading can't outvote a long paragraph in a different language. Proven by `tests/integration/test_multilingual_ingestion.py`'s mixed English/Arabic document test. | **BLOCKER → CLOSED** | Done |
| Translate-then-embed: **translation stored ALONGSIDE the original**, original never replaced, citations point to original | ~~**WRONG.** `pipeline.py:24-28` discards the original `raw_text`~~ **CLOSED (retrofit/phase-1, 2026-07-21).** New `Chunk.original_text` field, set only when translation actually ran; `pipeline.py`'s translation branch now splits explicit-`target_language` (always honored) vs. implicit `LanguagePolicy`-driven (safety-gated on the translator's output actually differing) paths. `Translator` itself remains the pre-existing no-op stub — unchanged, already-accepted scope boundary. | **BLOCKER → CLOSED** | Done |
| RTL text preserved end-to-end | ~~No RTL-specific handling found; zero test evidence~~ **CLOSED (retrofit/phase-1, 2026-07-21).** Real Arabic/Chinese/Hindi fixtures + a mixed English/Arabic document now prove this end-to-end through the real `/v1/documents` API (`tests/integration/test_multilingual_ingestion.py`), not assumed. | MAJOR → **CLOSED** | Done |
| Locale-aware metadata (dates/numbers/currency parsed per locale, explicit timezone) | Not verified present — `metadata.py` extracts source/mime/language/dates/page-refs but no locale-aware date/currency parsing library (e.g. `babel`) is referenced anywhere | MAJOR | **Explicitly out of scope for this retrofit pass** (not part of the approved PLAN v2's 12 items) — a separate, addable NLP feature not blocking anything else in this backlog; still open |
| Archives (ZIP with recursion + zip-bomb limits) | **ABSENT.** No `zipfile`/archive handling anywhere in `services` or `libs` | **BLOCKER** | **User-confirmed deferral to a dedicated follow-up** (2026-07-21) — architecturally a new feature (per-member sub-document tracking, recursive re-entry into the pipeline, zip-bomb limits), not a fix to existing broken behavior; still open |
| Embedded objects (images inside DOCX, attachments inside emails), recursive with depth limit | **ABSENT** — no recursive-parsing code found | MAJOR | **Deferred alongside archive handling** (builds on the same patterns) — still open |
| Encoding detection (chardet-style) for plain text/CSV/JSON/XML | ~~**ABSENT.** No `chardet`/`charset_normalizer` import anywhere~~ **CLOSED (retrofit/phase-1, 2026-07-21).** New `PlainTextParser` (`libs/connectors/src/connectors/parsers/plain_text_parser.py`) tries UTF-8 strict first, then `charset_normalizer.from_bytes(...).best()`, then a lossy last resort — proven against a real windows-1252-encoded legacy fixture. | MAJOR → **CLOSED** | Done |
| Unicode **NFC** normalization | ~~**WRONG FORM.** `cleaning.py:10` calls `unicodedata.normalize("NFKC", text)`~~ **CLOSED (retrofit/phase-1, 2026-07-21).** Changed to `"NFC"`. | MAJOR → **CLOSED** | Done |
| Distinct terminal statuses: `QUARANTINED` (password-protected), `FAILED_PARSE` (corrupt, with reason), `UNSUPPORTED` (unknown format) — ingestion never crashes | ~~**ABSENT.** Every failure mode collapsed into generic `"FAILED"`~~ **CLOSED (retrofit/phase-1, 2026-07-21).** `DocumentStatus` gained the 3 new members; `Document.failure_reason` added. **A more severe bug than originally characterized, found during planning and fixed here**: `process_document`'s download/parse step had NO try/except at all — any parsing exception left the document stuck at `UPLOADED` forever, worse than "collapses to generic FAILED." Fixed by restructuring so download/parse runs inside error handling, classifying into QUARANTINED/UNSUPPORTED/FAILED_PARSE. | **BLOCKER → CLOSED** | Done |
| Unknown format → graceful `UNSUPPORTED` via a parser plugin registry | ~~**ABSENT** — no plugin-registry mechanism~~ **CLOSED (retrofit/phase-1, 2026-07-21).** `ParserPolicy`'s fallback route resolves an unmapped mime type to `UNSUPPORTED` before `ParserRegistry` is ever reached, so an unmapped mime type never crashes the job. | **BLOCKER → CLOSED** | Done |
| Oversized files → streaming/chunked parsing with a size ceiling | Not verified present — no size-ceiling check found | MAJOR | **PARTIALLY CLOSED (retrofit/phase-1, 2026-07-21).** New `IngestionSettings.max_document_size_bytes` (default 50MB, stated ASSUMPTION) + `storage.get_object_size()` (a `HEAD` request checked before any download) reject oversized files as `UNSUPPORTED`. True streaming/chunked parsing (re-architecting each parser to consume input incrementally) remains explicitly deferred — this is a reject ceiling, not streaming. |
| Multilingual test fixtures: Arabic RTL, Chinese, Hindi, mixed-language | ~~**ABSENT.**~~ **CLOSED (retrofit/phase-1, 2026-07-21).** Real `sample_arabic.txt`/`sample_chinese.txt`/`sample_hindi.txt`/`sample_mixed_en_ar.html`, generated via the committed `generate_fixtures.py` script (per CLAUDE.md's "no fabricated fixtures" rule), proven through `tests/integration/test_multilingual_ingestion.py`. | **BLOCKER → CLOSED** | Done |
| Source connectors + **incremental sync** + **deletion propagation** + **source ACL capture** | **Well built.** `SourceConnector` ABC (`libs/core/src/core/interfaces.py:80`), `SharePointConnector` (delta-based incremental sync, `list_deletions()`, ACL principal extraction — `libs/connectors/src/connectors/sources/sharepoint_connector.py`), `BlobConnector` (LastModified-based incremental + listing-diff deletion — `.../blob_connector.py`). Genuinely one of the strongest areas in the audit. | — (DONE, as a library) | — |
| ...but is any of it **wired into a running service**? | ~~**NO.** No scheduled job, no admin endpoint, nothing calls these connectors outside their own unit tests.~~ **CLOSED (retrofit/phase-1, 2026-07-21).** New `services/ingestion/src/ingestion/sync.py` (`run_sync()`, sharing dedupe/policy/persistence logic with `process_document` via extracted `process_parsed_document()`) + `POST /v1/sync/{connector_name}` (blob only — SharePoint has no real Graph credentials in this environment, disclosed rather than guessed). Proven against real MinIO both at the function level and through the real HTTP endpoint. | MAJOR → **CLOSED** | Done |

---

## Phase 2 — Embeddings & vector store

| Requirement (updated spec) | Current state | Severity | Retrofit / Rewrite |
|---|---|---|---|
| **EmbeddingPolicy** (adaptive): route each chunk to an embedding model by language/content-type/domain, via config rules; one model per collection | **ABSENT.** A single embedding model (`get_default_embedding_model()`) is used uniformly for every chunk in every tenant — no per-chunk routing, no config rules. | **BLOCKER** | Retrofit: policy layer in front of the existing `EmbeddingProvider` adapters |
| Embedding provider adapters (local + OpenAI + Cohere), batching/retry/rate-limit | Present. DONE per Phase 2's own exit checklist and this session's spot-check. | — | — |
| Embedding versioning (`model_id`+`model_version` per record, re-embed pipeline) | Present (`EmbeddingRecord`, cutover/re-embed worker path). DONE. | — | — |
| `VectorStore` adapters (Qdrant primary, pgvector fallback), tenant-enforced payload filtering | Present. DONE. | — | — |
| ACL payloads on vector records, **pre-filtered** search (not post-filtered) | Present (`acl_principals` + `MatchAny` pre-filter in `QdrantVectorStore.search`). DONE. | — | — |
| **Hard-delete across all stores — "one API," tested** | **Foundation present, wiring absent.** `libs/connectors/src/connectors/erasure.py`'s `ErasureService` is a well-designed hook registry (`register(name, hook)` + `erase_document()`), explicitly built with cache-hook extensibility in mind ("Adding one later, e.g. Phase 4's semantic cache, is a single `register()` call"). Individual per-store `delete()` methods exist (`QdrantVectorStore.delete`, `OpenSearchIndex.delete`, `ChunkRepository.hard_delete`/`hard_delete_for_document`). **But `ErasureService` is never instantiated anywhere in `services/`** — no hooks are ever registered, and **`services/ingestion/src/ingestion/api.py` has no DELETE endpoint at all** (only `POST /` and `GET /{document_id}`). The "one API" outcome the Phase 2 task text describes was never actually built. | **BLOCKER** | Retrofit, not rewrite: construct `ErasureService`, register the already-existing per-store hooks (including Phase 4's `SemanticCache.invalidate_for_document`, itself also currently unwired — see Phase 4), and expose a `DELETE /v1/documents/{id}` endpoint |
| Keyword index tenant enforcement | Present. DONE. | — | — |
| Keyword index **language-aware analyzers** (ICU/CJK-n-gram/per-language stemmers) | **ABSENT — and this predates the spec update.** `libs/connectors/src/connectors/keyword/opensearch_index.py`'s `INDEX_MAPPING` maps `"text": {"type": "text"}` with no analyzer override — every chunk in every language gets OpenSearch's default English-oriented "standard" analyzer. `language` is stored only as a `keyword` *filter* field, never used to pick an analyzer. This is the exact failure mode the (both old and new) spec names by name: "a default English analyzer on non-English text silently ruins keyword recall." | **BLOCKER** | **Partial rewrite** — changing an existing index's analyzer requires deleting and reindexing (OpenSearch cannot alter an analyzer on a live index), so this is not a purely additive retrofit |
| Embedding worker idempotency + dead-letter queue | Present, proven via a real kill-mid-batch test. DONE. | — | — |

---

## Phase 3 — Retrieval & reranking

| Requirement (updated spec) | Current state | Severity | Retrofit / Rewrite |
|---|---|---|---|
| **QueryPolicy** (adaptive): classify intent (factual/summarization/comparison/aggregation/follow-up) *before* retrieving, cheap signals first, select search mode/top_k/decompose/multi-hop per intent, rules in config, logged | **ABSENT.** `retrieval.pipeline.retrieve()` always runs the same hybrid vector+BM25 path for every query, regardless of intent. There is no branch that skips vector search for aggregation-style queries, no config-driven intent rules. | **BLOCKER** | Retrofit: a classification+routing layer in front of the existing hybrid path |
| **RerankPolicy** (adaptive): skip reranking when first-stage scores are confident/well-separated (config margin threshold), log skip/run + margins | **ABSENT.** Reranker either always runs (if configured) or never runs (if `None`) — no margin-based adaptive decision at query time. | **BLOCKER** | Retrofit |
| Hybrid retrieval (vector+BM25, RRF), metadata filters | Present. DONE. | — | — |
| Reranker adapters (local cross-encoder + Cohere gated) | Present. DONE. | — | — |
| Query understanding: multi-turn rewriting, decomposition, `ChatSession` store | Present (`retrieval.query_understanding.rewrite_query`/`decompose_query`, `ChatSessionRepository`/`ChatTurn` keyed by tenant+user+session). DONE — degrades to heuristic pass-through without a live `OPENAI_API_KEY`, an already-disclosed, unchanged scope boundary. | — | — |
| Multi-hop retrieval (optional, off by default) | Present, flagged off, proven wired when enabled. DONE per scope. | — | — |
| GraphRAG (optional, flagged off; `KnowledgeGraph` interface + extraction pipeline) | Present per scope (foundation only — extraction runs, but retrieval doesn't yet query the graph; already disclosed as deferred, not a new gap from this spec update). | — | — |
| Retrieval eval harness (recall@k/MRR/nDCG, real fixture corpus) | Present, numbers actually computed and recorded. DONE. | — | — |
| Chunking auto-tuning loop (harness re-chunks eval corpus under alternative `ChunkingPolicy` rules, proposes a config diff) | **ABSENT** — has no `ChunkingPolicy` to tune in the first place. | **BLOCKER, but strictly dependent** | Cannot be built before Phase 1's `ChunkingPolicy` lands |
| p95 retrieval latency measured and recorded | Present. DONE. | — | — |

---

## Phase 4 — Orchestration, model routing & guardrails

| Requirement (updated spec) | Current state | Severity | Retrofit / Rewrite |
|---|---|---|---|
| **PromptPolicy** (adaptive): template selected by *detected* intent+domain+language, not hardcoded per endpoint | **PARTIAL.** `core.prompt_registry.get_prompt_template(type, domain, language)` is a genuine config/registry lookup, not a hardcoded per-endpoint template — that half is real. But `type`/`domain`/`language` are **caller-supplied request parameters**, not derived from an intent classifier — because `QueryPolicy` (Phase 3) doesn't exist, there is nothing to drive automatic selection. | MAJOR — mechanism present, the policy driving its inputs is not | Retrofit, blocked on `QueryPolicy` |
| **ContextPolicy** (adaptive): token budget from the routed model's context window, chunk count/order/dedupe by score, truncation logged | **ABSENT.** `orchestrator.pipeline.orchestrate()` builds `context_block` as a plain `"\n\n".join(...)` of every retrieved chunk — no token-budget check against `config/models.yaml`'s (nonexistent) context-window field, no dedupe, no truncation logic of any kind. | **BLOCKER** — a real correctness/availability risk: nothing stops an oversized context from erroring against the actual LLM API | Retrofit |
| **GuardrailProfile** (adaptive): strictness tier selected **per tenant/domain at runtime from config**, not compiled in | **WRONG — the literal anti-pattern the spec names.** `libs/connectors/src/connectors/guardrails/output_policy_guardrail.py`'s `DOMAIN_POLICIES` is a hardcoded Python `dict` literal (only `"healthcare"` populated) — "compiled in," not config-driven, and not tenant-configurable at all. | **BLOCKER** | Retrofit: move `DOMAIN_POLICIES` to `config/policies/guardrail-profile.yaml`, keyed by tenant+domain |
| **CachePolicy** (adaptive): semantic-cache similarity threshold varies by query intent (tight for factual, disabled for reasoning-heavy) | **ABSENT.** `OrchestratorSettings.cache_similarity_threshold` (`services/orchestrator/src/orchestrator/settings.py:22`) is one single global float (0.95) for every query regardless of intent. | MAJOR — depends on `QueryPolicy` to be meaningful | Retrofit, blocked on `QueryPolicy` |
| Prompt template registry (YAML, versioned, variables schema, domain packs) | Present. DONE. (`config/prompts/{common,bfsi,retail,healthcare}`) | — | — |
| **ModelRouter**: rules engine over `config/models.yaml`, never hardcoded model names | **PARTIAL.** No model id is ever hardcoded — genuinely true, verified. But the *routing rules themselves* (language match, budget filter, cost-sort-ascending-vs-descending by complexity) are hardcoded Python control flow in `services/orchestrator/src/orchestrator/model_router.py`, not declarative `config/policies/*.yaml` rules. It also **raises `ModelNotFoundError`** (a hard failure) when nothing fits, rather than "fall back to a safe default — never fail the request over strategy selection" as the Adaptive Policy Pattern explicitly requires. It does correctly log the decision + candidates considered. | MAJOR — closest-to-compliant of all eleven policies, still non-compliant on two explicit requirements | Retrofit: externalize the rule logic; add a configured safe-default fallback model instead of raising |
| `LLMProvider` adapters: OpenAI + Anthropic + self-hosted/OSS via OpenAI-compatible endpoint | Present (`OpenAIChatProvider`, `AnthropicProvider`, `base_url` param for vLLM/Ollama). DONE — self-hosted path never exercised against a real server, an already-disclosed stated assumption. | — | — |
| Token usage captured per call per tenant | Present (`TokenUsageRepository`). DONE. | — | — |
| **Response language**: answer in the query's language by default, even when chunks are in other languages; citations still point to original-language chunks | **ABSENT.** No language detection runs on the incoming query anywhere in `orchestrator.pipeline.orchestrate()` or `api.py` — the `language` request field defaults to `"en"` and must be supplied correctly by the caller. No prompt template contains an explicit "respond in the query's language" instruction. The fixed `REFUSAL_TEXT` fallback is a single hardcoded English sentence regardless of query language. | **BLOCKER** | Retrofit: detect query language (reuse `preprocessing.language_detect`), thread it through, add the instruction to templates, add per-language refusal text |
| Guardrails work **across languages**: per-locale PII recognizers, injection screening not English-only | **ABSENT.** `PresidioGuardrail` is constructed in `main.py` with no `language` argument, defaulting to `language="en"` with a single `en_core_web_sm` model — no per-locale recognizer routing exists. `PromptInjectionGuardrail`'s 6 patterns (`libs/connectors/src/connectors/guardrails/prompt_injection_guardrail.py`) are all English-phrase regexes ("ignore previous instructions", "DAN mode", etc.) — a non-English injection attempt would pass through undetected. | **BLOCKER** — a real, currently-shipping PII/security gap for any non-English tenant | Retrofit: multi-language Presidio config (`NlpEngineProvider` supports multiple `{lang_code, model_name}` pairs) + translated/localized injection pattern sets |
| Grounding: citation validation, refuse-when-absent | **Present and solid.** `orchestrator.citations.check_citations()`, `REFUSAL_TEXT` fallback for ungrounded/hallucinated answers, zero-retrieved-chunks short-circuit. Verified this session against 17 real adversarial queries plus a real end-to-end test suite (`tests/integration/test_orchestrator_e2e.py`). | — (DONE) | — |
| Guardrails: PII / injection / output-policy, both input and output | Present as a mechanism (`GuardrailPipeline` composing 3 real adapters at both stages). DONE for English; see the per-locale BLOCKER above for the language gap specifically (not double-counted here). | — | — |
| **Agentic RAG**: plan → select retrieval strategy per sub-question → execute → synthesize loop; max-iteration budget; per-tool caller-scoped permissions; human-approval gate; full trace logging | **PARTIAL, already disclosed in `docs/PROGRESS.md`.** `ToolRuntime` (`services/orchestrator/src/orchestrator/agent/tool_runtime.py`) genuinely provides: a max-iteration cap, principals passed to `Tool.run()` (never a super-user's), a human-approval halt/resume gate (`AgentStep.requires_approval`/`approved_by`), and step-level trace records (`AgentTrace`). This is real, tested infrastructure that satisfies OWASP "Excessive Agency" 's *gating* concern. But: **zero concrete `Tool` implementations exist**, there is **no autonomous plan→execute→synthesize loop** (`ToolRuntime` explicitly, by its own docstring, only executes one caller-chosen tool call at a time and never decides what to call next), and `AgentTrace`/`AgentStep` are **in-memory only** (a plain dict on `app.state`), not durable. Phase 4's own exit checklist does not test the full loop, so this was not a regression against that checklist — but it is a real gap against the TASKS text. | MAJOR (gating infra solid; the actual agentic *feature* doesn't exist yet) | This is closer to **new-build** than retrofit — the loop itself doesn't exist to retrofit |
| **Semantic cache keyed by tenant AND principals** | **WRONG — a real, currently-shipped security gap.** `SemanticCache.get(tenant_id, query_vector)` / `.put(tenant_id, ...)` (`services/orchestrator/src/orchestrator/semantic_cache.py:53,80`) key and filter **only on `tenant_id`**. Two different users in the *same* tenant with *different* document-level ACL principals can receive each other's cached answers — including an answer grounded in a document one of them has no access to. This is exactly the "cross-user leak channel" `docs/GAP-MATRIX.md`'s own row for this capability names. | **BLOCKER — security-critical, ship-stopping** | Retrofit: add `principals` to the Qdrant payload and to the `get()` filter (`MatchAny`, mirroring the existing ACL pre-filter pattern already used in `QdrantVectorStore.search`) |
| Semantic cache TTL + invalidation on document updates/deletes | TTL present (`created_at` + `DatetimeRange` filter). `invalidate_for_document()` **exists but is never called anywhere outside its own file** — same wiring gap as Phase 2's `ErasureService` (see above); nothing registers it as an erasure hook. | **BLOCKER** (ties directly to the Phase 2 erasure-wiring gap — one fix covers both) | Retrofit |

---

## Ordered retrofit backlog

Numbered in build order. Items at the same number have no ordering dependency
on each other and can proceed in parallel.

### 1 — Do first, independently of everything else (active risk, no dependencies)
1. **Semantic-cache principal-keying fix** (Phase 4 BLOCKER). This is a live cross-user data leak in already-merged code. Fix: add `principals` to `SemanticCache.get`/`.put` and the Qdrant filter.
2. **Erasure wiring**: instantiate `ErasureService`, register the existing per-store `delete()`/`invalidate_for_document()` hooks, add `DELETE /v1/documents/{id}`. Covers both the Phase 2 "one API" gap and the Phase 4 cache-invalidation-on-delete gap in one piece of work.
3. **NFC vs NFKC fix** — a one-line change (`cleaning.py`), zero dependencies, currently silently altering text.
4. **Per-locale guardrails** (Presidio multi-language config + localized injection patterns) — additive, no dependency on the policy-engine work below.
5. **Response-language handling** (detect query language, thread it through, add the template instruction) — additive.

### 2 — Foundational: the shared Policy-engine mechanism
6. ~~**Build the Adaptive Policy Pattern's shared scaffolding once**, in `libs/core` (or a new `libs/policy`): a generic "profile in → evaluate `config/policies/<name>.yaml` rules → log decision → fallback" helper, used by all eleven named policies rather than reimplemented eleven times. This is the single highest-leverage item in this backlog — nearly every other BLOCKER above that says "ABSENT" for a `*Policy` is waiting on this.**~~ **CLOSED (retrofit/phase-0, 2026-07-21)** — `core.policy_engine.evaluate_policy()`. Items 7–28 below that depend on this are now unblocked.

### 3 — Chunking correctness, before ChunkingPolicy can be honestly built
7. ~~**Token-based chunk sizing** in `FixedSizeChunker`~~ **CLOSED (retrofit/phase-1, 2026-07-21).**
8. ~~**`ChunkingPolicy`** (depends on 6, 7)~~ **CLOSED (retrofit/phase-1, 2026-07-21).**
9. ~~**Per-section `LanguagePolicy`** (depends on 6)~~ **CLOSED (retrofit/phase-1, 2026-07-21).**
10. **Chunking auto-tuning loop** (Phase 3) — strictly blocked on 8; unblocked now, but still Phase 3's own item, not built here.

### 4 — Remaining phase-1 robustness items (parallelizable, no cross-dependencies)
11. Archive/ZIP parsing (new `DocumentParser` adapter) — **user-confirmed deferral to a dedicated follow-up** (2026-07-21), still open.
12. Embedded-object recursive parsing — **deferred alongside item 11**, still open.
13. ~~Encoding detection (chardet-style)~~ **CLOSED (retrofit/phase-1, 2026-07-21)** — via `PlainTextParser`'s `charset_normalizer` fallback.
14. ~~Differentiated terminal statuses (`QUARANTINED`/`FAILED_PARSE`/`UNSUPPORTED`) + unknown-format plugin registry~~ **CLOSED (retrofit/phase-1, 2026-07-21).**
15. ~~Real RTL/Arabic/Hindi/Chinese/mixed-language test fixtures~~ **CLOSED (retrofit/phase-1, 2026-07-21).**
16. ~~Translate-then-embed original-text preservation~~ **CLOSED (retrofit/phase-1, 2026-07-21)** — landed as `Chunk.original_text` (whole-document granularity, a stated limitation since translation runs once over the whole document before chunking).
17. ~~Wire the already-correct `SharePointConnector`/`BlobConnector` into an actual sync job/endpoint~~ **CLOSED (retrofit/phase-1, 2026-07-21)** — `ingestion.sync.run_sync()` + `POST /v1/sync/{connector_name}` (blob only; SharePoint has no real credentials in this environment).
18. Locale-aware metadata extraction — **explicitly out of scope for this retrofit pass**, still open. Oversized-file size ceiling: ~~streaming ceiling~~ **PARTIALLY CLOSED (retrofit/phase-1, 2026-07-21)** — a reject-oversized-files ceiling (`IngestionSettings.max_document_size_bytes`) is built; true streaming/chunked parsing remains open.

### 5 — Query-time and orchestration policies (depend on 6; `QueryPolicy` gates several Phase 4 items)
19. **`ParserPolicy`** (depends on 6) — can proceed independently of the chunking track.
20. **`EmbeddingPolicy`** (depends on 6).
21. **`QueryPolicy`** (depends on 6) — build this before 22–24, since they consume its intent classification.
22. **`RerankPolicy`** (depends on 6, benefits from 21 but not strictly blocked by it).
23. **`PromptPolicy`**'s automatic type/domain selection (depends on 21).
24. **`CachePolicy`**'s intent-varied threshold (depends on 21).
25. **`ContextPolicy`** (depends on 6; independent of `QueryPolicy`) — token-budget-aware context assembly in `orchestrator.pipeline.orchestrate()`.
26. **`GuardrailProfile`** (depends on 6) — move `DOMAIN_POLICIES` to tenant/domain-configurable YAML.
27. **`ModelRouter`** hardening: externalize rules to config, add a configured safe-default fallback instead of raising.
28. **Language-aware OpenSearch analyzers** (Phase 2) — requires an index rebuild/reindex, not a pure retrofit; schedule as a maintenance window, ideally once 9/`LanguagePolicy` exists to decide per-language analyzer choice, though it can technically be done with a static language→analyzer map sooner if this needs to move faster than the rest of the policy track.

### 6 — Largest, most speculative item last
29. **Agentic RAG's autonomous loop** (plan → select retrieval per sub-question → execute → synthesize) plus at least one concrete `Tool` implementation and durable (Postgres-backed) trace storage. This is a new feature build, not a retrofit of existing code, and everything else in this backlog is higher-leverage per unit of effort — do this last.

---

*This report changed no code. Every row above is either directly quoted file/line
evidence or explicitly marked "not verified present" where evidence could not
be found — per this project's own anti-hallucination rule, absence of a grep
hit is treated as absence of the feature, not silently assumed to exist
elsewhere.*
