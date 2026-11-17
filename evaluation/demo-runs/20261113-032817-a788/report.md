# Demo smoke report 20261113-032817-a788

Result: **PASSED** in 63.7 s (mode smoke, AI backends: deterministic).
Git HEAD at run: `eb8ee55fe948e2af29043ec3be7acc685e9ab648`. Started 2026-11-13T03:28:18-05:00, finished 2026-11-13T03:29:21-05:00.

## Timeline (executed)

| Step | Result | Seconds | Detail |
|---|---|---|---|
| preflight | ok | 4.1 | 7 checks passed |
| create disposable database eaop_demo_20261113_032817_a788 | ok | 0.1 | created |
| apply migrations (alembic upgrade head) | ok | 1.6 | revision 0009 |
| seed Apex Industrial fixtures | ok | 1.7 | ok (log .demo\20261113-032817-a788\logs\seed-apex.log) |
| start ticketing and wait for readiness | ok | 1.9 | responds over HTTP |
| start inventory and wait for readiness | ok | 1.4 | responds over HTTP |
| start fleet and wait for readiness | ok | 1.6 | responds over HTTP |
| start crm and wait for readiness | ok | 1.7 | responds over HTTP |
| start servicedesk and wait for readiness | ok | 1.6 | responds over HTTP |
| start worker and wait for readiness | ok | 2.8 | logged 'worker started' |
| start api and wait for readiness | ok | 2.7 | GET /api/v1/health 200 (database reachable) |
| onboard Meridian Fleet (public API) | ok | 1.6 | ok (log .demo\20261113-032817-a788\logs\onboard-meridian.log) |
| start frontend and wait for readiness | ok | 2.3 | page, entry module and /api proxy answer 200 |
| customer workflows through the API (Apex and Meridian) | ok | 6.7 |  |
| browser smoke (Playwright, Microsoft Edge, against this demo stack) | ok | 15.5 |  |
| backup the demo database and prove it restores (isolated restore database) | ok | 2.5 |  |

Database: disposable `eaop_demo_20261113_032817_a788` created by this run, migrated to revision `0009` (head `0009`).

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
- ok: document maintenance_log.csv is listed and searchable before deletion 
- ok: an engineer cannot delete a document (403) (HTTP 403)
- ok: another tenant's supervisor cannot delete it or see it (404) (HTTP 404)
- ok: supervisor deletes: logically deleted at once, cleanup pending or already running (HTTP 200 pending)
- ok: the deleted document is gone from the listing, direct access (404) and search 
- ok: the worker removed the content and verified it (cleanup completed), a repeated delete is idempotent (state completed)
- ok: the audit log holds the deletion and the cleanup without content (document.cleanup_completed, document.created, document.deleted)

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
- ok: document telematics_alerts.csv is listed and searchable before deletion 
- ok: an engineer cannot delete a document (403) (HTTP 403)
- ok: another tenant's supervisor cannot delete it or see it (404) (HTTP 404)
- ok: supervisor deletes: logically deleted at once, cleanup pending or already running (HTTP 200 pending)
- ok: the deleted document is gone from the listing, direct access (404) and search 
- ok: the worker removed the content and verified it (cleanup completed), a repeated delete is idempotent (state completed)
- ok: the audit log holds the deletion and the cleanup without content (document.cleanup_completed, document.created, document.deleted)

## Browser smoke

2 passed, 0 failed, 0 skipped on this demo stack (real UI, API, worker, database; mock external systems); Microsoft Edge (installed; nothing downloaded).
Initial-navigation retries: 0.
- expected: apex-industrial: structured observation, human verification and server-driven priority through the browser (6.9 s)
- expected: meridian-fleet: structured observation, human verification and server-driven priority through the browser (6.0 s)

## Backup and restore proof

`backups\demo\eaop_demo_20261113_032817_a788-20261113T082906Z.dump` (90718 bytes, sha256 `5495e4098c321d23...`) of `eaop_demo_20261113_032817_a788` (15 tables, 150 rows; tenants apex-industrial, meridian-fleet) restored into the new isolated database `eaop_demo_restore_20261113_032906_27a0` (dropped):
- ok: backup file matches its manifest (sha256, size) (90718 bytes)
- ok: pg_restore into a new isolated database (completed)
- ok: migration revision preserved (0009)
- ok: tenants preserved (apex-industrial, meridian-fleet)
- ok: row counts of every table equal the source (15 tables, 150 rows)
- ok: per-tenant counts equal the source (documents, incidents, tickets, audit, approvals, outbox, connectors, memberships, chunks)
- ok: row-level security enabled and forced exactly as in the source (28 policies)
- ok: tenant isolation holds for the restricted application role (2 tenants each see only their own rows; with no tenant context 0 rows are visible)
- ok: backup contains no secret values from .env (no secret value found in the dump text)

## Cleanup

- process ui (pid 9072): stopped
- process api (pid 23964): stopped
- process worker (pid 31068): stopped
- process servicedesk (pid 19520): stopped
- process crm (pid 21632): stopped
- process fleet (pid 31400): stopped
- process inventory (pid 26172): stopped
- process ticketing (pid 29580): stopped
- database eaop_demo_20261113_032817_a788: dropped

Secrets and credentials are redacted from this report. Logs are kept under `.demo/<run id>/logs` (git-ignored).
