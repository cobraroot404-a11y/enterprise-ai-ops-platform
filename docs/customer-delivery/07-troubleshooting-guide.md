# 7. Troubleshooting guide

Symptoms below were seen during development or are produced by tested failure paths. Start with the correlation id: every response carries `X-Correlation-ID`, and server logs (JSON) carry the same id. Never paste secrets or customer content into tickets. The startup table in [../operations/local-runbook.md](../operations/local-runbook.md) section 9 covers environment problems.

## API and data
| Symptom | Likely cause | What to do |
|---|---|---|
| Empty lists or 404 for data you know exists | You are signed in to the other tenant, or the session has no tenant context (row-level security hides everything without one) | Sign in to the right tenant; never "fix" this by bypassing RLS |
| 401 `invalid_token` / `token_expired` | Expired or tampered token | Sign in again |
| 403 `insufficient_role` / `separation_of_duties` | Role lacks the permission, or you are acting on your own incident or ticket | Ask a different authorised person |
| 503 `embedding_unavailable` on upload or search | The embedding model is unavailable (Ollama/model not loaded) | Start the model service; an upload is kept as a durable job and finishes by itself, see below |
| 409 `embedding_model_mismatch` | Tenant was indexed with another embedding backend | Re-index with `scripts/reindex_embeddings.py` |
| 429 `server_busy` / `webhook_rate_limited` | Concurrency or per-endpoint rate limit reached (per process) | Retry after `Retry-After` |
| Errors about missing tables or columns | The database is behind the code (the shared `eaop` database is at `0006`; code head is `0013`) | Migrate with owner approval; use a disposable database for tests |

## Documents, jobs and connectors
| Symptom | Likely cause | What to do |
|---|---|---|
| Upload returned 503 and the document is not listed | Transient failure; the upload is a durable job (`GET /ingestion/jobs`, status `RETRY_PENDING`) | Wait for the worker (backoff) or repeat the upload (it resumes the same job); an exhausted job can be re-queued by a supervisor (`POST /ingestion/jobs/{id}/retry`) |
| Job `FAILED` with `source_missing` / `source_corrupted` | The retained original is gone or failed its checksum | Upload the document again; investigate storage if `source_corrupted` |
| Reprocess returns 409 `source_not_retained` | The document was uploaded before original files were retained | Upload the file again |
| Sync request returns 409 `invalid_connector_config` / `connector_destination_not_allowed` | The stored connector configuration is invalid or its origin is not approved for this tenant | Fix the configuration; origins are approved only on the server (`EGRESS_ALLOWLIST` / `EGRESS_DEV_MOCKS`) |
| Sync job `FAILED` with `credentials_missing` | The environment variable named by `secret_ref` is not set for the worker | Set it where the worker runs |
| Sync job `FAILED` with `source_unauthorized` / `pagination_loop` / `invalid_cursor` / `source_schema_invalid` | The upstream rejected the key, or returned an unusable response | Check the upstream; these are permanent and not retried |
| Sync reports `tombstoned_changed` or `skipped_deleted` | The customer deleted that record's document; deletion is permanent against upstream changes | Intended. A restore action does not exist; ask the owner |
| Health shows a connector `degraded` after `?probe=true` | The live probe class is in `live_probe.status` (authentication, rate_limited, schema, upstream_error, connectivity, denied) | Act on the class; nothing is ingested by a probe |

## Webhooks
| Response | Meaning | What to do |
|---|---|---|
| 401 `invalid_signature` | Unknown or disabled endpoint, missing header, wrong secret or tampered content (deliberately identical) | Check endpoint id, secret, and that the signature covers `timestamp.delivery_id.raw_body` byte for byte |
| 401 `timestamp_out_of_window` | Signature valid but the clock differs by more than 300 s | Synchronise the sender's clock |
| 409 `webhook_replayed` | That delivery id was already received | Use a new delivery id for each delivery and for a corrected payload |
| 422 `invalid_payload` | Valid signature, but the body can never be processed (not JSON, wrong shape, too many records) | Fix the payload and send with a new delivery id |
| 202 but nothing appears | 202 means queued, not processed | Follow `job_id` in `GET /ingestion/jobs`; the worker must be running |
| 503 `webhook_not_configured` | The signing-secret variable is missing on the server | Set it; the server never accepts without it |

## Start-up and tests
| Symptom | Cause | Action |
|---|---|---|
| "API was not ready after 90s" | REL-01: an unexplained intermittent stall seen once in ten starts | Read the diagnostics in the message and the logs; rerun; report if it recurs |
| Port in use | An earlier stack | `python scripts/demo.py down` for a recorded run, otherwise stop it yourself |
| Tests rewrite `evaluation/` files | Some tests refresh evidence | `git checkout -- evaluation/customer-acceptance evaluation/failure-reports evaluation/observability` unless you want the refresh |
| A test fails only when run with others | Shared test database state (jobs left active) | The `ticketing` fixture clears queues; run the failing file alone and report |
