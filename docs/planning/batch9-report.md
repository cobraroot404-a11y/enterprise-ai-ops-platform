# Batch 9 report: durable document ingestion, controlled retry and safe reprocessing

Requirements: V41-12.03 "Retry handling" and V41-12.04 "Reprocessing". Neither is marked Verified: both are recorded as **Partial, implemented and tested, pending owner review**. V41-17.03 stays VERIFIED; V41-14.02, V41-12.05 and V41-23.04 stay PARTIAL; no other requirement status was changed. REL-01 stays open. Nothing was pushed, merged, published or released.

## 1. Starting and ending Git HEAD
Starting: `05265f7fe9761823d34d11ef94b03df3c60a192c` (Batch 8). Ending: the final local commit of this batch (reported in the closing message; a file cannot name its own commit). Two local commits: code and documentation, then regenerated evidence.

## 2. Exact requirement wording reviewed
Original specification (SHA-256 verified before starting), lines 485 to 499: "Implement: Parsing, Normalization, Validation, Metadata extraction, Content hashing, Duplicate detection, Version tracking, Idempotent ingestion, Retry handling, Reprocessing, Deletion, Reindexing. Preserve source provenance, including page numbers and record identifiers." Acceptance for 12.03: "Failed ingestions are retried safely". For 12.04: "Documents can be reprocessed". Before Batch 9: 12.03 was **Missing** (no job entity or retry mechanism) and 12.04 **Partial** (re-embedding only).

## 3. Architecture manifest
[batch9-manifest.md](batch9-manifest.md) (written before implementation) and the resulting design in [../architecture/ingestion-jobs.md](../architecture/ingestion-jobs.md). The job table is itself the durable queue; the existing worker loop drains it; no new framework or service.

## 4. Files changed
New: `backend/app/ingestion/jobs.py`, `backend/migrations/versions/0010_ingestion_jobs.py`, `scripts/fault_boot.py`, tests `test_ingestion_jobs.py`, `test_migration_0010_ingestion_jobs.py`, `test_deletion_exposure_audit.py`, docs `ingestion-jobs.md`, `batch9-manifest.md`, this report. Changed: `models/__init__.py`, `ingestion/service.py`, `ingestion/lifecycle.py` (deletion cancels jobs), `workflows/worker.py`, `api/v1/domain_routes.py`, `response_models.py`, `error_contracts.py`, `core/rbac.py` (`documents:reprocess`), `pyproject.toml` (per-file E501 exemptions for two modules), `scripts/demo.py`, `scripts/demo_smoke.py`, `scripts/v41_requirements_data.py`, the OpenAPI snapshot, the affected existing tests (pinned operation counts, route table, migration tests pinned to their own revision instead of head, one test seam renamed), README, runbook, system architecture, API-quality, document-lifecycle, reliability register, regenerated reconciliation, traceability and response-inventory documents. Frontend: no change.

## 5. Persistent job schema and state machine
Table `ingestion_jobs` (tenant, job type `ingest` or `reprocess`, status, document and version, attempts and `max_attempts` (default 5), `next_attempt_at`, fencing `claim_token` and `locked_until`, sanitised `error_code`, `idempotency_key`, outcome, chunk counts, generations, requested-by, correlation id, parsed `payload` kept only while runnable). States and transitions: QUEUED to PROCESSING or CANCELLED; RETRY_PENDING to PROCESSING or CANCELLED; PROCESSING to COMPLETED, RETRY_PENDING, FAILED or CANCELLED; FAILED to QUEUED (manual retry, reprocess jobs only); COMPLETED and CANCELLED final. Enforced twice: by one server function and by database CHECK constraints (tests try forged states). Details: ingestion-jobs.md.

## 6. Migration evidence
Migration `0010` is additive (new table, `document_chunks.generation`, `document_versions.active_generation` and `processing_job_id`, RLS, worker policies and column-limited grants). `test_migration_0010_ingestion_jobs.py` (5 tests, disposable database): upgrade preserves data and defaults generation to 1; constraints reject forged rows; the application role is tenant isolated; the worker is tenant scoped with limited columns; downgrade refuses while jobs or reprocessed generations exist and otherwise restores the schema, and re-apply works. Every live run used a disposable database at `0010` and dropped it. **The shared `eaop` database was not migrated: it is still at revision `0006`** (checked after the runs).

## 7. Retry and failure-recovery results
`test_ingestion_jobs.py` covers: transient failure keeps the public 503 contract and queues a retry that the worker completes; a repeated upload resumes the same job; retries are bounded (FAILED `retries_exhausted`, content dropped); permanent failures are recorded once and never retried; a worker dying after claiming is recovered when the lease expires; a crash at each processing stage never duplicates chunks or versions; concurrent workers never claim the same job; a stale claim cannot overwrite newer state and a job completes exactly once. Live (item 14): retry and recovery after a **simulated** failure, 3 attempts of a limit of 5, on both tenants.

## 8. Reprocessing and version-lineage behaviour
`POST /documents/{id}/reprocess` (administrator or supervisor, 202) re-embeds the stored chunk text into a new generation, staged non-current, validated, then activated with the job completion in one transaction. Tests: replacement generation built with lineage preserved; incomplete replacement never retrievable and a failed reprocess keeps the active version; a failure between staging and activation rolls back the staged generation. Old generations stay non-current so historical citations keep meaning. **Limit:** there is no original-file store, so reprocessing re-embeds stored chunk text and does not re-parse the source file.

## 9. Deletion race-condition results
Tests: deletion cancels queued and retrying jobs and content never returns; deletion after a worker claimed a job, or during reprocessing, discards the late write; the activation boundary re-checks the lifecycle even if no job was cancelled; concurrent deletion and reprocessing requests serialise; re-upload after deletion leaves the new document processable. Live: a reprocessing job queued during the simulated failure is cancelled by deletion and never runs after recovery; the content stays deleted and unsearchable on both tenants.

## 10. Original-document cleanup audit
`test_deletion_exposure_audit.py` and the Exposure register in [document-lifecycle.md](../architecture/document-lifecycle.md). The platform stores **no original file** (no file store, no bytes column; tested). Removed by cleanup: chunks, embeddings, search vectors, versions, job payloads, all generations. Made inaccessible: listings, direct access, search, citations, reprocessing, jobs. **Remaining, documented and not fixed:** EXP-01 audit event keeps file name and SHA-256; EXP-02 job idempotency key embeds the SHA-256 and the job keeps the file name; EXP-03 tombstone keeps file name and kind; EXP-04 database dead tuples and earlier backups. Scrubbing EXP-01 to EXP-03 needs an owner policy decision.

## 11. API backward-compatibility evidence
No existing operation changed. `POST /documents` keeps its request, 201 body and error contract (503 `embedding_unavailable` with `Retry-After`; the baseline response-contract harness passes with the baseline file unedited). **A regression was found and fixed during this batch:** the first implementation answered simultaneous identical uploads with `503 ingestion_in_progress` for the losers where the previous behaviour was `201 duplicate`; fault-injection test FI-09 failed in the root test run. The loser now waits up to 15 s for the request that holds the job and resolves to the existing document. Four operations were added (50 in total: 42 return 200, 6 return 201, 2 return 202). Two baseline operations (`GET /audit`, `GET /observability/summary`) gained new vocabulary; the harness accepts exactly that growth through an explicit superset comparison and still fails on removal or change.

## 12. Tenant-isolation and authorization results
Reprocess and retry: administrator or supervisor only (engineer and auditor get 403, tested and live). Job reads are tenant scoped; another tenant's job or document is 404 (live, both directions). The worker has no RLS bypass: content writes run in tenant-scoped sessions, with policy tests that a forged cross-tenant write is refused. The authorization suite pins the four new routes.

## 13. Audit and observability evidence
Audit actions (content-free): `ingestion.job_created`, `attempt_started`, `attempt_abandoned`, `retry_scheduled`, `job_retry_requested`, `job_completed`, `job_failed`, `job_error`, `job_cancelled`, `document.reprocess_requested`, `document.reprocessed`. The live checkpoint asserts the chain in the audit log. Existing metrics only (a test checks they show job activity without content).

## 14. Live Apex and Meridian test results
Isolated disposable stack, both tenants, 15 checks each, all passed: `evaluation/demo-runs/20261113-043441-bf25/` (report.md, report.json). Command: `python scripts/demo.py smoke --ingestion --no-browser --backup`. Honest run history, all kept: `20261113-041404-1c87` and `20261113-041453-2ded` FAILED on a case-sensitive `Retry-After` comparison in the new checkpoint script (a harness bug, not an API defect); `20261113-041535-9e37` passed; `20261113-041657-5fa4` passed (added the report section); `20261113-043441-bf25` passed on the final code after the FI-09 fix. **The failure exercised is simulated**: `scripts/fault_boot.py` makes the embedder raise while a switch file exists, the same failure mode as an unloadable embedding model; it is not a real infrastructure outage and the browser smoke was skipped in these runs (`--no-browser`; no frontend change).

## 15. Full regression results
Backend: 583 passed, 18 skipped, 0 failed (final code). Root tests, secret scan, ruff and documentation consistency: see the table below.

| Check | Result |
|---|---|
| `pytest backend/tests` | 583 passed, 18 skipped |
| `pytest tests` (root: fault injection, reconciliation, documentation, launcher) | 118 passed, 1 skipped (final code) |
| secret scan | 0 findings |
| ruff (repository) | 8 findings, all pre-existing and unrelated (unchanged from Batch 8); none in changed files |
| first root run | 3 failed: FI-09 (real regression, fixed as in item 11) and two reconciliation checks (report path missing, documents stale; fixed by this report and regeneration) |

## 16. Remaining defects and limitations
REL-01 open and not investigated. A failed upload keeps no content, so manual retry applies to reprocess jobs only (the client repeats the upload). Only the embedding-step failure was exercised live. No dead-letter UI, no purge of old job rows. Old generations occupy storage until deletion. Reprocessing does not re-parse source files. EXP-01 to EXP-04 remain. Same-author evidence. Not run: frontend and browser smoke (unchanged).

## 17. V41-12.03 and V41-12.04 status recommendations
12.03: moved Missing to **Partial** (implemented, tested, live evidence). 12.04: remains **Partial** (stronger evidence). Recommendation: keep both Partial until owner review; a Verified decision would reasonably wait for (a) an independent review, (b) a decision on retention of failed-upload content, (c) a non-simulated failure test if one is acceptable at no cost.

## 18. V41-12.05 follow-up recommendation
Keep Partial. Open follow-ups: owner policy on EXP-01 to EXP-03, a UI control for deletion, retention policy for job rows and tombstones.

## 19. Updated requirements traceability
`scripts/v41_requirements_data.py` updated; reconciliation, gap register, traceability and `docs/api/response-inventory.md` regenerated. Status counts of the 85-item catalogue are unchanged.

## 20. Recommended Batch 10
Owner choice. Suggested: the REL-01 diagnosis with the readiness-timeout diagnostics, then the deletion UI control and the EXP-01 to EXP-03 policy decision.

## 21. Exact reproduction commands
```
python -m pytest backend/tests -q
python -m pytest tests -q
python scripts/demo.py smoke --ingestion --no-browser --backup
python scripts/api_quality_report.py
python scripts/api_response_inventory.py
python scripts/generate_v41_reconciliation.py
python scripts/secret_scan.py
```

## 22. Evidence and report paths
`evaluation/demo-runs/20261113-043441-bf25/` (final), the four earlier runs listed in item 14, `evaluation/api-quality/api-quality-evidence.json`, `backend/tests/snapshots/openapi_contract.json`, `docs/api/response-inventory.md`, [ingestion-jobs.md](../architecture/ingestion-jobs.md), [document-lifecycle.md](../architecture/document-lifecycle.md), the reliability register.

## 23. No push, merge or release
Confirmed: local commits only; no push, merge, tag, publish or release; no remote used; no downloads; no model or tool installation; $0.
