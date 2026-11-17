# Accelerated Batch 6 report: one-command local demonstration, isolated reproduction and operational readiness

Date: 2026-11-13 (EST). Starting HEAD `75024fe886ddb27817f4ecb439a9c607048337c1` (branch `feat/apex-vertical-slice`, clean; specification SHA-256 `b1c573e2…` verified). Developer tooling, tests and documentation only: **no application runtime code, migration, endpoint, dependency, model, evidence or licence change.** V41-17.03 stays VERIFIED; V41-14.02 stays PARTIAL. Nothing was pushed, merged, published or released.

## 1. Launcher design
`scripts/demo.py` (entry point) and `scripts/demo_smoke.py` (smoke checks and report writer) wrap what already exists: the `scripts/dev.py` process table and `.env` loader, `scripts/migrate.py`, `scripts/seed_apex.py`, `scripts/onboard_tenant.py`, `scripts/ollama_ctl.py`, the Vite dev server and Playwright. No second infrastructure system, no new dependency (it uses the standard library, SQLAlchemy and Alembic already in the virtual environment, and PowerShell only to read a process's creation time).
- **Disposable database:** `eaop_demo_<timestamp>_<id>`, created per run on the local server. Safety guard: the name must start with `eaop_demo_`, must not equal the configured shared database, and only a database recorded as *created by this run* is ever dropped. The shared `eaop` database (still at revision `0006`) is never migrated, reset or read.
- **Ownership record:** `.demo/state.json` (git-ignored) is written **before** anything is created and updated after each resource (database, each process with its creation time, Ollama only if the run started it). `down` terminates a process only if its creation time still matches (a recycled PID is left alone), stops Ollama only if the run started it, drops only its own database, and is safe to repeat. Unrelated processes holding ports are never touched; preflight stops instead.
- **Environment:** read through the existing `.env` loader (raw text, never through a shell). Validated before anything starts: required names present and non-empty, `EGRESS_ALLOWLIST` and `EGRESS_DEV_MOCKS` valid JSON objects, the mock origins authorised for both tenants, the two service-desk keys equal, `EAOP_ENV` not production. Messages name settings, never values.
- **Readiness (protocol-level):** API `GET /api/v1/health` 200 (this runs `SELECT 1`); each mock answers an HTTP request (they have no health route); the worker logged `worker started`; the UI page returns 200 and `/api/v1/health` through its proxy returns 200. All waits are bounded (90 s default); an early exit is reported with its log path; no process is declared ready merely because it exists.

## 2. Execution modes
`preflight [--ai real]`, `up [--ai real]` (interactive: services keep running, detached), `status`, `down` (explicit shutdown), `smoke [--no-browser]` (automated: start, verify, report, tear down only what it created, also on failure or Ctrl-C), and `--env-file` for tests. Documented in the README and [local runbook](../operations/local-runbook.md#0-one-command-demonstration-batch-6).

## 3. Preflight verification (executed on this machine)
`demo.py preflight` and `preflight --ai real` passed all checks: Python environment, `.env`, Node, frontend dependencies, Playwright, 113 GB free disk, ports free, PostgreSQL reachable with pgvector, Ollama installed, embedding cache present. Real-AI mode only preflight-checked the model when Ollama was running (see section 11, scenario 5); it was **not run end to end** with real AI.

## 4. Database initialisation (executed)
Per smoke run: database created (0.1 s), migrations applied (1.5 s) and verified at revision `0008` equal to the Alembic head, Apex seeded (1.4 s, deterministic embedder), Meridian onboarded through the public API (1.4 s); repeated runs each start from a fresh database, so state is predictable. Database dropped at the end of every run (verified by the report and by listing databases afterwards: no `eaop_demo_*` remains).

## 5. Service startup and readiness evidence
Each smoke report lists the startup timeline: ticketing, inventory, fleet, CRM, service desk, worker, API, onboarding, UI, each ready in 1.3 to 2.4 s. Reports: `evaluation/demo-runs/20261113-021005-f700/`, `20261113-021610-9fc9/` (the failed run, kept), `20261113-021857-0c9e/`.

## 6. Apex and 7. Meridian demonstration results (API, real application; ticketing and service desk are simulated mocks)
Both tenants, 18 checks each in runs 1 and 3, all passing: four-role sign-in; engineer submits a structured observation (class C, VALIDATED, not used for priority); asset registered; engineer and auditor refused (403 `insufficient_role`); another tenant's supervisor 404 and engineer 404; supervisor verifies (HUMAN_VERIFIED, class D, eligible); priority taken from the server (P3 to P2, equal in the incident, the response and the verification block); repeated decision 409; creator refused (403 `separation_of_duties`); ticket drafted, approval requested, author refused 403, supervisor approves; the worker submits to the mock (Apex `MNT-1001`, Meridian `WO-7001`); the audit log shows the whole chain. Nothing is hard-coded: each check reads the live response.

## 8. Browser smoke results (executed on this demo stack, Microsoft Edge, nothing downloaded)
`frontend/e2e/demo-smoke.spec.ts` with `frontend/playwright.demo.config.ts` (starts nothing; drives the running demo stack). Per tenant, **both Apex (`apex-industrial`) and Meridian (`meridian-fleet`)**: sign-in, Incident Explorer, structured observation form, measurement shown as "Submitted · awaiting verification", no verify controls for the engineer, API refusals for engineer and auditor, supervisor reaches the controls **by keyboard** (Tab from the justification box to Verify then Reject), verifies, the page shows exactly the server's `Priority X → Y (rule …)`, and a supervisor who created an incident sees no controls and is refused by the API. Run 1: 2 passed; run 3: 2 passed. Screenshots in each run's `screenshots/`. The existing keyboard-only spec (`keyboard-workflow.spec.ts`, modified in Batch 5 to `tabTo` the Analyse button because new fields now precede it, the assertion that it is focused being kept) was re-run: passed.

## 9. Failures encountered (honest history)
- Unit test run 1 found a **launcher bug**: an exception with an empty message (a Ctrl-C) crashed the step recorder. Fixed; test kept.
- **Smoke run 2 failed** (146 s): `page.goto` returned `net::ERR_ABORTED` on the first load of the Vite dev server (the same cold-start abort seen once in the Batch 5 full suite). Cleanup worked (processes stopped, database dropped). I added a bounded retry (3 attempts, only for `ERR_ABORTED`, only the initial navigation) in the demo spec; no assertion was weakened. Run 3 passed. The abort is a dev-server behaviour, not an application defect; it may still recur, which the retry absorbs.
- My first scratch script for the negative scenarios used a SQL pattern that psycopg rejected; fixed in the scenario script, not the launcher.

## 10. Launcher tests (Level 1, executed): `tests/test_demo_launcher.py`, 22 passed
Environment loading (missing file; JSON quotes kept), validation (invalid JSON named without echoing its value, missing secrets, unauthorised mock origins, mismatched keys, production), preflight (busy port not stolen, PostgreSQL unreachable, missing Ollama model with `ollama pull` guidance and no download), database ownership (names outside the namespace refused, real create/drop of a throwaway database, shared database untouched), orchestration with fake services (start, down stops only recorded processes while an unrelated process survives, repeated invocation refused and a second `down` harmless, readiness failure by early exit and by timeout cleans up, migration/seed/database/onboarding failures clean up, interrupted startup recoverable by `down`, recycled PID untouched, preflight failure creates nothing), and report redaction (no secret value in `report.md` or `report.json`).

## 11. Negative-path results against the real CLI (executed): `scripts/demo_negative_checks.py`, 7 of 7 passed; `evaluation/demo-runs/negative-scenarios.json`
1 missing environment file (exit 2, copy-`.env.example` guidance); 2 invalid JSON setting (named, nothing created); 3 PostgreSQL unavailable (nothing created, start instructions); 4 required port held by an unrelated program (named, holder untouched, nothing created); 5 missing local Ollama model (Ollama started by the run, `ollama pull` guidance, no download, Ollama stopped again, database dropped); 6 launcher killed mid-startup (3 processes and the database already recorded) then `down` recovered everything; 7 interactive `up` (health 200, UI 200), a repeated `up` refused, `status` showing all running, `down`, a second `down`, no processes on the demo ports, no demo database left. Mock-service startup failure, backend and frontend readiness failure, migration failure and fixture failure are covered by the fake-service unit tests (not by deliberately breaking the real services).

## 12. Cleanup verification
After every smoke run the report lists each process "stopped" and the database "dropped"; afterwards the demo ports (8000, 8101-8105, 5173, 11434) were closed, `.demo/state.json` was absent and the database list contained only the pre-existing ones. Only git-ignored `.demo/<run id>/logs` folders remain. No Docker image, volume or unrelated container was touched; no global Docker command was run.

## 13. Reproducibility classification
**Fresh application state: demonstrated** (new disposable database, existing installed dependencies, existing local tools; two clean passes plus the recovery runs). **Clean-room installation: not performed** (no new virtual environment, no `pip install`, no `npm install`, no new PostgreSQL volume, no browser provisioning); it would require installing dependencies on a clean machine and an independent reviewer. A disposable database is not a clean-room installation. Real-AI end-to-end mode: not run.

## 14. Duration and resource observations
Smoke run: 51.9 s and 52.2 s (preflight 4 s, startup of everything about 17 s, API workflows 4 s, browser smoke 14.6 s, teardown about 1 s); the failed run took 146 s. CPU, memory and peak process counts were not measured; deterministic backends were used, so no Ollama or MiniLM load occurred and only one heavy consumer ran at a time. Each run's report folder is about 1 MB (screenshots); the failed run also holds a 1.4 MB Playwright trace.

## 15. Testing strategy and what was not re-run
Executed: launcher unit tests (22), real-CLI negative scenarios (7), three smoke runs, Vitest 65 passed, TypeScript, ESLint, the existing keyboard-workflow spec, root suite and secret scan (section 16). **Not re-run**: the backend suite, the full Playwright suite, real-AI and numeric-safety evaluations: no runtime application code changed (only new scripts, a new Playwright spec and config, tests and documentation), so their Batch 3.1 and Batch 5 results (backend 528 passed, 18 skipped; Playwright 51 passed, 1 skipped) remain historical evidence, not new results. Authorization, tenant-isolation and numeric-trust behaviour was nevertheless exercised live by the smoke runs (403, 404, 409 and `separation_of_duties` checks on both tenants).

## 16. Final results table
Root suite (`tests`, including the 22 launcher tests, documentation consistency, reconciliation and traceability): **105 passed, 1 skipped, 0 failed** (83 + 22). Vitest **65 passed**; TypeScript and ESLint clean; secret scan **0 findings in 868 files**; ruff **8 findings, all pre-existing** (none added); existing keyboard-workflow spec **1 passed**; smoke runs **2 passed, 1 failed (documented above)**; negative scenarios **7 of 7**.

## 17. Remaining limitations
Clean-room installation and independent reproduction not done; real-AI mode only preflight-checked; fixed ports (a developer's own stack on 8000 or 5173 makes preflight stop; this is deliberate); Windows-oriented (PowerShell and `taskkill`); mocks are simulated; the Vite cold-start abort may recur (mitigated by a bounded retry); the browser smoke covers the incident-verification path, not every page; the launcher has no timeout for the API workflow phase beyond per-call limits; no backup/restore instructions (V41-23.03 still partial). **Application observations (not fixed):** the Batch 5 backend gaps remain (`verification.audit_event_id` absent from responses, no `created_by` on incidents).

## 18. Requirements traceability
V41-23.04 (CPU-only, reviewer-reproducible demonstration) stays **Partial**; its gap text and evidence now cite the launcher, its tests, the smoke reports and the negative scenarios, and state that an independent reviewer reproduction and a clean-room installation are still missing. No other requirement status changed; V41-17.03 Verified, V41-14.02 Partial. A reproducible startup does not demonstrate full V4.1 compliance.

## 19. Recommended Batch 7
A clean-room reproduction on a second machine or fresh Windows user profile (install dependencies from `requirements.lock.txt` and `package-lock.json`, create `.env` from `.env.example`, run `demo.py preflight` then `smoke`), recorded as evidence by an independent reviewer; in the same batch add backup and restore instructions for the demo database (V41-23.03) and a short 10 to 15 minute walkthrough script (V41-25.03). Backend fixes for the Batch 5 gaps and document deletion still need your decisions.

## 20. Reproduction commands, evidence paths and final counts
```
.venv\Scripts\python scripts\demo.py preflight
.venv\Scripts\python scripts\demo.py smoke                  # about one minute; writes evaluation/demo-runs/<run id>/
.venv\Scripts\python scripts\demo.py up  /  status  /  down  # interactive mode
.venv\Scripts\python -m pytest tests/test_demo_launcher.py -q
.venv\Scripts\python scripts\demo_negative_checks.py
cd frontend && npm run typecheck && npm run lint && npm test
```
Evidence: `evaluation/demo-runs/20261113-021005-f700/report.md|json` (passed), `20261113-021610-9fc9/` (failed: browser navigation abort; kept), `20261113-021857-0c9e/` (passed), `evaluation/demo-runs/negative-scenarios.json`.
Files changed: new `scripts/demo.py`, `scripts/demo_smoke.py`, `scripts/demo_negative_checks.py`, `tests/test_demo_launcher.py`, `frontend/e2e/demo-smoke.spec.ts`, `frontend/playwright.demo.config.ts`, `evaluation/demo-runs/*`, `docs/planning/batch6-report.md`; changed `.gitignore`, `README.md`, `docs/operations/local-runbook.md`, both demo guides, `scripts/v41_requirements_data.py` and the generated requirement documents.
