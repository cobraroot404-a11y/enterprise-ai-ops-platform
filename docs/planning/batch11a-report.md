# Batch 11A report: REST pull ingestion, pagination, rate limiting and live health validation

Requirements: V41-12.01 (REST part), V41-11.01, V41-11.02. **None of these three is marked Verified** (webhook and CSV work is Batch 11B; V41-11.02 awaits owner review). Owner-approved status decisions recorded in this batch: V41-12.03, V41-12.04 and V41-12.05 are now VERIFIED for the documented local scope. V41-17.03 stays VERIFIED; V41-14.02 and V41-23.04 stay PARTIAL; V41-16.04 stays PARTIAL; REL-01 stays OPEN. No unrelated status changed. Nothing was pushed, merged, deployed, published or released.

## 1. Starting and ending Git HEAD
Starting: `821d7bf77f6a0e1951007dd04b1ece8ce07efef2` (clean tree, branch `feat/apex-vertical-slice`, specification SHA-256 `b1c573e2...760da` verified). Ending: the final local commit of this batch (stated in the closing message; a file cannot name its own commit). Two local commits: code, tests, documentation; then evidence.

## 2. Requirement definitions and approved interpretation
The specification gives bare list items: Part 11 (lines 453 to 473: connectors for mock CRM, inventory, ticketing, CSV, REST APIs and webhooks; authentication, pagination, rate limiting, timeouts, retries, exponential backoff, schema validation, error classification, idempotency, health checks) and Part 12 (lines 477 to 483: PDF, CSV, JSON, REST API records, webhook payloads). It states no REST ingestion direction beyond "REST API records", so no conflict with the approved reading: *pulling structured records from an authorised REST API into the tenant ingestion pipeline*. This is an approved interpretation, not a declaration that V41-12.01 is satisfied. Check before changing 12.03 to 12.05: lines 495 to 497 are bare list items and nothing else in the specification attaches acceptance criteria to them (lines 548 and 559 are the ticket state list and a test category, 811 a metric, 956 a test list), so no additional binding criterion exists; all three recorded VERIFIED with their limitations (12.03: no automatic expiry of originals of exhausted jobs; 12.04: source reprocessing for documents with retained originals, legacy documents get 409 `source_not_retained`; 12.05: no guarantee of erasure from historical backups or external systems). No historical audit record was rewritten.

## 3. Implementation manifest
[batch11a-manifest.md](batch11a-manifest.md), written before implementation (with one amendment: connector states that cannot be synchronised are 409, not 422, because the repository's API-quality contract reserves 422 for operations with a body or query parameters).

## 4. Exact files changed
New: `backend/app/connectors/rest_records.py`, `backend/app/connectors/ratelimit.py`, `backend/app/ingestion/sync.py`, `backend/migrations/versions/0012_rest_sync.py`, `mock-services/records/records_app.py`, tests `test_rest_connector.py`, `test_rest_sync.py`, `test_migration_0012_rest_sync.py`, docs `architecture/rest-ingestion.md`, `planning/batch11a-manifest.md`, this report. Changed: `connectors/http.py` (Retry-After on the error; additive), `models/__init__.py`, `ingestion/jobs.py`, `ingestion/lifecycle.py`, `api/v1/core_routes.py`, `ops_routes.py`, `response_models.py`, `error_contracts.py`, `core/rbac.py` (`connectors:sync`), `domain_routes.py` (job type filter), `pyproject.toml` (lint and test path settings), `scripts/dev.py`, `scripts/demo.py`, `scripts/demo_smoke.py`, `scripts/v41_requirements_data.py`, `scripts/traceability_data.py`, test support, the contract suites and probes, the OpenAPI snapshot, the 0010 and 0011 migration tests (re-pinned to their own revision), README, runbook, system architecture, API quality, ingestion-jobs, reliability register, regenerated reconciliation, traceability and inventory documents. Frontend: no change. The shared `eaop` database was not touched.

## 5. Connector architecture
A tenant connector of kind `rest` with a `config.records` object; all traffic through the existing `HttpConnector` (per-request egress policy with a pinned address, no redirects, 1 MiB response bound, `X-API-Key` from `secret_ref`). Paths are relative; pagination values are tokens, never URLs; the destination is only the stored `base_url`. Details: [rest-ingestion.md](../architecture/rest-ingestion.md).

## 6. Supported pagination modes
`cursor`, `offset`, `page` and `none`. Handled and tested over real HTTP: multiple pages, empty dataset, empty page that carries a continuation, invalid (URL-like) cursor, repeated cursor, identical repeated page, missing continuation, unexpected shapes, oversize response, page and record limits (reported as `synced_truncated`), duplicates inside one sync.

## 7. Rate-limiting behaviour
Per (tenant, connector) token bucket, process-local, bounded waits, stop event, no cross-tenant sharing; HTTP 429/503 `Retry-After` honoured within 30 s; three bounded attempts per page. Tests: burst then spacing, bounded wait, Retry-After pause and cap, stop returns at once, per-tenant isolation; live: a connector at 2 requests per second took 1.4 s for 3 pages (Apex) and 0.85 s for 2 pages (Meridian). **Not distributed rate limiting; V41-16.04 stays Partial.**

## 8. Live health-probe evidence
`GET /connectors/health?probe=true` (opt-in): one bounded real request; classes `ok`, `connectivity`, `authentication`, `rate_limited`, `schema`, `upstream_error`, `denied`, `not_configured` all tested; without the parameter no network call is made (tested and live). Live: probe `ok` in 13.9 ms (Apex) and 13.7 ms (Meridian), engineer 403, audit event `connector.probed`.

## 9. REST synchronization workflow
`POST /connectors/{id}/sync` (administrator or supervisor) commits a durable `sync` job, then 202; the worker pulls pages, processes each record in its own fenced transaction (retained original, parser, embeddings, `store_parsed`), saves progress after every page and completes only after the last one. Duplicate requests return the active job.

## 10. Job-state and retry results
Same state machine, claims, leases and backoff as other jobs. Tested: transient failure mid-sync saves progress, retries and resumes at the saved cursor (page 1 not fetched again); retry exhaustion then manual re-queue (supervisor; engineer 403); embedding failure; permanent failures with fixed codes (`source_unauthorized`, `credentials_missing`, `source_schema_invalid`, `invalid_cursor`, `pagination_loop`, `source_rejected`, `egress_denied`, `invalid_connector_config`, `source_record_invalid`) fail at once with attempts 1; worker crash then lease expiry recovery without duplicates; concurrent claims (one winner); stale claim cannot write.

## 11. Source provenance and idempotency
`connector_sync_records` keeps per (tenant, connector, source record id): content SHA-256, version marker, document and version, last job and status; chunks carry the source record id; originals are retained. Repeat sync: unchanged skipped (not re-embedded), changed becomes a new version, new created; in-sync duplicate counted; conflicting duplicate keeps the first and is reported; user-deleted records stay deleted (post-11A follow-up: a changed source record no longer recreates them; see rest-ingestion.md).

## 12. Database migration results
Migration `0012` (additive): job type `sync`, `connector_id`, `progress`, the table `connector_sync_records` with forced RLS, a worker INSERT grant on `document_sources`. `test_migration_0012_rest_sync.py` (5 tests, disposable database): upgrade keeps existing jobs; constraints reject inconsistent rows; the application role is tenant isolated and can only mark records deleted; the worker is tenant scoped; downgrade refuses while sync jobs or records exist, restores otherwise, and re-application works. The 0010 and 0011 migration tests were re-pinned to their own revisions (they assumed head). The shared `eaop` database is still at `0006`.

## 13. SSRF and authorization results
Blocked: link-local metadata address (refused at sync request and at execution), destination not approved for the tenant, redirect to a metadata address (never followed, never contacted), absolute-URL and `//` paths, dot segments, URL-like cursors, edited connector `base_url` after queuing (job fails `egress_denied`, nothing sent), edited invalid configuration (fails `invalid_connector_config`). Authorization: engineer and auditor 403, unauthenticated 401, supervisor and administrator allowed; probe administrator only. Credentials: missing secret fails before any request; the key never appears in logs, errors, job JSON, audit or reports (tests and live scan).

## 14. Tenant-isolation evidence
Other tenant's connector id is 404 for sync, other tenant's job id is 404, sync records and documents are RLS-scoped, retrieval of one tenant never returns the other's records (tested and live), the worker's Meridian context shows no Apex provenance, and the 0012 migration tests prove the policies.

## 15. Apex live integration results
Run `20261113-130007-ab51`: 20 checks passed: cursor connector registered, invalid configuration rejected (422), engineer 403, other tenant 404, 202 QUEUED, 7 records over 3 pages created, 3 authenticated mock requests, retrievable with provenance, repeat sync 7 unchanged, update creates a new version (1 updated, 6 unchanged), rate limit spacing, health probe ok, controlled 503 burst retried and recovered in 2 attempts, user-deleted document stays deleted (`skipped_deleted` 1), audit and no-secret checks.

## 16. Meridian live integration results
Same run: 20 checks passed with offset pagination: 5 records over 2 pages, same repeat, update, rate limit, probe, recovery, deletion and isolation checks.

## 17. Negative and fault-injection results
All 18 required negative cases are covered: invalid configuration, blocked SSRF, redirect to a blocked destination, missing credentials, invalid pagination, repeated cursor, HTTP 429, temporary 5xx, permanent schema failure, worker interruption, duplicate synchronisation, concurrent claims, cross-tenant access, stale job completion, deletion during synchronisation (check-to-write race tested directly), duplicate source records, unexpected record changes (conflict), partial processing recovery. **All faults are controlled injections** (a mock that answers 429, 503, bad shapes or redirects; a patched embedder; a raised BaseException; owner-level SQL); none is a real upstream outage. Live runs: `20261113-125904-3ac8` FAILED on a check I wrote too broadly (the other tenant's search returned its own REST documents; Apex steps had all passed), kept; `20261113-130007-ab51` PASSED after the check was corrected.

## 18. API-quality regression results
All nine V41-17.03 properties re-verified by `scripts/api_quality_report.py` at the committed code. One new operation (51 in total: 42 return 200, 6 return 201, 3 return 202); error contract, response schemas, response baseline harness (baseline file unedited), namespace security and the OpenAPI snapshot pass after the reviewed snapshot update (new operation, health parameter, `LiveProbe`, `SyncSummary`, job fields). No existing response changed unless the new opt-in parameter is used.

## 19. Full applicable regression counts
| Check | Result |
|---|---|
| `pytest backend/tests` | **685 passed, 18 skipped, 0 failed** (Batch 10: 612; +73) |
| of which new | `test_rest_connector.py` 44 cases (28 functions), `test_rest_sync.py` 24 cases (22 functions), `test_migration_0012_rest_sync.py` 5 |
| `pytest tests` (root: fault injection incl. FI-09, reconciliation, documentation, launcher) | 118 passed, 1 skipped (one first-run failure, a port pin in the documentation-consistency test, updated for the new documented port 8106 and re-run) |
| secret scan | 0 findings in 953 files |
| ruff (repository) | 8 findings, all pre-existing (unchanged since Batch 8) and none in changed files |
| live checkpoint | `20261113-130007-ab51` PASSED (one earlier run failed, kept) |
Real-AI and browser suites were not run: no code they exercise changed (no frontend change, no prompt, ranking or citation change). Historical results were not rerun or re-claimed.

## 20. Requirement status updates
VERIFIED (owner decision, limitations recorded): V41-12.03, V41-12.04, V41-12.05. Evidence updated, still **Partial**: V41-12.01 (webhooks missing), V41-11.01 (CSV and webhook connectors missing), V41-11.02 (all ten capabilities now exist for the REST records connector; the limiter is process-local; pagination, rate limiting and probe are not applied to the ticketing, inventory, CRM and fleet clients; pending owner review against the complete acceptance criteria). Traceability catalogue R12.5 updated from not implemented to verified. Unchanged: V41-17.03 VERIFIED, V41-14.02, V41-23.04 and V41-16.04 PARTIAL.

## 21. Remaining limitations
API only (no UI); one connector kind with GET pulls; no scheduling; limiter is process-local; webhook and CSV not implemented; chunk text of a synchronised record is the flattened record; a record's identical content under two ids cannot occur because the id is part of the content (the link-duplicate path is defensive only). Open items kept visible: V41-14.02 formal numeric-safety acceptance, REL-01, legacy documents without originals, expiry of exhausted-job sources, deleted content in historical backups, missing independent reproduction, unmet Phase 8 AI-quality targets, distributed rate limiting, remaining deployment and infrastructure requirements.

## 22. Batch 11B architectural recommendations
Reuse the same pipeline: an inbound webhook should resolve the tenant from a small non-RLS endpoint table keyed by an unguessable identifier (never from the payload), verify an HMAC over the raw body with a per-endpoint secret reference using `hmac.compare_digest`, enforce a timestamp window and a nonce/replay record, a tight body-size limit before parsing, answer 202 only after a durable job and retained original are committed, and treat the payload as an `ingest` job with an idempotency key from the delivery id. CSV: a `csv` connector kind using the same pull machinery (`rest_records` pager with a CSV parser and field map from the tenant profile). Decisions needed from the owner first: webhook endpoint management scope (operations to create and rotate endpoints), replay window, and whether CSV pull needs scheduling.

## 23. Exact reproduction commands
```
python -m pytest backend/tests/test_rest_connector.py backend/tests/test_rest_sync.py backend/tests/test_migration_0012_rest_sync.py -q
python -m pytest backend/tests -q
python -m pytest tests -q
python scripts/demo.py smoke --rest --no-browser --backup
python scripts/api_quality_report.py
python scripts/api_response_inventory.py
python scripts/generate_v41_reconciliation.py
python scripts/secret_scan.py
```

## 24. Evidence paths
`evaluation/demo-runs/20261113-130007-ab51/` (report.md, report.json; passing) and `evaluation/demo-runs/20261113-125904-3ac8/` (failed on my check, kept), `evaluation/api-quality/api-quality-evidence.json`, `backend/tests/snapshots/openapi_contract.json`, `docs/api/response-inventory.md`, [rest-ingestion.md](../architecture/rest-ingestion.md), [batch11a-manifest.md](batch11a-manifest.md), the regenerated `docs/specification` and `docs/traceability` files.

## 25. No remote or release operations
Confirmed: local commits only; no push, merge, tag, deployment, publication or release; no remote created; no model or dependency downloaded; zero cost; shared `eaop` database untouched; no webhook or CSV code written.
