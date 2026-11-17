# Database entities (V41-17.04): decision record

The specification (Part 17) lists 17 "Database entities". This record maps each to the schema, states where an existing equivalent satisfies the entity, and records the one table that was added. It follows the rule "do not create duplicate sources of truth merely to satisfy a table-name checklist".

| Entity | Where it lives | Note |
|---|---|---|
| Tenants | `tenants` | not under RLS (identity table); access controlled in code |
| Users | `users` | not under RLS |
| Roles | `memberships.role` plus the permission matrix in `app/core/rbac.py` | **Equivalent, no `roles` table.** There are five fixed roles; the matrix is code under test (`test_api_namespace_security.py` pins every route to a permission and checks the role matrix). A `roles` table would be a second, editable source of authorisation truth and would be a change of authorisation policy, which needs an owner decision, not a checklist. |
| Memberships | `memberships` (RLS) | the user, tenant, role link |
| Connectors | `connectors` (RLS), plus `webhook_endpoints` for inbound endpoints | |
| Documents | `documents` (RLS) | with lifecycle and deletion state |
| Document versions | `document_versions` (RLS) | with the retained original (`source_id`) and active generation |
| Document chunks | `document_chunks` (RLS) | with the generation |
| Embeddings | `document_chunks.embedding` (pgvector) and `embedding_profiles` | **Equivalent**: an embedding belongs to exactly one chunk, so a separate table would only duplicate the key |
| Ingestion jobs | `ingestion_jobs` (RLS), migration 0010; `document_sources`, `connector_sync_records`, `webhook_deliveries` support it | |
| Incidents | `incidents` (RLS) | with measurements and review state |
| Tickets | `tickets` (RLS) | |
| Approvals | `approvals` (RLS) | |
| Workflow executions | `tickets` (state machine) with `approvals` and `outbox_events` (attempts, status, last error, lease) and `audit_events` (every transition); `ingestion_jobs` for ingestion workflows | **Equivalent, no `workflow_executions` table.** Each workflow execution already has a durable row with its state, attempts and history; a parallel table would duplicate it. |
| Outbox events | `outbox_events` | |
| Audit events | `audit_events` | append-only |
| Evaluation runs | **`evaluation_runs` (added, migration 0014)** | Evaluation runs had no database representation at all (files only), so the equivalent test failed. The table is an **index**, not a second source of truth: it registers each run manifest under `evaluation/` (run id, suite, command, dataset, timestamps, backends, git commit) with the manifest's SHA-256. The manifests and reports remain the evidence and the only source of measurements. A manifest that changes after registration is reported, never overwritten. The table holds no tenant data (so it is not under RLS, like `tenants`); the application and worker roles can only read it, and only the database owner (`scripts/index_evaluation_runs.py`) writes it. |

## Assessment
13 entities are tables of their own; roles, embeddings and workflow executions are satisfied by documented equivalents that carry the same facts; evaluation runs is a new registry table. This is the implementing engineer's assessment recorded for owner review: if the owner reads "Database entities" as one table per name, `roles` and `workflow_executions` remain to be added (and `roles` would need an authorisation-policy decision).

Evidence: `backend/tests/test_evaluation_registry.py`, the migration tests, `docs/architecture/system-architecture.md`.
