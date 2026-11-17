# Accelerated Batch 5 report: structured observation entry, human verification UI and browser acceptance

Date: 2026-11-13 (EST). Starting HEAD `58ef4cc5d724584969bb38aacf27b76f19f99d63` (branch `feat/apex-vertical-slice`, clean; specification SHA-256 `b1c573e2…` verified). Frontend-only batch: no backend, policy, migration, dependency or evidence change. V41-17.03 stays VERIFIED; V41-14.02 stays PARTIAL. Nothing was pushed, merged, published or released.

## 1. Existing API capabilities used (audit result)
- **Structured observations are accepted only by `POST /incidents/extract`** (`observations[]`, max 20: `asset_id`, `measurement_type` in vibration, brake_pressure, coolant_temperature, `value` float, `unit`, optional `observed_at`, optional `source` ≤ 80; optional `numeric_locale` en or de for the report text). There is **no endpoint to add an observation to an existing incident**, so the form is part of the existing "Report a fault" workflow. The request schema has no field for trust status, reviewer, provenance, signature authority or sensor authentication; the optional `simulation` claim (signed fixtures) is deliberately not exposed.
- Measurements come back inside `GET /incidents/{id}` (`measurements[]`, with `trust_status`, `evidence_class`, `eligible_for_numeric_priority`, `provenance`, `reason`, `verification`) and `review_urgency`.
- A measurement is identified by its `name` (for example `vibration_mm_s`); only `unverified` or `submitted` records are pending. `POST /incidents/{id}/measurements/{name}/verify` takes `decision` (approve, reject), `comment` (10 to 500 characters) and `expected_trust_status` (UNVERIFIED or VALIDATED), requires `incidents:review` (supervisor, tenant administrator), refuses the incident's creator (403 `separation_of_duties`), answers 409 `stale_measurement_state` or `measurement_not_pending` for stale or repeated decisions, and returns the updated incident including the recalculated `priority`.
- Roles that may submit observations: `incidents:write` (administrator, supervisor, engineer). Verification events appear in `GET /incidents/{id}/history` and `/audit` as `measurement.verified` or `measurement.rejected` (and `incident.priority_decided`).

## 2. Behaviour implemented
**Observation entry** (`frontend/src/components/ObservationForm.tsx`, wired into `IncidentsPage`): optional rows in the Report-a-fault form (type, asset, value, unit with a per-type default, optional observation time, source reference) plus an optional report number-format select. Validation mirrors the API (asset 2 to 40 characters, plain numbers only: a comma such as `8,4` is refused rather than guessed, unit up to 12, source up to 80). The payload contains only schema fields; a test asserts no trust, reviewer, provenance or signature field is ever sent. A submitted observation is shown as "Submitted · awaiting verification" (class C), never as verified.
**Review panel** (`frontend/src/components/MeasurementPanel.tsx`): per measurement shows candidate value and unit, asset, evidence source (free text, structured observation with its source label, simulation fixture, or "proposed by the language model"), source availability (an explicit "source not available" warning instead of invented evidence), review reason, trust badge and class, "Used for priority" or "Not used", the server's decision block (transition, priority before and after, rule applied), and the "urgent review requested" flag explicitly labelled as not a verified priority. Reviewers (supervisor, administrator) who are not the creator can verify or reject with a justification and a confirmation dialog; the decision guard `expected_trust_status` is taken from the displayed state; a ref guard prevents double submission. After a decision the incident and its history are re-fetched; the displayed priority is whatever the server returns (nothing is computed or hardcoded in React). Errors: 401 handled by the existing session handler; 403 (role or separation of duties), 404, 409 (message plus reload of the latest state), 422 and network errors each have a specific message.
**Audit history**: the timeline labels `measurement.verified`, `measurement.rejected` and `incident.priority_decided` and shows measurement, comment and priority change.

## 3. Role and permission enforcement
Controls are visibility aids; the server is authoritative. Engineers and auditors see the reason and no controls; the creator (recognised from the `incident.extracted` history actor) sees a notice and no controls; if the creator is not visible and the request is sent anyway, the UI shows the server's 403. Playwright proves server enforcement independently of the UI with direct API calls (engineer and auditor 403 `insufficient_role`, another tenant's supervisor 404, creator 403 `separation_of_duties`, repeated decision 409).

## 4. Results (executed in this batch)
| Check | Result |
|---|---|
| Vitest (all 5 files) | **65 passed, 0 failed** (43 existing + 22 new in `src/pages/measurements.test.tsx`) |
| TypeScript `tsc --noEmit` | exit 0 |
| ESLint (`src`, `e2e`) | clean |
| Playwright, new spec `e2e/measurement-verification.spec.ts`, **live stack** (real API, worker, PostgreSQL `eaop_e2e`, mock services via `scripts/e2e_stack.py`; Microsoft Edge; nothing mocked) | **4 passed** |
| Playwright, full deterministic suite, final run | **51 passed, 1 skipped (existing), 0 failed** |
| Backend suite (`backend/tests`, includes authorization, tenant isolation, numeric-trust, API contract suites) | **528 passed, 18 skipped, 0 failed** (identical to the Batch 3.1 and 4 results; no backend change) |
| Root suite (`tests`, includes documentation consistency, reconciliation and traceability) | **83 passed, 1 skipped, 0 failed** |
| Secret scan | **0 findings in 836 files** |
| Ruff (repository) | 8 findings, all pre-existing (frozen Phase 8 tooling and sample data); none added |

Honest history of the browser runs: the first run of the new spec failed because of a label I had added (`incident.priority_decided` described as "recomputed from a human-verified measurement", which is wrong because extraction records the same event); fixed. A second run failed on an audit-event number the API does not return (see defects). A first full-suite run had two failures: the existing keyboard-only test, which assumed the Analyse button is the next Tab stop after the report box (the new number-format select and observation controls now sit in between: I changed the test to `tabTo` the button, keeping its intent), and one page-load abort (`net::ERR_ABORTED`) in an unrelated spec that passed on rerun. The final full run had none.

## 5. Customer demonstration steps and evidence
Updated in both demo guides (Apex step 11, Meridian step 8). Screenshots from the live run: the engineering browser captures (omitted), `02-supervisor-confirmation-dialog.png`, `03-supervisor-verified-priority-from-server.png`, `04-supervisor-rejected.png`, `05-creator-cannot-verify.png`. Playwright traces are written to `frontend/test-results` only on failure (git-ignored). The Playwright test ran on the Apex e2e tenant; the Meridian UI path was not separately browser-tested (same code).

## 6. New defects and discoveries (not fixed; backend changes need approval)
1. `verification.audit_event_id` is documented and set by the service but absent from the live API response (observed in the browser run); the UI shows "recorded in the audit history below" when it is missing.
2. The incident response has no `created_by`; the creator can only be inferred from the history actor, so separation of duties is enforced by the server and only pre-empted in the UI when the history shows it.
3. Observations cannot be added after extraction; a wrong observation cannot be withdrawn (only rejected by a reviewer).
4. The first UI run revealed that `incident.priority_decided` is also an extraction-time event (label corrected).

## 7. Remaining API-only workflows
Simulation-fixture observations with signatures (class F), adding observations to an existing incident (no endpoint), the audit event number of a decision.

## 8. Requirements traceability
V41-14.02 (stays Partial) evidence text and test references extended with the Batch 5 frontend tests (no status change); V41-17.03 unchanged (Verified). No other requirement changed.

## 9. Recommended Batch 6
Either (a) one-command local demonstration script plus a clean-room reproduction (no code risk, closes the biggest portfolio gap in `docs/planning/batch4-report.md`), or (b) a small, separately approved backend fix for `audit_event_id` and an `created_by` field if you want the UI to be fully self-explanatory. Document deletion and ingestion lifecycle still need your decisions.

## 10. Reproduction
```
cd frontend && npm run typecheck && npm run lint && npm test
cd frontend && npx playwright test e2e/measurement-verification.spec.ts     # builds the UI, starts the isolated live stack, Edge
cd frontend && npx playwright test                                           # full deterministic suite
python -m pytest backend/tests -q && python -m pytest tests -q
```
Files changed: new `frontend/src/components/MeasurementPanel.tsx`, `frontend/src/components/ObservationForm.tsx`, `frontend/src/pages/measurements.test.tsx`, `frontend/e2e/measurement-verification.spec.ts`, the engineering browser captures (omitted), `docs/planning/batch5-report.md`; changed `frontend/src/pages/IncidentsPage.tsx`, `frontend/src/types/index.ts`, `frontend/src/components/provenance.tsx`, `frontend/src/test/utils.ts` (mock handlers may now be asynchronous), `frontend/e2e/keyboard-workflow.spec.ts`, README, architecture document, both demo guides, `scripts/v41_requirements_data.py` and generated requirement documents. Historical evidence files were not modified (an end-to-end run rewrote `evaluation/reports/phase6-closure/axe-results.json`; it was restored from git).
