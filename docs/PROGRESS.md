# Progress Log

## Phase 0 — Repo scaffold & foundations
Status: DONE — exit checklist all PASS (2026-07-19).

### Exit checklist results
| Item | Result | Evidence |
|---|---|---|
| `docker compose up` → all containers healthy | PASS | `docker compose -f infra/docker-compose.dev.yml ps` — 8/8 services `healthy` (postgres, qdrant, opensearch, redis, minio, prometheus, grafana, jaeger) |
| pytest → interface/model tests pass (≥1 test per core model) | PASS | `uv run pytest -v` — 31/31 passed, all 7 core models + 8 interfaces covered |
| CI workflow runs green on a test PR | PASS | PR #1, `gh pr checks 1` — lint/test/typecheck all `pass` |
| mypy + ruff clean | PASS | `uv run ruff check .` — all checks passed; `uv run mypy` — 0 issues in 30 files |

### Done
- uv workspace: 6 services (`ingestion`, `preprocessing`, `embedding`, `retrieval`, `orchestrator`, `gateway`) + 3 libs (`core`, `connectors`, `observability`), single lockfile, verified cross-package imports.
- `libs/core`: all 8 ABC interfaces from the architecture contract; 7 tenant-scoped Pydantic models (Tenant, Document, Chunk, EmbeddingRecord, Query, RetrievalResult, Completion); contextvar-based tenant context.
- `libs/observability`: stdlib-only structured JSON logger (request_id + tenant_id fields).
- `services/gateway`: FastAPI app with `/health`, `/metrics` (Prometheus exposition format), and `TenantContextMiddleware`.
- `infra/docker-compose.dev.yml`: all 8 images and tags confirmed to exist (Docker Hub API) and every healthcheck command empirically verified against a running container before being committed.
- `.github/workflows/ci.yml`: ruff + mypy + pytest jobs, verified against a real PR.
- `docs/adr/0001-architecture.md` recording the architecture decision.
- `config/models.yaml` schema stub with `verified_before_deploy` gate (no entries yet — correct for this phase).

### Stubbed (intentionally, flagged for later phases)
- `TenantContextMiddleware` token decoding is an **INSECURE STUB**: unsigned base64/JSON decode, no signature verification. Real OIDC/JWT validation is Phase 5 work — do not treat current auth as real.
- Only `services/gateway` has a live FastAPI app with `/health`/`/metrics`. `ingestion`, `preprocessing`, `embedding`, `retrieval`, `orchestrator` are package skeletons with no app/router yet — each gets its own `/health`+`/metrics` when it receives real logic in its respective phase.
- `libs/connectors` is an empty placeholder package — first real adapters land in Phase 1 (parsers/connectors) and Phase 2 (vector store/embedding adapters).

### Deferred
- Nothing from the Phase 0 task list was deferred; all tasks and all exit-checklist items are complete.

### Known risks / watch items
- OpenSearch's healthcheck needs a `start_period: 60s` in the compose file — it's consistently the slowest service to become ready; if CI runners are slower than this sandbox, that window may need to grow.
- Infra image tags (`postgres`/pgvector, qdrant, opensearch, redis, minio, prometheus, grafana, jaeger) are pinned to specific versions current as of 2026-07-19 — revisit at the start of Phase 7 (IaC) rather than silently drifting to `latest`.
- `starlette`'s `TestClient` now requires `httpx2`, not `httpx` (deprecation confirmed during Phase 0) — keep this in mind if any future test tooling assumes plain `httpx`.

### Top 3 priorities for Phase 1
1. Document parsers as `DocumentParser` adapters (PDF/DOCX/PPTX/XLSX/HTML via `unstructured`, images via Tesseract OCR, audio via faster-whisper) plus the `POST /v1/documents` ingestion endpoint — verify each library's installed API before use, per the anti-hallucination rules.
2. Source connectors with incremental sync and deletion propagation, plus ACL capture on ingest — GAP-MATRIX flags this as the row teams most often skip and then stall on at enterprise pilots.
3. Two chunking strategies (fixed-size + structure-aware) and document versioning/dedupe by checksum, with golden-file tests using real committed sample files (no fabricated fixtures).

## Phase 1 — Ingestion & preprocessing
(not started)

## Phase 2 — Embeddings & vector store
(not started)

## Phase 3 — Retrieval & reranking
(not started)

## Phase 4 — Orchestration, model routing & guardrails
(not started)

## Phase 5 — API gateway, auth & multi-tenant security
(not started)

## Phase 6 — Monitoring, evaluation & feedback
(not started)

## Phase 7 — CI/CD, IaC & prompt/embedding versioning
(not started)

## Phase 8 — Domain packs & SaaS hardening
(not started)
