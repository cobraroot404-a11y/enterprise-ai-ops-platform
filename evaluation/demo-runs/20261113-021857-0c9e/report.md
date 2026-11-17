# Demo smoke report 20261113-021857-0c9e

Result: **PASSED** in 52.2 s (mode smoke, AI backends: deterministic).
Git HEAD at run: `75024fe886ddb27817f4ecb439a9c607048337c1`. Started 2026-11-13T02:18:57-05:00, finished 2026-11-13T02:19:50-05:00.

## Timeline (executed)

| Step | Result | Seconds | Detail |
|---|---|---|---|
| preflight | ok | 4.1 | 7 checks passed |
| create disposable database eaop_demo_20261113_021857_0c9e | ok | 0.1 | created |
| apply migrations (alembic upgrade head) | ok | 1.7 | revision 0008 |
| seed Apex Industrial fixtures | ok | 1.4 | ok (log .demo\20261113-021857-0c9e\logs\seed-apex.log) |
| start ticketing and wait for readiness | ok | 1.8 | responds over HTTP |
| start inventory and wait for readiness | ok | 1.3 | responds over HTTP |
| start fleet and wait for readiness | ok | 1.3 | responds over HTTP |
| start crm and wait for readiness | ok | 1.4 | responds over HTTP |
| start servicedesk and wait for readiness | ok | 1.5 | responds over HTTP |
| start worker and wait for readiness | ok | 2.4 | logged 'worker started' |
| start api and wait for readiness | ok | 2.5 | GET /api/v1/health 200 (database reachable) |
| onboard Meridian Fleet (public API) | ok | 1.3 | ok (log .demo\20261113-021857-0c9e\logs\onboard-meridian.log) |
| start frontend and wait for readiness | ok | 1.7 | page 200 and /api proxy reaches the API |
| customer workflows through the API (Apex and Meridian) | ok | 4.0 |  |
| browser smoke (Playwright, Microsoft Edge, against this demo stack) | ok | 14.0 |  |

Database: disposable `eaop_demo_20261113_021857_0c9e` created by this run, migrated to revision `0008` (head `0008`).

## Workflow checks: apex-industrial (API, real application; external systems simulated)

- ok: sign in as engineer, supervisor, administrator and auditor 
- ok: engineer analyses a fault report with a structured observation (HTTP 201) (HTTP 201)
- ok: the observation is stored as a submitted observation awaiting verification (class C, VALIDATED, not used for priority) ({"trust_status": "VALIDATED", "evidence_class": "C", "eligible_for_numeric_priority": false})
- ok: asset is registered (P-101)
- ok: engineer cannot verify (403 insufficient_role) (HTTP 403)
- ok: auditor cannot verify (403 insufficient_role) (HTTP 403)
- ok: another tenant's supervisor gets 404 (tenant isolation) (HTTP 404)
- ok: another tenant's engineer cannot read the incident (404) (HTTP 404)
- ok: supervisor verifies; the server returns HUMAN_VERIFIED, class D, eligible (HTTP 200)
- ok: priority comes from the server: P3 -> P2 (verification block says P3 -> P2) 
- ok: a repeated decision is refused (409) (HTTP 409 measurement_not_pending)
- ok: the creator cannot verify their own incident's measurement (403 separation_of_duties) (HTTP 403)
- ok: engineer drafts a ticket (201, DRAFT) (HTTP 201)
- ok: approval requested (PENDING_APPROVAL) (HTTP 200)
- ok: the author cannot approve (403) (HTTP 403)
- ok: supervisor approves (HTTP 200)
- ok: the worker submits it to the (simulated) external system: SUBMITTED with an external id (state SUBMITTED external id MNT-1001)
- ok: the audit log shows the whole chain (missing [])

## Workflow checks: meridian-fleet (API, real application; external systems simulated)

- ok: sign in as engineer, supervisor, administrator and auditor 
- ok: engineer analyses a fault report with a structured observation (HTTP 201) (HTTP 201)
- ok: the observation is stored as a submitted observation awaiting verification (class C, VALIDATED, not used for priority) ({"trust_status": "VALIDATED", "evidence_class": "C", "eligible_for_numeric_priority": false})
- ok: asset is registered (VH-2101)
- ok: engineer cannot verify (403 insufficient_role) (HTTP 403)
- ok: auditor cannot verify (403 insufficient_role) (HTTP 403)
- ok: another tenant's supervisor gets 404 (tenant isolation) (HTTP 404)
- ok: another tenant's engineer cannot read the incident (404) (HTTP 404)
- ok: supervisor verifies; the server returns HUMAN_VERIFIED, class D, eligible (HTTP 200)
- ok: priority comes from the server: P3 -> P2 (verification block says P3 -> P2) 
- ok: a repeated decision is refused (409) (HTTP 409 measurement_not_pending)
- ok: the creator cannot verify their own incident's measurement (403 separation_of_duties) (HTTP 403)
- ok: engineer drafts a ticket (201, DRAFT) (HTTP 201)
- ok: approval requested (PENDING_APPROVAL) (HTTP 200)
- ok: the author cannot approve (403) (HTTP 403)
- ok: supervisor approves (HTTP 200)
- ok: the worker submits it to the (simulated) external system: SUBMITTED with an external id (state SUBMITTED external id WO-7001)
- ok: the audit log shows the whole chain (missing [])

## Browser smoke

2 passed, 0 failed, 0 skipped on this demo stack (real UI, API, worker, database; mock external systems); Microsoft Edge (installed; nothing downloaded).
- expected: apex-industrial: structured observation, human verification and server-driven priority through the browser (5.9 s)
- expected: meridian-fleet: structured observation, human verification and server-driven priority through the browser (5.3 s)

## Cleanup

- process ui (pid 24500): stopped
- process api (pid 25896): stopped
- process worker (pid 26508): stopped
- process servicedesk (pid 2548): stopped
- process crm (pid 28460): stopped
- process fleet (pid 8852): stopped
- process inventory (pid 15800): stopped
- process ticketing (pid 23380): stopped
- database eaop_demo_20261113_021857_0c9e: dropped

Secrets and credentials are redacted from this report. Logs are kept under `.demo/<run id>/logs` (git-ignored).
