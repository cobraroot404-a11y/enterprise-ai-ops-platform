# Demonstration handover package

For a technically capable reviewer who wants to run and judge the demonstration on one Windows machine. Everything here describes what exists in this repository and what was actually executed; nothing is deployed, nothing is production, and both customers are fictional. Start with the [README](../../README.md) for the overall status and its honest list of limitations.

## 1. Purpose
Show a multi-tenant AI operations platform turning free-text fault reports into evidence-grounded incidents and human-approved tickets, with numeric readings treated as untrusted until a person verifies them, tenant data isolated at the database level, and a full audit trail. Two fictional customers use the same application: Apex Industrial (pumps, [guide](apex-demo-guide.md)) and Meridian Fleet (trucks, [guide](meridian-demo-guide.md)).

## 2. What you are looking at (architecture in one paragraph)
A FastAPI backend, an outbox worker and PostgreSQL 16 with pgvector (row-level security per tenant), a React UI, and five **simulated** customer systems (ticketing, inventory, fleet telematics, CRM, service desk). Local AI (Ollama and MiniLM) is optional; the demo defaults to deterministic test-only backends so it proves workflow, security and isolation, not AI quality. Diagrams of the real data flows: [system architecture](../architecture/system-architecture.md).

## 3. Prerequisites (must already be present; the launcher installs and downloads nothing)
Windows with Docker Desktop (the project's PostgreSQL container running: `python scripts/dev.py up`), Python 3.10+ virtual environment at `.venv` with `backend/requirements-dev.txt` installed, Node 20+ with `frontend/node_modules` installed (`npm install`), the installed Microsoft Edge (used by the browser smoke), 2 GB free disk, free ports 8000, 8101-8105 and 5173, and a `.env` created from `.env.example` (see the [runbook](../operations/local-runbook.md) section 2; the launcher validates it and never prints values). Real-AI mode additionally needs Ollama with the model and the MiniLM cache already present.

## 4. One-command startup
```
.venv\Scripts\python scripts\demo.py preflight      # checks everything above, changes nothing
.venv\Scripts\python scripts\demo.py up             # disposable database, services, both customers, UI; returns with services running
.venv\Scripts\python scripts\demo.py status
.venv\Scripts\python scripts\demo.py down           # explicit shutdown
.venv\Scripts\python scripts\demo.py smoke --backup # automated: all checks, browser, backup and restore proof, report, teardown (about one minute)
```
UI http://127.0.0.1:5173, API docs http://127.0.0.1:8000/docs. Accounts: `admin|supervisor|engineer|auditor@apex.example.test` (tenant `apex-industrial`) and `...@meridian.example.test` (tenant `meridian-fleet`); the password is `SEED_PASSWORD` from your `.env`.

## 5. The demonstration journeys (10 minutes)
1. **Apex, report** (engineer): Incident Explorer, "Report a fault": "Pump P-101 shows abnormal vibration at the drive end, with a grinding noise since this morning." Add a structured observation (type Vibration, asset `P-101`, value `8.4`, unit `mm/s`, source "gauge GA-7").
2. **Visible result:** the incident shows the asset verified in the register, the observation as **"Submitted · awaiting verification"**, **"Not used for priority"**, and the current priority (P3, from deterministic rules).
3. **Human verification** (sign in as the supervisor in a second window): open the incident, write a justification, **Verify measurement…**, confirm. The measurement becomes **Human-verified**, **Used for priority**, and the page shows `Priority P3 → P2 (rule …)` exactly as returned by the server. History shows "Measurement verified by a human reviewer".
4. **Refusals** (engineer, auditor, the incident's creator, another tenant): no verify controls are shown to them and the API answers 403 (`insufficient_role` or `separation_of_duties`) or 404 across tenants.
5. **Ticket:** engineer drafts a ticket and requests approval; the author cannot approve (403); the supervisor approves; within seconds the worker submits it to the simulated ticketing system and the ticket shows **Submitted** with an external id (`MNT-…`); the Audit Logs page (auditor) shows the whole chain.
6. **Meridian:** repeat with tenant `meridian-fleet`, asset `VH-2101`, type Brake pressure, unit `psi`; the ticket goes to a different (simulated) service desk contract and shows a `WO-…` id. Meridian cannot see Apex's data.
`demo.py smoke` performs all of this automatically through the API and the browser for both tenants and writes the evidence.

## 6. Security and tenant-isolation controls on display
Database row-level security (forced) per tenant with a restricted application role; role permissions on every route enforced by the server; the incident's creator cannot verify its measurements; authors cannot approve their own tickets; numbers from text or the model never affect priority until a person verifies them; connector destinations restricted by a server-side allow-list; append-only audit log; error bodies without internals. After a backup is restored into a new database, the same isolation is re-proved (section 8).

## 7. Simulated versus actual
**Actual:** the API, worker, PostgreSQL with row-level security, migrations, ingestion and retrieval, the incident and ticket state machine, approvals, the outbox, the audit log, the React UI, authentication and roles, the verification workflow. **Simulated:** the five customer systems (local mock services), all customers, people, data and sensors; the default AI backends are deterministic test stand-ins (not AI performance). **Partly implemented:** document deletion exists as an API operation only (no UI control; see [document lifecycle](../architecture/document-lifecycle.md)). **Not implemented:** cloud deployment, OpenTelemetry spans and exporter, Grafana. See [Known limitations](../../README.md#known-limitations).

## 8. Backup and restore of a demo database
```
.venv\Scripts\python scripts\demo.py backup [--database eaop_demo_<id>]    # pg_dump (inside the project's PostgreSQL container) to backups\demo\ (git-ignored) plus a manifest
.venv\Scripts\python scripts\demo.py restore-check backups\demo\<file>.dump  # restore into a NEW isolated database, verify, drop it
```
Only disposable `eaop_demo_*` databases can be backed up; the shared `eaop` database is refused. The restore check proves: the file matches its checksum, the restore succeeds, the migration revision, tenants, every table's row count and each tenant's counts equal the source, row-level security flags and policies are identical, the restricted application role sees only each tenant's own rows (and nothing without a tenant context), and no `.env` secret value appears in the dump. A backup contains tenant data, the audit log and the password **hashes** of the fictional demo accounts; keep it local. This is a procedure for demonstration databases, not production backup infrastructure; backing up the shared `eaop` database is deliberately not offered.

## 9. Expected visible results and evidence
Each `smoke` run writes `evaluation/demo-runs/<run id>/report.md` (timeline, per-tenant checks, browser results, backup proof, cleanup) and `report.json`, with screenshots. Executed runs and their outcomes, including failures, are listed in the [Batch 7 report](../planning/batch7-report.md).

## 10. Troubleshooting
| Symptom | Action |
|---|---|
| `preflight` names a busy port | something else (often your own dev stack) holds it; stop that program yourself, or `demo.py down` if it is a previous demo |
| "a previous demo run is recorded" | `demo.py down` (resumable; stops only what that run created) |
| "its launcher is no longer running" | a run was interrupted; `demo.py down` cleans up what it recorded |
| invalid JSON setting | edit `.env` directly keeping the double quotes; never source it through a shell |
| PostgreSQL unreachable | `python scripts/dev.py up`, start Docker Desktop |
| a service "was not ready after 90s" | the error now includes the process state, port state, two probe results and the log tail; logs are in `.demo/<run id>/logs` |
| browser navigation aborted (`ERR_ABORTED`) | the demo spec retries only the first page load, at most twice, and records each retry in the report |

## 11. Safe shutdown and cleanup
`demo.py down` stops only recorded processes (verified by creation time), stops Ollama only if the run started it, and drops only its own database; it is safe to repeat and resumable after an interruption. Delete `.demo/<run id>/logs` and `backups/demo/*` by hand when no longer needed. Never run global Docker cleanup; the project's `pgdata` volume holds your shared databases.

## 12. Reproduction evidence and its level
**Gate A:** fresh demo state was demonstrated repeatedly. **Gate B:** a [clean checkout and fresh local dependency installation](../../evaluation/clean-environment/20261113-183717/report.md) passed on the same machine. **Gate C:** the owner closed [technical acceptance with documented limitations](../planning/gate-c-owner-disposition.md); no independent human reproduction is claimed. Complete demonstration reproducibility remains open. Use the [27-step guide](demonstration-27-steps.md) and [08F disposition](../planning/eaop-08f-local-disposition.md) to verify Apex connector configuration and a useful cited maintenance answer and record the reviewer procedure and its deviations.

## EAOP 09 owner reproduction closure ? 2026-11-16

Owner reviewer: Gautham. Scope: same-machine local portfolio reproduction. No independent-human or different-hardware reproduction is claimed.

Baseline: `9801a60213147a29571100559c3d23248613a61d` on `docs/eaop-08e-owner-governance`.

Evidence retained:

- Deterministic customer acceptance: **21 passed**.
- Deterministic isolated container smoke: `evaluation/container-smoke/20261116-203247/` ? **PASS**.
- Ollama isolated container smoke: `evaluation/container-smoke/20261116-203745/` ? **PASS**, using the already-installed `qwen2.5:1.5b` model.
- Apex and Meridian workflows passed in the isolated container stack.
- Temporary `eaop-app` containers, volume and network were removed after review. The temporary `.env` was removed. Protected development resources were not modified.

### Apex connector observation

The Apex Data Sources UI showed:

- `apex-industrial-ticketing` ? ticketing ? `http://127.0.0.1:8101` ? status `ok`.
- `apex-industrial-inventory` ? inventory ? `http://127.0.0.1:8102` ? status `ok`.

The observed table exposed configuration and health status but no manual Save or Sync control for those seeded connector rows. No manual Save/Sync action is claimed. Connector configuration for this demonstration was supplied by the reproducible seed/onboarding path.

### Useful cited maintenance answer

Question:

`What should I check when pump P-101 shows abnormal vibration?`

Observed answer:

`Check coupling alignment; angular and parallel offset must be below 0.05 mm.`

The UI identified supporting evidence from `apex_cp200_pump_manual.pdf`, version 1, page 2, and marked the passage as retrieved evidence with the verbatim quote verified. The displayed source text directly supported both the maintenance action and the `0.05 mm` threshold.

Assessment: **PASS**. No unsupported numeric claim was observed in this answer.

### P32L1277 disposition

The two residual demonstration-reproduction observations identified by the 08F local disposition are now evidenced for the owner-authorized same-machine local scope: Apex connector configuration was observed and a useful maintenance answer was reproduced with directly supporting citation evidence.

`P32L1277` is locally satisfied for this scoped owner reproduction. This does not establish independent-human reproduction, different-hardware reproduction, remote CI, publication, or a tested published release. Those remain separate owner-gated requirements.
