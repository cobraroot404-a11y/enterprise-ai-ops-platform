# Demo smoke report 20261113-023551-e1b8

Result: **PASSED** in 34.8 s (mode smoke, AI backends: deterministic).
Git HEAD at run: `54dd375127a8275620a89dc476157cea88d31d17`. Started 2026-11-13T02:35:52-05:00, finished 2026-11-13T02:36:26-05:00.

## Skipped
- browser smoke (--no-browser)

## Timeline (executed)

| Step | Result | Seconds | Detail |
|---|---|---|---|
| preflight | ok | 3.6 | 7 checks passed |
| create disposable database eaop_demo_20261113_023551_e1b8 | ok | 0.1 | created |
| apply migrations (alembic upgrade head) | ok | 1.7 | revision 0008 |
| seed Apex Industrial fixtures | ok | 1.4 | ok (log .demo\20261113-023551-e1b8\logs\seed-apex.log) |
| start ticketing and wait for readiness | ok | 1.8 | responds over HTTP |
| start inventory and wait for readiness | ok | 1.2 | responds over HTTP |
| start fleet and wait for readiness | ok | 1.3 | responds over HTTP |
| start crm and wait for readiness | ok | 1.2 | responds over HTTP |
| start servicedesk and wait for readiness | ok | 1.3 | responds over HTTP |
| start worker and wait for readiness | ok | 1.2 | logged 'worker started' |
| start api and wait for readiness | ok | 2.4 | GET /api/v1/health 200 (database reachable) |
| onboard Meridian Fleet (public API) | ok | 1.3 | ok (log .demo\20261113-023551-e1b8\logs\onboard-meridian.log) |
| customer workflows through the API (Apex and Meridian) | ok | 3.8 |  |
| backup the demo database and prove it restores (isolated restore database) | ok | 2.2 |  |

Database: disposable `eaop_demo_20261113_023551_e1b8` created by this run, migrated to revision `0008` (head `0008`).

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

## Backup and restore proof

`backups\demo\eaop_demo_20261113_023551_e1b8-20261113T073614Z.dump` (86709 bytes, sha256 `3ab7ae00227e9aac...`) of `eaop_demo_20261113_023551_e1b8` (15 tables, 136 rows; tenants apex-industrial, meridian-fleet) restored into the new isolated database `eaop_demo_restore_20261113_023615_9337` (dropped):
- ok: backup file matches its manifest (sha256, size) (86709 bytes)
- ok: pg_restore into a new isolated database (completed)
- ok: migration revision preserved (0008)
- ok: tenants preserved (apex-industrial, meridian-fleet)
- ok: row counts of every table equal the source (15 tables, 136 rows)
- ok: per-tenant counts equal the source (documents, incidents, tickets, audit, approvals, outbox, connectors, memberships, chunks)
- ok: row-level security enabled and forced exactly as in the source (25 policies)
- ok: tenant isolation holds for the restricted application role (2 tenants each see only their own rows; with no tenant context 0 rows are visible)
- ok: backup contains no secret values from .env (no secret value found in the dump text)

## Cleanup

- process api (pid 22272): stopped
- process worker (pid 17312): stopped
- process servicedesk (pid 24640): stopped
- process crm (pid 25032): stopped
- process fleet (pid 2548): stopped
- process inventory (pid 9988): stopped
- process ticketing (pid 19044): stopped
- database eaop_demo_20261113_023551_e1b8: dropped

Secrets and credentials are redacted from this report. Logs are kept under `.demo/<run id>/logs` (git-ignored).
