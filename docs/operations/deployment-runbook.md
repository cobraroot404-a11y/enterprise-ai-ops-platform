# Deployment runbook (local)

The deployment this repository supports is **local**: a developer workstation. This runbook is the ordered, checkable procedure; [local-runbook.md](local-runbook.md) has the full command reference and failure table, and [../customer-delivery/05-deployment-plan.md](../customer-delivery/05-deployment-plan.md) the plan and its limits. No cloud or server deployment is provided. For the isolated local container stack, follow the container smoke procedure in the linked deployment plan.

## Before you start
- [ ] Windows 11, Python 3.10 virtual environment (`.venv`), Node 20+, Docker Desktop running, about 2 GB free disk.
- [ ] `.env` exists (copy `.env.example`; set strong local values; never commit it). `python scripts/secret_scan.py` reports 0 findings.
- [ ] Ports free: 8000, 8101-8106, 5173, 5432.

## Procedure
1. `python scripts/demo.py preflight` must pass (it names what is missing).
2. `docker compose up -d --wait` (PostgreSQL 16 + pgvector).
3. For a **disposable** run (recommended): `python scripts/demo.py up`; it creates a database named `eaop_demo_<timestamp>`, migrates it to head (`0017`), seeds Apex, starts the mocks, worker and API, onboards Meridian and starts the UI.
   For the long-lived stack: `python scripts/dev.py migrate`, `python scripts/dev.py seed`, `python scripts/dev.py onboard-meridian`, then `python scripts/dev.py stack`. **Do not migrate the shared `eaop` database without the owner's decision and a backup.**
4. Verify: `GET http://127.0.0.1:8000/api/v1/health` returns 200; `python scripts/demo.py status` lists every process as running; sign in at http://127.0.0.1:5173.
5. Acceptance check: `python scripts/demo.py smoke --rest --no-browser --backup` passes (it uses its own isolated database).

## Operate
Logs: `.demo/<run id>/logs` for demo runs, the console for `dev.py stack` (JSON, correlation ids). Health: `/api/v1/health`, `/api/v1/connectors/health[?probe=true]`, `/api/v1/observability/summary`. Backups: `python scripts/demo.py backup` and `restore-check`.

## Shut down and clean up
`python scripts/demo.py down` stops only the recorded processes and drops only the database that run created. `docker compose down` stops PostgreSQL (data volume kept). Nothing else is removed; unrelated containers, volumes and models are never touched.

## Rollback and recovery
Each of migrations 0009 to 0013 and 0015 refuses to downgrade while data created by its feature exists; recover by restoring a backup into a new database and re-pointing the configuration. Failed jobs are retried by the worker; exhausted jobs can be re-queued by a supervisor.

## Troubleshooting
[../customer-delivery/07-troubleshooting-guide.md](../customer-delivery/07-troubleshooting-guide.md).
