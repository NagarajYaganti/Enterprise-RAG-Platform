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
