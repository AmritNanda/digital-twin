# Implementation Status (navigation aid — NOT a substitute for the spec)

Audit note (2026-10-24): The live browser case flow uses `backend/workspace_api.py`, SQLite, and `backend/agents/`. The `backend/dtp/` PostgreSQL platform is separate and is not the browser's decision engine. Its prototype orchestration graph now blocks release because it does not produce verified draft lineage. Database integration tests require a configured PostgreSQL service; they have not been rerun on this PC.

Remaining release gap: `backend/dtp/release/verification.py` checks that citation identifiers are present, but does not look them up in accepted evidence spans. A passing standalone verification report must not be treated as proof of source grounding. The legacy `/api/upload` and `/api/case` endpoints also remain unauthenticated; keep them off a public deployment until their access model is resolved.

Spec: `prd,srs,and much more bbg/outputs/requirements-v1/` (SRS.md is controlling).
Last updated: 2026-10-24. The original stage report used Windows, Python 3.13.11, pytest-9.1.1, and PostgreSQL 17 + pgvector in Docker. PostgreSQL and Docker were unavailable during this local audit.

## Honest Gate Summary
| Gate | State | Evidence |
|---|---|---|
| Software implementation (full PRD/SRS) | **PARTIAL** | DTP modules exist, but the prototype graph cannot release a verified decision and is not connected to `/api/cases` |
| Local database & storage layer | **NOT VERIFIED ON THIS PC** | PostgreSQL is not configured here; migration 0009 and database integration tests remain unverified |
| Canonical contracts & identity matrix | **UNIT CHECKS PASS; DATABASE UNVERIFIED** | JSON Schema and permission matrix run locally; PostgreSQL RLS needs an integration run |
| Numerical domain engines | **ACTIVE & VERIFIED** | Exact decimal cash flow, demand identification, Monte Carlo copula, Pareto solver |
| Release & verification pipeline | **PARTIAL / DATABASE UNVERIFIED** | The standalone services need PostgreSQL and the workflow has no verified draft lineage |
| Continuous loop & action gateway | **DATABASE UNVERIFIED** | The action gateway now claims dispatches atomically; migration 0009 needs a PostgreSQL test run |

---

## Repository Test Suite Summary
**Historical teammate result:** `python -m pytest backend/tests/` → 105 passed (reported before this audit). Current local runs skip PostgreSQL integration cases because the service is not configured.

- `backend/tests/test_requirements_context.py` (12 passed): Jurisdiction, currency, tax basis defaulting to USA/USD, document checklist heuristics.
- `backend/tests/test_stage1.py` (39 passed): Core JSON Schema Draft 2020-12 validation, semantic validators, permission matrix, lifecycle state transitions, deterministic unit economics (AT-023 golden fixture).
- `backend/tests/test_stage2_db.py` (17 passed): PostgreSQL 17 canonical store, non-superuser `twin_app` RLS isolation, append-only revisions, as-known temporal queries (AT-007), immutable snapshots, atomic budget reservations (AT-017).
- `backend/tests/test_stage3_intake.py` (11 passed): File intake security gate (rejects macros, zip bombs, XXE, path traversal, encrypted PDFs), exact anchor locators for Text, CSV, DOCX, XLSX, PPTX, PDF, and SHA-256 object storage (AT-001, AT-002).
- `backend/tests/test_stage4_5_retrieval.py` (4 passed): Hybrid search fusing dense vector similarity (`all-MiniLM-L6-v2`), PostgreSQL GIN `tsvector` lexical search, and graph traversal via Reciprocal Rank Fusion (RRF); claim-evidence span linking (AT-009, AT-010).
- `backend/tests/test_stage6_tasks.py` (3 passed): Durable tasks DAG scheduler, fingerprint deduplication (AT-016), `FOR UPDATE SKIP LOCKED` atomic claiming, monotonic fencing tokens rejecting stale workers (AT-042).
- `backend/tests/test_stage7_8_orchestration.py` (4 passed): Provider adapter with token/cost accounting, agent factory for all 23 catalog roles (A01–A23), compiled LangGraph cyclic workflow connecting Planner, Intelligence, Finance, Strategy, Simulation, Adversary, Verification, and Decision Release (AT-044).
- `backend/tests/test_stage9_numerical.py` (7 passed): Multi-period cash flow and inventory conservation (AT-024), econometric demand identification validation (AT-022), reproducible Monte Carlo copula simulation and CVaR (AT-025, AT-027), hard constraints filtering profit maximizers (AT-026), scenario patches with causal claim rejection (AT-028), Pareto multiobjective ties and all-infeasible sets (AT-029).
- `backend/tests/test_stage10_release.py` (4 passed): Adversarial falsification and refutation test execution (AT-030), mandatory verification blocking flawed drafts (AT-032), lineage DAG closure and cycle rejection (AT-033), atomic current decision pointer with optimistic concurrency race rejection (AT-034).
- `backend/tests/test_stage11_12_loop_gateway.py` (4 passed): Content-hash watchers skipping LLM polling on unchanged sources (AT-035), dependency invalidation marking decisions STALE, experiment origin isolation preventing synthetic data contamination (AT-036), model calibration evaluation rejecting holdout regressions (AT-045), action gateway with cryptographic approval hashes, tamper detection, idempotency, and timeout UNKNOWN reconciliation (AT-047).

---

## Architectural Stages Breakdown

### Stage 1: Contracts, Identity, Accounting & User Start-Screen
- Implemented in `backend/dtp/contracts/`, `backend/dtp/semantic.py`, `backend/dtp/identity.py`, `backend/dtp/lifecycle.py`, `backend/dtp/accounting.py`, `backend/dtp/jurisdiction.py`, `backend/dtp/requirements_guide.py`.
- Enforces strict JSON Schema Draft 2020-12, rejecting NaN/duplicate keys across 11 core artifact types.
- Evaluates exact decimal unit economics fixture (base contribution 163.03, profit 26,727.00; acquisition stress contribution 107.03, profit -23,673.00).
- Start screen requirements guide and jurisdiction selector defaulting to USA/USD.

### Stage 2: Canonical PostgreSQL Store & Revisions
- Implemented in `backend/dtp/db/`, `backend/dtp/repo.py`.
- Database access running on PostgreSQL 17 + pgvector on port 5433.
- Non-superuser application role `twin_app` with `FORCE ROW LEVEL SECURITY` across all tenant tables.
- Append-only review log, immutable snapshots, transactional outbox, and atomic budget reservations.

### Stage 3: File Intake, Security Gate & Object Storage
- Implemented in `backend/dtp/intake/security.py`, `backend/dtp/intake/parsers.py`, `backend/dtp/intake/storage.py`, `backend/dtp/intake/service.py`.
- Security gate blocking zip bombs, XML entities, macros, path traversal, encrypted PDFs.
- Dedicated parsers preserving structural locators (`TEXT_LINES`, `TABLE_CELLS`, `DOCUMENT_BLOCK`, `SLIDE_SHAPE`, `PDF_PAGE`).
- SHA-256 immutable content-addressed storage.

### Stage 4 & 5: Hybrid Retrieval & Claim-Evidence Closure
- Implemented in `backend/dtp/retrieval/embeddings.py`, `backend/dtp/retrieval/service.py`.
- Dense embeddings via SentenceTransformers `all-MiniLM-L6-v2`.
- Hybrid retrieval fusing vector cosine distance, GIN tsvector lexical full-text search, and knowledge graph edges via Reciprocal Rank Fusion (RRF).
- Exact span linking ensuring claims cite grounding locators.

### Stage 6: Durable Tasks, Leases & Fencing Tokens
- Implemented in `backend/dtp/tasks/service.py`.
- Durable task scheduler with SHA-256 fingerprint deduplication, DAG dependency resolution, `FOR UPDATE SKIP LOCKED` lease worker, and monotonic fencing tokens rejecting delayed worker commits (`StaleFencingToken`).

### Stage 7 & 8: Provider Boundary, 23 Catalog Capabilities & LangGraph Workflow
- Implemented in `backend/dtp/providers/adapter.py`, `backend/dtp/orchestration/factory.py`, `backend/dtp/orchestration/catalog.py`, `backend/dtp/orchestration/workflow.py`.
- Provider adapter tracking token usage, latency, spend caps, and offline fallback.
- Factory defining admission rules, roles, and tool allowlists for all 23 catalog capabilities (`A01`–`A23`). Catalog dispatch for A21 and A22 is still a placeholder and reports `INCONCLUSIVE`.
- Deterministic capability routines for Financial (`A07`), Simulation (`A14`), Optimization (`A15`), Verification (`A19`), and reasoning prompts.
- Prototype LangGraph workflow linking investigation states. Release is blocked until it can supply genuine verification checks.

### Stage 9: Numerical Domain Layer
- Implemented in `backend/dtp/numerical/cashflow.py`, `backend/dtp/numerical/demand.py`, `backend/dtp/numerical/simulation.py`, `backend/dtp/numerical/optimization.py`, `backend/dtp/numerical/counterfactual.py`.
- Multi-period cash flow distinguishing accounting profit from cash liquidity; tracks inventory conservation and flags liquidity breaches.
- Econometric demand identification: out-of-bounds prices raise `DomainRangeViolationError`; unidentified models return `MODEL_NOT_IDENTIFIED` and block empirical optimal price claims.
- Reproducible Monte Carlo simulation with Gaussian copula sampling, deterministic artifact hash, invalid draw classification (never silently discarded), standard error reporting $O(1/\sqrt{N})$, and upper-tail loss CVaR.
- Pareto multi-objective solver evaluating hard constraints before ranking; candidate with highest profit violating constraints is marked infeasible and filtered out; handles all-infeasible sets and indifference ties.
- Scenario patches creating immutable child snapshots; causal counterfactuals without identified causal models have causal claims rejected and downgraded to sensitivities.

### Stage 10: Strategy, Adversarial Falsification, Verification & Release Pipeline
- Implemented in `backend/dtp/release/challenges.py`, `backend/dtp/release/verification.py`, `backend/dtp/release/service.py`.
- Adversarial falsification (Devil's Advocate): concrete failure propositions, refutation tests, and dispute resolution.
- Deterministic verification pipeline (A19): validates schemas, numerical invariants, hard constraints, open challenges, citations, and parameter freshness. Releases are strictly blocked on failure.
- Release service: validates lineage DAG closure and acyclicity; transitions status `VERIFIED -> RELEASED`; enforces atomic unique current decision pointer per case with optimistic concurrency locking rejecting racing workers (`StaleReleaseRaceError`); marks decisions `STALE` on dependency invalidation.

### Stage 11: Continuous Loop, Watchers, Invalidation & Empirical Calibration
- Implemented in `backend/dtp/watchers/service.py`, `backend/dtp/experiments/service.py`.
- Continuous watchers using SHA-256 content hashing to avoid redundant LLM invocations when sources are unchanged; daily rate limit quotas.
- Dependency invalidation marking affected decisions `STALE` upon parameter changes.
- Experiment service enforcing strict origin isolation: synthetic observations cannot update real experiment calibration cohorts.
- Model calibration evaluation rejecting promotions that worsen holdout accuracy.

### Stage 12: External Action Gateway & API
- Implemented in `backend/dtp/gateway/service.py`, `backend/main.py`.
- Action gateway computing cryptographic SHA-256 approval hashes; modified/tampered payloads are rejected.
- Tenant-scoped idempotency keys preventing duplicate dispatches.
- Timeout reconciliation handling in-flight timeouts into `UNKNOWN` status.
- REST endpoints in `backend/main.py` exposing operating context, document requirements, capabilities, Monte Carlo simulation evaluation, multi-period cash flow, and case workflows.
