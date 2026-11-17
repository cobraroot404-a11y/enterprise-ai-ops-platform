# Phase 2: Apex vertical slice

A modular monolith (FastAPI) plus an outbox worker, PostgreSQL 16 + pgvector, and a minimal React UI. All customer data is fictional.

## Flow
1. Engineer reports a fault (`POST /api/v1/incidents/extract`). Rules extract the asset and category; **priority is decided by deterministic business rules**, never the model.
2. Hybrid retrieval (pgvector cosine + PostgreSQL FTS, reciprocal rank fusion) finds manual passages and related historical incidents, always tenant-filtered.
3. The answer is built only from non-suspicious passages. Every citation is verified: it must reference a retrieved passage and its quote must appear verbatim. Otherwise the answer is withheld; with no evidence the system says so.
4. The incident is validated by a Pydantic schema, then a ticket draft is created (one live ticket per incident).
5. A supervisor approves (`POST /approvals/{id}/decision`). The ticket row is locked (`FOR UPDATE`), the decision is stored in `approvals` (unique per ticket), the state moves to `APPROVED` and an outbox event is written in the same transaction.
6. The worker claims events with `FOR UPDATE SKIP LOCKED` and a lease, re-verifies the approval record, sends the ticket with the ticket's `Idempotency-Key`, and records `SUBMITTED` plus the external ID. Transient failures back off exponentially (`RETRY_PENDING`); permanent failures or exhausted retries end in `FAILED` (dead letter).

## Security controls in this slice
- JWT (HS256) with expiry; the **current database role** (not the token claim) decides permissions.
- PostgreSQL row-level security with FORCE on the approved tenant relations and [three documented exceptions](../security/identity-tables.md#owner-security-disposition-for-gate-c). The API and worker use non-superuser, non-`BYPASSRLS` roles. Tenant context is set with `set_config(..., is_local => true)` per transaction, so it cannot leak through the connection pool.
- The audit log is append-only (trigger blocks UPDATE/DELETE for every role).
- Separation of duties: authors cannot decide on their own tickets.
- Upload allow-list, filename sanitising, size limit, prompt-injection heuristics on retrieved text.
- Connector rows store only the name of an environment variable for secrets.

## AI backends
`LLM_BACKEND=deterministic` / `EMBEDDING_BACKEND=deterministic` are **test-only**: an extractive rule-based LLM and a hashed bag-of-words embedder. They verify behaviour, not AI quality. Ollama and Sentence Transformers are Phase 3 and need approved downloads. Responses and incident records include the backend name.

## Known limitations (Phase 2)
- No real-LLM or real-embedding validation yet (Phase 3).
- `tenants` and `users` are not under RLS (access is controlled in application code). `memberships` IS under RLS since migration 0002: reads are limited to the current tenant or the caller's own rows; writes require a tenant context plus a user context and can never touch the caller's own row (no self-assignment or self-escalation). Platform administration works by setting the administered tenant's context.
- No rate limiting, document deletion/reindex, or ingestion-job table yet.
- Minimal UI only (login, assistant, incidents/tickets, approvals, documents, audit); the remaining pages come in Phase 6.
- Hybrid search filters `base` by tenant before ranking, so the HNSW index is unused at this scale; fine for the demo, to be revisited for large corpora.
- The deterministic assistant often quotes section headings as "answers"; this is a property of the test-only extractive backend.
- The CI workflow is written but has not run (nothing pushed).
