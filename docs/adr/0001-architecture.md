# ADR 0001: Monorepo, Ports-and-Adapters, Tenant-First Architecture

## Status
Accepted

## Context
We are building a multi-tenant RAG platform serving BFSI, Retail, and
Healthcare customers, each with different compliance requirements and vendor
preferences (vector store, LLM provider, embedding model). The platform must
let a customer swap any of these vendors without a code change, must never
leak one tenant's data to another, and must survive model/API churn over a
9-12 month build without needing a rewrite.

Three architectural risks drove this decision:
- Coupling business logic to a specific vendor SDK (e.g. calling the Qdrant
  client directly from retrieval logic) makes swapping vendors per-customer
  expensive.
- Retrofitting `tenant_id` and hard-delete support after data already exists
  in vector stores/caches is significantly more expensive than building it in
  from the first commit (see docs/GAP-MATRIX.md rows on hard-delete and
  ACL capture).
- Model/API names and signatures drift constantly; hardcoding them in
  business logic causes silent breakage on provider-side changes.

## Decision
1. **Monorepo with ports-and-adapters.** One repository (`rag-platform/`)
   split into `services/` (deployable units), `libs/core` (interfaces +
   shared models, no vendor imports), `libs/connectors` (the only place
   vendor SDKs are imported), and `libs/observability`. The full layout and
   data flow are recorded verbatim in `docs/ARCHITECTURE.md` and are treated
   as fixed — implementation adapts to this contract, not the reverse.
2. **Every core interface is an ABC** (`DocumentParser`, `Chunker`,
   `EmbeddingProvider`, `VectorStore`, `Reranker`, `LLMProvider`,
   `ModelRouter`, `Guardrail`), defined once in `libs/core/interfaces.py`.
   Concrete adapters are added phase by phase; business logic depends only on
   the interface.
3. **`tenant_id` is mandatory on every core Pydantic model** from Phase 0,
   before any real data exists, so no later migration is needed to retrofit
   tenant scoping.
4. **Model/provider identifiers never appear in code.** They live in
   `config/models.yaml`, each entry gated by a `verified_before_deploy` flag a
   human must set after checking provider docs.
5. **uv workspace** for dependency management: a single lockfile across all
   `services/*` and `libs/*` members, chosen over Poetry for native multi-package
   workspace support and faster CI installs.

## Consequences
- Adding a new vendor (e.g. a new vector store) means writing one adapter in
  `libs/connectors` against an existing interface — no changes to
  `services/retrieval` business logic.
- Every phase's plan must be checked against `docs/GAP-MATRIX.md` before
  work starts, so capability rows mapped to that phase aren't silently
  dropped.
- The interface set in `libs/core/interfaces.py` is intentionally minimal in
  Phase 0 (method signatures only, no adapters) — Phases 1-4 add concrete
  adapters without changing the interfaces themselves. If an interface later
  proves insufficient, that is itself an ADR-worthy decision, not a silent
  edit.

## Alternatives considered
- **Per-service repositories** instead of a monorepo: rejected because the
  shared `libs/core` contract would need to be versioned and published
  separately, adding release overhead disproportionate to a pre-launch
  platform with a single team.
- **No ports-and-adapters, call vendor SDKs directly**: rejected because it
  was the fastest path to vendor lock-in, which conflicts with the
  BFSI/Retail/Healthcare requirement that customers pick their own cloud and
  vendor stack.
