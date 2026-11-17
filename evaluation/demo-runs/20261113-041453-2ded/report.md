# Demo smoke report 20261113-041453-2ded

Result: **FAILED** in 37.1 s (mode smoke, AI backends: deterministic).
Git HEAD at run: `05265f7fe9761823d34d11ef94b03df3c60a192c`. Started 2026-11-13T04:14:53-05:00, finished 2026-11-13T04:15:30-05:00.

## Failures
- apex-industrial: during the SIMULATED embedding outage the upload keeps its contract: 503 embedding_unavailable with Retry-After failed HTTP 503 {"error": {"code": "embedding_unavailable", "message": "The embedding model is unavailable; nothing was stored, retry shortly", "correlation_id": "88b178cb-8d9f-49c3-bacf-c10a84587cbc"}} headers=['Connection', 'content-length', 'content-type', 'date', 'retry-after', 'server', 'vary', 'x-correlation-id']

## Timeline (executed)

| Step | Result | Seconds | Detail |
|---|---|---|---|
| preflight | ok | 3.5 | 7 checks passed |
| create disposable database eaop_demo_20261113_041453_2ded | ok | 0.1 | created |
| apply migrations (alembic upgrade head) | ok | 1.4 | revision 0010 |
| seed Apex Industrial fixtures | ok | 1.4 | ok (log .demo\20261113-041453-2ded\logs\seed-apex.log) |
| start ticketing and wait for readiness | ok | 1.8 | responds over HTTP |
| start inventory and wait for readiness | ok | 1.3 | responds over HTTP |
| start fleet and wait for readiness | ok | 1.4 | responds over HTTP |
| start crm and wait for readiness | ok | 1.3 | responds over HTTP |
| start servicedesk and wait for readiness | ok | 1.3 | responds over HTTP |
| start worker and wait for readiness | ok | 2.3 | logged 'worker started' |
| start api and wait for readiness | ok | 2.5 | GET /api/v1/health 200 (database reachable) |
| onboard Meridian Fleet (public API) | ok | 1.6 | ok (log .demo\20261113-041453-2ded\logs\onboard-meridian.log) |
| customer workflows through the API (Apex and Meridian) | ok | 6.5 |  |
| live ingestion checkpoint: jobs, retry (simulated outage), reprocessing, deletion races | FAILED | 0.5 | apex-industrial: during the SIMULATED embedding outage the upload keeps its contract: 503 embedding_unavailable with Retry-After failed HTTP 503 {"error": {"code": "embedding_unavailable", "message": "The embedding model is unavailable; nothing was stored, retry shortly", "correlation_id": "88b178cb |

Database: disposable `eaop_demo_20261113_041453_2ded` created by this run, migrated to revision `0010` (head `0010`).

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

## Cleanup

- process api (pid 23216): stopped
- process worker (pid 25380): stopped
- process servicedesk (pid 12224): stopped
- process crm (pid 20620): stopped
- process fleet (pid 30016): stopped
- process inventory (pid 27164): stopped
- process ticketing (pid 24880): stopped
- database eaop_demo_20261113_041453_2ded: dropped

Secrets and credentials are redacted from this report. Logs are kept under `.demo/<run id>/logs` (git-ignored).
