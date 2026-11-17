# Demo smoke report 20261113-165814-3fa8

Result: **PASSED** in 153.5 s (mode smoke, AI backends: deterministic).
Git HEAD at run: `3e891e0161fd0df9a015dc2a44827b8ab447d47e`. Started 2026-11-13T16:58:15-05:00, finished 2026-11-13T17:00:47-05:00.

## Timeline (executed)

| Step | Result | Seconds | Detail |
|---|---|---|---|
| preflight | ok | 5.1 | 7 checks passed |
| create disposable database eaop_demo_20261113_165814_3fa8 | ok | 0.1 | created |
| apply migrations (alembic upgrade head) | ok | 3.9 | revision 0015 |
| seed Apex Industrial fixtures | ok | 1.8 | ok (log .demo\20261113-165814-3fa8\logs\seed-apex.log) |
| start ticketing and wait for readiness | ok | 2.5 | responds over HTTP |
| start inventory and wait for readiness | ok | 1.7 | responds over HTTP |
| start fleet and wait for readiness | ok | 1.7 | responds over HTTP |
| start crm and wait for readiness | ok | 1.8 | responds over HTTP |
| start servicedesk and wait for readiness | ok | 1.7 | responds over HTTP |
| start records and wait for readiness | ok | 1.7 | responds over HTTP |
| start worker and wait for readiness | ok | 3.0 | logged 'worker started' |
| start api and wait for readiness | ok | 3.4 | GET /api/v1/health 200 (database reachable) |
| onboard Meridian Fleet (public API) | ok | 1.9 | ok (log .demo\20261113-165814-3fa8\logs\onboard-meridian.log) |
| start frontend and wait for readiness | ok | 2.6 | page, entry module and /api proxy answer 200 |
| customer workflows through the API (Apex and Meridian) | ok | 7.2 |  |
| live ingestion checkpoint: jobs, retry (simulated outage), reprocessing, deletion races | ok | 21.1 |  |
| live REST pull synchronization: connector, pagination, rate limit, health probe, recovery (both tenants) | ok | 23.2 |  |
| live CSV connector and signed webhook integrations (both tenants) | ok | 14.0 |  |
| manual versus automated measurement protocol (class A measured automated; no B or C data unless supplied) | ok | 21.6 |  |
| browser smoke (Playwright, Microsoft Edge, against this demo stack) | ok | 14.5 |  |
| backup the demo database and prove it restores (isolated restore database) | ok | 3.0 |  |

Database: disposable `eaop_demo_20261113_165814_3fa8` created by this run, migrated to revision `0015` (head `0015`).

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


## Live CSV and signed-webhook integrations

CSV: real HTTP pull from mock-services/records. Webhooks: real HMAC-signed deliveries to the API; adversarial deliveries are deliberate negative tests. Signing secrets are run-only and never recorded.

### apex-industrial

- ok: the administrator registers a CSV connector through the public API (HTTP 201)
- ok: an invalid CSV configuration is rejected at creation (422) (HTTP 422)
- ok: a supervisor starts the CSV synchronisation: 202 with a durable QUEUED job (HTTP 202)
- ok: the worker fetched the CSV file and ingested every row: 7 records created ({"pages": 1, "seen": 7, "created": 7, "updated": 0, "unchanged": 0, "linked_duplicate": 0, "skipped_deleted": 0, "tombstoned_changed": 0, "duplicate_in_sync": 0, "conflict": 0, "invalid": 0, "rejections": {}, "truncated": false})
- ok: the records mock served the CSV to the authenticated connector (1 requests)
- ok: the rows are retrievable with their record id as provenance 
- ok: a repeated CSV synchronisation is idempotent: every row unchanged ({"pages": 1, "seen": 7, "created": 0, "updated": 0, "unchanged": 7, "linked_duplicate": 0, "skipped_deleted": 0, "tombstoned_changed": 0, "duplicate_in_sync": 0, "conflict": 0, "invalid": 0, "rejections": {}, "truncated": false})
- ok: the live probe validates the CSV source header (nothing ingested) 
- ok: the administrator provisions a webhook endpoint (only the NAME of the secret variable is supplied; no secret is returned) (HTTP 201)
- ok: an engineer cannot provision endpoints (403) 
- ok: a correctly signed delivery is acknowledged 202 QUEUED (durably queued, not yet processed) (HTTP 202)
- ok: the worker processed the delivery through the ingestion pipeline: 1 record created ({"pages": 1, "seen": 1, "created": 1, "updated": 0, "unchanged": 0, "linked_duplicate": 0, "skipped_deleted": 0, "tombstoned_changed": 0, "duplicate_in_sync": 0, "conflict": 0, "invalid": 0, "rejections": {}, "truncated": false})
- ok: the delivered content is retrievable by this tenant and not by the other tenant 
- ok: a wrong secret and a tampered body are rejected with the same 401 invalid_signature (401 401)
- ok: a validly signed but stale delivery is rejected by the timestamp window (401) (HTTP 401)
- ok: replaying a received delivery id is rejected (409 webhook_replayed) (HTTP 409)
- ok: an oversized body is refused (413, or the connection is closed by the server while it is still being sent) and a non-JSON content type is refused (415) (0 415)
- ok: a signed delivery that can never be processed is rejected after authentication (422) (HTTP 422)
- ok: a later delivery with changed content becomes a new document version ({"pages": 1, "seen": 1, "created": 0, "updated": 1, "unchanged": 0, "linked_duplicate": 0, "skipped_deleted": 0, "tombstoned_changed": 0, "duplicate_in_sync": 0, "conflict": 0, "invalid": 0, "rejections": {}, "truncated": false})
- ok: secret rotation: both secrets work during the overlap, the old one is rejected after it is dropped (202 202 401)
- ok: another tenant cannot see or change this endpoint 
- ok: a disabled endpoint rejects even a correctly signed delivery (401) 
- ok: the audit log records endpoint changes and every authenticated delivery outcome (missing [])
- ok: no signing secret, API key or delivery content appears in the audit log, job list or endpoint list 

### meridian-fleet

- ok: the administrator registers a CSV connector through the public API (HTTP 201)
- ok: an invalid CSV configuration is rejected at creation (422) (HTTP 422)
- ok: a supervisor starts the CSV synchronisation: 202 with a durable QUEUED job (HTTP 202)
- ok: the worker fetched the CSV file and ingested every row: 5 records created ({"pages": 1, "seen": 5, "created": 5, "updated": 0, "unchanged": 0, "linked_duplicate": 0, "skipped_deleted": 0, "tombstoned_changed": 0, "duplicate_in_sync": 0, "conflict": 0, "invalid": 0, "rejections": {}, "truncated": false})
- ok: the records mock served the CSV to the authenticated connector (1 requests)
- ok: the rows are retrievable with their record id as provenance 
- ok: a repeated CSV synchronisation is idempotent: every row unchanged ({"pages": 1, "seen": 5, "created": 0, "updated": 0, "unchanged": 5, "linked_duplicate": 0, "skipped_deleted": 0, "tombstoned_changed": 0, "duplicate_in_sync": 0, "conflict": 0, "invalid": 0, "rejections": {}, "truncated": false})
- ok: the live probe validates the CSV source header (nothing ingested) 
- ok: the administrator provisions a webhook endpoint (only the NAME of the secret variable is supplied; no secret is returned) (HTTP 201)
- ok: an engineer cannot provision endpoints (403) 
- ok: a correctly signed delivery is acknowledged 202 QUEUED (durably queued, not yet processed) (HTTP 202)
- ok: the worker processed the delivery through the ingestion pipeline: 1 record created ({"pages": 1, "seen": 1, "created": 1, "updated": 0, "unchanged": 0, "linked_duplicate": 0, "skipped_deleted": 0, "tombstoned_changed": 0, "duplicate_in_sync": 0, "conflict": 0, "invalid": 0, "rejections": {}, "truncated": false})
- ok: the delivered content is retrievable by this tenant and not by the other tenant 
- ok: a wrong secret and a tampered body are rejected with the same 401 invalid_signature (401 401)
- ok: a validly signed but stale delivery is rejected by the timestamp window (401) (HTTP 401)
- ok: replaying a received delivery id is rejected (409 webhook_replayed) (HTTP 409)
- ok: an oversized body is refused (413, or the connection is closed by the server while it is still being sent) and a non-JSON content type is refused (415) (0 415)
- ok: a signed delivery that can never be processed is rejected after authentication (422) (HTTP 422)
- ok: a later delivery with changed content becomes a new document version ({"pages": 1, "seen": 1, "created": 0, "updated": 1, "unchanged": 0, "linked_duplicate": 0, "skipped_deleted": 0, "tombstoned_changed": 0, "duplicate_in_sync": 0, "conflict": 0, "invalid": 0, "rejections": {}, "truncated": false})
- ok: secret rotation: both secrets work during the overlap, the old one is rejected after it is dropped (202 202 401)
- ok: another tenant cannot see or change this endpoint 
- ok: a disabled endpoint rejects even a correctly signed delivery (401) 
- ok: the audit log records endpoint changes and every authenticated delivery outcome (missing [])
- ok: no signing secret, API key or delivery content appears in the audit log, job list or endpoint list 


## Live REST pull synchronization (connector, pagination, rate limit, health probe, recovery)

Source: mock-services/records (separate local process, X-API-Key required; run-only key not recorded)
Fault model: controlled injection in the records mock (a 503 burst after the first page): the retry logic is exercised against that failure, it is not a real upstream outage

### apex-industrial

- ok: the administrator registers a REST records connector (cursor pagination) through the public API (HTTP 201)
- ok: an invalid connector configuration (an absolute URL as the path) is rejected at creation (422) (HTTP 422)
- ok: an engineer cannot start a synchronisation (403) 
- ok: another tenant's administrator gets 404 for this connector 
- ok: a supervisor starts a synchronisation: 202 with a durable QUEUED sync job (HTTP 202)
- ok: the worker pulled every page and ingested every record: COMPLETED, 7 records created over 3 pages ({"status": "COMPLETED", "outcome": "synced", "error_code": null} {"pages": 3, "seen": 7, "created": 7, "updated": 0, "unchanged": 0, "linked_duplicate": 0, "skipped_deleted": 0, "tombstoned_changed": 0, "duplicate_in_sync": 0, "conflict": 0, "invalid": 0, "rejections": {}, "truncated": false})
- ok: the records mock saw real authenticated paginated requests from the connector (3 requests)
- ok: the synchronised content is retrievable by this tenant, with the source record id as provenance (1 hits)
- ok: the other tenant's retrieval never returns this tenant's records (searching the same words) 
- ok: the other tenant cannot read this tenant's sync job (404) 
- ok: a repeated synchronisation is safe: every record unchanged, nothing created twice ({"pages": 3, "seen": 7, "created": 0, "updated": 0, "unchanged": 7, "linked_duplicate": 0, "skipped_deleted": 0, "tombstoned_changed": 0, "duplicate_in_sync": 0, "conflict": 0, "invalid": 0, "rejections": {}, "truncated": false})
- ok: a changed source record becomes a new document version, unchanged ones are skipped ({"pages": 3, "seen": 7, "created": 0, "updated": 1, "unchanged": 6, "linked_duplicate": 0, "skipped_deleted": 0, "tombstoned_changed": 0, "duplicate_in_sync": 0, "conflict": 0, "invalid": 0, "rejections": {}, "truncated": false})
- ok: the update is retrievable 
- ok: a connector limited to 2 requests per second spaces its real requests (3 pages took 1.6 s) ({"elapsed_s": 1.61, "pages": 3})
- ok: without probe=true the health endpoint makes no live request (unchanged behaviour) 
- ok: probe=true makes one bounded real request to the source: ok in 28.4 ms (nothing ingested) ({"status": "ok", "http_status": null, "duration_ms": 28.4, "checked_at": "2026-11-13T21:59:23.753753+00:00"})
- ok: an engineer cannot run the probe (403) 
- ok: a controlled upstream failure is retried with backoff and the job recovers by itself (2 attempts) ({"seen": "RETRY_PENDING", "attempts": 2, "outcome": "synced"})
- ok: a document the user deleted stays deleted after the next synchronisation ({"pages": 3, "seen": 7, "created": 0, "updated": 0, "unchanged": 6, "linked_duplicate": 0, "skipped_deleted": 1, "tombstoned_changed": 0, "duplicate_in_sync": 0, "conflict": 0, "invalid": 0, "rejections": {}, "truncated": false})
- ok: the audit log records the connector, synchronisations, ingested records, the probe and the retry, without content or credentials (missing [])
- ok: no credential and no record content appears in the audit log or the job list 

### meridian-fleet

- ok: the administrator registers a REST records connector (offset pagination) through the public API (HTTP 201)
- ok: an invalid connector configuration (an absolute URL as the path) is rejected at creation (422) (HTTP 422)
- ok: an engineer cannot start a synchronisation (403) 
- ok: another tenant's administrator gets 404 for this connector 
- ok: a supervisor starts a synchronisation: 202 with a durable QUEUED sync job (HTTP 202)
- ok: the worker pulled every page and ingested every record: COMPLETED, 5 records created over 2 pages ({"status": "COMPLETED", "outcome": "synced", "error_code": null} {"pages": 2, "seen": 5, "created": 5, "updated": 0, "unchanged": 0, "linked_duplicate": 0, "skipped_deleted": 0, "tombstoned_changed": 0, "duplicate_in_sync": 0, "conflict": 0, "invalid": 0, "rejections": {}, "truncated": false})
- ok: the records mock saw real authenticated paginated requests from the connector (2 requests)
- ok: the synchronised content is retrievable by this tenant, with the source record id as provenance (4 hits)
- ok: the other tenant's retrieval never returns this tenant's records (searching the same words) 
- ok: the other tenant cannot read this tenant's sync job (404) 
- ok: a repeated synchronisation is safe: every record unchanged, nothing created twice ({"pages": 2, "seen": 5, "created": 0, "updated": 0, "unchanged": 5, "linked_duplicate": 0, "skipped_deleted": 0, "tombstoned_changed": 0, "duplicate_in_sync": 0, "conflict": 0, "invalid": 0, "rejections": {}, "truncated": false})
- ok: a changed source record becomes a new document version, unchanged ones are skipped ({"pages": 2, "seen": 5, "created": 0, "updated": 1, "unchanged": 4, "linked_duplicate": 0, "skipped_deleted": 0, "tombstoned_changed": 0, "duplicate_in_sync": 0, "conflict": 0, "invalid": 0, "rejections": {}, "truncated": false})
- ok: the update is retrievable 
- ok: a connector limited to 2 requests per second spaces its real requests (2 pages took 1.3 s) ({"elapsed_s": 1.3, "pages": 2})
- ok: without probe=true the health endpoint makes no live request (unchanged behaviour) 
- ok: probe=true makes one bounded real request to the source: ok in 27.8 ms (nothing ingested) ({"status": "ok", "http_status": null, "duration_ms": 27.8, "checked_at": "2026-11-13T21:59:34.971405+00:00"})
- ok: an engineer cannot run the probe (403) 
- ok: a controlled upstream failure is retried with backoff and the job recovers by itself (2 attempts) ({"seen": "RETRY_PENDING", "attempts": 2, "outcome": "synced"})
- ok: a document the user deleted stays deleted after the next synchronisation ({"pages": 2, "seen": 5, "created": 0, "updated": 0, "unchanged": 4, "linked_duplicate": 0, "skipped_deleted": 1, "tombstoned_changed": 0, "duplicate_in_sync": 0, "conflict": 0, "invalid": 0, "rejections": {}, "truncated": false})
- ok: the audit log records the connector, synchronisations, ingested records, the probe and the retry, without content or credentials (missing [])
- ok: no credential and no record content appears in the audit log or the job list 


## Browser smoke

2 passed, 0 failed, 0 skipped on this demo stack (real UI, API, worker, database; mock external systems); Microsoft Edge (installed; nothing downloaded).
Initial-navigation retries: 0.
- expected: apex-industrial: structured observation, human verification and server-driven priority through the browser (6.0 s)
- expected: meridian-fleet: structured observation, human verification and server-driven priority through the browser (5.9 s)

## Backup and restore proof

`backups\demo\eaop_demo_20261113_165814_3fa8-20261113T220030Z.dump` (224796 bytes, sha256 `1b693de4e0daa64f...`) of `eaop_demo_20261113_165814_3fa8` (23 tables, 1350 rows; tenants apex-industrial, meridian-fleet) restored into the new isolated database `eaop_demo_restore_20261113_170031_4c08` (dropped):
- ok: backup file matches its manifest (sha256, size) (224796 bytes)
- ok: pg_restore into a new isolated database (completed)
- ok: migration revision preserved (0015)
- ok: tenants preserved (apex-industrial, meridian-fleet)
- ok: row counts of every table equal the source (23 tables, 1350 rows)
- ok: per-tenant counts equal the source (documents, incidents, tickets, audit, approvals, outbox, connectors, memberships, chunks)
- ok: row-level security enabled and forced exactly as in the source (39 policies)
- ok: tenant isolation holds for the restricted application role (2 tenants each see only their own rows; with no tenant context 0 rows are visible)
- ok: backup contains no secret values from .env (no secret value found in the dump text)

## Cleanup

- process ui (pid 12436): stopped
- process api (pid 14248): stopped
- process worker (pid 21812): stopped
- process records (pid 31884): stopped
- process servicedesk (pid 20540): stopped
- process crm (pid 17172): stopped
- process fleet (pid 28384): stopped
- process inventory (pid 24212): stopped
- process ticketing (pid 28028): stopped
- database eaop_demo_20261113_165814_3fa8: dropped

Secrets and credentials are redacted from this report. Logs are kept under `.demo/<run id>/logs` (git-ignored).
