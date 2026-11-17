# Demo smoke report 20261113-140424-3fb1

Result: **PASSED** in 82.2 s (mode smoke, AI backends: deterministic).
Git HEAD at run: `247026fc0f0576cf4aad0166bf60a572eb7834ae`. Started 2026-11-13T14:04:24-05:00, finished 2026-11-13T14:05:46-05:00.

## Skipped
- browser smoke (--no-browser)

## Timeline (executed)

| Step | Result | Seconds | Detail |
|---|---|---|---|
| preflight | ok | 4.1 | 7 checks passed |
| create disposable database eaop_demo_20261113_140424_3fb1 | ok | 0.1 | created |
| apply migrations (alembic upgrade head) | ok | 1.6 | revision 0013 |
| seed Apex Industrial fixtures | ok | 1.6 | ok (log .demo\20261113-140424-3fb1\logs\seed-apex.log) |
| start ticketing and wait for readiness | ok | 1.8 | responds over HTTP |
| start inventory and wait for readiness | ok | 1.3 | responds over HTTP |
| start fleet and wait for readiness | ok | 1.3 | responds over HTTP |
| start crm and wait for readiness | ok | 1.2 | responds over HTTP |
| start servicedesk and wait for readiness | ok | 1.3 | responds over HTTP |
| start records and wait for readiness | ok | 1.3 | responds over HTTP |
| start worker and wait for readiness | ok | 2.3 | logged 'worker started' |
| start api and wait for readiness | ok | 2.4 | GET /api/v1/health 200 (database reachable) |
| onboard Meridian Fleet (public API) | ok | 1.5 | ok (log .demo\20261113-140424-3fb1\logs\onboard-meridian.log) |
| customer workflows through the API (Apex and Meridian) | ok | 6.5 |  |
| live REST pull synchronization: connector, pagination, rate limit, health probe, recovery (both tenants) | ok | 24.1 |  |
| live CSV connector and signed webhook integrations (both tenants) | ok | 15.6 |  |
| backup the demo database and prove it restores (isolated restore database) | ok | 2.5 |  |

Database: disposable `eaop_demo_20261113_140424_3fb1` created by this run, migrated to revision `0013` (head `0013`).

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
- ok: a connector limited to 2 requests per second spaces its real requests (3 pages took 1.3 s) ({"elapsed_s": 1.26, "pages": 3})
- ok: without probe=true the health endpoint makes no live request (unchanged behaviour) 
- ok: probe=true makes one bounded real request to the source: ok in 14.1 ms (nothing ingested) ({"status": "ok", "http_status": null, "duration_ms": 14.1, "checked_at": "2026-11-13T19:04:59.594341+00:00"})
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
- ok: a connector limited to 2 requests per second spaces its real requests (2 pages took 0.8 s) ({"elapsed_s": 0.77, "pages": 2})
- ok: without probe=true the health endpoint makes no live request (unchanged behaviour) 
- ok: probe=true makes one bounded real request to the source: ok in 13.8 ms (nothing ingested) ({"status": "ok", "http_status": null, "duration_ms": 13.8, "checked_at": "2026-11-13T19:05:11.706052+00:00"})
- ok: an engineer cannot run the probe (403) 
- ok: a controlled upstream failure is retried with backoff and the job recovers by itself (2 attempts) ({"seen": "RETRY_PENDING", "attempts": 2, "outcome": "synced"})
- ok: a document the user deleted stays deleted after the next synchronisation ({"pages": 2, "seen": 5, "created": 0, "updated": 0, "unchanged": 4, "linked_duplicate": 0, "skipped_deleted": 1, "tombstoned_changed": 0, "duplicate_in_sync": 0, "conflict": 0, "invalid": 0, "rejections": {}, "truncated": false})
- ok: the audit log records the connector, synchronisations, ingested records, the probe and the retry, without content or credentials (missing [])
- ok: no credential and no record content appears in the audit log or the job list 


## Backup and restore proof

`backups\demo\eaop_demo_20261113_140424_3fb1-20261113T190532Z.dump` (164854 bytes, sha256 `4e725640c2319770...`) of `eaop_demo_20261113_140424_3fb1` (20 tables, 618 rows; tenants apex-industrial, meridian-fleet) restored into the new isolated database `eaop_demo_restore_20261113_140533_0438` (dropped):
- ok: backup file matches its manifest (sha256, size) (164854 bytes)
- ok: pg_restore into a new isolated database (completed)
- ok: migration revision preserved (0013)
- ok: tenants preserved (apex-industrial, meridian-fleet)
- ok: row counts of every table equal the source (20 tables, 618 rows)
- ok: per-tenant counts equal the source (documents, incidents, tickets, audit, approvals, outbox, connectors, memberships, chunks)
- ok: row-level security enabled and forced exactly as in the source (39 policies)
- ok: tenant isolation holds for the restricted application role (2 tenants each see only their own rows; with no tenant context 0 rows are visible)
- ok: backup contains no secret values from .env (no secret value found in the dump text)

## Cleanup

- process api (pid 27884): stopped
- process worker (pid 3812): stopped
- process records (pid 2672): stopped
- process servicedesk (pid 10804): stopped
- process crm (pid 21696): stopped
- process fleet (pid 24616): stopped
- process inventory (pid 27760): stopped
- process ticketing (pid 31588): stopped
- database eaop_demo_20261113_140424_3fb1: dropped

Secrets and credentials are redacted from this report. Logs are kept under `.demo/<run id>/logs` (git-ignored).
