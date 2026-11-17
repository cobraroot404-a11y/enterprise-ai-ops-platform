# Demo smoke report 20261113-024910-f780

Result: **PASSED** in 58.7 s (mode smoke, AI backends: deterministic).
Git HEAD at run: `ae8fd5512c57e49d820a7fc26858a586d4031200`. Started 2026-11-13T02:49:10-05:00, finished 2026-11-13T02:50:09-05:00.

## Timeline (executed)

| Step | Result | Seconds | Detail |
|---|---|---|---|
| preflight | ok | 4.1 | 7 checks passed |
| create disposable database eaop_demo_20261113_024910_f780 | ok | 0.1 | created |
| apply migrations (alembic upgrade head) | ok | 1.4 | revision 0008 |
| seed Apex Industrial fixtures | ok | 1.4 | ok (log .demo\20261113-024910-f780\logs\seed-apex.log) |
| start ticketing and wait for readiness | ok | 1.9 | responds over HTTP |
| start inventory and wait for readiness | ok | 1.3 | responds over HTTP |
| start fleet and wait for readiness | ok | 1.5 | responds over HTTP |
| start crm and wait for readiness | ok | 1.6 | responds over HTTP |
| start servicedesk and wait for readiness | ok | 1.7 | responds over HTTP |
| start worker and wait for readiness | ok | 3.0 | logged 'worker started' |
| start api and wait for readiness | ok | 2.8 | GET /api/v1/health 200 (database reachable) |
| onboard Meridian Fleet (public API) | ok | 1.6 | ok (log .demo\20261113-024910-f780\logs\onboard-meridian.log) |
| start frontend and wait for readiness | ok | 2.4 | page, entry module and /api proxy answer 200 |
| customer workflows through the API (Apex and Meridian) | ok | 4.2 |  |
| browser smoke (Playwright, Microsoft Edge, against this demo stack) | ok | 14.2 |  |
| backup the demo database and prove it restores (isolated restore database) | ok | 2.4 |  |

Database: disposable `eaop_demo_20261113_024910_f780` created by this run, migrated to revision `0008` (head `0008`).

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
Initial-navigation retries: 0.
- expected: apex-industrial: structured observation, human verification and server-driven priority through the browser (6.2 s)
- expected: meridian-fleet: structured observation, human verification and server-driven priority through the browser (5.4 s)

## Backup and restore proof

`backups\demo\eaop_demo_20261113_024910_f780-20261113T074954Z.dump` (87942 bytes, sha256 `682fe827d59a81ff...`) of `eaop_demo_20261113_024910_f780` (15 tables, 152 rows; tenants apex-industrial, meridian-fleet) restored into the new isolated database `eaop_demo_restore_20261113_024954_ce1b` (dropped):
- ok: backup file matches its manifest (sha256, size) (87942 bytes)
- ok: pg_restore into a new isolated database (completed)
- ok: migration revision preserved (0008)
- ok: tenants preserved (apex-industrial, meridian-fleet)
- ok: row counts of every table equal the source (15 tables, 152 rows)
- ok: per-tenant counts equal the source (documents, incidents, tickets, audit, approvals, outbox, connectors, memberships, chunks)
- ok: row-level security enabled and forced exactly as in the source (25 policies)
- ok: tenant isolation holds for the restricted application role (2 tenants each see only their own rows; with no tenant context 0 rows are visible)
- ok: backup contains no secret values from .env (no secret value found in the dump text)

## Cleanup

- process ui (pid 28824): stopped
- process api (pid 3560): stopped
- process worker (pid 13392): stopped
- process servicedesk (pid 24864): stopped
- process crm (pid 24504): stopped
- process fleet (pid 26300): stopped
- process inventory (pid 32292): stopped
- process ticketing (pid 28260): stopped
- database eaop_demo_20261113_024910_f780: dropped

Secrets and credentials are redacted from this report. Logs are kept under `.demo/<run id>/logs` (git-ignored).
