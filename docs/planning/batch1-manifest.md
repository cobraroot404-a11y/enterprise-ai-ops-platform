# Accelerated gap closure, Batch 1 execution manifest

Date: 2026-11-12 (EST). Starting HEAD `a8813ab4888b14b25f0c8d5028b96bf87bd9b9af` (branch `feat/apex-vertical-slice`, clean; original specification SHA-256 `b1c573e2…760da` verified). Written before any implementation.

## Selection
| Candidate | Definition (from `v4.1-requirements.json`) | Decision | Reason |
|---|---|---|---|
| **V41-17.03** | "Typed contracts, Validation, Pagination, Standardized errors, OpenAPI documentation, Database migrations, Transactions, Constraints, Indexes"; status Partial, phase "defect (test gap)"; gap: pagination has no dedicated API test, OpenAPI not separately verified; acceptance: "Nine API-quality properties verified" | **SELECTED** | Defined in the approved plan as work package A3 (S-M, risk L, independent, no approval, no migration); test and evidence work in the API layer; no shared safety component; customer-visible (stable, documented API for both tenants) |
| V41-12.05 | "Deletion"; missing; phase "defect (earlier phase) / approval"; acceptance "Documents can be deleted with audit" | not selected | Needs a deletion lifecycle (cascade semantics over documents, versions, chunks, embeddings, citations in incidents) and an owner scope decision; the plan marks it high risk and approval-gated; would touch ingestion/service, models and migrations |
| V41-16.04 | "Input validation / Upload restrictions / Rate limiting"; partial; phase "Phase 9/10 (before production)" | not selected | Phase 9/10 item; the plan requires an owner choice between building a shared limiter and documenting the per-process limitation |

## Requirement and scope
- **IDs:** V41-17.03 only. Its nine properties map to nine verification groups: typed contracts, validation, pagination, standardized errors, OpenAPI documentation, database migrations, transactions, constraints, indexes.
- **Not changed:** numeric-safety components (`measurement_*`, `incident_service` numeric logic), trust policy, retrieval, citations, prompts, Phase 8 candidate, frozen evidence, migrations (read-only checks only), licensing, remotes.
- **Dependencies:** none on V41-14.02; uses the existing test infrastructure (`support.py`, deterministic backends, the migrated test database).

## Files to be changed
| File | Change |
|---|---|
| `backend/tests/test_api_contract.py` (new) | verification suite for the nine properties, negative and failure cases included, plus an evidence writer |
| `backend/tests/snapshots/openapi_contract.json` (new) | committed OpenAPI route/contract snapshot (methods, paths, parameters, request/response schema names, security) with an update procedure |
| `evaluation/api-quality/api-quality-evidence.json` (new, generated from the run) | requirement id, properties, commands, results, snapshot hash, commit |
| `docs/api/api-quality.md` (new) | what is verified, how to reproduce, how to update the snapshot, known limits |
| `docs/specification/*`, `docs/traceability/*` (regenerated) and `scripts/v41_requirements_data.py`, `scripts/traceability_data.py` | requirement evidence updated from the actual results only |
| API layer files (`backend/app/core/errors.py`, `backend/app/main.py`, route modules) | **only** if the suite finds a genuine defect in error shape, pagination bounds or OpenAPI metadata; minimal fix, reported separately |

## Tests (levels)
1. **Targeted:** `backend/tests/test_api_contract.py`.
2. **Subsystem:** affected API, authorization and tenant-isolation suites (`test_api_namespace_security.py`, `test_security.py`, `test_ops_routes.py`, `test_control_mutations.py`).
3. **Integration checkpoint:** full backend and root suites; real-AI and real-stack acceptance serially; lint; secret scan; traceability and reconciliation tests.

## Acceptance criteria (V41-17.03 is "verified" only if all hold, each with an executed test)
1. **Typed contracts:** every route with a request body references a typed schema; list and detail responses of the main resources keep their documented keys; no untyped free-form bodies except a documented list.
2. **Validation:** wrong types, missing fields, out-of-range values, oversize input and invalid enums return 422 with the standard error body, never 500.
3. **Pagination:** every list endpoint accepts `limit`/`offset`, bounds enforced (limit 1..100, offset >= 0), `total` correct, pages disjoint and ordered, offset beyond total returns an empty page, per-tenant scoping.
4. **Standardized errors:** 401, 403, 404, 409, 422 (and 413 where defined) all use `{"error": {"code", "message", "correlation_id"}}`, with a correlation header, no stack traces or internals.
5. **OpenAPI documentation:** `/openapi.json` valid; every route has a summary or description, a tag and the security scheme where protected; the committed snapshot matches the live contract.
6. **Database migrations:** a single linear head, the test database is at head, and the models match the migrated schema (no drift).
7. **Transactions:** a failed operation leaves no partial rows (a rejected upload, a failed review step rolls back together with its audit event).
8. **Constraints:** key unique, foreign-key, check and not-null constraints exist and reject violating rows at the database.
9. **Indexes:** tenant-scoped tables have a tenant-leading index; unique, full-text and vector indexes exist.

If a criterion fails, the failure is retained and reported (the test is not weakened); a genuine defect found is fixed minimally in the API layer and listed under remaining defects only if left open.
Status after completion: V41-17.03 updated from the executed results; it is marked verified only when every criterion above passes.

## Stop condition
After Batch 1 is implemented, tested, committed locally and reported: stop and request approval before Batch 2. No push, merge, publication or release.
