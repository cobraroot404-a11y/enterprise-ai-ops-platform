# 9. Architecture tradeoff record

Decisions that shaped the system, with the alternative and the cost accepted. The broader monolith-versus-services and cloud comparison is [../architecture/deployment-tradeoffs.md](../architecture/deployment-tradeoffs.md).

| Decision | Chosen | Alternative considered | Why, and the cost accepted |
|---|---|---|---|
| Service shape | Modular monolith plus a worker | Microservices | One transaction boundary for approval + outbox + audit; simple local run. Cost: scaling units are coupled |
| Tenant isolation | PostgreSQL forced row-level security with a per-session tenant, plus application filters | Application filters only; database per tenant | Isolation holds even if application code forgets a filter, tested with filters bypassed. Cost: every session must set the tenant; one narrow pre-authentication lookup function for webhooks |
| Work queue | The database (outbox table, `ingestion_jobs`) | Redis/RabbitMQ | No new service on a workstation; transactional enqueue. Cost: polling, per-process concurrency; not a high-throughput queue |
| Original files | Stored in PostgreSQL (`document_sources`, checksum-verified) | Filesystem or object store | Same transaction as the job and document, same RLS and backups, no orphan files. Cost: database size and backup size grow; erasure from old backups is impossible |
| Reprocessing | Re-parse the retained original into a new generation, activate atomically | In-place update; re-embed chunks only | Failed attempts never damage usable content. Cost: old generations use storage until deletion |
| Deletion vs sync | Customer deletion is a permanent tombstone against upstream changes | Re-import changed records | A customer's deletion is an explicit decision. Cost: no restore action exists |
| Numeric evidence | Numbers from free text are unverified candidates; priority comes from server rules using signed fixtures or human-verified readings | Let the model's numbers drive priority | Three live acceptance runs showed model-extracted numbers cannot be trusted for safety decisions. Cost: more human review (a large share of incidents) |
| AI | Local models (Ollama, MiniLM), deterministic backends for tests only | Hosted APIs | No cost, no data leaves the machine. Cost: CPU-only latency and measured quality limits |
| Rate limiting | Process-local token buckets and concurrency limits | Redis/gateway | Zero extra infrastructure. Cost: not distributed (V41-16.04 stays partial) |
| Webhook authentication | HMAC over timestamp, delivery id and raw body; replay ledger in the database | Bearer tokens; mutual TLS | Standard sender pattern, replay protection that survives restarts. Cost: shared secrets must be rotated and held outside the database |
