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
