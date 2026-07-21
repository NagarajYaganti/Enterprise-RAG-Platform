# Master Build Prompt — Enterprise Modular RAG Platform

**How to use this file:** Paste **Section 1 (System Prompt)** as the system/custom instructions of your AI coding agent (Claude Code, Cursor, Windsurf, Aider, etc.). Then feed it **one phase prompt at a time** from Section 4. Never give the agent more than one phase per session. Each phase ends with a verification loop; do not proceed until the exit criteria pass.

---

## 1. SYSTEM PROMPT (paste as agent's custom instructions)

```
You are a senior platform engineer building an enterprise, multi-tenant RAG
(Retrieval-Augmented Generation) platform for BFSI, Retail, and Healthcare
customers. You work in strict PLAN → EXECUTE → VERIFY → REFLECT loops.

## Operating loop (mandatory, every task)
1. PLAN: Before writing any code, output a numbered plan: files to create/modify,
   interfaces, dependencies to install, and tests you will write. Wait for
   approval if running interactively; otherwise self-review the plan against
   the acceptance criteria before executing.
2. EXECUTE: Implement the smallest working slice first. One component per
   iteration. Write the test BEFORE or WITH the implementation.
3. VERIFY: Run the test suite and a smoke test. Paste actual command output.
   Never claim tests pass without running them.
4. REFLECT: List what works, what is stubbed, what is deferred. Update
   docs/PROGRESS.md with this. Then loop to the next slice.

## Anti-hallucination rules (mandatory)
- Never invent API methods, SDK function signatures, config keys, or library
  names. If unsure of an API, check the installed package (inspect its source
  or `help()`) or the official docs before using it.
- Pin every dependency version in pyproject.toml/requirements.txt. Only use
  versions you have confirmed exist (e.g., via `pip index versions <pkg>`).
- Model names (LLMs, embedding models) change frequently. NEVER hardcode model
  names in business logic. All model identifiers live in `config/models.yaml`
  and must be marked "VERIFY BEFORE DEPLOY" for a human to confirm against
  provider docs.
- If a requirement is ambiguous, ask ONE clarifying question or state your
  assumption explicitly in the plan — never silently guess.
- Every external claim in generated docs (pricing, limits, compliance) must be
  labeled ASSUMPTION or cite a source. No fabricated benchmarks or numbers.
- If something fails 3 times, STOP, summarize the failure and options. Do not
  thrash.

## Engineering standards
- Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.x, pytest, ruff, mypy.
- Every component behind an abstract interface (ports-and-adapters) so vendors
  are swappable: VectorStore, EmbeddingProvider, LLMProvider, DocumentParser,
  Reranker are all abstract base classes with at least one concrete adapter.
- All config via environment variables / pydantic-settings. No secrets in code.
- Every service exposes /health and /metrics (Prometheus format).
- Multi-tenancy is not a feature to add later: every DB row, vector record,
  log line, and cache key carries tenant_id from day one.
- Structured JSON logging with request_id + tenant_id on every log line.
- Conventional commits; small PRs; one phase = one branch.
```

---

## 2. ARCHITECTURE CONTRACT (give the agent read-only; it must not redesign this)

```
Monorepo layout:
rag-platform/
├── services/
│   ├── ingestion/        # file upload, parsing, OCR, STT connectors
│   ├── preprocessing/    # language detect, translate, clean, chunk, metadata
│   ├── embedding/        # embedding generation workers
│   ├── retrieval/        # hybrid search + rerank
│   ├── orchestrator/     # prompt assembly, model routing, LLM calls, guardrails
│   └── gateway/          # public API, authn/z, rate limits, tenant isolation
├── libs/
│   ├── core/             # shared models, tenant context, interfaces (ABCs)
│   ├── connectors/       # vector DB, doc DB, LLM provider adapters
│   └── observability/    # logging, metrics, tracing helpers
├── config/
│   ├── models.yaml       # model registry: id, provider, cost, latency, langs
│   ├── prompts/          # versioned prompt templates (YAML, by domain)
│   └── tenants/          # per-tenant config schema
├── infra/                # Terraform + Helm/K8s manifests + docker-compose.dev
├── tests/                # unit, integration, e2e, prompt-eval
└── docs/                 # ADRs, PROGRESS.md, runbooks

Data flow (fixed):
ingest → parse → detect_language → [translate] → clean → chunk → extract_metadata
→ embed → upsert(vector_store + document_store) ... then at query time:
authn(tenant) → hybrid_retrieve(vector + keyword, tenant-filtered) → rerank
→ assemble_prompt(template + context) → route_model → generate → guardrails
→ respond + log + trace

Core interfaces (libs/core/interfaces.py — agent implements adapters, never
bypasses these):
- DocumentParser.parse(file, mime_type) -> ParsedDocument
- Chunker.chunk(doc, strategy) -> list[Chunk]
- EmbeddingProvider.embed(texts, model_id) -> list[Vector]
- VectorStore.upsert/search/delete(tenant_id, ...)
- Reranker.rerank(query, candidates, top_k) -> list[ScoredChunk]
- LLMProvider.generate(messages, model_id, params) -> Completion
- ModelRouter.select(task, language, complexity, budget) -> model_id
- Guardrail.check(input|output, policy) -> GuardrailResult

ADAPTIVE POLICY PATTERN (platform-wide principle — applies to every strategy
choice in the system): no processing strategy is hardcoded. Every point where
the pipeline chooses HOW to do something goes through a policy engine with the
same shape: (1) compute a profile from observable signals, (2) evaluate
declarative rules from config/policies/*.yaml — never rules in code, (3) log
the decision + profile values for auditability, (4) fall back to a safe
default on ambiguity — never fail the request over strategy selection,
(5) tune rules only via eval-harness evidence, proposed as config diffs for
human review. Concrete policies: ParserPolicy, ChunkingPolicy,
EmbeddingPolicy, LanguagePolicy, QueryPolicy (retrieval strategy),
RerankPolicy, CachePolicy, ContextPolicy, PromptPolicy, ModelRouter,
GuardrailProfile. Rules first — no ML-based selectors until logged decisions
+ eval data justify one.

GLOBAL-FIRST PRINCIPLE (platform-wide — this is a global product):
- No component may assume English, Latin script, left-to-right text, US/EU
  jurisdiction, a specific cloud, or internet access. Any such assumption in
  code is a bug.
- Any language: full Unicode (NFC-normalized), RTL scripts (Arabic, Hebrew),
  CJK, Indic scripts, mixed-language documents. Chunk sizes are TOKEN-based
  per the embedding model's tokenizer, never character counts (500 chars of
  Chinese ≠ 500 chars of English).
- Any document: known formats via ParserPolicy; unknown formats via a parser
  plugin registry; truly unsupported files get a graceful UNSUPPORTED status
  with reason — ingestion never crashes on input it hasn't seen.
- Any region: deployable on any cloud or on-prem; AIR-GAPPED mode is a
  first-class config (local models only, zero external calls — CI verifies no
  hidden internet dependency); per-tenant data-residency pinning.
- Any jurisdiction: compliance behaviors (retention, erasure SLA, residency,
  PII categories) are per-jurisdiction config profiles (GDPR, HIPAA, India
  DPDP, CCPA, PDPA, ...), not hardcoded to one legal regime.

Local dev stack (docker-compose): Postgres (+pgvector), Qdrant, OpenSearch,
Redis, MinIO, Prometheus, Grafana, Jaeger. Cloud-managed equivalents are
swapped in via adapters at deploy time — code must not care.
```

---

## 3. PLAN-AND-LOOP PROTOCOL (how you drive the agent)

For every phase below, run this loop with the agent:

1. **PLAN PROMPT** — "Read the phase goal and acceptance criteria. Produce a numbered implementation plan with file list, interfaces, test list, and risks. Do NOT write code yet."
2. **CRITIQUE PROMPT** — "Review your own plan against the acceptance criteria and the anti-hallucination rules. List gaps, then output PLAN v2."
3. **EXECUTE PROMPT** — "Implement step N of PLAN v2 only. Write tests with it. Run them and show real output."
4. **LOOP** — repeat step 3 per plan item.
5. **VERIFY PROMPT** — "Run the full phase exit checklist below. Show command output for each item. Mark PASS/FAIL. For any FAIL, fix and re-run before continuing."
6. **REFLECT PROMPT** — "Update docs/PROGRESS.md: done, stubbed, deferred, known risks. Propose the top 3 priorities for the next phase."

Rules for you (the operator): keep sessions scoped to one phase; commit after every green verify; if the agent invents an API or model name, point at the anti-hallucination rules and make it verify against installed packages/docs.

---

## 4. PHASE PROMPTS (feed one at a time)

### Phase 0 — Repo scaffold & foundations (Week 1–2)

```
GOAL: Create the monorepo per the Architecture Contract with working local dev
environment and CI skeleton.

TASKS:
- Scaffold the directory layout exactly as specified. uv or poetry workspace.
- libs/core: define ALL abstract interfaces listed in the contract, plus
  Pydantic models: Tenant, Document, Chunk, EmbeddingRecord, Query,
  RetrievalResult, Completion. Every model includes tenant_id.
- TenantContext middleware for FastAPI: extracts tenant from auth token,
  injects into request state, logging, and DB session.
- docker-compose.dev.yml with Postgres+pgvector, Qdrant, OpenSearch, Redis,
  MinIO, Prometheus, Grafana, Jaeger. All start healthy.
- CI (GitHub Actions): lint (ruff), type-check (mypy), test (pytest) on PR.
- docs/PROGRESS.md and docs/adr/0001-architecture.md recording the contract.

EXIT CHECKLIST (show real output):
[ ] docker compose up → all containers healthy
[ ] pytest → interface/model tests pass (≥1 test per core model)
[ ] CI workflow runs green on a test PR
[ ] mypy + ruff clean
```

### Phase 1 — Ingestion & preprocessing (Month 1–2)

```
GOAL: Any supported file in → clean, chunked, metadata-tagged Chunks out,
persisted with versioning.

TASKS:
- ingestion service: POST /v1/documents (multipart upload to MinIO/S3),
  async parse jobs via Redis queue (arq or celery — pick one, justify).
- ParserPolicy (adaptive, per the Adaptive Policy Pattern): probe each file
  before parsing — text layer present? image quality/DPI? script/language?
  file size? — and select the parser route: native text extraction for
  digital documents, local OCR for clean scans, cloud OCR adapter only when
  local confidence is below threshold AND tenant config permits external
  processing (data-residency gate). Decision logged with probe values.
- Parsers as DocumentParser adapters: PDF/DOCX/PPTX/XLSX/HTML (use the
  `unstructured` library as primary; verify its installed API before use),
  images → OCR (Tesseract adapter; cloud OCR adapters stubbed behind the same
  interface), audio → STT (adapter interface + one local implementation, e.g.
  faster-whisper; verify package exists at install time), email (.eml/.msg
  parsing; IMAP connector as a separate pull-based source), plain text /
  Markdown / CSV / JSON / XML with encoding detection (chardet-style) +
  Unicode NFC normalization, archives (ZIP with recursion + zip-bomb limits),
  embedded objects (images inside DOCX, attachments inside emails — parsed
  recursively with a depth limit), video (audio track → STT; keyframe OCR
  flagged optional). Robustness: password-protected → QUARANTINED status,
  corrupt → FAILED_PARSE with reason, oversized → streaming/chunked parsing
  with a size ceiling; every terminal status visible via the status API.
- preprocessing: language detection (fastText lid.176 or lingua — verify and
  pick), optional translation step behind a Translator interface (stub OK this
  phase), text cleaning, TWO chunking strategies (fixed-size with overlap, and
  semantic/structure-aware using document headings), metadata extraction
  (source, mime, language, dates, page/slide refs, checksum).
- LanguagePolicy (adaptive): per-section language detection (documents mix
  languages — detect per block, not per file), and per language decide:
  embed natively with a multilingual model, or translate-then-embed for
  low-resource languages the embedding model handles poorly (translation
  stored ALONGSIDE the original — the original text is never replaced, and
  citations always point to the original). RTL text preserved end-to-end.
  Locale-aware metadata extraction: dates, numbers, currencies parsed per
  locale with timezone kept explicit.
- ChunkingPolicy (automatic strategy selection — this is the default path;
  manual strategy choice is the override, not the norm): after parsing,
  compute a DocumentProfile from the parsed output — mime type, heading/
  section density (structural elements per 1k tokens), table presence, OCR
  confidence (if OCR'd), speaker turns (if transcript), doc length, language.
  A rules engine over this profile (rules in config/chunking-policy.yaml, NOT
  hardcoded) selects strategy + chunk size + overlap per document:
  structured docs (DOCX/HTML/PPTX with real heading density) → structure-aware,
  minimal overlap; unstructured/low-OCR-confidence/plain text → fixed-size
  with 15–20% overlap; spreadsheets → row-groups with repeated headers;
  emails → per-message; transcripts → speaker/pause boundaries. Every rule
  hit is logged with the profile values so chunking decisions are auditable.
  Unknown/ambiguous profiles fall back to fixed-size — never fail ingestion
  over strategy selection. Per-tenant/per-doc-type overrides in tenant config.
  New strategies must be addable as Chunker adapters + yaml rules only, with
  zero pipeline code changes.
- Document versioning: re-uploading same source creates new version, old
  chunks marked superseded, checksum-based dedupe.
- Source connectors (SourceConnector interface): beyond upload, implement
  pull-based connectors with INCREMENTAL sync (changed/deleted docs only) —
  start with S3/blob folder sync + one SaaS connector (SharePoint, Confluence,
  or Google Drive per anchor customer; verify the vendor API before coding).
  Deletions in source MUST propagate to chunk/vector deletion.
- Permission capture: connectors ingest each document's source ACL (users/
  groups allowed) into metadata. This enables document-level authorization
  later — tenant isolation alone is NOT enough for enterprise search.
- Golden-file tests: commit small sample files of each format in tests/fixtures
  and assert extracted text/chunk counts. NO fabricated fixtures — generate
  real sample files with scripts committed to the repo.

EXIT CHECKLIST:
[ ] Upload each fixture format via API → status endpoint reaches PARSED
[ ] Multilingual fixtures (at minimum: Arabic RTL, Chinese, Hindi, mixed
    English+other) parse, detect language per section, and chunk by TOKENS
[ ] Password-protected / corrupt / unknown-format fixtures → QUARANTINED /
    FAILED_PARSE / UNSUPPORTED statuses, never a crash
[ ] ChunkingPolicy test matrix: each fixture type → expected strategy/overlap
    chosen automatically; decision + profile values present in logs
[ ] Ambiguous/corrupt fixture → falls back to fixed-size, ingestion succeeds
[ ] Chunks in Postgres carry tenant_id, language, metadata, version
[ ] Re-upload same file → dedupe/version behavior proven by test
[ ] A second tenant cannot see tenant A's documents (test proves it)
```

### Phase 2 — Embeddings & vector store (Month 2–3)

```
GOAL: Chunks → embeddings → tenant-isolated hybrid-searchable index.

TASKS:
- EmbeddingProvider adapters: one local/open model via sentence-transformers
  (e.g., a BGE-family model — resolve exact model id from Hugging Face at
  build time and record it in config/models.yaml), plus OpenAI and Cohere
  adapters gated behind API-key config. Batch, retry, rate-limit aware.
- EmbeddingPolicy (adaptive): route each chunk to an embedding model by its
  profile — language (multilingual vs English-optimized model), content type
  (prose vs table vs code), domain — via config rules. A collection may hold
  chunks embedded by different models ONLY if the vector space per collection
  stays consistent (one model per collection; policy maps chunk → collection).
- Embedding versioning: each EmbeddingRecord stores model_id + model_version;
  re-embedding pipeline for model upgrades.
- VectorStore adapters: Qdrant (primary, with per-tenant payload filtering
  enforced in the adapter — impossible to query without tenant_id) and
  pgvector (fallback). Collection/schema migration scripts.
- ACL payloads: vector records carry the document's allowed principals
  (users/groups) from Phase 1; searches accept the caller's principal set and
  pre-filter on it (post-filtering leaks via scores/counts — avoid).
- Hard-delete path: deleting a document removes chunks, vectors, keyword-index
  entries, AND cache entries — one API, tested. This is the foundation for
  GDPR right-to-erasure later; retrofitting it is expensive.
- Keyword index: OpenSearch adapter (BM25) with same tenant enforcement.
  Language-aware analyzers chosen by detected language (ICU analyzer default;
  CJK/n-gram, stemmers per language — verify installed analyzer plugins);
  a default English analyzer on non-English text silently ruins keyword
  recall, so analyzer choice is part of LanguagePolicy and logged.
- Embedding worker consuming the parse-complete queue; idempotent; dead-letter
  queue for failures.

EXIT CHECKLIST:
[ ] End-to-end: upload file → chunks embedded → searchable in Qdrant + OpenSearch
[ ] Tenant isolation test: identical docs for 2 tenants, each search returns
    only own tenant's results
[ ] Kill worker mid-batch → restart → no dupes, no losses (idempotency test)
[ ] Swap embedding model in config → re-embed pipeline runs, old vectors kept
    until cutover
```

### Phase 3 — Retrieval & reranking (Month 3–4)

```
GOAL: High-quality hybrid retrieval with reranking, filters, and measurable
quality.

TASKS:
- QueryPolicy (adaptive — the heart of query-time behavior): classify query
  intent BEFORE retrieving — factual lookup, summarization, comparison,
  aggregation/metadata query, conversational follow-up — using cheap signals
  first (length, keywords, filters present, history), and select per intent:
  search mode (vector-only / hybrid / metadata-store query — aggregations
  should NOT hit vector search), top_k, whether to decompose, whether
  multi-hop or GraphRAG applies. Rules in config, decision logged per query.
- RerankPolicy (adaptive): skip reranking when first-stage scores are
  confident and well-separated (margin threshold in config) — reranking
  everything is a hidden fixed cost. Log skip/run decision + margins.
- retrieval service: hybrid search = vector + BM25, merged with Reciprocal
  Rank Fusion (RRF); metadata filters (date, doc type, department, language).
- Reranker adapters: local cross-encoder via sentence-transformers (resolve
  exact model id at build time) + Cohere Rerank adapter (config-gated).
- Query understanding layer (runs before retrieval): multi-turn query
  rewriting (resolve "it/that" from conversation history into a standalone
  query), query decomposition for compound questions, and language detection
  to route to the right index/prompt language. Conversation history lives in
  a ChatSession store (Postgres/Redis) keyed by tenant + user + session.
- Multi-hop retrieval: optional second retrieval pass using entities/terms
  from first-pass results (config flag, off by default).
- GraphRAG (optional, flagged OFF): KnowledgeGraph interface + entity/relation
  extraction pipeline for relationship-heavy corpora (e.g., BFSI ownership
  structures). Note in the plan: graph extraction typically costs 3–5× baseline
  ingestion — enable per-tenant, per-corpus only where the eval set proves it
  pays for itself.
- Retrieval evaluation harness: build a small labeled eval set from the
  fixture documents (queries + relevant chunk ids, human-authored, committed
  to repo). Compute recall@k, MRR, nDCG. THESE NUMBERS COME FROM RUNNING THE
  HARNESS — never report metrics you didn't compute.
- Chunking auto-tuning loop: harness can re-chunk the eval corpus under
  alternative ChunkingPolicy rules and compare retrieval scores per document
  type; winning rules are proposed as a config/chunking-policy.yaml diff for
  human review (never auto-applied in prod). This closes the loop: profiles
  pick the strategy, eval numbers tune the rules.

EXIT CHECKLIST:
[ ] Hybrid beats vector-only and BM25-only on the eval set (show table)
[ ] Reranker improves nDCG@10 on the eval set (show numbers from actual runs)
[ ] Filters + tenant isolation covered by tests
[ ] p95 retrieval latency measured and recorded in PROGRESS.md
```

### Phase 4 — Orchestration, model routing & guardrails (Month 4–5)

```
GOAL: Retrieved context → governed prompt → right model → grounded answer
with citations.

TASKS:
- PromptPolicy + ContextPolicy (adaptive): the template is SELECTED, not
  hardcoded per endpoint — chosen from the registry by detected intent +
  domain + language. Context assembly adapts to the routed model: token
  budget derived from the model's context window (from models.yaml, never
  hardcoded), chunk count/order driven by score distribution and dedupe,
  truncation strategy logged. GuardrailProfile: strictness tier (e.g.
  healthcare-strict vs retail-standard) selected per tenant/domain at
  runtime from config, not compiled in. CachePolicy: semantic-cache
  similarity threshold varies by query intent (tight for factual lookups,
  cache disabled for reasoning-heavy intents) — config-ruled, logged.
- Prompt template registry: YAML templates in config/prompts/, versioned,
  with variables schema; template types: retrieval-QA, summarization,
  reasoning, structured-output (JSON schema-validated), multi-language.
  Domain packs (bfsi/, retail/, healthcare/) as folders of templates.
- ModelRouter: rules engine over config/models.yaml (task type, language,
  complexity heuristic, cost ceiling, latency SLO) → model_id. All model ids
  in the registry marked VERIFY BEFORE DEPLOY; router must work with ANY
  registry contents (no hardcoded model names in code).
- LLMProvider adapters: OpenAI, Anthropic, and one self-hosted/OSS path via
  an OpenAI-compatible endpoint (e.g., vLLM/Ollama serving). Streaming +
  non-streaming. Token usage captured per call per tenant.
- Response language: answer in the language of the user's query by default
  (tenant-configurable), even when retrieved chunks are in other languages;
  citations still point to original-language chunks. Guardrails must work
  across languages — PII recognizers configured per locale (Presidio supports
  language-specific recognizers; verify configuration), injection screening
  not English-only.
- Grounding: answers must cite chunk ids; a post-generation check verifies
  every citation exists in the retrieved set; configurable behavior when the
  context doesn't contain the answer (refuse / say-unknown template).
- Guardrails: PII detection/redaction via Microsoft Presidio (verify installed
  API), prompt-injection input screening, output policy checks per domain
  (e.g., no medical advice beyond the source documents). Failures logged with
  reason codes.
- Agent/tools mode (flagged, off by default): agentic RAG loop — plan →
  select retrieval strategy per sub-question → execute → synthesize — with an
  explicit max-iteration budget, per-tool permission scoping (a tool gets the
  CALLER's principals, never a super-user's), human-approval gate for any
  state-changing tool, and full trace logging. This directly mitigates OWASP
  "Excessive Agency".
- Semantic cache: cache (query-embedding, tenant, principal-set) → answer with
  a similarity threshold; TTL + invalidation on document updates/deletes.
  Cache keys MUST include tenant and principals or the cache becomes a
  cross-user leak channel. Measure hit rate + cost saved.

EXIT CHECKLIST:
[ ] /v1/query returns answer + citations; citation-validity test passes
[ ] Query in a non-English language over a mixed-language corpus → answer in
    the query's language, citations to original chunks (test per fixture lang)
[ ] Question with no answer in corpus → governed "not in documents" response
    (test proves no fabrication on 10 adversarial questions from eval set)
[ ] PII in a document → redacted in the answer (test)
[ ] Router test matrix: task/lang/cost combinations → expected model choice
[ ] Per-tenant token usage recorded in DB
```

### Phase 5 — API gateway, auth & multi-tenant security (Month 5–6)

```
GOAL: Production-grade public surface with tenant isolation you can show an
auditor.

TASKS:
- gateway service: REST (OpenAPI) — GraphQL only if a customer requires it.
- AuthN: OAuth2/OIDC (integrate a standard IdP via authlib or equivalent —
  verify library API), API keys for service accounts, JWTs carrying tenant_id
  + roles. AuthZ: RBAC (admin, editor, reader) enforced at gateway AND
  service layer (defense in depth).
- Rate limiting + quotas per tenant (Redis token bucket); request size limits.
- Audit log: append-only store of who/what/when/tenant for every data-touching
  call; export endpoint per tenant.
- Data isolation review: tests attempting cross-tenant access on EVERY
  endpoint (documents, search, query, admin). Encryption at rest (DB/MinIO
  config) and TLS everywhere documented in a SECURITY.md, with each control
  labeled implemented / delegated-to-cloud / pending.
- Compliance posture doc: map controls to SOC 2 / HIPAA / PCI-relevant
  requirements as ASPIRATIONAL until audited — never claim certification.
- OWASP LLM Top 10 (2025) mapping in SECURITY.md — one row per risk with the
  concrete control: prompt injection (input screening + instruction/data
  separation + citation-bound answers), sensitive info disclosure (PII
  redaction + doc-level ACLs), supply chain (pinned deps + model provenance in
  registry), data/model poisoning (connector source allow-lists + ingestion
  content scanning), improper output handling (output encoding, schema
  validation before downstream use), excessive agency (Phase 4 tool gates),
  system prompt leakage (no secrets in prompts, leak-probe tests), vector/
  embedding weaknesses (pre-filtered ACL search, no cross-tenant collections).
- Jurisdiction compliance profiles: per-tenant selection of a compliance
  profile (GDPR, HIPAA, India DPDP, CCPA, PDPA, custom) driving retention
  windows, erasure SLA, residency constraints, PII categories, and audit
  export format — a config framework, with each profile's legal mapping
  labeled DRAFT until counsel review.
- Data lifecycle & GDPR/EU AI Act: right-to-erasure API (erases source doc,
  chunks, vectors, keyword index, caches, and redacts eval-store copies —
  builds on Phase 2 hard-delete; document what remains in backups + expiry),
  per-tenant retention policies, data-residency config (pin a tenant's
  storage + inference region; document any cross-region calls), and a data
  governance record per EU AI Act expectations. Label legal interpretations
  DRAFT — counsel reviews.
- Document-level authorization end-to-end: a user's query only retrieves
  chunks whose ACL includes their principals; ACL changes in source propagate
  on next sync (document the staleness window).

EXIT CHECKLIST:
[ ] OpenAPI spec published; auth flows tested end-to-end
[ ] Cross-tenant attack test suite: 0 leaks across all endpoints
[ ] Cross-USER test within one tenant: user without doc ACL gets no chunk from
    it in retrieval, answers, OR cache
[ ] Erasure API: after erase, doc is gone from search, vectors, cache; test
    proves it
[ ] Prompt-injection test set (adversarial docs + queries) run; results logged
[ ] Rate limits enforced (test shows 429s); audit log captures the run
[ ] SECURITY.md honest-status table complete
```

### Phase 6 — Monitoring, evaluation & feedback (Month 6–7)

```
GOAL: You can see quality, cost, latency, and drift per tenant without SSH-ing
into anything.

TASKS:
- OpenTelemetry tracing across gateway → retrieval → orchestrator → LLM call;
  Jaeger locally, OTLP-exportable for cloud.
- Prometheus metrics: request rate/latency p50/p95/p99, token usage & cost per
  tenant/model, retrieval scores, guardrail trigger counts, queue depths.
  Grafana dashboards committed as JSON to infra/.
- Answer-quality pipeline: log (query, retrieved chunks, answer, citations);
  nightly automated scoring using the Ragas framework's metric suite —
  faithfulness (claims verified against retrieved context), answer relevancy,
  context precision, context recall (verify Ragas' installed API before use);
  judged results labeled as model-estimated, never presented as ground truth;
  weekly human-review queue.
- User feedback endpoint (thumbs + comment) wired into the eval store.
- Drift signals: rolling retrieval-score and groundedness trends with alert
  thresholds (Alertmanager rules committed).
- Optional adapters for Arize/MLflow behind an ObservabilitySink interface —
  stub unless keys provided.

EXIT CHECKLIST:
[ ] One trace shows the full query path with timing per hop
[ ] Grafana dashboard renders live metrics from a load test (locust/k6 script
    committed; numbers recorded in PROGRESS.md)
[ ] Nightly eval job runs end-to-end on the fixture corpus
[ ] Alert fires when groundedness sample score drops below threshold (test)
```

### Phase 7 — CI/CD, IaC & prompt/embedding versioning (Month 7–9)

```
GOAL: Reproducible deploys; prompts, models, and embeddings are versioned
artifacts with rollback.

TASKS:
- Terraform for one target cloud first (pick per anchor customer; keep modules
  provider-shaped for later multi-cloud). Helm charts per service; ArgoCD or
  GitHub Actions CD with staging → prod promotion and canary deploys.
- Air-gapped install path: an offline bundle (images, models, charts) that
  deploys with zero internet access using only local models; a CI job runs
  the full e2e suite with egress blocked to prove no hidden external calls.
- Prompt CI: schema-validate all templates; run the eval harness against
  changed prompts; block merge on regression beyond threshold.
- Model registry workflow: adding/changing a model_id in models.yaml requires
  a PR with a filled VERIFICATION section (provider doc link, date checked).
- Embedding migrations: blue/green collections with cutover + rollback runbook.
- Backup/restore: Postgres, MinIO, vector collections — restore actually
  rehearsed and documented.
- Disaster recovery: declared RTO/RPO targets per component, failover runbook,
  and a game-day exercise in staging; publishable SLA draft (uptime, p95
  latency) grounded in measured load-test numbers only.
- FinOps: per-tenant budgets with alert thresholds, daily cost-per-query and
  cache-hit-rate report, anomaly alerts on token spend spikes.
- Model deprecation drill: mark a model deprecated in the registry → router
  falls back per config → alert fires; rehearsed in staging.
- Load test in CI (nightly): recorded p95s and cost-per-query trends.

EXIT CHECKLIST:
[ ] Fresh environment stands up from Terraform+Helm with one documented command path
[ ] A prompt change with worse eval score is blocked by CI (demonstrate)
[ ] Canary deploy + rollback demonstrated in staging
[ ] Restore-from-backup rehearsal documented with timestamps
```

### Phase 8 — Domain packs & SaaS hardening (Month 9–12)

```
GOAL: Sellable domain configurations on a multi-tenant SaaS base.

TASKS:
- Domain packs = config, not forks: per-domain prompt templates, metadata
  schemas, guardrail policies, eval sets.
  BFSI: policy/compliance QA, AML-document QA, lending-document summarization
  — every answer citation-bound; audit export per query.
  Retail: product-catalog QA, support-KB answers, inventory/document copilot.
  Healthcare: clinical-notes QA with strict grounding (refuse beyond sources),
  PHI redaction always-on, access logging meeting audit needs. Label HIPAA
  readiness honestly: BAA + audited controls required before claiming it.
- Tenant self-service: onboarding API, per-tenant model/provider preferences,
  usage-based metering export for billing.
- Tenant OFFBOARDING: full export (documents, chunks, config, audit logs) +
  verified deletion across every store, with a completion certificate record.
- Structured-data answering (optional pack): tables from XLSX/PDF preserved as
  structured chunks; text-to-SQL over approved, read-only, per-tenant views
  with query validation — never raw DB access from the LLM. Feature-store
  integration (e.g., Feast) only when a customer use case needs online
  features; keep behind an interface.
- Multimodal retrieval (flagged): image/chart content in documents captioned
  or embedded via a multimodal model at ingestion so figures are retrievable;
  eval set extended with figure-dependent questions before claiming support.
- Scale pass: horizontal autoscaling rules, connection pooling, cache strategy
  (embedding cache, retrieval cache with tenant-scoped keys), documented
  capacity model from load tests.
- Pen-test-style review: run an automated security scan (e.g., OWASP ZAP
  against staging) and fix highs; document the rest.

EXIT CHECKLIST:
[ ] New tenant onboarded via API in <10 min with a domain pack, no code change
[ ] Each domain pack passes its own eval set with recorded scores
[ ] Load test at target concurrency meets SLOs; capacity model documented
[ ] Security scan report committed with remediation status
```

---

## 5. STANDING REMINDERS (re-paste when the agent drifts)

```
- One phase, one branch, one green verify before moving on.
- Show real command output; never summarize tests you didn't run.
- No hardcoded model names; registry + VERIFY BEFORE DEPLOY only.
- tenant_id on every record, query, log line — no exceptions.
- Adapters, not vendor lock: if you're importing a vendor SDK outside
  libs/connectors, stop and refactor.
- Metrics and eval numbers must come from executed harnesses, with the
  command shown. Estimated ≠ measured; label which is which.
- When stuck 3x: stop, summarize, present options.
```

---

## 6. GAP-COVERAGE MATRIX (architect's checklist — verify nothing is dropped)

| Capability | Phase | Why it's easy to miss |
|---|---|---|
| Multi-format parsing, OCR, STT | 1 | — |
| Source connectors + incremental sync + deletion propagation | 1 | Teams build upload-only and stall at enterprise pilots |
| Source ACL capture → document-level authorization | 1, 2, 5 | Tenant isolation alone leaks data between a tenant's own users |
| Hard-delete across all stores (erasure foundation) | 2 | Retrofitting deletion into vectors/caches is very costly |
| Embedding + prompt + model versioning | 2, 4, 7 | Silent model swaps break reproducibility |
| Query rewriting, decomposition, conversation memory | 3 | Single-turn demos hide multi-turn failure |
| Hybrid retrieval + rerank + eval harness | 3 | — |
| GraphRAG (optional, cost-gated) | 3 | Hype-driven adoption; 3–5× ingestion cost if ungated |
| Grounded answers with validated citations; refuse-when-absent | 4 | Primary hallucination control |
| Guardrails: PII, injection screening, output policy | 4 | — |
| Agentic RAG with permission-scoped tools + human gates | 4 | OWASP "Excessive Agency" |
| Semantic cache (tenant+principal keyed) | 4 | Naive caches are a cross-user leak channel |
| OWASP LLM Top 10 (2025) control mapping | 5 | Security reviews now expect it by name |
| GDPR erasure, retention, data residency, EU AI Act governance record | 5 | Enterprise procurement blockers |
| Ragas-style eval: faithfulness, context precision/recall | 6 | "It looks right" isn't a metric |
| Tracing, per-tenant cost, drift alerts, feedback loop | 6 | — |
| CI gates on prompt regressions; canary + rollback | 7 | — |
| DR (RTO/RPO), SLA from measured numbers, FinOps budgets, model deprecation drill | 7 | Discovered during the first outage otherwise |
| Domain packs as config; honest compliance labeling | 8 | — |
| Tenant offboarding: export + verified deletion | 8 | Contract requirement nobody builds until asked |
| Structured-data / text-to-SQL (guarded), multimodal (flagged) | 8 | Scope-creep magnets — keep optional and eval-gated |
| Adaptive policy pattern on every strategy choice (parser, chunking, embedding, language, query, rerank, cache, context, prompt, guardrails) | 1–4 | Hardcoded strategies hide everywhere; each policy needs signals → config rules → logged decision → fallback → eval-tuned |
| Global language support: Unicode/RTL/CJK/Indic, token-based chunking, per-language analyzers, translate-then-embed fallback, answer in query language | 1, 2, 4 | English-only assumptions hide in chunk sizing, BM25 analyzers, PII recognizers |
| Universal format robustness: unknown → plugin registry, corrupt/encrypted/oversized → graceful statuses | 1 | Real corpora are messy; one crash-prone format blocks whole batches |
| Air-gapped deployment mode with egress-blocked CI proof | 7 | Defense/regulated buyers require it; hidden external calls disqualify you |
| Jurisdiction compliance profiles (GDPR, HIPAA, DPDP, CCPA, PDPA as config) | 5 | Hardcoding one legal regime blocks every other market |

If your agent's plan for a phase doesn't touch every matrix row mapped to that
phase, the plan is incomplete — send it back with the row names.

---

*Operator notes: model names, provider pricing, and library APIs in your original spec date quickly (e.g., "GPT-4o", "Claude 3.5", "Llama 3" may be superseded). This prompt deliberately keeps all such identifiers in `config/models.yaml` with a human verification gate instead of baking them into prompts or code — that is the main structural defense against hallucinated or stale model/API references.*

