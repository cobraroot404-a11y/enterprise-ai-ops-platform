# Rate limiting and resource limits: design, coverage and limitations

## What is shared across processes (PostgreSQL, migration 0015)
Token buckets and fixed-window counters live in the `rate_limit_state` table, reached only through `SECURITY DEFINER` functions (`rate_limit_take`, `rate_limit_pause`, `rate_limit_window_*`, `rate_limit_sweep`); no application role can read or write the table. Each call locks the one bucket row and refills from the **database clock**, so any number of API and worker processes draw from one bucket, clock skew between processes is irrelevant, and concurrent callers cannot over-spend (proved with four separate OS processes and with many threads: `backend/tests/test_shared_rate_limits.py`). Keys carry the tenant id, so one tenant's limits and Retry-After pauses never affect another's.

| Surface | Limit | Scope |
|---|---|---|
| REST and CSV connectors | the connector's configured rate and burst, honouring upstream `Retry-After` | per tenant and connector, all processes |
| Signed webhook receiver | per-endpoint bucket plus a shared pre-lookup bucket | per endpoint, all processes |
| Every outbound HTTP client (ticketing, inventory, CRM, fleet, service desk, connectors) | 50 requests/s, burst 100, bounded wait 2 s, then a transient `ConnectorError` | per tenant and upstream host, all processes |
| AI question, incident extraction, document upload | `API_RATE_PER_SECOND` (default 20) and `API_RATE_BURST` (default 100) per operation | per tenant, all processes; HTTP 429 `rate_limited` with `Retry-After` |
| Sign-in failures | 10 failures per account per 60 s (fixed window), then 429 `too_many_attempts` | per account, all processes |

Waits are bounded (30 s maximum), never busy loops, and a stop event ends a wait immediately.

## When the database is unavailable
Every shared limiter falls back to a **process-local bucket** (limits still apply, per process, never unlimited) and counts the event in `ratelimit_store_unavailable_total`. After a failure the shared store is not retried for 5 seconds, so an outage does not slow every call; sharing resumes afterwards. The sign-in throttle always also keeps a process-local counter, so it can only become stricter during an outage, never weaker. While the database is down the API cannot authenticate users anyway.

## Concurrency limits (shared leases, migrations 0016 and 0017)
The in-flight caps for AI inference and document ingestion (`MAX_CONCURRENT_LLM`, `MAX_CONCURRENT_INGEST`, 429 `server_busy` with `Retry-After`) are shared across API processes: `concurrency_acquire` takes an advisory lock on the pool key, discards that key's expired leases, and inserts a lease only while fewer than the limit are live, so two processes can never both take the last slot (tested with four OS processes and 12 threads).
- **Fairness between tenants:** a tenant may hold at most all-but-one of a pool's slots (its own share key is taken first, then the pool), so one organisation's long requests cannot occupy the whole pool; another tenant still gets a slot. With a one-slot pool there is no separate share.
- **Bounded waiting:** a caller waits at most `BUSY_WAIT_SECONDS` (default 2) for its share and the pool together, then gets 429.
- **Crash recovery:** a holder that dies frees its slot when its lease expires (330 s, longer than the model timeout). A rejected or failing request releases everything it took, including its tenant share.
- **Housekeeping:** the worker runs `maintenance` every five minutes: `rate_limit_sweep` removes buckets and sign-in counters idle for an hour (so attempted addresses cannot accumulate without bound) and `concurrency_sweep` (0017) removes expired leases of every key. Neither removes a live lease or a paused bucket.
- **Metrics:** `concurrency_rejected_total` (by pool and reason: `tenant_share` or `pool_full`) and `concurrency_fallback_total`; rejections are not written to the audit log (they change nothing and would let a flood fill it).
- **Database unavailable:** the caps fall back to **per-process** enforcement (a semaphore for the pool and an in-memory count for the tenant share). What is lost during the outage: the cross-process guarantee (N API processes then allow up to N times the cap in total) and crash-expiry; what remains: each process still enforces both caps, and nothing becomes unlimited. The fallback is counted and logged. (While the database is down the API cannot authenticate requests, so in practice these endpoints are unreachable anyway.)
Tests: `backend/tests/test_shared_concurrency.py`, `test_concurrency_fairness.py`.

## What is still per process
- Request-size limits (JSON 1 MiB, uploads `MAX_UPLOAD_BYTES`) are properties of each request and need no sharing.

## Remaining limitations
- All state is in one PostgreSQL database: a very hot bucket (hundreds of takes per second) serialises on its row lock; the 2 s `lock_timeout` turns pathological contention into the local fallback rather than a hang.
- The sign-in window is a fixed window (a burst at a window boundary can allow up to twice the nominal number), unlike the previous sliding window.
- No limit applies to unauthenticated traffic other than the webhook receiver and sign-in; there is no IP-keyed limit and no per-tenant quota product. A public deployment still needs edge or gateway controls.
- A lease is held for the whole request, so a very long request (up to the model timeout) keeps its slot; a crashed process blocks its slot for up to 330 s.
- Tested locally on one machine with separate processes, not across machines.
