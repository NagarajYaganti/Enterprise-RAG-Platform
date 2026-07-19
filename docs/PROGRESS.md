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
Status: DONE — exit checklist all PASS (2026-07-19).

### Exit checklist results
| Item | Result | Evidence |
|---|---|---|
| Upload each fixture format via API → status reaches PARSED | PASS | `tests/integration/test_ingestion_e2e.py` — 8/8 formats (pdf, docx, pptx, xlsx, html, png, wav, eml) |
| Chunks in Postgres carry tenant_id, language, metadata, version | PASS | Asserted in the same e2e test against real Postgres rows |
| Re-upload same file → dedupe/version behavior proven by test | PASS | `tests/integration/test_versioning.py` — identical re-upload stays v1, changed content bumps to v2 and supersedes old chunks |
| Second tenant cannot see tenant A's documents | PASS | `tests/integration/test_tenant_isolation.py` — API returns 404 (not 403) cross-tenant; repository layer double-checked independently |

Full suite: `uv run pytest` → 107 passed. `uv run ruff check .` → clean. `uv run mypy` → 0 issues in 87 files.

### Done
- `libs/core`: `ParsedDocument` model; `Document`/`Chunk` extended with `language`, `version`, status enums (`DocumentStatus`, `ChunkStatus`), and `acl_principals`; `SourceConnector` and `Translator` interfaces added (phase-directed, not a redesign of the fixed 8).
- `TenantContextMiddleware` relocated `services/gateway` → `libs/core` so `ingestion` shares it instead of duplicating the auth stub.
- `libs/connectors/postgres`: tenant-scoped `DocumentRepository`/`ChunkRepository` on SQLAlchemy 2.x + psycopg, every query requiring `tenant_id`.
- Real golden-file fixtures (pdf/docx/pptx/xlsx/html/png/wav/eml) generated by a committed script (`tests/fixtures/scripts/generate_fixtures.py`), not hand-fabricated.
- Four `DocumentParser` adapters: `unstructured` (pdf/docx/pptx/xlsx/html), Tesseract OCR, faster-whisper STT, stdlib email — each verified against the real fixtures.
- `BlobSourceConnector` (S3/MinIO, incremental sync + deletion propagation, tested against real MinIO) and `SharePointConnector` (Microsoft Graph delta + permissions, tested against a mock transport built from the actual verified Graph API response shapes) — both capture source ACLs into `acl_principals`.
- `services/preprocessing`: language detection (`lingua`, a fixed 9-language subset — not all 75, for build speed and short-text accuracy), stub translator, text cleaning, two chunking strategies (fixed-size+overlap, structure-aware via headings/page numbers), metadata extraction, and a pipeline tying them together per the fixed data flow.
- `services/ingestion`: multipart upload API, MinIO storage, arq queue + worker, checksum-based dedupe/versioning, full FastAPI app with `/health`, `/metrics`, `TenantContextMiddleware`.
- CI workflow updated: system packages (tesseract-ocr, ffmpeg) installed, Postgres+Redis added as GitHub Actions services, MinIO started via a manual `docker run` step (GH Actions' `services:` block can't pass MinIO's required `server /data` command args).

### Two real bugs found and fixed during integration testing (Step 13)
- **Dedupe placeholder-checksum bug**: the API creates a placeholder `Document` row (`checksum=""`) before enqueueing so `GET` has something to show immediately. The worker's `determine_version` was comparing against that placeholder's empty checksum as if it were a real prior version, so *every* first-time upload was misclassified as a re-upload and bumped straight to version 2. Fixed by treating `checksum == ""` as "no real prior version" in `determine_version`.
- **Non-deterministic document identity**: the API originally minted a random UUID per upload, so "re-uploading the same file" could never actually collide with the original — each upload became an unrelated new document, making the version-bump path unreachable in practice. Fixed by deriving `document_id` deterministically from `uuid5(tenant_id, filename)`, and by having the API leave an existing document's row untouched on re-upload (so the worker still has the real previous checksum to compare against, instead of it being clobbered by a reset placeholder).
- Both were caught only once real end-to-end integration tests exercised the actual API → queue → worker path — the unit-level tests for `dedupe.py` and `worker.process_document` in isolation could not have caught either, since they called the pipeline pieces directly rather than through the real API's document-identity and placeholder-row logic.

### Stubbed / deferred (intentionally)
- `.msg` email parsing deferred: no credible script-based fixture-generation path exists for the OLE compound format (`extract-msg` only reads it). `.eml` covers the format-support requirement for this phase.
- `Translator` is an identity-function stub, per the phase spec ("stub OK this phase").
- SharePoint connector auth: takes a pre-obtained bearer token; MSAL/Azure AD token acquisition is out of scope for this phase. No live SharePoint tenant was tested against — tests use a mock transport built from Microsoft's official, fetched API documentation.
- Document-level ACL is captured and stored (`acl_principals`) but not yet enforced at query/retrieval time — that's Phase 2 (vector pre-filter) and Phase 5 (gateway authZ), per GAP-MATRIX's row spanning phases 1/2/5.

### Known risks / watch items
- `faster-whisper`'s "tiny" model is imprecise on synthetic TTS audio; the STT golden-file test asserts on keyword substrings, not exact transcription, and required tuning the fixture's TTS speech rate (130wpm, not the 200wpm default) to get reliable results at all — revisit if real customer audio proves harder than this synthetic case.
- `arq`'s `ArqRedis.close()` is deprecated in favor of `.aclose()`; the deprecation warning currently fires from inside arq's own `Worker.close()`, not our code — nothing to fix on our side, but worth checking on an arq upgrade.
- GitHub Actions CI cannot use `services:` for MinIO (no `command:` override support there); the workaround is a manual `docker run` step — confirm this still works after any future GH Actions runner image changes.
- Whisper model size ("tiny") is registered in `config/models.yaml` per the anti-hallucination rule but is `verified_before_deploy: false` — a human must confirm it against provider docs before any real deploy.

### Top 3 priorities for Phase 2
1. `VectorStore` adapters (Qdrant primary, pgvector fallback) with per-tenant payload filtering enforced in the adapter itself — "impossible to query without tenant_id," mirroring the Postgres repository pattern already proven in Phase 1.
2. Hard-delete path across chunks/vectors/keyword-index/cache in one API — GAP-MATRIX flags this as expensive to retrofit later, and Phase 1's chunk/document model (with `status` fields) is already shaped to support it.
3. `EmbeddingProvider` adapters (local sentence-transformers + OpenAI/Cohere gated behind API keys) with embedding versioning (`model_id` + `model_version` on `EmbeddingRecord`, already defined in `libs/core/models.py` since Phase 0) and an idempotent embedding worker consuming the parse-complete queue.

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
