# Full Compose backup and restore

The owner-session drill `261116030432-aa2fb41e` ran against `5972d1ea08a7fb87916a98ad0e0af044e84ab8c2` on November 15, 2026, Eastern time. This is same-machine evidence for P23L841. The source and restore projects used the suffixes `-source` and `-restore` on `p23l841-261116030432-aa2fb41e`, with separate `eaop_demo_*` databases, project volumes, and networks. The database service had no published port.

## Procedure

1. Use `docker-compose.app.yml` with a unique project name, fresh disposable database, per-run credentials, and available loopback API and UI ports. Use the verified local images with build and pulling disabled. Keep `RUN_REAL_AI` unset. Confirm successful migration and Apex seed, database and API health, worker startup, five mock endpoints, and the UI and its API proxy. Onboard Meridian using the existing inside-container command from `scripts/container_smoke.py`.
2. Capture API state, then stop the source service writers and record the database baseline. Run `pg_dump -Fc` inside the source project's `db` service as its database owner. Record size and SHA-256 and check the archive rendered by `pg_restore -f -` for per-run secret values.
3. Start the separate restore project's `db` service. Use the existing migrations against a separate disposable bootstrap database in that cluster to create the cluster-wide app and worker roles. Confirm ownership and zero public tables in the actual restore database. Recheck the checksum and run `pg_restore --exit-on-error` into that database using the restore project's `db` service. Compare the database baseline before starting the restored API and worker. Start and check the application services without running the seed or migration against the restored database.
4. Compare the two API snapshots. Remove both task-owned projects with their volumes and networks. Remove temporary environment files and the dump, then compare Docker resource inventories.

## Observed results

Both deployments passed health checks. The dump was 154,664 bytes. Its SHA-256 was `e91a6d5ae4ad1fae0edffc4a236700d0460cd5c230fb064a117bee3e6904b888`. Secret exclusion passed. Restore completed without repair, and all twelve source-to-restore comparisons matched.

| Check | Source | Restored |
|---|---|---|
| Database | PostgreSQL 16.15, vector 0.8.7, pgcrypto 1.3, Alembic 0017 | Same |
| Full database row counts | 24 public tables, 130 total rows | Every table matched |
| Apex | 5 documents, 16 chunks, 4 memberships, 2 connectors, 5 audit events | Same |
| Meridian | 5 documents, 15 chunks, 4 memberships, 3 connectors, 30 audit events | Same |
| Other tenant counts | Zero incidents, tickets, approvals and outbox events in both tenants | Same |
| Tenant API | Each tenant saw 5 documents, zero incidents and tickets, and its own audit count. Both passed 8 of 8 onboarding checks. Registry was empty for both tenants and its response hash matched. | Same |
| Cross-tenant checks | Five foreign-document requests per tenant returned 404. Restricted app and worker logins each saw five own documents and zero foreign or unscoped documents. The runbook app-role check also passed on incidents, tickets, and audit events. | Same |
| RLS and privileges | 16 relations had enabled and forced RLS, with 39 policies. Neither role had superuser, BYPASSRLS, role creation, database creation, replication or inherited memberships. Both could read the registry and had no insert, update or delete grant on it. | Same policies, relation flags, role properties and grants |

Both projects were removed. Docker inventories matched before and after, the protected shared database was outside both projects, and temporary credential files and the dump were removed. The report and build evidence contain no exposed credentials.

The backend digest changed from `sha256:60b7a6dca35448a7fbe635cdf01eb36ef5511100c3f46602036bc2b6d0e8d734` to `sha256:10f6d1ce2eb627dd3c3dfa9378f18e83b2bbca5aebfbdb3676a3444cef0ee96c`. The rebuilt image passed runtime lock checks on Python 3.12.16, `pip check`, and verification of the registry route files against HEAD. The successful build used a local OCI base and a cached dependency layer. The build log records no downloads, and the drill pulled no images.

Owner-session originals are retained outside the repository. Their SHA-256 hashes are:

| File | SHA-256 |
|---|---|
| `p23l841-261116030432-aa2fb41e.json` | `8f4b9c50269def6e3f0d21250dfe2aa298e8c9865e9646e5836fdd4b56c4863b` |
| `p23l841-backend-network-rebuild.json` | `12db9819d7baaf5d84946a4f0bd78aab7044cb0df58814a2bff826ac72794442` |
| `p23l841-backend-network-rebuild.log` | `a7d95fbfaaa34e9fd565116d70167738ed7cdad0efacd84340d34d136105e981` |
