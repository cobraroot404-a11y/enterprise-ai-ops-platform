# 5. Deployment plan

**Scope: local only.** Nothing in this repository has been deployed to a cloud, a server or a container platform, and no such deployment is claimed. Cloud portability is analysed in [../architecture/cloud-portability.md](../architecture/cloud-portability.md).

## Target environment (as exercised)
Windows 11 workstation, about 16 GB RAM, CPU-only inference, Python 3.10 virtual environment, Node 20+, Docker Desktop for the PostgreSQL 16 + pgvector container, Ollama with `qwen2.5:1.5b` and the MiniLM embedding model for real-AI runs.

## Steps
1. **Prerequisites and configuration.** Create `.env` from `.env.example` (secrets are generated or chosen locally, never committed; `scripts/secret_scan.py` checks). `python scripts/demo.py preflight` verifies tools, ports (8000, 8101-8106, 5173), JSON settings and egress allow-lists.
2. **Database.** `docker compose up -d` starts PostgreSQL with pgvector. `python scripts/dev.py migrate` applies Alembic migrations to head (currently `0013`) as the owner role; application and worker use restricted roles (`eaop_app`, `eaop_worker`) under forced row-level security.
3. **Seed and onboard.** Apex fixtures are seeded; Meridian is onboarded through the public API (`scripts/onboard_tenant.py`).
4. **Start services.** `python scripts/dev.py stack` (API :8000, worker, mocks :8101-:8106) and the Vite UI, or the one-command demonstration `python scripts/demo.py up`, which uses a **disposable** database and stops only what it started with `demo.py down`.
5. **Verify.** `python scripts/demo.py smoke --rest --no-browser --backup` runs both customers' workflows, ingestion, REST/CSV/webhook integrations, a backup and a restore proof on an isolated database.

## Shared development database
The long-lived `eaop` database reported revision `0006` and has deliberately never been migrated automatically; migrating it is an owner decision (take a backup first: `demo.py backup` works on disposable databases; use `pg_dump` for `eaop`).

## Rollback
Migrations 0009 to 0013 each refuse to downgrade while data created by the feature exists (to avoid silent loss); restore from a backup instead. The demonstration launcher's `down` removes only its own disposable database.

## Container images (local stack, built and smoke-tested)
`docker-compose.app.yml` builds two images from `infrastructure/docker/` (`eaop-app-backend:local` 276 MB with API, worker, migration, seed and the mock systems; `eaop-app-ui:local` 94 MB, nginx serving the host-built `frontend/dist` and proxying `/api`) and runs them with their own PostgreSQL container and volume, separate from the development database. `python scripts/container_smoke.py` builds, starts, onboards Meridian, runs the Apex and Meridian workflow checks (25 per tenant) against the containerised API, checks the UI proxy, and removes only its own compose project (two passing runs, `evaluation/container-smoke/`). Limits: the images run the deterministic test-only AI backends (no torch, no models); the [same-machine Gate B run](../../evaluation/clean-environment/20261113-183717/report.md) reached a configured host Ollama instance from the container (the default smoke remains deterministic); the UI image does not build from source in-container; the worker and mocks share the API container's network namespace because the connector egress policy deliberately refuses private container-network addresses; images are not hardened or scanned beyond running as a non-root user.

## Production readiness
Not claimed. Gaps include public exposure controls (TLS, gateway, distributed rate limiting), managed secrets, retention and backup policy, monitoring beyond local counters, and independent security review.
