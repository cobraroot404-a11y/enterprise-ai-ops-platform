# Document lifecycle: audited deletion with reliable cleanup (V41-12.05)

Requirement wording reviewed (original specification, document-handling list, line 497): the list ends "... Reprocessing, Deletion, Reindexing"; the project's acceptance statement for this item is "Documents can be deleted with audit". The approved policy below is compatible with that wording; no revised specification was invented.

## Policy (as implemented)
**Stage A, immediate logical deletion** (the `DELETE` request, one transaction): the server marks the document `deleted` (a client can set nothing), records who and when, clears `is_current` on its chunks, replaces the content hash of its versions and the name it held (so the same name and bytes can be uploaded again as a *new* document), queues one `document.cleanup` outbox event and writes one audit event, all or nothing. From that commit on the document is excluded from listings, `GET /documents/{id}` (404, indistinguishable from unknown or another tenant's), counts, `/ingestion/status`, hybrid, vector and full-text retrieval, entity and register lookups, citation verification and passage lookups.
**Stage B, content cleanup** (outbox worker, `document.cleanup`): in a session whose tenant context is the event's tenant, in one transaction: redact the quotes and summaries copied from the document's chunks into incident citations and related-incident summaries; delete the chunks (text and embeddings) and versions; verify that none remain; only then set `cleanup_state = completed` and write `document.cleanup_completed` (counts only). Any failure rolls the whole transaction back and the event is retried with backoff; when the retry budget is spent the document is marked `cleanup_failed` (audit event with the error class only) and a **repeated delete request re-queues it**. A completed cleanup is never claimed before the verification passes.

## Data and dependency map
| Artifact | On deletion (stage A) | On cleanup (stage B) | Notes |
|---|---|---|---|
| `documents` row | `lifecycle_status = deleted`, `deleted_at`, `deleted_by`, `cleanup_state = pending`, `source_key` freed | `cleanup_state = completed`, `cleanup_completed_at` | kept as a tombstone: id, tenant, filename, kind, actor, times, state |
| `document_versions` | `content_hash` replaced by a tombstone value | deleted | no content hash of deleted content remains |
| `document_chunks` (text, embedding, tsv) | `is_current = false` | deleted | the only place document text lives; there is no file store (no content files or storage references exist) |
| `incidents.citations`, `incidents.related_incidents` | masked at read time | quotes and summaries replaced by a fixed notice | filenames, record ids and the incident itself are kept |
| `tickets`, `approvals`, workflow history | untouched | untouched | never erased; ticket text already derived from the document is retained (limit) |
| `audit_events` | `document.deleted` (outcome, state, counts of versions and chunks; no text) | `document.cleanup_completed` or `document.cleanup_failed` or `document.cleanup_requeued` | the actor, tenant, correlation id and time are recorded |
| `outbox_events` | one `document.cleanup` event | `done`, or `dead` after retries | payload is empty |
| retrieval caches | none exist for document content or search results (the only caches in the code hold embedding-model and language-model client objects); every retrieval reads the tables | n/a | `is_current` and the lifecycle join are both enforced in SQL |

## Authorization and isolation
`documents:delete` is granted to tenant administrator and maintenance supervisor only (the server decides; engineers and auditors get 403). Another tenant's id is a 404 in every operation, including repeats, so deletion status cannot be probed. The worker role was given the minimum for cleanup (migration 0009): SELECT on `documents`; UPDATE of `cleanup_state` and `cleanup_completed_at` only; SELECT and DELETE on chunks and versions; UPDATE of `incidents.citations` and `related_incidents` only; and **tenant-scoped** row-level-security policies on the three document tables (`tenant_id = app_current_tenant()`), so without a tenant context it sees nothing and with one it sees only that tenant. The cleanup also refuses any document that is not deleted or not in the event's tenant (a forged or orphaned event is marked dead and deletes nothing).

## Failure and concurrency behaviour (all covered by tests)
Repeat delete: 200, same state, `already_deleted: true`, no second audit event or queue entry. Two simultaneous deletes serialise on the row lock: one audit event, one queue entry. An upload racing a deletion waits for the lock, then finds the document gone and creates a new document; it can never add chunks to or revive the deleted one. Uploading the same bytes after deletion is a new document, not a duplicate. A stage-A failure (for example in the audit write) rolls back everything. A cleanup failure after the deletes rolls the deletes back and retries; a worker that dies after claiming leaves a lease that expires and the event is reclaimed; exhausted retries record `failed` and never make the content visible again.

## Not covered (stated, not hidden)
No UI control (API only). No legal-retention or regulatory-erasure policy (none was approved). Text already copied into tickets, sent to external systems, kept in backups taken before deletion (including the demonstration backups) or copied by a person is not erased. Incident fields derived from the document by analysis (for example the recommended action) are retained as workflow history. Version history is removed with the document (there is no per-version deletion). No scheduled purge of tombstones. (Reprocessing and the ingestion-job entity were added in Batch 9: see [ingestion-jobs.md](ingestion-jobs.md); deletion cancels active jobs and cleanup removes every chunk generation.)

## Exposure register (Batch 9 audit; kept in step with `backend/tests/test_deletion_exposure_audit.py`)

What deletion physically **removes** once cleanup is `completed`: the retained original files (`document_sources`, every version, Batch 10), parsed text, chunks, embeddings and text-search vectors (all generations, including those retired by reprocessing), document versions, and any ingestion-job payload (the job payload is nulled at every terminal state and active jobs are cancelled by the deletion). Citation quotes and related-incident summaries copied from the document are redacted (Batch 8).

What is made **inaccessible** at once (stage A): listings, direct access (404), search in every mode, citation lookups, counts, reprocessing, and any queued or retrying job for the document (cancelled with `document_deleted`).

What **remains** (documented, not fixed in Batch 9):

| Id | Where | What remains | Why |
|---|---|---|---|
| EXP-01 | `audit_events` (`document.created`) | file name and the SHA-256 of the content | identifies the content, is not the content; the audit trail is append-only by design |
| EXP-02 | `ingestion_jobs` (`idempotency_key`, `filename`) | `ingest:<sha256>` and the file name | job history is kept as operational evidence; the payload (text) is removed |
| EXP-03 | `documents` tombstone | file name and kind, actor, times, states | identification of what was deleted |
| EXP-04 | PostgreSQL storage and backups | dead tuples (now including deleted original bytes) until VACUUM; backups taken earlier, which contain the original files | outside the application's control; deletion here is **application-level deletion**, not irreversible physical erasure |

A decision to also scrub EXP-01 to EXP-03 (for example hashing the file name) needs an owner policy decision and is not made here.

Evidence: `backend/tests/test_document_lifecycle.py`, `backend/tests/test_migration_0009_document_lifecycle.py`, the API contract and authorization suites, [Batch 8 report](../planning/batch8-report.md).

Batch 10 note: since original files are retained, EXP-04 now includes them: a backup made before a deletion holds the deleted document's original bytes until that backup is discarded. No retention or backup-expiry policy exists or was approved. Application-level deletion (the data is unreachable and removed from live tables) is distinguished from irreversible physical erasure (not provided).
