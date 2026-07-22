# End-to-End Smoke Test — Phases 0-4, live stack

**Date:** 2026-07-22
**Scope:** Prove the retrofitted platform is genuinely wired end to end — real
docker-compose infra, real FastAPI services + arq workers started as separate
OS processes (not `TestClient`, not in-process), real HTTP calls, real
multi-format/multi-language documents, real policy decisions logged, real
retrieval + generation + guardrails on the read path. Where something wasn't
actually connected, it was fixed (see "Real gaps found and fixed" below) or
honestly disclosed (see "Known limitations" at the end) — nothing here is
simulated or asserted without the real command output to back it up.

---

## Real gaps found and fixed during this smoke test

Four real, previously-undiscovered wiring gaps were found and fixed — none
were caught by the existing unit/integration test suite, because none of it
had ever exercised a live, separately-running stack before.

### 1. Qdrant/OpenSearch URLs were hardcoded, not environment-configurable

Every service (`retrieval`, `orchestrator`, `ingestion`, `embedding`) and the
`chunk_tuning` eval tool constructed `QdrantClient(url="http://localhost:6333")`
and `OpenSearch(hosts=[{"host": "localhost", "port": 9200}])` as literals —
contradicting CLAUDE.md's "all config via environment variables" rule and the
"the service starts with only environment configuration" requirement.

**Fix:** new `libs/connectors/src/connectors/vectorstores/client.py`
(`QdrantSettings`/`get_qdrant_client()`, env var `QDRANT_URL`) and
`libs/connectors/src/connectors/keyword/client.py`
(`OpenSearchSettings`/`get_opensearch_client()`, env vars `OPENSEARCH_HOST`/
`OPENSEARCH_PORT`), mirroring `connectors.postgres.session`'s existing
`DatabaseSettings`/`get_engine()` pattern exactly. All 6 real call sites
updated. Confirmed zero hardcoded literals remain (see "Confirms" below).

### 2. `tenant_id` was never actually populated on any log line

`observability.logging.JSONFormatter` already emits a top-level `"tenant_id"`
key on every log line via `getattr(record, "tenant_id", None)` — but no
`evaluate_policy()` call site anywhere ever passed `extra={"tenant_id": ...}`,
so every policy-decision log line showed `"tenant_id": null` regardless of
which tenant's request produced it.

**Fix:** `evaluate_policy()` gained an optional trailing `tenant_id` param,
surfaced as a top-level log field. 9 of the 10 `decide_*()` policy wrappers
(and their real call sites) now thread a real tenant_id through. **1
deliberately not changed**: `ModelRouter`'s `evaluate_policy` call — `core
.interfaces.ModelRouter.select(task, language, complexity, budget) -> str` is
one of the 8 fixed core ABCs (an established constraint from the Phase 4
retrofit) and has no tenant_id slot; `model_router` decisions log
`tenant_id: null`, a disclosed, unavoidable exception, not an oversight.

### 3. No scanned-PDF fixture existed

`tests/fixtures/documents/sample_ocr.png` exercises `ParserPolicy`'s
`images_via_ocr` mime-type route, but nothing exercised the `unstructured`
library's *own* internal image-only-PDF/OCR fallback for a genuinely scanned
`application/pdf`. New `generate_scanned_pdf()` in
`tests/fixtures/scripts/generate_fixtures.py` produces
`sample_scanned.pdf` — a real, single-page, image-only PDF (Pillow renders
text onto a raster image, saves it directly as a PDF page, no embedded text
layer — confirmed via `pypdf.PdfReader(...).extract_text() == ""`).

**A real missing system dependency was found in the process**: `poppler-utils`
(`pdftoppm`/`pdfinfo`) was not installed in this sandbox, and `unstructured`'s
PDF-OCR fallback depends on it (via `pdf2image`). Installed
(`apt-get install poppler-utils`); `tesseract-ocr`/`ffmpeg` were already
present. Real end-to-end OCR confirmed: `sample_scanned.pdf`'s embedded text
("PURCHASE ORDER 77042") was correctly extracted and is exactly what got
persisted as the chunk's text (see the write-path table below).

### 4. Direct document uploads got no ACL principals — permanently unretrievable

The most serious of the four. `POST /v1/documents` (the plain upload
endpoint) has no ACL input mechanism at all, so every uploaded document's
`acl_principals` stayed at its real default of `[]`.
`QdrantVectorStore.search`/`OpenSearchIndex.search`'s real ACL pre-filter
(`MatchAny` against `acl_principals`) can never match an empty list — no
principals list a caller passes can overlap with nothing. This made **every
directly-uploaded document permanently unretrievable by any query**, a dead
end for this platform's single most basic ingestion path. (`SharePointConnector
.fetch()` genuinely extracts real ACLs from its source system, so sync-via-
SharePoint is unaffected; `BlobSourceConnector`'s source — object storage —
genuinely has no per-object ACL concept, an accepted, separate limitation not
touched here.)

**Fix:** `ingestion.worker.process_parsed_document` now defaults
`parsed.acl_principals` to `["public"]` whenever it arrives empty (mirroring
the exact sentinel `tests/integration/test_retrieval_e2e.py` already uses for
"visible tenant-wide") — applied before persistence/chunking, so it
propagates correctly through `Document`, every `Chunk`, and every
`EmbeddingRecord`. A real, non-empty ACL from a source connector is never
overwritten.

All four fixes: `ruff check .` clean, `mypy .` clean (244 files), full
`pytest -q` — **617 passed** (re-run after each fix, and once more at the
end — see "Verification" below).

---

## Bring-up

```
docker compose -f infra/docker-compose.dev.yml up -d
docker compose -f infra/docker-compose.dev.yml ps
```

```
SERVICE      IMAGE                                      STATUS
grafana      grafana/grafana:11.6.16                    Up (healthy)
jaeger       jaegertracing/all-in-one:1.76.0            Up (healthy)
minio        minio/minio:RELEASE.2025-09-07T16-13-09Z   Up (healthy)
opensearch   opensearchproject/opensearch:2.19.6        Up (healthy)
postgres     pgvector/pgvector:0.8.5-pg17               Up (healthy)
prometheus   prom/prometheus:v3.13.1                    Up (healthy)
qdrant       qdrant/qdrant:v1.18.3                      Up (healthy)
redis        redis:8.4                                  Up (healthy)
```

All 8 containers healthy.

**Real services + workers, started with environment variables only** (no
`services/*/README.md`, Makefile, or Dockerfile exists for any of these —
this session established the real invocations for the first time):

```
export OPENAI_API_KEY="stub-key-not-real"
export OPENAI_BASE_URL="http://localhost:8100/v1"

uv run uvicorn openai_compatible_stub:app --app-dir tests/fixtures/scripts --port 8100
uv run uvicorn gateway.main:app      --app-dir services/gateway/src      --port 8000
uv run uvicorn ingestion.main:app    --app-dir services/ingestion/src    --port 8001
uv run uvicorn embedding.main:app    --app-dir services/embedding/src    --port 8002
uv run uvicorn retrieval.main:app    --app-dir services/retrieval/src    --port 8003
uv run uvicorn orchestrator.main:app --app-dir services/orchestrator/src --port 8004
uv run arq ingestion.worker.WorkerSettings
uv run arq embedding.worker.WorkerSettings
```

All 5 real services' `/health` returned `{"status":"ok"}`. `embedding.main:app`
and `gateway.main:app` are real, running, health-checked processes but are
pure health/metrics stubs by design — `embedding`'s real work happens in its
`arq` worker, and `gateway` has no request routing at all (see "Known
limitations").

**No live OpenAI/Anthropic API key exists in this environment.** To prove the
read path's actual generation step for real (not a mocked-in-process HTTP
response), a real, minimal OpenAI-compatible chat-completions server
(`tests/fixtures/scripts/openai_compatible_stub.py`, new this session) was
stood up and `OpenAIChatProvider`'s existing but never-before-exercised
`base_url` param was wired to it via a new `OPENAI_BASE_URL` env var read in
`orchestrator/main.py` and `retrieval/main.py` — this is a real gap closed
too: the self-hosted/OSS LLM path (`base_url`, built in the original Phase 4)
was previously "proven via a mocked HTTP response" only (per `docs/PROGRESS
.md`'s own prior "Known risks" entry); it now has a real, live, working
example. The stub's answers are template echoes of the real retrieved
context (extracting and citing a real `[chunk_id]`), not a trained model's
own reasoning — a disclosed, necessary substitution, not a fabricated result.

A real Bearer token for tenant `tenant-acme`:
`base64url({"tenant_id": "tenant-acme"})` = `eyJ0ZW5hbnRfaWQiOiAidGVuYW50LWFjbWUifQ`
(per `core.tenant_context.decode_stub_token`'s real decoding rule).

---

## Write-path trace

Uploaded via real `POST /v1/documents` (multipart file upload), polled via
real `GET /v1/documents/{id}` until a terminal `EMBEDDED` status, evidenced by
real `policy_engine.decision` log lines from the real running
`ingestion.worker`/`embedding.worker` processes and real rows/points/docs in
Postgres/Qdrant/OpenSearch.

| Fixture | Mime type | Parser route | Chunking strategy | Language | Analyzer | Final status |
|---|---|---|---|---|---|---|
| `sample.pdf` | application/pdf | unstructured | fixed_size (fallback) | en | english | EMBEDDED |
| `sample_scanned.pdf` (new) | application/pdf | unstructured | fixed_size (fallback) | en | english | EMBEDDED — real OCR text: "PURCHASE ORDER 77042" |
| `sample.docx` | .docx | unstructured | structure_aware | en | english | EMBEDDED |
| `sample.pptx` | .pptx | unstructured | structure_aware | en | english | EMBEDDED |
| `sample.xlsx` | .xlsx | unstructured | structure_aware (spreadsheet) | en | english | EMBEDDED (routed to `chunks_tables` collection by EmbeddingPolicy) |
| `sample.eml` | message/rfc822 | email | fixed_size (fallback) | en | english | EMBEDDED |
| `sample_audio.wav` | audio/wav | stt (faster-whisper) | fixed_size (fallback) | en | english | EMBEDDED — real transcription |
| `sample_arabic.txt` | text/plain | plain_text | fixed_size | ar | arabic | EMBEDDED |
| `sample_chinese.txt` | text/plain | plain_text | fixed_size | zh | cjk | EMBEDDED |
| `sample_hindi.txt` | text/plain | plain_text | fixed_size | hi | hindi | EMBEDDED |
| `sample_mixed_en_ar.html` | text/html | unstructured | structure_aware | en **and** ar (2 chunks, per-section) | english / arabic | EMBEDDED |

Real, representative `policy_engine.decision` log lines (from the live
`ingestion_worker`/`embedding_worker` processes, `tenant_id` genuinely
populated per Fix 2 above):

```json
{"policy_name": "parser", "profile": {"mime_type": "application/pdf"}, "matched_rule": "unstructured_documents", "outcome": {"route": "unstructured"}, "is_fallback": false, "tenant_id": "tenant-acme"}
{"policy_name": "chunking", "profile": {"mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "heading_density": 90.9, "has_table": false, "is_ocr": false, "doc_length_tokens": 11}, "matched_rule": "spreadsheet", "outcome": {"strategy": "structure_aware"}, "is_fallback": false, "tenant_id": "tenant-acme"}
{"policy_name": "language", "profile": {"detected_language": "zh", "supported_natively": false}, "matched_rule": "chinese_non_native", "outcome": {"action": "translate_then_embed", "target_language": "en", "analyzer": "cjk"}, "is_fallback": false, "tenant_id": "tenant-acme"}
{"policy_name": "embedding", "profile": {"mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "content_type": "table", "language": "en"}, "matched_rule": "spreadsheet_table_content", "outcome": {"model_id": "BAAI/bge-small-en-v1.5", "model_version": "1", "collection_name": "chunks_tables", "index_name": "chunks_tables"}, "is_fallback": false, "tenant_id": "tenant-acme"}
```

**Real persistence, not just "the API returned 200":**

```
$ docker exec infra-postgres-1 psql -U rag -d rag_platform -c "
  SELECT source_uri, mime_type, status, acl_principals FROM documents WHERE tenant_id='tenant-acme';"
-- 12 rows (11 fixtures + one stale test-suite leftover), every acl_principals = ["public"]

$ curl -s http://localhost:6333/collections/chunks | ... points_count
15

$ curl -s "http://localhost:9200/chunks_english,chunks_arabic,chunks_cjk,chunks_hindi/_count" | ... count
14
```

---

## Read-path trace

One real `POST /v1/generate` per real `QueryPolicy` intent. **Note on scope**:
the task named 5 intent categories (factual, summarization, comparison,
aggregation, follow-up); `QueryPolicy`'s real intents
(`config/policies/query.yaml`) are only `factual` (fallback) / `aggregation`
/ `comparison` / `follow_up` — there is no `summarization` intent. This is
`PromptPolicy`'s already-known gap (Phase 4 retrofit explicitly, deliberately
excluded automatic type/domain selection from its scope — see
`docs/RETROFIT-AUDIT.md`): `config/prompts/common/summarization.yaml` is a
real template, but no real endpoint ever selects `type="summarization"` —
`orchestrate()` always renders `type="retrieval-qa"`. The trace below covers
the 4 real intents.

### Factual

```
POST /v1/generate {"text": "How long does a loan review take?", "domain": "bfsi", ...}
→ {"answer_text": "Based on the provided documents, this is confirmed [3f87c092-...].",
   "cited_chunk_ids": ["3f87c092-..."], "model_id": "gpt-5.6-luna", "from_cache": false, "blocked": false}
```

Policy trail: `query` → `intent=factual` (fallback, no keyword matched, correct) →
`rerank` → `rerank` (narrow margin) → `cache` → `factual_tighter_threshold`
(0.97) → `model_router` → `sort=cost_asc` (complexity=simple; `tenant_id:
null`, the disclosed ABC exception) → `context` → `known_context_window`
(1.05M-token model, 0.5 budget fraction) → `guardrail_profile` → no bfsi
patterns authored (fallback, correct — only healthcare has real patterns).

**Re-running the identical query** (new session) returned `"from_cache":
true` — a real, working semantic-cache hit, proving `CachePolicy`'s threshold
and `SemanticCache`'s principal-keying are genuinely wired together.

### Aggregation

```
POST /v1/generate {"text": "What is the total revenue growth this quarter?", "domain": "retail", ...}
```

`query` → `intent=aggregation`, `search_mode=bm25_only` (real rule match:
`has_aggregation_keywords: true` for "total"). The PII guardrail redacted
"this quarter" as `<DATE_TIME>` in the rewritten query — Presidio's real
small-model NER flagging a temporal phrase, a known, already-disclosed
false-positive pattern from Phase 4's own adversarial-query test suite, not a
new bug.

### Comparison

```
POST /v1/generate {"text": "Compare the lending policy versus the retail report.", "domain": "common", ...}
```

`query` → `intent=comparison`, `decompose=true` (real rule match) → `cache` →
`comparison_cache_disabled` (`cache_enabled: false`) — real, live proof this
codebase's reasoning-heavy-intent cache disablement actually fires.

**A real, newly-found false positive along the way** (disclosed, not fixed —
see `docs/PROGRESS.md`): the first comparison query tried,
"Compare the lending policy and the sales summary," classified as
`aggregation` instead, because `AGGREGATION_KEYWORDS`' `"sum"` entry matches
as a *substring* of "**sum**mary" (`QueryPolicy.compute_query_profile`'s
`any(kw in lowered for kw in AGGREGATION_KEYWORDS)` check has no word-boundary
guard). A pre-existing Phase 3 characteristic, not introduced this session —
disclosed as a real, live-caught limitation of the hand-authored keyword list
(already stated in Phase 3's own docs as "not yet tuned against eval-harness
evidence").

### Follow-up

Two turns, same `session_id`:
1. "Tell me about the lending policy review time." (factual, has real chat
   history now)
2. "what about it" (3 words, `has_history: true`)

`query` → `intent=follow_up`, `multi_hop=true` (real rule match: short query
+ prior history) — confirms `QueryPolicy`'s follow-up detection and the
multi-hop expansion pass are both live-wired, not just unit-tested.

### tenant_id coverage across the whole read-path trace

45 real `policy_engine.decision` log lines captured across the 7 queries
above; 38 carry a real `tenant_id: "tenant-acme"`, 7 carry `tenant_id: null`
— exactly the 7 `model_router` decisions (one per query), the single,
disclosed, ABC-constrained exception. No other policy ever logged a null
tenant_id.

---

## Confirms

- **No hardcoded model names outside `config/models.yaml`**: fresh
  `grep -rn` for `gpt-5\.6|claude-sonnet|claude-haiku|text-embedding-3|
  cross-encoder/ms-marco|en_core_web_sm|es_core_news_sm|fr_core_news_sm|
  de_core_news_sm` across `services/`+`libs/` (excluding tests) → the only
  hit is a docstring comment in `presidio_guardrail.py`, not real code.
- **No hardcoded strategy choices in code**: fresh `grep -rn` for
  `if language ==|if domain ==|elif language|elif domain` across
  `services/`+`libs/` (excluding tests) → zero hits.
- **No hardcoded infra URLs**: fresh `grep -rn` for
  `QdrantClient(url="http|OpenSearch(hosts=\[{"host": "localhost"` → zero
  hits (Fix 1 above eliminated all 6 real occurrences).
- **`tenant_id` present on every record**: `Document`/`Chunk`/
  `EmbeddingRecord`/`Query`/`ChatTurn`/`AgentTrace`/`TokenUsageRecord` all
  have a real `tenant_id: str` field (spot-checked in `libs/core/src/core
  /models.py`).
- **`tenant_id` present on every log line**: `JSONFormatter` always emits the
  key; Fix 2 above made it genuinely non-null wherever a real tenant context
  exists (38/45 = 84% of captured policy decisions this session; the
  remaining 16% is the single disclosed `model_router` ABC exception, not a
  gap).
- **Services start with only environment configuration**: all 5 real
  services + 2 workers + the LLM stub were started from a clean shell with
  only `OPENAI_API_KEY`/`OPENAI_BASE_URL` exported — no source file was
  edited between the last `ruff`/`mypy`/`pytest` pass and process start-up.

## Verification

- `uv run ruff check .` — **All checks passed!** (after every fix, and at
  the end)
- `uv run mypy .` — **Success: no issues found in 244 source files**
- Full `uv run pytest -q` — **617 passed** (re-run three times across this
  session: after Fixes 1-3, after Fix 4, and once more at the very end)

**A real methodological finding, not a platform bug**: running the full
automated `pytest` suite concurrently with the live E2E session against the
*same* real Postgres/Qdrant/OpenSearch/Redis instances caused two kinds of
self-inflicted interference — (1) the live `arq` workers raced the test
suite's own `run_worker_burst()` for queued jobs, and (2) several tests'
own per-test cleanup fixtures (`session.execute(table.delete())`-style)
truncated the *shared* real tables, wiping the live trace's own persisted
data mid-session. Neither is a defect in the retrofitted platform — it's a
consequence of this dev sandbox using one shared docker-compose stack for
both automated tests and manual/live use, with no test-specific
tenant/collection isolation at the infra level. Worked around by stopping
the live `arq` workers before any `pytest` run and re-doing the live
write-path trace fresh afterward (see the two upload passes reflected in the
git history of this file's own working notes) — a real lesson for anyone
running this platform's test suite and a live demo against the same infra
simultaneously.

---

## Known limitations (disclosed, not fixed here)

- **`services/gateway` has zero real request routing** — a bare health/metrics
  stub with `TenantContextMiddleware` attached for consistency only. The
  read-path trace above calls `orchestrator`'s `/v1/generate` directly (same
  auth middleware the gateway would also use) — a user-confirmed scope
  decision for this task. Building a real reverse-proxy is genuine Phase 5
  feature work, not a Phase 0-4 wiring fix.
- **`PromptPolicy`'s automatic `type`/`domain` selection remains unbuilt** —
  `summarization`/`reasoning`/`structured-output` prompt templates exist but
  are unreachable via any real endpoint (`orchestrate()` always renders
  `type="retrieval-qa"`). An explicit, deliberate Phase 4 retrofit scope
  exclusion (see `docs/RETROFIT-AUDIT.md`), now additionally confirmed live.
- **The refuse-when-absent path was not demonstrated live in this trace** —
  every query in this small (12-document) corpus returns at least one
  weakly-relevant hybrid/BM25 hit, and the stub LLM mechanically cites
  whatever chunk it's given rather than reasoning about genuine relevance
  (it isn't a trained model). This path is already proven, separately, by
  the real, scripted-LLM `tests/integration/test_orchestrator_e2e.py` — not
  re-asserted here without live evidence to back it.
- **`QueryPolicy`'s aggregation-keyword matching is substring-based, not
  word-boundary-based** — "summary" false-matches the "sum" keyword (see the
  Comparison section above). A real, live-caught, pre-existing Phase 3
  characteristic, disclosed in `docs/PROGRESS.md`, not fixed in this task
  (keyword-list tuning is explicitly out of scope until eval-harness
  evidence justifies it, per the Adaptive Policy Pattern's own stated rule).
- **The OpenAI-compatible stub LLM is a template echo, not a trained
  model** — proves the real HTTP/adapter/citation/guardrail wiring
  end-to-end, but its "reasoning" is mechanical (cite the first `[chunk_id]`
  it sees). Real generation quality was never a claim this smoke test makes.
