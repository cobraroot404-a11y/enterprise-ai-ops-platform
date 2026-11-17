# Demo smoke report 20261113-041657-5fa4

Result: **PASSED** in 60.0 s (mode smoke, AI backends: deterministic).
Git HEAD at run: `05265f7fe9761823d34d11ef94b03df3c60a192c`. Started 2026-11-13T04:16:58-05:00, finished 2026-11-13T04:17:57-05:00.

## Skipped
- browser smoke (--no-browser)

## Timeline (executed)

| Step | Result | Seconds | Detail |
|---|---|---|---|
| preflight | ok | 3.5 | 7 checks passed |
| create disposable database eaop_demo_20261113_041657_5fa4 | ok | 0.1 | created |
| apply migrations (alembic upgrade head) | ok | 1.5 | revision 0010 |
| seed Apex Industrial fixtures | ok | 1.5 | ok (log .demo\20261113-041657-5fa4\logs\seed-apex.log) |
| start ticketing and wait for readiness | ok | 1.8 | responds over HTTP |
| start inventory and wait for readiness | ok | 1.3 | responds over HTTP |
| start fleet and wait for readiness | ok | 1.3 | responds over HTTP |
| start crm and wait for readiness | ok | 1.3 | responds over HTTP |
| start servicedesk and wait for readiness | ok | 1.3 | responds over HTTP |
| start worker and wait for readiness | ok | 2.3 | logged 'worker started' |
| start api and wait for readiness | ok | 2.4 | GET /api/v1/health 200 (database reachable) |
| onboard Meridian Fleet (public API) | ok | 1.7 | ok (log .demo\20261113-041657-5fa4\logs\onboard-meridian.log) |
| customer workflows through the API (Apex and Meridian) | ok | 6.7 |  |
| live ingestion checkpoint: jobs, retry (simulated outage), reprocessing, deletion races | ok | 20.9 |  |
| backup the demo database and prove it restores (isolated restore database) | ok | 2.2 |  |

Database: disposable `eaop_demo_20261113_041657_5fa4` created by this run, migrated to revision `0010` (head `0010`).

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

## Live ingestion checkpoint (durable jobs, retry, reprocessing, deletion races)

Fault model: simulated: the embedding step raises while the fault switch file exists (scripts/fault_boot.py); the retry logic is exercised against that failure mode

### apex-industrial

- ok: a supported document uploads synchronously (201) as before (HTTP 201)
- ok: the upload left a COMPLETED durable ingestion job with its outcome and chunk count ({"status": "COMPLETED", "outcome": "created", "attempts": 1})
- ok: the content is retrievable once indexed 
- ok: during the SIMULATED embedding outage the upload keeps its contract: 503 embedding_unavailable with Retry-After (HTTP 503)
- ok: a RETRY_PENDING job with a sanitised error and a next attempt time exists 
- ok: bounded retry then recovery: COMPLETED after 3 attempts (limit 5), document created, now retrievable 
- ok: repeating the upload afterwards is a duplicate: nothing is stored twice 
- ok: an engineer cannot reprocess (403) (HTTP 403)
- ok: a supervisor queues reprocessing (202) (HTTP 202)
- ok: replacement generation activated (1 to 2); retrieval serves the document once, no duplicates 
- ok: another tenant cannot see this tenant's jobs (404, indistinguishable from unknown) 
- ok: another tenant's supervisor cannot reprocess it (404) (HTTP 404)
- ok: deletion while a reprocessing job is queued cancels it (document_deleted); the content never returns 
- ok: after recovery the cancelled job does not run: the document stays deleted, unsearchable, not reprocessable (404) 
- ok: the audit log records job creation, retry, completion, reprocessing, cancellation and cleanup (missing [])

### meridian-fleet

- ok: a supported document uploads synchronously (201) as before (HTTP 201)
- ok: the upload left a COMPLETED durable ingestion job with its outcome and chunk count ({"status": "COMPLETED", "outcome": "created", "attempts": 1})
- ok: the content is retrievable once indexed 
- ok: during the SIMULATED embedding outage the upload keeps its contract: 503 embedding_unavailable with Retry-After (HTTP 503)
- ok: a RETRY_PENDING job with a sanitised error and a next attempt time exists 
- ok: bounded retry then recovery: COMPLETED after 3 attempts (limit 5), document created, now retrievable 
- ok: repeating the upload afterwards is a duplicate: nothing is stored twice 
- ok: an engineer cannot reprocess (403) (HTTP 403)
- ok: a supervisor queues reprocessing (202) (HTTP 202)
- ok: replacement generation activated (1 to 2); retrieval serves the document once, no duplicates 
- ok: another tenant cannot see this tenant's jobs (404, indistinguishable from unknown) 
- ok: another tenant's supervisor cannot reprocess it (404) (HTTP 404)
- ok: deletion while a reprocessing job is queued cancels it (document_deleted); the content never returns 
- ok: after recovery the cancelled job does not run: the document stays deleted, unsearchable, not reprocessable (404) 
- ok: the audit log records job creation, retry, completion, reprocessing, cancellation and cleanup (missing [])


## Backup and restore proof

`backups\demo\eaop_demo_20261113_041657_5fa4-20261113T091745Z.dump` (104441 bytes, sha256 `bbb8d4aafb6d007d...`) of `eaop_demo_20261113_041657_5fa4` (16 tables, 218 rows; tenants apex-industrial, meridian-fleet) restored into the new isolated database `eaop_demo_restore_20261113_041746_4e08` (dropped):
- ok: backup file matches its manifest (sha256, size) (104441 bytes)
- ok: pg_restore into a new isolated database (completed)
- ok: migration revision preserved (0010)
- ok: tenants preserved (apex-industrial, meridian-fleet)
- ok: row counts of every table equal the source (16 tables, 218 rows)
- ok: per-tenant counts equal the source (documents, incidents, tickets, audit, approvals, outbox, connectors, memberships, chunks)
- ok: row-level security enabled and forced exactly as in the source (31 policies)
- ok: tenant isolation holds for the restricted application role (2 tenants each see only their own rows; with no tenant context 0 rows are visible)
- ok: backup contains no secret values from .env (no secret value found in the dump text)

## Cleanup

- process api (pid 13844): stopped
- process worker (pid 28144): stopped
- process servicedesk (pid 544): stopped
- process crm (pid 17628): stopped
- process fleet (pid 27068): stopped
- process inventory (pid 25280): stopped
- process ticketing (pid 20344): stopped
- database eaop_demo_20261113_041657_5fa4: dropped

Secrets and credentials are redacted from this report. Logs are kept under `.demo/<run id>/logs` (git-ignored).
