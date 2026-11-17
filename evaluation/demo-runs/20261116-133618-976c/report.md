# Demo smoke report 20261116-133618-976c

Result: **FAILED** in 89.5 s (mode smoke, AI backends: deterministic).
Git HEAD at run: `1cf61890b7296a23b5e2d166840f2bf7ada45f77`. Started 2026-11-16T13:36:18-05:00, finished 2026-11-16T13:37:47-05:00.

## Failures
- [WinError 10054] An existing connection was forcibly closed by the remote host

## Timeline (executed)

| Step | Result | Seconds | Detail |
|---|---|---|---|
| preflight | ok | 4.0 | 7 checks passed |
| create disposable database eaop_demo_20261116_133618_976c | ok | 0.1 | created |
| apply migrations (alembic upgrade head) | ok | 1.5 | revision 0017 |
| seed Apex Industrial fixtures | ok | 1.4 | ok (log .demo\20261116-133618-976c\logs\seed-apex.log) |
| start ticketing and wait for readiness | ok | 1.1 | responds over HTTP |
| start inventory and wait for readiness | ok | 1.1 | responds over HTTP |
| start fleet and wait for readiness | ok | 1.1 | responds over HTTP |
| start crm and wait for readiness | ok | 1.1 | responds over HTTP |
| start servicedesk and wait for readiness | ok | 1.1 | responds over HTTP |
| start records and wait for readiness | ok | 1.1 | responds over HTTP |
| start worker and wait for readiness | ok | 2.1 | logged 'worker started' |
| start api and wait for readiness | ok | 2.2 | GET /api/v1/health 200 (database reachable) |
| onboard Meridian Fleet (public API) | ok | 1.4 | ok (log .demo\20261116-133618-976c\logs\onboard-meridian.log) |
| customer workflows through the API (Apex and Meridian) | ok | 7.7 |  |
| live ingestion checkpoint: jobs, retry (simulated outage), reprocessing, deletion races | ok | 22.1 |  |
| live REST pull synchronization: connector, pagination, rate limit, health probe, recovery (both tenants) | ok | 25.4 |  |
| live CSV connector and signed webhook integrations (both tenants) | FAILED | 5.2 | [WinError 10054] An existing connection was forcibly closed by the remote host |

Database: disposable `eaop_demo_20261116_133618_976c` created by this run, migrated to revision `0017` (head `0017`).

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
- ok: a connector limited to 2 requests per second spaces its real requests (3 pages took 1.3 s) ({"elapsed_s": 1.27, "pages": 3})
- ok: without probe=true the health endpoint makes no live request (unchanged behaviour)
- ok: probe=true makes one bounded real request to the source: ok in 23.1 ms (nothing ingested) ({"status": "ok", "http_status": null, "duration_ms": 23.1, "checked_at": "2026-11-16T18:37:16.503759+00:00"})
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
- ok: a connector limited to 2 requests per second spaces its real requests (2 pages took 0.9 s) ({"elapsed_s": 0.89, "pages": 2})
- ok: without probe=true the health endpoint makes no live request (unchanged behaviour)
- ok: probe=true makes one bounded real request to the source: ok in 28.1 ms (nothing ingested) ({"status": "ok", "http_status": null, "duration_ms": 28.1, "checked_at": "2026-11-16T18:37:27.596201+00:00"})
- ok: an engineer cannot run the probe (403)
- ok: a controlled upstream failure is retried with backoff and the job recovers by itself (2 attempts) ({"seen": "RETRY_PENDING", "attempts": 2, "outcome": "synced"})
- ok: a document the user deleted stays deleted after the next synchronisation ({"pages": 2, "seen": 5, "created": 0, "updated": 0, "unchanged": 4, "linked_duplicate": 0, "skipped_deleted": 1, "tombstoned_changed": 0, "duplicate_in_sync": 0, "conflict": 0, "invalid": 0, "rejections": {}, "truncated": false})
- ok: the audit log records the connector, synchronisations, ingested records, the probe and the retry, without content or credentials (missing [])
- ok: no credential and no record content appears in the audit log or the job list


## Cleanup

- process api (pid 23116): stopped
- process worker (pid 22780): stopped
- process records (pid 10792): stopped
- process servicedesk (pid 8796): stopped
- process crm (pid 1632): stopped
- process fleet (pid 5248): stopped
- process inventory (pid 8844): stopped
- process ticketing (pid 21584): stopped
- database eaop_demo_20261116_133618_976c: dropped

Secrets and credentials are redacted from this report. Logs are kept under `.demo/<run id>/logs` (git-ignored).
