# 8. Operational handover

For an engineer taking over this local system. Nothing here describes a production service.

## What runs
PostgreSQL (container), API (:8000), worker (outbox submissions, ingestion jobs and sync/webhook processing, document cleanup), mock external systems (:8101-:8106), UI (:5173), optionally Ollama. Start and stop: [../operations/local-runbook.md](../operations/local-runbook.md) (`scripts/dev.py`, `scripts/demo.py`).

## Daily and weekly checks (local)
Health: `GET /api/v1/health`; connectors: `GET /api/v1/connectors/health` (add `?probe=true` for one live request per REST/CSV source); workload: `GET /api/v1/ingestion/jobs?status=RETRY_PENDING` and `FAILED`; tickets stuck in `RETRY_PENDING` or `FAILED` on the workflow page; observability summary `GET /api/v1/observability/summary` (process-scoped counters, reset on restart). Logs are JSON with correlation ids and contain no secrets or customer content ([../operations/observability.md](../operations/observability.md)).

## Routine operations
* **Secrets:** held in `.env` (git-ignored) and in the worker/API environment; connectors and webhook endpoints store only variable names. Rotate a webhook secret by naming a new variable (`PATCH /webhook-endpoints/{id}`), switching senders, then dropping the previous reference.
* **Backups:** `python scripts/demo.py backup` and `restore-check` for disposable databases (proves checksum, row counts, RLS flags and tenant isolation after restore); for the shared database use `pg_dump` and test the restore in a new database. Backups contain customer content and retained originals; deletion in the application does **not** erase copies in older backups.
* **Deletion:** `DELETE /documents/{id}` (administrator or supervisor) removes access at once and cleans content in the worker; verify `cleanup_state` becomes `completed`.
* **Reprocessing:** `POST /documents/{id}/reprocess` re-parses the retained original; documents without one return 409.
* **Migrations:** apply to disposable databases first; migrating the shared `eaop` database needs the owner's decision and a backup.

## Known limits (do not discover these in production)
Process-local rate limits and metrics; connector and webhook screens are basic (Data Sources and Integration Health pages); no scheduler for synchronisation; no ledger or job-history purge; originals kept for exhausted jobs never expire; one intermittent start-up stall (REL-01) unexplained; AI-quality targets partly unmet; container images exist only for the local deterministic-AI stack and no cloud deployment exists; single-author evidence.

## Where the truth is
Requirements and evidence: [../planning/progress-tracker.md](../planning/progress-tracker.md), [../specification/v4.1-gap-register.md](../specification/v4.1-gap-register.md), the batch reports. Security design: [../security](../security/). Reliability: [../reliability/fault-injection-results.md](../reliability/fault-injection-results.md).
