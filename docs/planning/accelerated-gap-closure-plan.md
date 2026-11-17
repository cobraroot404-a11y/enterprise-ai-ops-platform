# Accelerated gap-closure plan (PLANNING ONLY: nothing here is authorised)

Date: 2026-11-12 (EST). Basis: the reconciled 238-requirement baseline (`docs/specification/v4.1-requirements.json`: 104 unresolved = 66 Partial, 32 Missing, 6 Not evaluable), `v4.1-gap-register.md`, and targeted repository inspection by a read-only planning pass that changed no file. No requirement is marked complete by this document. All 238 original requirements stay in scope; deferrals below are proposals that need an explicit owner decision.

## 1. Updated status after hardening V5 to V8
> **Current status.** [Gate C owner disposition](gate-c-owner-disposition.md) records technical acceptance complete and owner disposition closed for the pinned candidate, with the reproduction and accessibility evidence gaps retained. EAOP 09 is next. Phase 10 exit, publication, and release remain owner-gated.

At this historical planning checkpoint V41-14.02 was **PARTIAL**. After three failed free-text confirmations (V5, V6, V7) the V8 architecture made numeric priority structured-only: free-text and LLM numbers are UNVERIFIED candidates; only signed simulation-fixture observations and human-verified observations are eligible; every priority decision is audited. The frozen safety-v8 run met every safety gate except complete priority-decision provenance (63/64). See `docs/evaluation/numeric-safety-architecture-v8.md`. Open owner decisions: whether to fix the one provenance gap (a single narrow change), whether sensor authentication (class E) and simulation key management are in scope, and the formal acceptance wording. Plan status: Batch 1 (V41-17.03) and Batch 2 (migration 0008 tenant-leading indexes) executed on 2026-11-12; eight of nine API-quality properties verified, the typed-response gap is open (see `docs/planning/batch1-report.md` and `docs/planning/batch2-report.md`); Track A items 12.05, 17.03 and 16.04 are independent of 14.02; Batches B to E and the 104-item classification below are unchanged and remain planning only.

## 2. Classification of the 104 unresolved requirements (counts by primary class)
| Class | Count | Anchor items |
|---|---|---|
| Critical security / safety defect | 1 | V41-14.02 (open; own checkpoint) |
| Missing mandatory functionality | 9 | 12.05 document deletion; 12.03 ingestion job + retry; 12.04 reprocess; 17.04 four missing entity tables or approved deviation; 11.01 CSV/webhook connectors; 11.02 pagination, connector rate limit, live probe; 12.01 REST/webhook ingestion; 32.05, 34.09 (close with 11.x) |
| Incomplete implementation | 6 | 22.01 trace ids/persisted metrics (closes 04.03); 05.06 OpenTelemetry; 09.01 evaluation as managed module; 16.04 distributed rate limiting; 27.01 CI enlargement |
| Missing tests or evidence | 13 | 17.03 API contract/pagination tests; 21.10 + 21.02 recovery and integration-success definition and rates; 26.01; 18.03; 01.04; 02.04 (closes 32.02); 23.04; 34.01; 04.07; 31.02; 34.02 |
| Infrastructure and portability | 21 | 23.01 Dockerfiles + full compose (closes 05.04, 32.20, 34.17); 05.08 Terraform/OpenTofu (closes 24.02, 32.23, 34.27, 04.06); 24.04 portability docs (closes 24.01, 32.22, 34.26); 24.05; 24.07 tradeoffs (closes 32.24, 34.28); optional 24.06, 22.02, 22.03, 23.02 |
| Documentation and handover | 35 | 06.01 discovery; 25.01-25.03 delivery set; 34.23 runbook; 34.25 troubleshooting; 23.03 backup/restore; 29.01/29.02 README; 34.20 diagrams; 03.02 notices; 06.02 traceability; 21.01; 34.24; 27.02; 28.01; 30.01 demo; umbrella rows 01.01, 01.02, 31.01, 34.35, 34.37; 34.34 final report |
| External-dependency blockers | 10 | 02.01, 05.07, 32.21, 34.18 (CI never run; needs a remote); 33.01; 34.31, 32.34, 32.35; 32.36, 34.32 (release) |
| AI-quality targets needing separate authorisation | 9 | 21.04/13.05 citation correctness; 13.04 grounded coverage; 13.06; 21.05 schema validity; 04.04; 34.16; 21.14; 13.03 reranker |

Per-requirement fields (existing status, action, files, dependencies, effort, tests, evidence, risk, workstream, independence, approval) are carried by the work packages below; duplicate statements close with their anchor but stay listed.

## 3. Work packages (effort S 1-4 h, M 4-12 h, L 12-40 h; estimates, not commitments)
| WP | Scope | Effort | Risk | Needs approval/download |
|---|---|---|---|---|
| A2 | Ingestion lifecycle: jobs entity, retry, deletion with audit and RLS, reprocess (migration 0008) | L 18-32 h | H | owner scope decision |
| A3 | API contract tests: pagination, errors, OpenAPI snapshot | S-M 4-8 h | L | no |
| A4 | Rate limiting beyond one process: DB-backed limiter, or documented deviation | M 8-14 h / S 2 h | M | owner decision |
| B1 | Connectors: CSV, webhook, pagination, rate limit, live health | L 16-28 h | M | no |
| B2 | REST/webhook ingestion (HMAC, tenant binding, size limits) | M-L 10-18 h | H | no; needs A2 and B1 |
| B3 | Observability: trace ids, persisted metrics, timings | M 8-14 h | M | no (OTel packages need approval) |
| B4 | Recovery / integration-success suite definition and rates | M 8-14 h | M | suite definition approval |
| B5 | Domain-entity deviation decision or four tables | S 2-4 h / L 16-30 h | M | owner decision |
| C1 | Backend/frontend Dockerfiles, full compose | L 14-24 h | M | base-image pulls |
| C2 | Terraform/OpenTofu | M-L 10-18 h | M | tool download (none installed) |
| C3 | Portability and tradeoff docs | M-L 12-20 h | L | no |
| D1-D9 | Discovery, delivery set, README, diagrams, notices, traceability refresh, demo, accessibility, final report | S-L, ~100-160 h total | L-M | licence lookups, independent reviewer |
| E1 | CI enlargement (local edit; execution needs a remote) | M 6-10 h | L | remote for execution |
| Q1/Q2 | AI-quality targets; manual-vs-automated comparison | XL 40-100+ h | H | separate authorisation and a fresh held-out set |

## 4. Shared dependencies and overlaps
Migrations (12.03/04/05, 17.04) need one author; `domain_routes.py` and `ingestion/service.py` are shared by 12.x and 17.03 (A2 before B2); connectors and `worker.py` are shared by 11.x, 12.01, 21.10, 22.01; observability files by 22.01, 04.03, 05.06; evaluation tooling by 21.x and 13.x (add new scripts, never edit frozen baselines); `backend/app/ai/*` is shared by 14.02 and the quality work (quality work waits for the 14.02 decision); the two generator pairs (`v41_requirements_data.py` + `generate_v41_reconciliation.py`, `traceability_data.py` + `generate_traceability.py`) have a single owner in Batch E.

## 5. Minimum blocking set for a credible LOCAL portfolio demonstration
14.02 (decision after the failed v5 gate); 12.05 plus the 17.04 decision; 17.03; 16.04 (documented-limitation variant); 21.10 and 21.02 suite definition so no recovery claim lacks a denominator; 29.01, 29.02, 01.04 (README shows NOT MET items honestly); 34.20; 30.01 and a self-run 23.04; 34.24; 06.02. Recommended: 03.02 local licence inventory, 06.01, 25.03, 34.01, 21.01, 22.01.
**Everything else is still required for full V4.1 completion**, including all optional items unless the owner records a deviation. Proposed deferrals needing an owner decision: 22.02, 22.03, 23.02, 24.06, 13.03, 21.14, the AI-quality targets (21.04, 21.05, 13.04-06), 17.04 build-vs-deviation, 16.04 build variant. The 10-item publication chain stays blocked until the owner creates and authorises a repository.

## 6. Workstreams, file ownership, integration order
- **A safety/authorisation**: ingestion/*, domain_routes.py, models, migrations, core/limits.py, new test files. **B functional**: connectors/*, mock-services/*, worker.py, observability/*, ops_routes.py, evaluation tooling (new scripts only). **C infrastructure**: docker-compose.yml, infrastructure/*, Dockerfiles, ci.yml, Makefile, deployment docs. **D documentation**: README, docs/customer-*, operations docs, security docs, notices, traceability data. **E final acceptance**: generator pairs, specification outputs, CHANGELOG, final report (sequential, last).
- Never edited concurrently: migrations, `models/__init__.py`, `domain_routes.py`, `ingestion/service.py`, `worker.py`, `evaluation/phase8/metrics.py`, README, `docker-compose.yml`, `scripts/dev.py`, `ci.yml`, generator files.
- Parallelism: B1, B3, B4 and C3/D docs can run in parallel (separate worktrees); A2 before B2; C1 after the schema stabilises; D last for measured numbers; E last. If safe isolation fails, execute sequentially.
- Integration order: (1) 14.02 decision; (2) A: 17.03, 16.04 decision, migration 0008, A2; (3) B1/B3/B4 in parallel, then B2; (4) C1; C2/C3 docs any time; (5) Q only with authorisation; (6) D; (7) E full regression + regeneration; (8) external chain only on owner approval.

## 7. Testing schedule (one heavy consumer at a time; 16 GB RAM, CPU-only)
L1 targeted tests after each change; L2 workstream integration + security + workflow before integrating a batch; L3 full regression at integration checkpoints and before final acceptance (backend, real-AI, UAT, fault injection, security/tenant isolation, frontend, secret scan, traceability). Order: T1 lint/static (may run beside editing) -> T2 backend deterministic (exclusive DB) -> T3 acceptance + fault injection (no Ollama) -> T4 FI-10 disruptive alone -> T5 Playwright/axe (no Ollama, no Docker builds) -> T6 Docker build/compose smoke -> T7 real-AI/evaluation sequential -> T8 IaC validation after an approved download -> T9 final full regression and regeneration.

## 8. Required downloads or approvals
Terraform/OpenTofu and providers; Docker base images; OpenTelemetry packages (if adopted); reranker weights (13.03); Playwright browsers (cross-browser a11y); licence lookups; scope decisions for 12.x, 17.04, 16.04; documented reviewer reproduction for 23.04 (owner eligible under [EAOP 08E](eaop-08e-owner-governance.md)); a repository, push and release authorisation for the 10-item external chain.

## 9. Local-demonstration readiness and full-completion criteria
Local demo ready = the blocking set in section 5 verified with reproducible evidence, a green full regression, honest NOT MET statements in the README, no open critical safety defect or an owner-accepted documented limitation. Full V4.1 completion = every one of the 238 requirements Verified or covered by an explicit owner-approved deviation, plus documented demo reproduction, explicit owner acceptance and the authorised publication chain.

## 10. Risk register
R1 residual numeric-safety defects (H; no zero-defect claim); R2 deletion cascades break citations or leak across tenants (M; RLS and cited-document tests); R3 migration collision (M; single author); R4 inbound webhook attack surface (M; HMAC, tenant binding, limits); R5 concurrent runs share one Postgres (H; one DB session at a time); R6 RAM exhaustion with Ollama + Docker + Playwright (M); R7 AI targets unreachable on a CPU model with a consumed held-out set (H; honest reporting, owner decision); R8 no Terraform/OpenTofu installed (H; report 'unvalidated' until approved); R9 image pulls need network (M); R10 README/matrix drift (M; regenerate and test); R11 incomplete licence audit (M; mark 'to verify'); R12 publication needs owner actions (H); R13 fictional-customer documents mistaken for real interviews (L; label them).

## 11. Exact stop checkpoints
Stop and request approval: after each batch (A, B, C, D, E); on any failed safety gate; before any download, remote, push, merge, release or deviation; before starting Phase 9 or the AI-quality work.

**This plan is not authorisation to implement any batch.**
