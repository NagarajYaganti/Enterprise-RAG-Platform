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
Status: DONE — exit checklist re-verified, all PASS (2026-07-19).

### Exit checklist results (re-run, matching CI's exact environment — no `fixtures` dependency group synced)
| Item | Result | Evidence |
|---|---|---|
| Upload each fixture format via API → status reaches PARSED | PASS | `tests/integration/test_ingestion_e2e.py` — 8/8 formats (pdf, docx, pptx, xlsx, html, png, wav, eml) |
| Chunks in Postgres carry tenant_id, language, metadata, version | PASS | Asserted in the same e2e test against real Postgres rows |
| Re-upload same file → dedupe/version behavior proven by test | PASS | `tests/integration/test_versioning.py` — identical re-upload stays v1, changed content bumps to v2 and supersedes old chunks |
| Second tenant cannot see tenant A's documents | PASS | `tests/integration/test_tenant_isolation.py` — API returns 404 (not 403) cross-tenant; repository layer double-checked independently |

Full suite: `uv run pytest` → 107 passed. `uv run ruff check .` → clean. `uv run mypy` → 0 issues in 87 files.

### Third bug found: local/CI mypy discrepancy (caught via real PR CI, not local runs)
PR #2's `typecheck` job failed in real GitHub Actions even though every local `mypy` run in this session had passed. Root cause: `tests/fixtures/scripts/generate_fixtures.py` imports `fpdf` (from the `fpdf2` package), which lives in a separate, non-default `fixtures` uv dependency group — deliberately excluded from the standard `uv sync --all-packages` that both local dev and CI's `typecheck`/`test` jobs run, since it's only needed to *regenerate* fixtures, not to run tests against the already-committed ones. Locally, this stayed hidden because an earlier `uv sync --all-packages --group fixtures` (run once to actually generate the fixtures) had left `fpdf2` installed in the local `.venv`, masking the gap — `docx`/`pptx`/`PIL`/`openpyxl` didn't have the same problem because they're transitive dependencies of `unstructured[docx,pptx,xlsx]`, a real (non-fixtures-group) dependency, so they're present regardless. Fixed by adding `types-fpdf2` (confirmed on PyPI, version `2.8.4.20260712`) to the `dev` group. Reproduced and fixed by deleting `.venv` and running `uv sync --all-packages` with no `--group fixtures`, matching CI exactly, before re-confirming green.
**Lesson**: a clean local `mypy`/`pytest` run is not sufficient evidence once dependency groups diverge between local and CI — this only surfaces by actually observing the real CI job, which is why the "CI runs green on a test PR" checklist item matters as its own check, not a formality.

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
Status: DONE — exit checklist all PASS (2026-07-19).

### Exit checklist results
| Item | Result | Evidence |
|---|---|---|
| End-to-end: upload file → chunks embedded → searchable in Qdrant + OpenSearch | PASS | `tests/integration/test_embedding_e2e.py` — real upload → ingestion worker → embedding worker → raw Qdrant scroll + real OpenSearch BM25 search both find the document |
| Tenant isolation: identical docs for 2 tenants, each search returns only own tenant's results | PASS | `tests/integration/test_embedding_tenant_isolation.py` — two tenants upload identical `sample.html`; Qdrant point counts and OpenSearch hits partition exactly by `tenant_id` |
| Kill worker mid-batch → restart → no dupes, no losses (idempotency) | PASS | `tests/integration/test_embedding_idempotency.py` — direct call crashes after 2/5 chunks, real arq `embed_chunks` job restarts and finishes; final count is exactly 5, all point ids unique |
| Swap embedding model in config → re-embed pipeline runs, old vectors kept until cutover | PASS | `tests/integration/test_reembed_cutover.py` — real embed pass with the default model, second model's vector added directly, both `active` and coexisting; `cutover()` flips the old model's status to `superseded`, new stays `active` |

Full suite: `uv run pytest -q` → 171 passed. `uv run ruff check .` → clean. `uv run mypy .` → 0 issues in 126 files.

### Done
- `libs/core`: `Vector` type alias, `EmbeddingStatus` literal, `EmbeddingRecord` extended with `document_id`/`status`/`acl_principals`, new `VectorSearchHit`/`KeywordSearchHit` models; `EmbeddingProvider.embed()` return type tightened to `list[Vector]`; new `KeywordIndex` ABC (phase-directed addition, disclosed not silently added to the fixed 8).
- `core.model_registry`: `load_models_config`/`get_default_embedding_model`, reading `config/models.yaml` — no model id is ever hardcoded in application code.
- `config/models.yaml`: added a `version` field to the schema and 3 real embedding entries (`BAAI/bge-small-en-v1.5` local/huggingface with a real measured dimension of 384; `text-embedding-3-small` and `embed-v4.0` gated behind API keys, cost fields marked ASSUMPTION where not confirmed) — all `verified_before_deploy: false` pending human sign-off.
- `libs/connectors/vectorstores`: `migrations.py` (`ensure_qdrant_collection`, SQLAlchemy-Core-based `ensure_pgvector_table`), `QdrantVectorStore` and `PgvectorStore` — both enforce tenant_id server-side and pre-filter search by ACL principals (`MatchAny`/`.overlap()`), never post-filter.
- `libs/connectors/keyword`: `OpenSearchIndex` (BM25) with an explicit index mapping (keyword vs text fields) so tenant/ACL/id fields can never fall into OpenSearch's dynamic-mapping-driven analysis.
- `libs/connectors/embeddings`: `SentenceTransformersProvider` (local BGE model), `OpenAIEmbeddingProvider`, `CohereEmbeddingProvider` — both remote providers layer an outer `tenacity` retry for rate-limit errors on top of the SDK's own `max_retries`.
- `libs/connectors/erasure.py`: `ErasureService` with a `register(name, hook)` extension point — runs every registered `CleanupHook` even if some fail, collects all failures, then raises. Hard-delete (not status-flip) added to `DocumentRepository`/`ChunkRepository` for the Postgres leg.
- `services/embedding`: `queue.py` (arq producer), `worker.py` (idempotent `process_embedding_job` with deterministic `uuid5(chunk_id:model_id)` point ids, a hand-built dead-letter queue since arq has none natively, `on_startup` wiring real Qdrant/OpenSearch/model resources), `reembed.py` (`cutover()` — explicit, separate call that supersedes old-model vectors only after confirming active chunks exist), `main.py` (FastAPI `/health`/`/metrics`).
- `services/ingestion/worker.py`: now enqueues a real `embed_chunks` job (config-driven model id/version) right after a document reaches `PARSED`.
- CI: added `qdrant` and `opensearch` as GitHub Actions `services:` entries with real healthchecks.

### Four real bugs found and fixed during this phase
- **Hardcoded model id in worker startup**: `on_startup` originally constructed `SentenceTransformersProvider("BAAI/bge-small-en-v1.5")` directly, violating the "never hardcode model names" rule. Fixed to call `get_default_embedding_model()["id"]`, caught by re-reading the code against CLAUDE.md before writing the e2e test, then confirmed necessary when that test subsequently passed with the fix in place.
- **Missing collection/index bootstrap**: the real worker never called `ensure_qdrant_collection`/`ensure_index` before use — first real deployment against an empty Qdrant/OpenSearch would fail outright. Fixed by calling both in `on_startup` before constructing the store adapters.
- **Semantically wrong `model_version`**: the ingestion→embedding enqueue call initially passed `model.get("dimensions", "1")` as `model_version` — caught before running anything, since dimensions is not a version. Fixed by adding a real `version` field to `config/models.yaml`'s schema and using `model["version"]`.
- **arq's actual retry behavior differs from the initial assumption**: assumed a failed-but-not-exhausted job would sit in the queue for a later, separate burst call to pick up as a "restart." Empirically (via captured tracebacks), arq retries a failed job immediately within the *same* burst call up to `max_tries`, so a naive test using arq's own retry exhausted all tries identically and left nothing to restart. Fixed by redesigning the idempotency test: a direct `_CrashAfterN`-wrapped call for the deterministic "kill mid-batch" step, then the real arq queue+worker only for the "restart" step.

### One test-infrastructure bug found and fixed
- **Shared production resource names bled state between tests**: all embedding integration tests hit the same hardcoded Qdrant collection / OpenSearch index names the real worker uses, with no cleanup between runs — a prior test's leftover points inflated a later test's "partial count" assertion (5 instead of 2). Fixed with a `clean_embedding_stores` fixture (deletes+recreates the Qdrant collection, deletes the OpenSearch index) applied to every embedding integration test; re-verified passing twice consecutively.

### Stubbed / deferred (intentionally)
- pgvector is implemented and unit-tested but not exercised by any integration test in this phase — Qdrant is the primary store per the phase task text ("Qdrant primary, pgvector fallback"); pgvector's turn as the tested primary path is implicit fallback-only for now.
- Re-embed/cutover is proven at the `cutover()` logic level (payload status flip) but not as a live "worker picks up a newly-swapped model from a config change and restarts" scenario — the real worker binds one `SentenceTransformersProvider` to one model id per process lifetime, and a live model swap would require downloading and running a second real embedding model, which was out of scope for cost/time this phase. Documented as an explicit scope note in `test_reembed_cutover.py`'s module docstring, not silently skipped.
- Cross-tenant ACL search enforcement (searching *with* a caller's principal set) is implemented and unit-tested in `QdrantVectorStore.search`/`PgvectorStore.search`, but end-to-end proof that a real query only returns chunks a specific user is entitled to is Phase 5 (gateway authZ) territory per GAP-MATRIX's phase-1/2/5-spanning ACL row.
- Erasure (`ErasureService`) covers vectors + keyword index + Postgres hard-delete; it does not yet touch a cache layer, since no cache layer exists before Phase 6.

### Known risks / watch items
- The dead-letter queue is a plain Redis list (`dlq:embed_chunks`), hand-built since arq has none — no consumer/replay tooling exists yet for it; revisit when an ops/runbook phase needs it.
- `config/models.yaml`'s OpenAI/Cohere `cost_per_1k_tokens` values are `null`/ASSUMPTION, not confirmed against current provider pricing pages — must be verified before any real deploy that uses cost-based routing.
- All 3 embedding model entries remain `verified_before_deploy: false`; a human must confirm each against provider docs before production use, per the anti-hallucination rule.

### Top 3 priorities for Phase 3
1. Hybrid retrieval combining Qdrant vector search and OpenSearch BM25 (reciprocal rank fusion or similar), both already ACL-pre-filtering per this phase's work — Phase 3 wires them together behind one retrieval interface rather than adding new tenant/ACL logic.
2. Reranker adapter (the 5th of the 8 fixed core ABCs still unimplemented) — cross-encoder or provider-hosted, verified against real installed API before use.
3. Retrieval-quality evaluation harness (even a minimal golden-query set) so later phases (orchestration, guardrails) have a regression baseline before more moving parts are added.

## Phase 3 — Retrieval & reranking
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
