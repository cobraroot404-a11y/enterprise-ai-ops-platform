# Accelerated Batch 4 report: API-quality closure, local demonstration and customer handover documentation

Date: 2026-11-13 (EST). Starting HEAD `3ef28527ce2d0f73d4da7810f84d705fc1a2dfb7` (branch `feat/apex-vertical-slice`, clean; original specification SHA-256 `b1c573e2…760da` verified by recomputing it from `docs/specification/ORIGINAL_MASTER_SPECIFICATION_V4.1.txt`). No push, merge, publication or release. No application code, migration, dependency, model download, infrastructure or licence change. V41-14.02 stays PARTIAL.

## 1. V41-17.03 closure (owner decision recorded)
Status changed from Partial to **Verified** in `scripts/v41_requirements_data.py` and the generated reconciliation documents (counts now 135 verified, 65 partial, 32 missing, 6 not evaluable; no other requirement changed status). Basis, re-checked before the change against the executed Batch 3.1 evidence (`evaluation/api-quality/api-quality-evidence.json`, generated at commit `3bcfdf0` from a clean tree, all nine properties `verified`, 0 failures): typed contracts (45 operations; 39 return 200, 6 return 201), validation, pagination, standardized errors, OpenAPI documentation (typed error schemas; the 422 mismatch fixed), migrations through 0008, transactions, constraints, tenant-leading indexes. The original wording (lines 609-619) lists exactly these nine. Recorded limitations: the HTTP 413 size-limit error body (`payload_too_large`) has no `correlation_id` in the body (header only); handlers return dictionaries validated at the framework boundary; error codes are an open vocabulary; **all tests and evaluations are same-author, not externally certified**. Historical test results and evidence files were not modified.

## 2. Verified local startup results
Environment: Windows 11, Docker 29.7.2 (PostgreSQL 16 + pgvector container already running and healthy), existing `.venv` and `frontend/node_modules`, Ollama with `qwen2.5:1.5b` already pulled. To avoid touching shared databases, everything ran on a new disposable database `eaop_batch4` (created and dropped by me; the shared databases were not modified).

| Check | Result |
|---|---|
| Environment-variable configuration | `.env` present; names match `.env.example`; **defect found in my method, reproduced and documented:** sourcing `.env` in a POSIX shell strips the JSON quotes of `EGRESS_*`; connector creation then returns HTTP 500 `internal_error` (a malformed setting is a generic 500 rather than a startup error). `scripts/dev.py` loading `.env` itself works |
| PostgreSQL initialisation | new database migrated from empty to Alembic `0008`; extensions `vector`, `pgcrypto` present |
| Backend startup | `python scripts/dev.py stack`: API :8000, worker, mocks :8101-:8105 all listening within seconds; `/api/v1/health` 200; `/docs` and `/openapi.json` 200 |
| Seed and onboarding | `dev.py seed` (Apex, five documents) and `dev.py onboard-meridian` (tenant, four members, three connectors, profile, five documents) succeeded; onboarding re-run is idempotent; onboarding health 8 of 8 |
| Frontend startup | `npm run dev` served on :5173 and proxied `/api` to the API (health through the proxy returned 200). UI pages were **not** exercised in a browser |
| Ollama connectivity | `ollama_ctl.py start` ready, model listed, one one-word generation answered, `stop` clean |
| Authentication and RBAC | login for all four roles in both tenants; auditor create-ticket 403; engineer approve 403; engineer verify 403 |
| Tenant isolation | Meridian engineer reading an Apex incident id and Apex engineer reading a Meridian ticket id: both 404; document lists disjoint; a Meridian search for an Apex pump term returned only Meridian files |
| Health and readiness | single route `/api/v1/health` (runs `SELECT 1`; no model or mock check); no separate readiness endpoint; mock services have no health route |

**Known configuration problem (not fixed, not applied):** the long-lived shared dev database `eaop` reports Alembic revision `0006` while the code is at `0008` (0007 adds incident measurement storage). Running `python scripts/dev.py migrate` against it is the documented remedy; I did not run it on a shared database.
**Not performed (cannot be claimed):** a clean-room install (new virtual environment, `pip install`, `npm install`, new Docker volume); `dev.py up` and `down`; frontend type-check, lint and Vitest re-run; Playwright; real-AI and fault-injection suites. No independent reviewer has reproduced the demonstration.

## 3. Deliverables
README rewritten ([README.md](../../README.md)); architecture diagrams ([system-architecture.md](../architecture/system-architecture.md): 7 sections, 6 Mermaid diagrams (the README adds one overview diagram): components and ports, authentication and tenant isolation sequence, ingestion and retrieval, incident to approved ticket, numeric trust boundary, audit and observability, plus the data-model summary); local runbook ([local-runbook.md](../operations/local-runbook.md): all twelve requested sections with an executed or inspected status per step); demonstration guides ([apex](../customer-delivery/apex-demo-guide.md), [meridian](../customer-delivery/meridian-demo-guide.md)); documentation consistency test (`tests/test_documentation_consistency.py`, 7 static checks).

## 4. Apex demonstration (executed through the API, deterministic backends)
Documents 5; unanswerable question refused (`grounded: false`, no citations); fault report to incident (asset `P-101` verified, `mechanical_vibration`, priority P3 by rules, `pending_review`, `review_urgency: urgent`; the 8.4 mm/s reading an UNVERIFIED class A candidate, not eligible); draft ticket; auditor 403; request approval; engineer 403; supervisor approval; worker submission to `SUBMITTED` with external id `MNT-1001`; structured observation arrived as class C `VALIDATED`, engineer 403 on verify, supervisor verify 200, class D `HUMAN_VERIFIED`, eligible, priority P3 to P2. UI steps are in the guide but were not executed.

## 5. Meridian demonstration (executed through the API, deterministic backends)
Onboarding health 8 of 8; five Meridian documents; fault report `VH-2101` low brake pressure to incident (`brake_system`, P3, `pending_review`, urgent, class A candidate); draft, approval, submission to `SUBMITTED` with external id `WO-7001` from the Meridian service-desk mock; cross-tenant reads 404; structured observation plus supervisor verification P3 to P2; audit actions listed.

## 6. Documentation consistency results
Executed: `python -m pytest tests/test_documentation_consistency.py tests/test_v41_reconciliation.py tests/test_traceability.py` (15 passed) and the full root suite (see section 9). The new checks verify that markdown links resolve, backticked repository paths exist, `dev.py` tasks named in the docs exist, runbook environment variable names exist in `.env.example`, documented ports equal the launcher's, the requirement records show V41-17.03 Verified and V41-14.02 Partial, and the README makes no production-readiness claim. Not verified by a test: that every command in the README works on a clean machine; API-documentation links are to the local server.

## 7. Remaining customer-facing gaps
No UI for structured observations or measurement verification; no document deletion, reprocessing or ingestion jobs; no live connector probe; mocks only; minimal, partly profile-driven UI; CPU-model answer quality (citation correctness below target, about three in four incidents held for review); no customer discovery or delivery document set (the two demo guides are two of the ten delivery documents V41-25.01 expects; not closed).

## 8. Portfolio-readiness blocker assessment
Priority is by user value and dependency. Counts refer to the 104 unresolved requirements in [the gap register](../specification/v4.1-gap-register.md); no requirement other than V41-17.03 changed status.

| Class | Blockers | Assessment |
|---|---|---|
| Critical customer-workflow gaps | V41-12.05 deletion (Missing), V41-12.03 ingestion retry (Missing), V41-12.04 reprocess, V41-17.04 four entity tables or approved deviation, V41-11.01 CSV and webhook connectors, V41-12.01 REST and webhook ingestion | Deletion and the entity decision need owner decisions first (migrations, audit and RLS design). None blocks the demonstrated incident-to-ticket workflow |
| Safety and authorization gaps | V41-14.02 Partial (frozen v5-v7 acceptance failed, v8 failed a provenance count 63 of 64), V41-16.04 distributed rate limiting (documented per-process limits), the 413 body distinction | 14.02 needs its own checkpoint; it is the main honesty constraint on the AI-safety claim |
| Local execution gaps | Shared dev DB behind the code (0006 vs 0008); no application containers or full Compose (V41-23.01, 05.04, 32.20, 34.17); no single-command demonstration or independent reviewer run (V41-23.04); no backup and restore (V41-23.03); mocks have no health route; malformed `EGRESS_*` yields a generic 500; CI has never run (no remote) | A one-command local demo script and a clean-room reproduction are the most valuable fixes |
| Frontend demonstration gaps | No UI for structured observations or measurement verification; UI only partly profile-driven; accessibility audited by automated axe in one browser only (V41-18.03) | See the explicit assessment below |
| Documentation gaps | Customer discovery (V41-06.01, empty directory), delivery set (V41-25.01, empty directory beyond two demo guides), 10-15 minute walkthrough script (V41-25.03), troubleshooting and handover (V41-04.05), notices audit (V41-03.02), deployment tradeoffs (V41-24.07), docs/performance (V41-21.01) | Runbook, architecture diagrams and README now exist but their requirements were not re-assessed or re-statused in this batch |
| Final integrated acceptance gaps | Full regression and real-AI re-run on final code; independent reproduction; citation-correctness 95% target (V41-21.04) and raw schema validity (V41-21.05) not met; recovery-rate definitions (V41-21.02); manual-versus-automated comparison (V41-21.14); Phase 9 items; release chain | Late-stage; depends on all of the above |

**Is the missing human-verification frontend a critical demonstration blocker?** No, but it is the highest-value demonstration gap. The core Apex and Meridian workflows (report, review gate, draft, approval, submission, audit, isolation) run end to end in the UI today, and the numeric-trust boundary is visible there (the reading is shown as an UNVERIFIED candidate with urgent review). What cannot be shown in the UI is the other half of the trust story: a supervisor verifying a reading, and the priority changing as a result. That half works only through the API (observed P3 to P2 on both customers), so a UI-only demonstration cannot show the strongest safety feature, and a reviewer may read the boundary as a restriction without a resolution path. It is not critical because it does not block any customer workflow and the API path is documented.

## 9. Test results
Executed at this batch: documentation and requirement tests (15 passed); full root suite 83 passed, 1 skipped (76 existing plus 7 new); lint 8 findings, all pre-existing and unchanged. The backend suite was **not** re-run: no backend code changed since Batch 3.1 (528 passed, 18 skipped at that HEAD, recorded as historical evidence). Frontend, real-AI, Playwright and fault-injection suites were not run.

## 10. Recommended Batch 5 (not started)
**Incident-detail UI for structured observations and measurement verification** (frontend only; the API, the provenance display in `frontend/src/components/provenance.tsx` and the role rules already exist): an observation entry form on the incident report card, and a verify/reject control with the required comment and the `expected_trust_status` guard on the measurement panel, gated by `incidents:review`, with Vitest and one Playwright path covering engineer-creates, supervisor-verifies, priority-changes. Estimated small to medium; no migration, no dependency. Followed by the one-command local demonstration script and a clean-room reproduction.

## 11. Reproduction commands
```
python -m pytest tests/test_documentation_consistency.py tests/test_v41_reconciliation.py tests/test_traceability.py -q
python scripts/generate_v41_reconciliation.py && python scripts/generate_traceability.py
# live verification (disposable database; see docs/operations/local-runbook.md): create database, then with POSTGRES_DB set:
python scripts/dev.py migrate && python scripts/dev.py seed && python scripts/dev.py stack     # then: python scripts/dev.py onboard-meridian
```

## 12. Evidence paths
`docs/specification/v4.1-requirements.json`, `docs/specification/v4.1-gap-register.md`, `docs/specification/v4.1-reconciliation-matrix.md`, `evaluation/api-quality/api-quality-evidence.json`, `docs/planning/batch3_1-report.md`, `docs/customer-delivery/apex-demo-guide.md`, `docs/customer-delivery/meridian-demo-guide.md`, `docs/operations/local-runbook.md`, `docs/architecture/system-architecture.md`, `README.md`. The live run output was captured in this session and summarised above; it was not saved as an evidence file.

## 13. Files changed
New: `docs/architecture/system-architecture.md`, `docs/operations/local-runbook.md`, `docs/customer-delivery/apex-demo-guide.md`, `docs/customer-delivery/meridian-demo-guide.md`, `docs/planning/batch4-report.md`, `tests/test_documentation_consistency.py`. Changed: `README.md`, `scripts/v41_requirements_data.py`, and the generated `docs/specification/v4.1-{requirements.json,gap-register.md,reconciliation-matrix.md,acceptance-criteria.md}`.
