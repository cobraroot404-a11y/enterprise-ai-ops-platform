# Accelerated gap closure, Batch 2 report: tenant-leading indexes (V41-17.03-IDX)

Date: 2026-11-12 (EST). Starting HEAD `ebaedf4c1dbca7b67901b242f011fd754ac94bdd` (branch `feat/apex-vertical-slice`, clean; original specification SHA-256 `b1c573e2…760da` verified). No push, merge, publication, release or deployment occurred. V41-14.02 stays PARTIAL and untouched; no document deletion, rate limiting, Phase 9, numeric-safety, retrieval, citation or prompt work was done.

## 1. Existing-index audit (before 0008) and migration chain
Alembic chain `0001`..`0007` is linear with a single head; `0008` is the correct next identifier (verified). Existing indexes on the three tables:
| Table | Indexes before | Tenant-leading? |
|---|---|---|
| `incidents` | primary key only | no |
| `approvals` | primary key, unique `(ticket_id)` | no |
| `outbox_events` | primary key, partial unique `(topic, aggregate_id) WHERE status IN ('pending','processing')` | no |
The other nine tenant-scoped tables already had a tenant-leading index. Constraints and RLS (`tenant_isolation` for the app role, `worker_access` for the worker) were inspected and are unchanged by this batch.

## 2. Query patterns and final index definitions
| Table | Tenant-scoped queries in the code | Index (migration `0008_tenant_leading_indexes`) |
|---|---|---|
| `incidents` | list endpoint and metrics: `WHERE tenant_id = ? [filters] ORDER BY created_at DESC`, tenant counts | `incidents_tenant_created_idx ON incidents (tenant_id, created_at DESC)` |
| `approvals` | decided-approvals list: `WHERE tenant_id = ? ORDER BY decided_at DESC` (lookups by `ticket_id` use the existing unique index) | `approvals_tenant_decided_idx ON approvals (tenant_id, decided_at DESC)` |
| `outbox_events` | workflow history and metrics: `WHERE tenant_id = ? [status or aggregate_id] ORDER BY id DESC` | `outbox_events_tenant_id_idx ON outbox_events (tenant_id, id DESC)` |
Rationale: one index per table, tenant first (every query is tenant-scoped and, under RLS, filtered by tenant), second column the actual sort key so the newest-first listing and `LIMIT` need no sort. Deliberately not added: extra `(tenant_id, status)`, `(tenant_id, asset_id)` or `(tenant_id, aggregate_id)` indexes (low selectivity or speculative; the first index already narrows by tenant), any index for the worker's claim query (it is cross-tenant: `topic`, `status`, `available_at` ordered by `id`; not tenant-leading and outside this batch), and any change to foreign keys, constraints, grants or RLS.
**Locking (documented, not a production claim):** plain `CREATE INDEX` takes a SHARE lock that blocks writes while building. That is acceptable for the current local development database (small tables; builds in milliseconds). A large live deployment would create the indexes with `CREATE INDEX CONCURRENTLY` outside a transaction (Alembic `autocommit_block`) in a separate reviewed step; no zero-downtime claim is made.

## 3. Migration evidence (`backend/tests/test_migration_0008_indexes.py`, 7 tests, disposable database)
Upgrade 0007 to 0008 on seeded data (two tenants with incident, ticket, approval, outbox row): exactly the three indexes appear; definitions are btree, tenant-leading, with the intended second column in DESC order, non-partial, non-unique; no duplicate or redundant definition exists (index counts per table: incidents 2, approvals 3, outbox_events 3). Data (row counts and content hashes of six tables), constraints, RLS flags and policies, grants and all pre-existing indexes are byte-for-byte equal before and after upgrade, after downgrade, and after reapply. Downgrade to 0007 removes only the three indexes and `alembic_version` returns to 0007; reapply and a second `upgrade head` are safe; a manual duplicate create is rejected. As the application role with RLS enforced, each tenant sees only its own rows in all three tables through the new indexes. The shared test database was only read; the destructive steps ran in a scratch database that was dropped afterwards. Note: migrations 0001 to 0007 have no downgrade (they raise by design), so downgrade is verified for 0008 only.

## 4. Query-plan evidence (`evaluation/api-quality/index-query-plans.json`; `python scripts/index_query_plans.py`)
Disposable PostgreSQL 16.15 database, synthetic data: 200,040 incidents, 50,040 approvals, 100,050 outbox events, 11 tenants (10 large with 20,000 incidents each, interleaved; one small tenant whose 40 incidents and 50 outbox events are the oldest rows). `VACUUM ANALYZE` before and after; median of 7 warm runs; `EXPLAIN (ANALYZE, BUFFERS)`; shared_buffers 128MB, work_mem 4MB. Owner role with an explicit tenant predicate (RLS adds a predicate and is covered by the migration tests, not by these timings).
| Query | Large tenant before to after (ms) | Small tenant before to after (ms) | Plan after (large / small) |
|---|---|---|---|
| Q1 incidents newest 50 | 13.9 to 0.04 (4520 to 15 buffer hits) | 10.9 to 0.04 (4520 to 4) | index scan on the new index / bitmap on the new index |
| Q2 incidents newest 50 needing review | 12.5 to 0.14 | 12.1 to 0.03 | new index (filter on review_status) |
| Q3 incidents tenant count | 10.4 to 2.2 | 9.6 to 0.02 | index-only scan on the new index |
| Q4 approvals newest 50 | 2.7 to 0.03 | 2.6 to 0.02 | new index |
| Q5 outbox newest 50 | 0.076 to 0.059 (no change; planner keeps the primary key) | 5.5 to 0.02 | primary key (large) / **new index (small)** |
| Q6 outbox newest 50 dead letters | 5.3 to 2.7 | 5.6 to 0.02 | bitmap on the new index |
Honest reading: the largest gains are for queries on a tenant that is small relative to its neighbours or has a selective filter; for the unfiltered newest-50 outbox query on an evenly interleaved large tenant PostgreSQL correctly keeps the primary key and the new index changes nothing (0.076 vs 0.059 ms). Index sizes: incidents 7960 kB, approvals 2008 kB, outbox 3992 kB (the cost: extra write and storage overhead, not measured here). The numbers are for this laptop and synthetic data, not production claims; planner limitations: statistics-driven plan choice, warm cache, single connection, no concurrent writers.

## 5. API-quality results (regenerated from the executed suite: `evaluation/api-quality/api-quality-evidence.json`)
The strict expected failure for the index defect flipped to XPASS when the migration was applied, proving the condition resolved; it was then converted into a normal passing test plus an assertion of the three index definitions (not removed or weakened). P9 indexes: **verified**. The review you asked for on OpenAPI response documentation found a material gap: **0 of 45 operations declare a typed success response schema** (handlers return dictionaries). A new strict expected failure records it under P1 (V41-17.03-TYPED-RESPONSES), so the evidence now reports P1 as a known gap and the other eight properties as verified.

## 6. Regression results
Backend 508 passed, 18 skipped, 1 expected failure (the typed-responses gap); root suites 73 passed plus the generated-document consistency tests that failed only until the documents were regenerated (they referenced this report); real-AI 12 passed; real-stack customer acceptance 21 passed; secret scan 0 findings (808 files); lint 8 findings, all pre-existing in frozen Phase 8 tooling and sample data (none added). Frontend not rerun: no frontend file changed. Outbox reliability, RLS, tenant-isolation, authorization and numeric trust-policy suites pass unchanged.

## 7. Requirement status recommendation and traceability
**V41-17.03: keep PARTIAL.** Eight of nine properties are verified, including the previously open indexes. It is not eligible for VERIFIED because the typed-contract property is only half met: request bodies are typed, responses are untyped in OpenAPI. Options for the owner: accept that reading of "typed contracts" as satisfied by request typing plus test-pinned responses, or approve a small non-breaking batch adding response models for the main resources. Catalogue R17.2 (migrations, transactions, constraints, indexes) is back to verified; R17.1 is partially verified for the same typed-response gap. All 238 original requirements, the 13 newly discovered ones and the five catalogue-only additions are retained and separately identified.

## 8. Files changed
New: `backend/migrations/versions/0008_tenant_leading_indexes.py`, `backend/tests/test_migration_0008_indexes.py`, `scripts/index_query_plans.py`, `evaluation/api-quality/index-query-plans.json`, `docs/planning/batch2-report.md`. Changed: `backend/tests/test_api_contract.py`, `docs/api/api-quality.md`, `scripts/v41_requirements_data.py`, `scripts/traceability_data.py`, regenerated `docs/specification/*`, `docs/traceability/*`, `evaluation/api-quality/api-quality-evidence.json`. No existing migration, data, constraint, RLS policy or grant was modified.

## 9. Remaining limitations
Typed responses (above); the worker's cross-tenant outbox claim query has no dedicated index (not tenant-scoped, outside this batch, not measured); plain `CREATE INDEX` locking is acceptable only for local development; index write overhead not measured; migrations 0001 to 0007 cannot be downgraded; plan evidence is synthetic and single-machine; same-author evidence.

## 10. Recommended next independent batch
Batch 3: **response models for the main resources** (incidents, tickets, documents, approvals, workflows, audit, list envelope) with `response_model` and a refreshed OpenAPI snapshot. This is non-breaking (same JSON), has no migration and no safety-component dependency, closes V41-17.03-TYPED-RESPONSES and lets V41-17.03 move to verified. Alternatively, the local-demo documentation set (README, architecture diagrams, runbook), or the decisions that unlock document deletion (V41-12.05).

## 11. Reproduce
```
cd backend
python -m pytest tests/test_migration_0008_indexes.py tests/test_api_contract.py
cd .. && python scripts/api_quality_report.py              # regenerates evaluation/api-quality/api-quality-evidence.json
python scripts/index_query_plans.py                       # regenerates evaluation/api-quality/index-query-plans.json (disposable DB, about 1 minute)
python -m pytest backend/tests -q && python -m pytest tests -q
```
