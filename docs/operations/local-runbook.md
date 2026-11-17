# Local operations runbook

Use this runbook for startup, validation and teardown on one local Windows machine. The manual startup table records historical observations from 2026-11-13. The [Batch 7 report](../planning/batch7-report.md) documents existing-environment reproduction, and the [final validation report](../planning/final-validation-report.md) records the later same-machine clean checkout and isolated PostgreSQL regression. Independent Gate C reproduction is pending.

Never put real secrets in this file or in the repository. `.env` is git-ignored; values in `.env.example` are placeholders.

## 1. Required tools
Docker (Compose v2), Python 3.10+, Node 20+ with npm, git. Optional: Ollama (for real local AI; `qwen2.5:1.5b` already pulled) and a Sentence Transformers MiniLM cache (`data/models`, git-ignored). Python dependencies: `backend/requirements-dev.txt` (lock file `backend/requirements.lock.txt`); AI extras: `backend/requirements-ai.txt`. Inspected, not re-installed.

## 2. Environment configuration
`cp .env.example .env`, then replace every placeholder. Variable names (from `.env.example`): `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT`, `MIGRATION_DATABASE_URL`, `APP_DB_PASSWORD`, `WORKER_DB_PASSWORD`, `DB_HOST`, `JWT_SECRET`, `JWT_EXPIRE_MINUTES`, `LLM_BACKEND`, `EMBEDDING_BACKEND`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `MOCK_TICKETING_API_KEY`, `MOCK_SERVICEDESK_API_KEY`, `MERIDIAN_SERVICEDESK_KEY` (must equal `MOCK_SERVICEDESK_API_KEY`), `SEED_PASSWORD`, `EAOP_ENV`, `EGRESS_ALLOWLIST`, `EGRESS_DEV_MOCKS`. `scripts/dev.py` loads `.env` itself (an already-set environment variable wins).

Two backend modes (see [configurations](configurations.md)): `LLM_BACKEND=deterministic` / `EMBEDDING_BACKEND=deterministic` are test-only and labelled so in `/api/v1/health`; `ollama` / `sentence_transformers` are real local AI. A tenant indexed with one embedding backend is refused by the other until `python scripts/reindex_embeddings.py --tenant <slug> --backend <backend>`.

**Pitfall (hit and reproduced):** do not `source .env` in a POSIX shell. The `EGRESS_*` values are JSON with double quotes that the shell strips; the server then cannot parse them and connector creation returns HTTP 500 `internal_error`. Let `scripts/dev.py` read `.env`, and only export overrides.

## 0. One-command demonstration (Batch 6)
`scripts/demo.py` wraps the existing tools (the `scripts/dev.py` process table, migrations, the Apex seed, the Meridian onboarding tool, the Vite dev server, Playwright, `scripts/ollama_ctl.py`). It is the recommended way to demonstrate the platform. It never touches the shared `eaop` database: every run creates a **disposable** database named `eaop_demo_<timestamp>_<id>`, migrates it to head (`0017`), seeds Apex, starts the services, onboards Meridian and (on `down` or at the end of `smoke`) drops only that database.

| Command (from the repository root, with the project's Python) | What it does |
|---|---|
| `.venv\Scripts\python scripts\demo.py preflight [--ai real]` | checks the Python environment, `.env` (required names present, `EGRESS_*` valid JSON and authorising the mock origins, mock keys consistent, not production), Node, frontend dependencies, Playwright, 2 GB of disk, free ports 8000, 8101-8105, 5173, a reachable local PostgreSQL with pgvector; with `--ai real` also Ollama, the model named by `OLLAMA_MODEL` (default `qwen2.5:1.5b`) and the MiniLM cache. Changes nothing |
| `.venv\Scripts\python scripts\demo.py up [--ai real]` | interactive mode: preflight, create database, migrate, seed Apex, start ticketing, inventory, fleet, CRM, service desk, worker and API, wait for each to be ready, onboard Meridian, start the UI, print the URLs, and **return** with the services running detached. Records everything it created in `.demo/state.json` |
| `.venv\Scripts\python scripts\demo.py status` | what the last `up` created and whether it is running and healthy |
| `.venv\Scripts\python scripts\demo.py down` | the explicit shutdown: stops only the recorded processes (it re-checks each process's creation time, so a recycled process id is left alone), stops Ollama only if that run started it, and drops only the database that run created (the name must start with `eaop_demo_` and differ from the configured shared database). Safe to repeat |
| `.venv\Scripts\python scripts\demo.py smoke [--no-browser]` | automated mode: the same startup, then the Apex and Meridian workflows through the API (sign-in for four roles, structured observation, refusal of engineers, auditors, other tenants and the incident's creator, verification, server-driven priority, repeated decision refused, ticket draft, approval, worker submission, audit chain), a bounded Playwright browser smoke (Edge, both tenants, keyboard reachability of the review controls), then teardown of everything it created. Writes `evaluation/demo-runs/<run id>/report.md` and `report.json` (secrets redacted), screenshots and Playwright results; logs stay in `.demo/<run id>/logs` (git-ignored) |
| `.venv\Scripts\python scripts\demo.py backup [--database eaop_demo_<id>]` | exports ONE disposable demo database with `pg_dump` run inside the project's PostgreSQL container to `backups\demo\<db>-<UTC time>.dump` plus a `.manifest.json` (revision, tenants, row counts per table and per tenant, row-level-security flags, checksum). `backups/` is git-ignored and outside `.demo/`, so teardown never removes it. Refuses `eaop` and any name outside `eaop_demo_*` |
| `.venv\Scripts\python scripts\demo.py restore-check backups\demo\<file>.dump [--keep]` | restores the dump into a NEW database `eaop_demo_restore_<time>_<id>`, proves checksum, revision, tenants, every row count, per-tenant counts, identical row-level-security flags and policies, that the restricted application role sees only each tenant's own rows (and nothing without a tenant context), and that no `.env` secret value occurs in the dump; then drops only that database (unless `--keep`). A tampered or truncated backup is refused before any restore. `smoke --backup` runs backup and restore-check on the live run's database |
| `--env-file <path>` on `preflight`, `up`, `smoke`, `down` | use another environment file (for example a copy with one setting changed) instead of `.env` |

Readiness is protocol-level, not "the process exists": API `GET /api/v1/health` 200 (this runs `SELECT 1`); each mock answers an HTTP request (they have no `/health` route); the worker has logged `worker started`; the UI page returns 200 **and** `/api/v1/health` through its proxy returns 200. Every wait is bounded (90 s per service by default) and a service that exits early is reported with its log path.

**State, concurrency and interruption (Batch 7).** `.demo/state.json` is claimed with an exclusive create, so two launchers started at the same moment cannot both own a run (exactly one proceeds, the other is refused before it creates anything) and updates are atomic. `down` refuses while the launcher that wrote the state is still working (phase `starting` or `smoke`), treats a state whose launcher is gone as **stale** (it is described as such and cleaned up by `down`), updates the state after every resource it releases, and is therefore **resumable**: if a shutdown is interrupted (Ctrl-C or a killed `down`), the next `down` finishes only what is left. A process is stopped only when its creation time still matches the recorded one.

**Readiness failures** now carry diagnostics: whether the process is alive, whether the port accepts connections, the result of a request that needs no database and of the readiness request, and the last log lines (secrets redacted).

Ports are fixed by the existing launcher and `.env` origin allow-list: if any is occupied (for example by your own development stack) the preflight stops and names it; the launcher never stops a process it did not start. Repeating `up` while a run is recorded is refused with a pointer to `down`. Mock external systems (ticketing, inventory, fleet, CRM, service desk) are **simulated**. With the default deterministic AI backends the demo proves workflow, security and isolation, not AI quality; `--ai real` needs Ollama, the model and the MiniLM cache to exist already (nothing is downloaded or installed) and was only preflight-checked, not run, in Batch 6.

Use the real-AI variants only within the approved scope described in section 8.

### Live ingestion checkpoint (Batch 9)
`python scripts/demo.py smoke --ingestion --no-browser --backup` additionally exercises durable ingestion jobs on both tenants: upload job completion, retry and recovery under a **simulated** embedding failure (the API and worker are started through `scripts/fault_boot.py`, which makes the embedder raise while a switch file exists; it refuses `EAOP_ENV=production` and is never used by the normal demo), reprocessing (generation 1 to 2), cross-tenant refusal, and a reprocess-versus-delete race. Operating the jobs: list `GET /api/v1/ingestion/jobs?status=RETRY_PENDING`; a failed reprocess job can be re-queued with `POST /api/v1/ingestion/jobs/{id}/retry`; the worker drains jobs automatically. Details: [ingestion-jobs.md](../architecture/ingestion-jobs.md).

## 3. Startup order (manual alternative to the launcher)
Use only the isolated configuration in section 8. Stop if any configured connection targets the protected shared instance or database. Run from the repository root and use the virtual environment's Python (`.venv\Scripts\python` on Windows).

| # | Command | Result checked | Status |
|---|---|---|---|
| 1 | `python scripts/dev.py up` (`docker compose up -d --wait`) | container `...-postgres-1` healthy, port 127.0.0.1:5432 | container already running and healthy (not re-run); inspected |
| 2 | `python scripts/dev.py migrate` (Alembic to `0017` as the owner role of the disposable database) | `migrations applied` | **executed** on a new empty database: reached `0008`, extensions `vector` and `pgcrypto` present |
| 3 | `python scripts/dev.py seed` | Apex tenant `apex-industrial`, four demo users, five sample documents | **executed** (ingestion with the deterministic embedder) |
| 4 | `python scripts/dev.py stack` | API :8000, worker, ticketing :8101, inventory :8102, fleet :8103, CRM :8104, service desk :8105 | **executed**; all listening within seconds |
| 5 | `python scripts/dev.py onboard-meridian` | tenant `meridian-fleet`, members, connectors, profile, documents; `onboarding complete` | **executed**; re-running is idempotent (`exists`, `duplicate`, profile version bumps) |
| 6 | `cd frontend && npm run dev` | UI on http://127.0.0.1:5173 proxying `/api` to :8000 | `npm run dev` **executed** (dependencies already installed); the proxy returned the API health |
| 7 | `python scripts/ollama_ctl.py start` (owner-authorized real AI only) | `Ollama ready`; one tiny generation answered | **executed**, then stopped with `... stop` |

Users: tenant `apex-industrial` or `meridian-fleet`, with `admin@`, `supervisor@`, `engineer@`, `auditor@` plus `apex.example.test` or `meridian.example.test`; password is `SEED_PASSWORD` from your `.env`. The platform administrator is created by the seed; see `scripts/seed_apex.py`.

## 4. Migrations
`python scripts/dev.py migrate` applies pending migrations to the disposable database named by `POSTGRES_DB` as the database owner. Check the target connection before migrating and confirm the query below returns `0017`. Check a database's version: `docker compose exec -T postgres psql -U <owner> -d <db> -tAc "select version_num from alembic_version"`.

## 5. Safe fixture initialization
`seed` and `onboard-meridian` are idempotent. Use a disposable database for experiments instead of touching shared ones: create it with `docker compose exec -T postgres psql -U <owner> -d postgres -c "CREATE DATABASE <name>"` and start every command with `POSTGRES_DB=<name>` in the environment (this is how the 2026-11-13 verification ran, on `eaop_batch4`). Automated tests use their own databases (`eaop_test`, `eaop_bench`, `eaop_e2e`, ...) and rebuild them. Fixture tenants for UI testing: [test-fixtures](test-fixtures.md).

## 6. Health verification
| Check | Command | Expected |
|---|---|---|
| API | `curl http://127.0.0.1:8000/api/v1/health` | `{"status":"ok","llm_backend":...,"embedding_backend":...}` |
| API docs | http://127.0.0.1:8000/docs and `/openapi.json` | HTTP 200 |
| Tenant onboarding | `GET /api/v1/onboarding/health` as the tenant admin | `passed` equals `total` (8 of 8 for Meridian on 2026-11-13) |
| Connectors | `GET /api/v1/connectors/health` as the tenant admin | configuration and recent outcomes; **no live probe** |
| Metrics | `GET /api/v1/observability/summary` | process counters, uptime, durable database counts |
| Mock services | they have no `/health` route (`GET /` and `/health` return 404 while running); confirm the port is listening or watch the stack output | |
| Ollama | `curl http://127.0.0.1:11434/api/tags` | lists `qwen2.5:1.5b` |

There is no separate readiness endpoint; `/api/v1/health` is the single health route. It runs `SELECT 1` on the database (HTTP 503 `database_unavailable` with `Retry-After` if the database is down) but does not call the language model, Ollama or the mock services.

## 7. Application URLs
UI http://127.0.0.1:5173 · API http://127.0.0.1:8000 (docs `/docs`) · mocks 8101 to 8106 (8106 = the records mock) · PostgreSQL 127.0.0.1:5432 · Ollama 127.0.0.1:11434. End-to-end tests use a separate port range 8210 to 8215 and 8220.

## 8. Isolated validation

### Prerequisites and database lifecycle

Use the installed Python virtual environment, Docker Compose v2, a locally available `pgvector/pgvector:pg16` image and, for root checks that inspect frontend dependencies or run browser smoke, the existing Node dependencies and supported browser. Use `python scripts/demo.py preflight` to check the demo environment before smoke. Missing tools, dependencies, images or models require an owner decision before acquisition.

Use a disposable checkout with an ignored local configuration, a unique `COMPOSE_PROJECT_NAME`, its own volume and a free loopback port distinct from the shared instance. The recorded clean-checkout procedure used port `15432` and `docker compose up -d --wait`. Use the existing project Compose file and confirm the service is healthy and pgvector is available. The accepted regression used PostgreSQL 16.15. See [clean environment procedure](../../scripts/clean_environment_check.py) and the [validation report](../planning/final-validation-report.md). Use already installed dependencies for deterministic validation. The full clean-install workflow has separate acquisition requirements.

For direct pytest runs, set the isolated connection in the process environment using `DB_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `APP_DB_PASSWORD` and `WORKER_DB_PASSWORD`. The environment must agree with Compose and the migration and launcher configuration. Use per-run credentials and keep them out of terminal transcripts and tracked files. Confirm the host, port, Compose project and database before every lifecycle command. Run suites sequentially on a given instance. The [backend fixture](../../backend/tests/support.py) drops and recreates its fixed `eaop_test` database and migrates it to Alembic head. The demo launcher creates its own `eaop_demo_*` database and drops it at teardown. For a manual migration check, use the create/migrate/query procedure in sections 4 and 5 and confirm revision `0017`.

### Normal deterministic validation

Leave `RUN_REAL_AI`, `RUN_DISRUPTIVE` and `UAT_BACKEND` unset and use deterministic AI settings for demo commands. Run these from the repository root with the project's Python.

| Validation | Existing command |
|---|---|
| Registry/API contracts | `python -m pytest backend/tests/test_evaluation_registry.py backend/tests/test_ops_routes.py backend/tests/test_meridian.py backend/tests/test_api_contract.py backend/tests/test_api_error_contract.py backend/tests/test_api_namespace_security.py backend/tests/test_api_response_schemas.py -q` |
| Backend regression | `python -m pytest backend/tests -q` |
| Root regression | `python -m pytest tests -q --deselect tests/fault_injection` |
| Root diagnostic confirmation | `python -m pytest tests -vv --deselect tests/fault_injection --maxfail=1 -o faulthandler_timeout=120 -o console_output_style=classic --durations=10 -ra` |
| Apex and Meridian UAT | `python -m pytest tests/acceptance -q` |
| Simulated faults | `python -m pytest tests/fault_injection -q`, with `RUN_DISRUPTIVE` unset |
| Workflow benchmark | `python scripts/demo.py smoke --compare` |
| Functional benchmark | `python evaluation/benchmarks/run_phase3.py --embedding deterministic --llm deterministic`. Run only against the isolated instance. The script drops and recreates its fixed `eaop_bench` database. |
| Backup, restore and isolation | `python scripts/demo.py smoke --rest --backup`. For a separate dump and restore check use the commands in section 0. |

The API contract and regression suites exercise role-based authorization, real PostgreSQL RLS, Apex and Meridian visibility, and cross-tenant denials. During restore-check, require tenant counts and RLS flags and policies to match the source, and verify that the restricted application role sees only its own tenant's rows and has no visibility without tenant context. Check the dump checksum, Alembic revision, row counts and secret exclusion before accepting the restore result. The [full Compose drill](full-compose-backup-restore.md) records the procedure for the container stack’s separate database service and the source and restore results. Keep protected databases outside both procedures.

Tests and benchmark commands can write acceptance, observability, fault-injection and performance artifacts. Run them in the disposable checkout and keep fresh outputs separate from frozen reports, labels and datasets. See the [benchmark evidence index](../performance/benchmark-reports-index.md) for commands, artifacts and limitations. Phase 8 scoring of existing outputs is documented there. Preserve the frozen evidence and closed experiment decisions.

### Disruptive fault injection

Set `RUN_DISRUPTIVE=1` in the isolated runner's environment only for `python -m pytest tests/fault_injection -q`. The live restart test stops and restarts the current Compose project's PostgreSQL service. Before running, verify that Compose resolves to the task-owned project and pytest connects to that same isolated instance. Afterward confirm service recovery and clear the opt-in. Keep the protected shared service running.

### Owner-authorized real AI and owner-only operations

Enable real inference only with explicit approval for the run. Existing commands are `python scripts/demo.py preflight --ai real` for readiness, `RUN_REAL_AI=1` with `python -m pytest backend/tests/test_real_ai.py -q` for local integration, `UAT_BACKEND=real` with `python -m pytest tests/acceptance -q` for real UAT and `python evaluation/benchmarks/run_phase3.py --embedding sentence_transformers --llm ollama` for the Phase 3 benchmark. Check Ollama, the approved model and the local MiniLM cache first. Do not download dependencies, providers or models without separate owner authorization. Keep new inference and experiments out of routine validation. Use the [evaluation protocol](../evaluation/phase8-evaluation-protocol-v1.1.md) for any separately approved independent evaluation.

Repository access changes, remote CI, publication and release follow the [publication handoff](../planning/publication-handoff.md). The shared `eaop` instance, frozen evaluation records, and `v4.1.0-local-rc1` are protected throughout this workflow.

### Governance and documentation checks

- Run `python scripts/provenance_check.py` and require zero new violations. Preserve [PROV-01](../planning/provenance-exceptions.json) and use the owner's author and committer identity.
- Run `python scripts/secret_scan.py`. Review candidate and publication scope as described in the handoff. Keep local credentials out of logs, examples and commits.
- Check the report, documentation and traceability with `python -m pytest -q tests/test_final_validation_report.py tests/test_documentation_consistency.py tests/test_delivery_documents.py tests/test_v41_reconciliation.py tests/test_traceability.py tests/test_full_traceability.py tests/test_readme_results.py`.
- Run `python scripts/generate_v41_reconciliation.py --check`, `python scripts/generate_full_traceability.py --check` and `python scripts/generate_third_party_notices.py --check`. After register edits, regenerate the closure plan with `python scripts/generate_closure_plan.py` and review its diff and count against the register.
- Use the [existing local and CI checks](ci-and-local-tests.md) for Ruff and workflow validation. Run `git diff --check` and inspect the staged candidate before committing.

## 9. Common startup failures
| Symptom | Cause | Action |
|---|---|---|
| `set POSTGRES_PASSWORD in .env` from compose | `.env` missing or placeholder removed | create `.env` from `.env.example` |
| `ModuleNotFoundError: alembic` (or similar) | the global Python was used | use `.venv\Scripts\python` |
| Connector creation or onboarding returns 500 `internal_error` | `EGRESS_*` JSON mangled (for example by sourcing `.env` in a shell) | restore the JSON, let `dev.py` load `.env` |
| `connector_destination_not_allowed` (422) | origin not in `EGRESS_DEV_MOCKS` / `EGRESS_ALLOWLIST` for that tenant slug | add the origin on the server side (tenants cannot) |
| 409 `embedding_model_mismatch` | tenant indexed with a different embedding backend | `scripts/reindex_embeddings.py` |
| Errors about missing columns or tables | Database is behind the code | Confirm the target is disposable, then use section 4 to migrate and check revision `0017`. Preserve the protected shared `eaop` database. |
| Port already in use | an earlier stack or your own dev stack | stop it yourself; for a previous demo run `python scripts/demo.py down` (section 11) |
| `demo.py` says a run "is in progress" | another launcher is still working; wait, or interrupt it with Ctrl-C and run `demo.py down` |
| `demo.py` says a run "was recorded earlier ... launcher is no longer running" | stale state from an interrupted run: `demo.py down` |
| A service "was not ready after 90s" | read the diagnostics in the message and the log named there; the API stall seen once in Batch 7 is unexplained |
| `demo.py` says a previous run is recorded | `.demo/state.json` exists | `python scripts/demo.py down`, then start again |
| `demo.py preflight` reports an invalid JSON setting | `.env` was edited or exported through a shell | edit `.env` directly and keep the double quotes (only names are printed) |
| `docker` errors | Docker Desktop not running | start it |
| Real AI slow or timing out | CPU-only 1.5B model, about 24 tokens/s; first call loads the model | wait; `OLLAMA_TIMEOUT` (default 240 s) |

## 10. Logs
The stack prints JSON log lines (correlation id, route template, status, duration; document and report text are never logged) to the terminal that runs it; redirect to a file to keep them (`python scripts/dev.py stack > stack.log 2>&1`; `*.log` is git-ignored). Search by the `X-Correlation-ID` value from a response header or error body. Container logs: `docker compose logs postgres`. Audit trail: `GET /api/v1/audit` (admin, auditor).

## 11. Safe shutdown
- Demo launcher runs: `python scripts/demo.py down` (stops only the processes it recorded and drops only its own disposable database). `smoke` does this itself at the end, also after a failure or Ctrl-C.
- Stack: press Ctrl-C in its terminal (it terminates the API, worker and mocks). If it was started in the background, stop only those processes (`dev.py stack`, `uvicorn` with `app.main`, `ticketing_app`, `inventory_app`, `fleet_app`, `crm_app`, `servicedesk_app`, `run_worker.py`).
- UI dev server: Ctrl-C.
- Ollama: `python scripts/ollama_ctl.py stop` only if you started the instance for this task.
- PostgreSQL: leave the shared service running. Use `python scripts/dev.py down` only for the isolated Compose project you started. It keeps that project's volume.

## 12. Project-specific cleanup
Leftover `.demo/<run id>/logs` folders are git-ignored and can be deleted by hand. Drop only a database you created for an experiment (`down` does this for the demo launcher): `docker compose exec -T postgres psql -U <owner> -d postgres -c "DROP DATABASE <name>"`. Do not run global Docker cleanup (`docker system prune`, volume removal), which would affect unrelated projects and the `pgdata` volume. Delete scratch log files you created. Audit rows are append-only by design, so a fixture is re-seeded rather than deleted.

For the isolated validation Compose project, the clean-environment procedure uses `docker compose down -v --remove-orphans` only after confirming the same unique project owns the container, network and volume and they are all disposable. Preserve the shared Compose project, `pgdata` volume, database, other projects, installed images and model caches. Keep backup artifacts and diagnostic logs according to the task's evidence needs.
