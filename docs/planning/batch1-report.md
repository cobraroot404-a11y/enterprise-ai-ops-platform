# Accelerated gap closure, Batch 1 report: V41-17.03 API-quality verification

Date: 2026-11-12 (EST). Starting HEAD `a8813ab4888b14b25f0c8d5028b96bf87bd9b9af` (branch `feat/apex-vertical-slice`, clean; original specification SHA-256 `b1c573e2…760da` verified). Manifest written and committed before coding: `docs/planning/batch1-manifest.md` (commit `300484f`). No push, merge, publication, release or deployment occurred.

## 1. Selected requirement and why
**V41-17.03** (typed contracts, validation, pagination, standardized errors, OpenAPI, migrations, transactions, constraints, indexes; acceptance "Nine API-quality properties verified"). Chosen because it is defined as work package A3 in the approved plan (independent, low risk, no migration, no approval, no numeric-safety or shared-safety file), is a defect (test gap) rather than new scope, and makes the API contract of both customer tenants verifiable and documented. Not selected, with reasons: **V41-12.05** (deletion lifecycle with cascade semantics, migration and an owner scope decision; high risk) and **V41-16.04** (phase 9/10 item; needs an owner decision between a shared limiter and a documented limitation).

## 2. Work completed
A nine-property verification suite (`backend/tests/test_api_contract.py`, 43 tests including negative and failure cases), a committed OpenAPI contract snapshot, an evidence generator that builds the evidence from the executed JUnit results, API-quality documentation, and four API-layer fixes for defects the suite found. V41-14.02 was not touched (still PARTIAL; its formal acceptance obligation is carried into the final integrated validation).

## 3. Results by property (from `evaluation/api-quality/api-quality-evidence.json`)
| Property | Result |
|---|---|
| P1 typed contracts | verified (3/3) |
| P2 validation | verified (11/11) |
| P3 pagination | verified (10/10) |
| P4 standardized errors | verified (5/5) |
| P5 OpenAPI documentation | verified (3/3) |
| P6 database migrations | verified (3/3) |
| P7 transactions | verified (3/3) |
| P8 constraints | verified (2/2) |
| P9 indexes | **known defect** (1 of 2 passed; the tenant-index check is a strict expected failure) |

## 4. Defects found
Fixed (API layer only, minimal): (1) unknown routes and wrong methods returned `{"detail": …}` instead of the standard error body; (2) OpenAPI declared no security scheme (now `bearerAuth` on every non-public operation); (3) a 500 response lacked `X-Correlation-ID`; (4) `GET /platform/audit` had no offset, total or validated bounds (now the common envelope; additive, the frontend reads only `items`).
**Open:** V41-17.03-IDX: `incidents`, `approvals` and `outbox_events` have no tenant-leading index (the other nine tenant-scoped tables have one). The fix needs migration 0008, which Batch 1 did not include. The check is kept as a strict expected failure, not weakened or removed.
Test-authoring corrections made while building the suite (not product defects): `audit_events.tenant_id` is nullable by design (platform events), so it is excluded from the not-null expectation, and the ORM-versus-schema drift check is one-directional because the migrations own indexes, constraints and RLS.

## 5. Files changed
New: `backend/tests/test_api_contract.py`, `backend/tests/snapshots/openapi_contract.json`, `scripts/api_quality_report.py`, `docs/api/api-quality.md`, `docs/planning/batch1-manifest.md`, `docs/planning/batch1-report.md`, `evaluation/api-quality/api-quality-evidence.json`. Changed: `backend/app/main.py`, `backend/app/api/v1/core_routes.py`, `scripts/v41_requirements_data.py`, `scripts/traceability_data.py` and the regenerated `docs/specification/*` and `docs/traceability/*`. No migration, dependency, model or numeric-safety change.

## 6. Architecture decisions
Standardize routing errors through one Starlette HTTP-exception handler so every error has one shape; declare the bearer scheme once in a custom OpenAPI builder (public operations: login and health); keep the contract snapshot as a normalized, diff-friendly JSON (operations, parameters, body schema names, response codes, security, schema property names) updated only by an explicit environment switch; keep the migration check read-only; use a strict expected failure to record the index defect so the suite stays green yet cannot hide it.

## 7. Test and security results (integration checkpoint)
Backend 499 passed, 18 skipped, 1 expected failure (the documented index defect); root suites 74 passed after the two generated-document consistency tests were rerun following regeneration (they failed only until the requirement and traceability documents were regenerated); real-AI 12 passed; real-stack customer acceptance 21 passed; frontend 43 passed; secret scan 0 findings (803 files); lint 8 findings, all pre-existing in frozen Phase 8 tooling and sample data (the new code adds none). Authorization, tenant isolation (route-table matrix, cross-tenant list scoping, other-tenant 404s) and the numeric trust-policy suites all pass unchanged.

## 8. Customer-facing demonstration steps
1. Start the API and open `/docs`: every operation is documented, grouped by tag and shows the Bearer authorization. 2. Call any list endpoint (`/api/v1/incidents?limit=2&offset=2`) as either tenant: identical envelope, bounded, tenant-scoped. 3. Request an unknown path or send a bad body: one error shape with a correlation id that matches the response header and the log line. 4. Run `python scripts/api_quality_report.py` to regenerate the evidence file.

## 9. Updated requirement status
V41-17.03: remains **Partial** (eight of nine properties verified; indexes open). Catalogue R17.2 moved from verified to partially verified for the same reason (an honest downgrade: the index gap was found by this batch). No other requirement status changed; all 238 originals, the 13 newly discovered and the five catalogue-only additions are retained and separately identified.

## 10. Remaining defects and critical path
Open: V41-17.03-IDX (needs migration 0008); everything else from the plan is unchanged. Updated critical path: A: migration 0008 (tenant indexes) can be bundled with the 12.04/12.05 and 17.04 migrations under one author; 12.05 and 16.04 still need owner decisions; B-E unchanged. V41-14.02 remains in the final integrated validation plan.

## 11. Recommended Batch 2
One approval unit, **migration 0008 plus its dependants**: (a) tenant-leading indexes on `incidents`, `approvals`, `outbox_events` (closes V41-17.03-IDX and lets V41-17.03 move to verified), and (b) only if you also decide the scope questions, document deletion (V41-12.05) with its cascade and audit semantics. If you prefer no schema work yet, the next independent items without a migration are the documentation set for the local demo (README, architecture diagrams, runbook) and the customer-delivery documents.

## 12. Reproduce
```
cd backend
python -m pytest tests/test_api_contract.py
python ../scripts/api_quality_report.py
python -m pytest tests -q                      # full backend
cd .. && python -m pytest tests -q            # root suites
```
Evidence: `evaluation/api-quality/api-quality-evidence.json`, `backend/tests/snapshots/openapi_contract.json`, `docs/api/api-quality.md`.
