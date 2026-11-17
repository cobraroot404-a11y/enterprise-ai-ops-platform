# Batch 10 implementation manifest (written before implementation)

Start: HEAD `b7c7cf48de2046488e2d4d7cea0e6a093aab6f15`, branch `feat/apex-vertical-slice`, clean tree, migration head `0010`, specification SHA-256 `b1c573e2...760da` verified. Requirements V41-12.03 (retry handling) and V41-12.04 (reprocessing); V41-12.05 stays Partial.

## Audit findings
- No original content is retained anywhere: the upload route reads at most `MAX_UPLOAD_BYTES` (10 MiB, 413 above), parses and keeps only chunk text. Batch 9 reprocessing therefore re-embedded stored chunk text (it did not re-parse a source), and a failed upload could not be retried manually once its parsed payload was dropped.
- Parsing is `parsers.parse(filename, data, field_map, id_field)`; one parsed segment becomes one chunk. `store_parsed` writes document, version and chunks in the caller's transaction; jobs complete in that same transaction (0010).
- Roles: `eaop_app` is tenant-isolated by RLS; `eaop_worker` claims jobs across tenants but writes document data only through tenant-scoped policies and column-limited grants (0009, 0010).
- Deletion (Batch 8): stage A logical delete and job cancellation; stage B worker cleanup removes chunks and versions and verifies. Backups: `scripts/demo.py --backup` uses `pg_dump`, so anything in the database is in a backup.

## Storage decision: PostgreSQL (`bytea`), not the filesystem
PostgreSQL gives one transaction boundary with the job and the document (no orphan or half-written files to reconcile after a crash), RLS tenant isolation with no path handling at all (nothing for a client to forge), integrity by a stored SHA-256 plus a CHECK on length, backups that already cover it (and a retention limit that is stated, not hidden), deletion in the existing cleanup, and no new service or dependency. The 10 MiB bound keeps rows small (large values are TOASTed). A filesystem store would need its own atomic-write, fsync, orphan sweep, permission and backup logic: more operational footprint, not less. No storage abstraction is introduced.

## Design (migration 0011, additive)
- Table `document_sources` (id, tenant_id, document_id and version once linked, filename, kind, media_type, size_bytes, content_hash, `parse_options` jsonb (CSV field map and id field), `content bytea`), RLS for the app role, tenant-scoped worker policy, CHECKs (length equals `size_bytes`, at most 16 MiB, hash is 64 hex).
- `ingestion_jobs.source_id` and `document_versions.source_id` (nullable: existing documents have no source and stay fully supported).
- Upload: parse (permanent failures unchanged) then, in the transaction that opens the job, store the source; embedding and the final write happen as before; the final write links the source to the version in the same transaction as the document and the job completion. New jobs no longer keep the parsed text in `payload`; a retry re-reads and re-parses the source (checksum verified). Jobs created before 0011 keep the old payload path.
- Retry: transient failures retry from the source with the existing bounded backoff, fenced claims and idempotency. A job that exhausted its retries keeps its source and can be re-queued with `POST /ingestion/jobs/{id}/retry` (now allowed for ingest jobs that have a source). The synchronous contract is untouched: no success is reported before indexing completes, and a concurrent identical upload still waits for the first and resolves to its result (FI-09).
- Source lifecycle: removed when its job is cancelled, when a permanent failure makes it useless, when the result is a duplicate, and with the document at deletion cleanup (all versions); cleanup verifies none remain.
- Reprocessing: reads the version's source, verifies the checksum, re-runs the supported parser, embeds, stages a new generation, validates, activates atomically (unchanged 0010 mechanics). A document without a retained source gets `409 source_not_retained` at request time (explicit documented limitation); chunk re-embedding is no longer presented as reprocessing.
- No download endpoint for sources: source content is reachable only by tenant-scoped server code (the worker and the upload path), never through the API.

## API
No new operation. Behaviour changes: `POST /documents/{id}/reprocess` can answer 409 `source_not_retained`; `POST /ingestion/jobs/{id}/retry` accepts failed ingest jobs that have a source. Responses of `POST /documents` are unchanged.

## Tests
Level 1 after each checkpoint (storage; ingestion and FI-09; reprocessing), Level 2 (worker, retrieval, authorization, deletion, contract suites), Level 3 once (full backend, root, live Apex and Meridian on isolated state). Failures injected: upload interruption, source persistence failure, parse failure, embedding failure, worker crash, retry exhaustion, concurrent uploads, incomplete generations, reprocess failure, missing and corrupted source, deletion during ingestion and reprocessing, cross-tenant access, forged ids, cleanup retry, worker restart. All injections are simulated and labelled so.
