# Changelog

## Unreleased

### Phase 8 held-out evaluation (one observational run of the frozen candidate, test split; 2026-11-12)
- Frozen candidate (hash 4e24e63f...) versus the unchanged baseline on the frozen test split: retrieval, abstention, review burden and numeric safety improved; grounded coverage, citation correctness and the unsupported-answer rate did not replicate the dev gains (small samples, not significant). Report: docs/evaluation/phase8-heldout-report.md. Challenge split not run; nothing tuned; the candidate is not production-ready.

### Phase 8 (in progress; development split only) - evaluation foundation and controlled optimisation
- eval-v2 dataset (both tenants, 215 queries, 60 incident cases, frozen splits and hashes), metric/scoring code with hand-calculated tests, baseline (3 repetitions; the first attempt is preserved as INVALID), integrity verifier, erratum E-001, original V4.1 specification preserved (reconciliation pending, completeness UNVERIFIED).
- Quality switches (`EAOP_TUNING`, all default to the baseline): identifier boost, entity and override gates, citation completion, numeric measurement audit (migration 0007), asset-context guidance query. Development candidate hash `4e24e63f...`; two quality targets (grounded coverage, citation correctness) remain unmet on dev; held-out evaluation not run.
- Reports: docs/evaluation/phase8-candidate-report.md, phase8-optimization-log.md, phase8-baseline-report.md.

### Phase 7 - Reliability, acceptance, observability, traceability
- Fault injection: FI-01..FI-10 (+FI-09b) re-run with data-integrity, duplicate-action and log evidence; REL-01..REL-04 added for LLM failure, embedding failure, invalid structured AI output and API restart (docs/reliability/fault-injection-results.md).
- Hardening found by those scenarios: embedding failures return 503 `embedding_unavailable`; a model-claimed asset id absent from the report is rejected for every model client.
- Customer acceptance UAT-A01..A08 and UAT-B01..B07 in deterministic and real-AI modes, plus end-to-end reliability tests for both customers (docs/customer-acceptance/uat-results.md).
- Observability: redacted JSON logs, tenant-labelled in-process metrics, `/api/v1/observability/summary`, telemetry card on the Integration health page, reproducible evidence under evaluation/observability.
- Requirements traceability matrix (83 requirements, generator and consistency test) in docs/traceability.
- Test-infrastructure fix: the shared service-desk mock now resets per test.
- Gate: docs/phase7/phase7-gate.md.

### Phase 6 - Full 13-page frontend
- Shared React/TypeScript UI for Apex and Meridian: Overview, Customer Onboarding, Data Sources, Document Library, AI Knowledge Assistant, Incident Explorer, Support Tickets, Approval Queue, Workflow History, Integration Health, Evaluation Dashboard, Audit Logs, Administration. Session expiry handling, role-aware navigation, provenance labels (AI-generated / retrieved evidence / verified / human-reviewed / approved / submitted), confirmation dialogs, server-side search/sort/pagination, responsive layout.
- Backend support: list filters and sorting, ticket/incident history, extended metrics, connector health, onboarding health checks, evaluation evidence endpoint.
- Tests: 43 Vitest, 39 Playwright (deterministic stack), 3 Playwright real-AI smoke tests, 10 backend tests for the new endpoints; ESLint added.
- Report: docs/phase6/phase6-review-report.md.

### Phase 5 closure - connector egress security, Apex compatibility, Meridian smoke evidence
- Connector SSRF protection (`app/connectors/egress.py`, migration 0006): server-controlled per-tenant origin allow-list, address validation (IPv4/IPv6, metadata, alternative encodings), DNS-pinned connections, no redirects, enforced on every request including worker retries and enrichments; development-only mock exception refused in production. 79 tests.
- Apex compatibility evidence (golden outputs from commit 44b1083, rules module hash, Phase 3 prompt hash) and a documented plan for unifying the two execution paths.
- Release-gate regression: retry of a failed ticket re-checks the incident gate.
- Meridian real-AI smoke evaluation (17 functional checks, raw outputs preserved; not a benchmark).
- Per-process rate-limit limitations documented.

### Phase 5 - Meridian Fleet Logistics (second customer, configuration only)
- Tenant profiles (migration 0005, `/api/v1/tenant-profile`): domain vocabulary, categories, numeric signals, deterministic priority rules, enrichments and CSV mappings are configuration; Ollama extraction prompt/schema built from the profile; ticketing contract (`create_path`, `payload_map`, `priority_map`, `id_field`) lives on the connector. Tenants without a profile behave exactly as before.
- Meridian: `onboarding/meridian.json` applied by `scripts/onboard_tenant.py` through public APIs only; fictional fleet documents (PDF/CSV) with column mappings; mock fleet telematics, CRM and service-desk (different work-order API) services.
- Tests: 12 Meridian integration, 28 profile engine (including equivalence with the built-in rules), 3 real-AI Meridian/both-tenant tests; cross-tenant isolation across APIs, retrieval, workflows and external systems.
- Phase 4 closure: strengthened review gate (unregistered assets must be re-verified against the register before approval/submission; worker defence in depth), identity-table RLS and audited platform administration (migration 0004), request-size limits and bounded concurrency, AI quality re-measured on the frozen Phase 3 split (no change; citation target still NOT MET).

### Phase 4 - Security hardening and reliability
- Dev config on real AI (ollama + sentence_transformers); functional tests/CI force deterministic backends; `scripts/ollama_ctl.py` start/stop/status; configurations documented (docs/operations/configurations.md).
- Safeguards: citation source/tenant ownership checks, identifier and number support checks (numbers must be in cited evidence), incident `needs_review` gate with audited human review endpoint and UI.
- Hardening: malformed JWT claims -> 401, DB outage -> 503, login throttle, authorization before validation on member endpoints, poison outbox events dead-lettered, concurrent-upload race resolved as duplicate.
- Tests: 111 functional passed + 10 opt-in/skipped; route-table authorization matrix over every OpenAPI route; 9 mutation-style control proofs; fault injection FI-01..FI-10 (11/11 passed) with JSON/Markdown reports; 9 real-AI tests.
- Phase 3 evidence untouched; AI-quality targets remain not met. Phase 8 dataset plan: docs/evaluation/phase8-dataset-plan.md.

### Phase 3 - Real local AI (Ollama + MiniLM)
- Providers: Ollama LLM (qwen2.5:1.5b, structured JSON output, per-call latency/token stats) and Sentence Transformers embedder (all-MiniLM-L6-v2 pinned to a commit, offline loading). Deterministic backends remain for functional tests/CI only; functional tests force them regardless of `.env`.
- Embedding profiles (migration 0003): provider/model/revision/dimension recorded per tenant and per chunk; mixing or querying with an incompatible model is refused (HTTP 409); atomic, repeatable reindex tool with count/dimension verification, index rebuild and retrieval self-check. Both dev tenants migrated to MiniLM.
- Evidence gate now similarity-only for the real embedder (threshold 0.50, calibrated on the dev split); retrieval ablations (vector-only, text-only).
- Evaluation: `apex-eval-v1` synthetic dataset and `evaluation/benchmarks/run_phase3.py` (isolated `eaop_bench` database); three real-AI runs and one deterministic baseline with manifests; `SUMMARY.md` generated from results.
- Tests: 72 functional (deterministic) + 8 real-AI (opt-in) backend tests, 3 frontend tests.
- Known gaps: citation correctness 89-93% (target 95%, not met); about 22% of answerable questions are withheld or refused by the 1.5B model; precision@5 ceiling is 0.2; corpus of 86 chunks; no UI re-verification under real AI.

### Security hardening (post Phase 2 review)
- PostgreSQL RLS on memberships (migration 0002) with member list/role-change/removal endpoints; 12 new tests (9 membership, 3 fixture isolation).
- apex-uitest is now an explicitly marked, deterministic, development-only fixture (scripts/seed_uitest.py).

### Phase 2 - Apex vertical slice
- Backend: auth/RBAC, tenant isolation with PostgreSQL RLS, ingestion, hybrid retrieval, verified citations, incident extraction, ticket state machine, approvals, outbox worker, mock ticketing/inventory, audit log, metrics.
- Minimal React UI (login, assistant, incidents/tickets, approvals, documents, audit).
- Tests: 66 backend (pytest) and 3 frontend (vitest) passing locally with deterministic test-only AI backends.
- Limitations: no real LLM/embedding validation yet; CI not yet executed; see docs/architecture/phase2-apex-slice.md.

### Phase 1 - Foundation
- LICENSE, notices inventory, repo structure, Docker Compose (PostgreSQL 16 + pgvector), hardware capture script, CI skeleton.
