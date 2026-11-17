# Batch 10 report: controlled source storage and ingestion completion

Requirements: V41-12.03 (retry handling) and V41-12.04 (reprocessing); V41-12.05 preserved. Neither 12.03 nor 12.04 is marked Verified: both stay **Partial, implemented and tested, pending owner review**. V41-17.03 stays VERIFIED; V41-14.02, V41-12.05 and V41-23.04 stay PARTIAL; no other requirement status changed. REL-01 stays open (not investigated). Nothing was pushed, merged, deployed, published or released.

## 1. Starting and ending Git HEAD
Starting: `b7c7cf48de2046488e2d4d7cea0e6a093aab6f15` (clean tree, branch `feat/apex-vertical-slice`, specification SHA-256 `b1c573e2...760da` verified). Ending: the final local commit of this batch (stated in the closing message; a file cannot name its own commit). Two local commits: code and documentation, then evidence.

## 2. Implementation manifest
[batch10-manifest.md](batch10-manifest.md), written before implementation. Audit result: no original content was retained; storage in PostgreSQL supports the design without any new service, dependency or storage abstraction.

## 3. Exact files changed
New: `backend/app/ingestion/sources.py`, `backend/migrations/versions/0011_document_sources.py`, tests `test_document_sources.py`, `test_migration_0011_document_sources.py`, `test_source_ingestion.py`, `docs/planning/batch10-manifest.md`, this report. Changed: `models/__init__.py`, `ingestion/jobs.py`, `ingestion/service.py`, `ingestion/lifecycle.py`, `api/v1/error_contracts.py` (409 declared for reprocess), `pyproject.toml` (per-file lint settings), OpenAPI snapshot (one added status), tests `test_ingestion_jobs.py`, `test_deletion_exposure_audit.py`, `test_migration_0010_ingestion_jobs.py` (re-pinned to its own revision), `api_error_probes.py`, README, runbook, system architecture, API quality, ingestion-jobs, document-lifecycle, requirement records and regenerated reconciliation, traceability and inventory documents. Frontend: no change. Shared `eaop` database: not touched.

## 4. Source-storage architecture
`document_sources` table in PostgreSQL (`bytea`), chosen over a filesystem because it commits in one transaction with the job and document (no orphan files, no crash reconciliation), is isolated by the same RLS, needs no path handling (nothing to forge), is covered by the existing `pg_dump` backups, and is deleted by the existing cleanup. Content is immutable (no UPDATE privilege on bytes, hash or size for either role), bounded (upload limit 10 MiB, database CHECK 16 MiB), checksum-verified on store and on every read, linked to the document version in the same transaction as the final write, and never returned by any API route. Details: [ingestion-jobs.md](../architecture/ingestion-jobs.md).

## 5. Migration results
Migration `0011` (additive; head moved from `0010`). `test_migration_0011_document_sources.py` (5 tests, disposable database): upgrade keeps existing documents with no source; constraints reject length lies, malformed hashes, empty and half-linked rows; the application role is tenant isolated and cannot edit content; the worker reads, links and deletes only inside its tenant and cannot create or edit; downgrade refuses while sources exist, restores the schema otherwise, and re-application works. Live runs used disposable databases at head. **The shared `eaop` database was not migrated or reset (still revision `0006`).**

## 6. Checkpoint A results (storage)
`test_document_sources.py` 6 passed plus the 5 migration tests: persistence and read-back by app and worker, checksum mismatch refused at store, simulated bit rot detected on read, other-tenant and forged identifiers find nothing and delete nothing, interrupted and crashed writes leave nothing, release removes only unlinked sources and purge removes every source of a document.

## 7. Checkpoint B results (recoverable initial ingestion)
`test_source_ingestion.py` (B part) and the updated `test_ingestion_jobs.py` passed. Sources retained and linked on success with the response unchanged; an upload "killed" after the job and source were saved is completed by the worker from the source after lease expiry; a source-persistence failure accepts nothing (no job, source or document); parse failure stores nothing; retries stay bounded with the existing fenced claims; an exhausted job is re-queued with `POST /ingestion/jobs/{id}/retry` without re-uploading and cannot be double re-queued; permanent failures keep no content.

## 8. Checkpoint C results (source reprocessing)
The worker reads the retained original, verifies its checksum, re-runs the parser with the stored options, embeds, stages a new generation, validates and activates atomically (migration 0010 mechanics). Proof it is genuine: the test overwrites the stored chunks with junk and the new generation still equals the parse of the original (record identifiers included). Historical documents without an original get `409 source_not_retained` with an explicit message. Missing or corrupted originals fail permanently and leave the active generation untouched; an embedder failure keeps the old generation serving and then recovers.

## 9. Initial-ingestion recovery evidence
Controlled injections (simulated, none a real outage): embedding failure, worker "crash" (BaseException) after claim and after the job and source were stored, lease expiry and worker restart, retry exhaustion then manual retry, source persistence failure, missing and corrupted source, forged source identifier. Live: 3 attempts of 5 then completion on both tenants.

## 10. Duplicate-upload compatibility evidence
FI-09 (root fault-injection test) and a new test (six simultaneous identical uploads): all 201, one `created`, five `duplicate`, one version, one retained original. A repeat of identical content while the first upload is unresolved (embedder down) is a 503 and never a fabricated duplicate; one job and one source exist. Sequential duplicate returns `duplicate` after completion, as before.

## 11. Source-reprocessing evidence
Section 8, plus the live checkpoint: generation 1 to 2 on both tenants through the source path, no duplicate results, engineer 403, other tenant 404.

## 12. Version and generation integrity
A new version stores its own original and older versions keep theirs; reprocessing updates `active_generation` and `chunk_count` with the job id in the same transaction as the activation; retired generations remain non-current; failed or incomplete generations are never retrievable (Batch 9 tests still pass).

## 13. Deletion and cleanup results
Cleanup removes every retained original of the document (all versions), verifies none remain, and audits `sources_removed` without content. Tests: deletion cancels a retrying new-version job and releases its original at once, retry of the cancelled job is refused and nothing recreates content; a reprocess job queued before deletion is cancelled and cannot activate; a failed cleanup rolls back, keeps the originals, and the retry completes; cleanup of an old document leaves a replacement upload of the same bytes and another tenant's identical document untouched. Live: reprocess-versus-delete race cancelled on both tenants, cleanup completed.

## 14. Backup and retention limitations
Application-level deletion is not irreversible physical erasure. Backups taken before a deletion (including the demonstration backups) contain the original bytes of deleted documents until discarded; dead tuples remain in PostgreSQL pages until VACUUM; no retention or backup-expiry policy was approved or implemented. Originals kept for jobs that exhausted their retries have no automatic expiry. Audit events were not modified (the upload audit still holds file name and SHA-256, EXP-01 to EXP-03 unchanged).

## 15. Tenant-isolation and authorization results
RLS on `document_sources` (forced); worker access is tenant-scoped by policy with column-limited grants; cross-tenant read, delete and forged-identifier tests pass; no source download route exists. Reprocess and retry remain administrator or supervisor only.

## 16. Live Apex and Meridian results
`evaluation/demo-runs/20261113-075909-0569/` (report.md, report.json), command `python scripts/demo.py smoke --ingestion --no-browser --backup`: PASSED, 15 ingestion checks per tenant (30 in total) plus the existing workflow checks and the backup and restore proof, on a disposable database at revision `0011`, dropped afterwards. The failure exercised is **simulated** (`scripts/fault_boot.py`), not a real infrastructure outage. Browser smoke skipped (`--no-browser`; no frontend change). This was the only live run of the batch (no failed attempts).

## 17. Backend and API-quality regressions
Backend: **612 passed, 18 skipped, 0 failed** (Batch 9 ended at 583; +29 new tests: 18 + 6 + 5). Contract suites (error, schemas, response baseline, namespace security, OpenAPI snapshot): passed after the snapshot gained one declared status (409 on reprocess; the diff was reviewed and is exactly that line). All nine API-quality properties re-verified by `scripts/api_quality_report.py` at the committed code. Root tests: see the table below.

| Check | Result |
|---|---|
| `pytest backend/tests` | 612 passed, 18 skipped |
| `pytest tests` (root, includes FI-09 and reconciliation) | 118 passed, 1 skipped |
| first targeted run after wiring sources | 4 failed (tests encoding the Batch 9 "no content kept" behaviour and the "no content columns" exposure assertion); updated deliberately, see section 19 |

## 18. Security and secret-scan results
Secret scan: 0 findings in 938 files. Ruff: the same 8 pre-existing findings (none in changed files); one `ruff --fix` run touched a historical evaluation script and was reverted at once.

## 19. Remaining defects and limitations
REL-01 open. Documents uploaded before 0011 cannot be reprocessed from source (explicit 409). No expiry for originals of exhausted jobs; no dead-letter UI; backups retain originals; EXP-01 to EXP-04 remain; only the embedding-step failure was exercised live; same-author evidence. Test corrections made this batch (preserved in the diff): Batch 9 tests that asserted failed uploads keep no content, the missing-content test (now missing and corrupted original), and the exposure audit's "no bytes column" assertion (now: the only bytes store is `document_sources` and it is empty for the deleted document).

## 20. Requirements status recommendations
12.03: stay **Partial**; the original definition ("Failed ingestions are retried safely") is now met by recoverable, bounded, idempotent retry from retained originals; a Verified decision should wait for owner review and the retention decision. 12.04: stay **Partial** pending owner review; true source-based reprocessing now exists but historical documents are excluded by documented limitation. 12.05: stays Partial (deletion now also removes originals; physical-erasure and backup policy are separate decisions).

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

## 22. Evidence paths
`evaluation/demo-runs/20261113-075909-0569/`, `evaluation/api-quality/api-quality-evidence.json`, `backend/tests/snapshots/openapi_contract.json`, `docs/api/response-inventory.md`, [ingestion-jobs.md](../architecture/ingestion-jobs.md), [document-lifecycle.md](../architecture/document-lifecycle.md), [batch10-manifest.md](batch10-manifest.md).

## 23. Recommended Batch 11
Owner choice. Suggested: an owner policy for retention of originals (expiry for exhausted-job originals, backup retention) with the EXP-01 to EXP-03 scrub decision, then the REL-01 diagnosis, then a deletion control in the UI.
