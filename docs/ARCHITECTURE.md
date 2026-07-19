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

Local dev stack (docker-compose): Postgres (+pgvector), Qdrant, OpenSearch,
Redis, MinIO, Prometheus, Grafana, Jaeger. Cloud-managed equivalents are
swapped in via adapters at deploy time — code must not care.
