# Gate C reviewer guide (operational checklist)

**Status: prepared, NOT performed.** This is the hands-on companion to the [independent review package](independent-review-package.md) (tracks, scope, record). It reuses existing runbooks and does not replace them. Nothing here is a review result: the only same-author dry run is listed in section 9 and is not independent. Under the [EAOP 08E owner decision](../planning/eaop-08e-owner-governance.md), independent-human review is optional additional assurance. The [Gate C owner disposition](../planning/gate-c-owner-disposition.md) closes technical acceptance and owner disposition for the pinned candidate. Manual accessibility and demo reproduction stay **Partial** pending the applicable evidence.

## 1. Prerequisites (nothing is downloaded or paid for)
Windows 11 or similar, about 16 GB RAM, 2 GB free disk, Docker Desktop (the project's PostgreSQL 16 + pgvector container), Python with the project `.venv`, Node and `npm ci` done in `frontend/`, Microsoft Edge and, for the second-browser run, Google Chrome. Ollama and the model are optional (deterministic AI backends prove workflow, security and isolation, not AI quality). Follow [README section 8](../../README.md#8-local-setup) and the [local runbook](../operations/local-runbook.md) sections 1 and 2 (create `.env` from `.env.example`; do not `source` it in a POSIX shell). Run `.venv\Scripts\python scripts\demo.py preflight` first: it checks everything and changes nothing. Record the machine, OS, tool versions and `git rev-parse HEAD`.

## 2. Start and stop the application
```
.venv\Scripts\python scripts\demo.py up       # disposable database eaop_demo_*, migrated, Apex seeded, Meridian onboarded, UI at http://127.0.0.1:5173
.venv\Scripts\python scripts\demo.py status
.venv\Scripts\python scripts\demo.py down     # stops only recorded processes, drops only the database it created
```
API http://127.0.0.1:8000 (Swagger at `/docs`). Accounts: `admin@`, `supervisor@`, `engineer@`, `auditor@` with `apex.example.test` (tenant `apex-industrial`) or `meridian.example.test` (tenant `meridian-fleet`); the password is `SEED_PASSWORD` from your own `.env`. Never use or touch the shared `eaop` database.

## 3. Customer acceptance scenarios
Walk the tables in [Apex guide](apex-demo-guide.md) (steps 1 to 11) and [Meridian guide](meridian-demo-guide.md) (steps 1 to 9), plus the [27 demonstration steps](demonstration-27-steps.md). For every step record pass, fail or could-not, with what you saw. Key expectations: Apex fault report gives asset `P-101`, category `mechanical_vibration`, priority `P3`, `pending_review`, and the vibration number is an unverified candidate that does not affect priority; Meridian gives `VH-2101`, `brake_system`, `P3`. Ticket path: `DRAFT`, `PENDING_APPROVAL`, `APPROVED`, then `SUBMITTED` with an external id from the mock (simulated system).

## 4. REST, CSV and signed webhook verification
Automated live checkpoint (both tenants, isolated database, torn down afterwards):
```
.venv\Scripts\python scripts\demo.py smoke --ingestion --rest --compare --backup
```
Read `evaluation/demo-runs/<run id>/report.md`; failed checks are shown, not hidden. To probe by hand see [REST ingestion](../architecture/rest-ingestion.md) and [webhooks and CSV](../architecture/webhooks-and-csv.md). Webhook probes (use an endpoint created by the tenant administrator; signature is HMAC-SHA256 over `timestamp.delivery_id.raw_body`): a correct delivery returns 202 (queued, not processed); a wrong secret, tampered body, tampered delivery id or unknown endpoint all return the identical 401 `invalid_signature`; a stale timestamp returns 401 `timestamp_out_of_window`; a repeated delivery id returns 409 `webhook_replayed`; a non-JSON content type returns 415; an oversized body (over 256 KiB) returns 413. A `tenant_id` in the body must be ignored. Any deviation is a finding.

## 5. Tenant-isolation and approval checks
1. Meridian engineer requests an Apex incident id (`GET /incidents/{id}`) and an Apex engineer requests a Meridian ticket id: expect 404 `not_found` both ways. A Meridian search for an Apex pump term returns only Meridian documents.
2. Auditor `POST /tickets`: 403 `insufficient_role`. Engineer `POST /approvals/{id}/decision`: 403. The author of a ticket cannot approve it. A repeated decision returns 409.
3. The incident's creator cannot verify its measurements; only a different supervisor can, and priority then changes only from the server's response.
4. Audit log (`GET /audit` as auditor or admin) shows extraction, priority decision, drafting, approval, submission; the audit log has no update or delete path.
5. Database level: `smoke --backup` restores into a new database and re-proves row-level security. Try to break the numeric boundary as described in Track 2 of the package.

The owner runner checkpoints raw catalog output before comparing the [approved RLS and FORCE relation sets](../security/identity-tables.md#owner-security-disposition-for-gate-c). It separately records command, parsing and policy failures. The restricted-role authorization regression must pass before the RLS catalog gate runs. Both checks must pass before live smoke. Use `--rls-continuation` for the targeted continuation after prior suites have passed at the same candidate.

## 6. Accessibility review (this is the part only a person can do)
Context: automated axe found 0 violations on 43 states in Edge and 44 in Chrome (same author; `evaluation/reports/phase6-closure/`). That is not a conformance claim and not a screen-reader audit. Reviewer tasks:
- **Keyboard only** (no mouse): sign in; reach every one of the 13 pages through the navigation; submit a fault report; open an incident; use the confirm dialog (focus moves in, Escape closes it, focus returns to the trigger); approve and reject a ticket. Record any control you cannot reach, any focus trap, any invisible focus indicator and any logical-order problem.
- **Screen reader** (NVDA with Edge or Chrome, free; or Narrator, built into Windows): sign in, read each page's heading structure and landmarks, fill the sign-in and fault-report forms and trigger a validation error (is it announced?), review a citation, approve a ticket, read a table. Record the reader and version and what was unclear, unlabelled or announced wrongly.
- Optional: 200% zoom and a 375 px width; reduced-motion and high-contrast settings.
Reproduce the automated runs with `cd frontend && npx playwright test e2e/accessibility.spec.ts` (Edge) and `$env:E2E_BROWSER_CHANNEL="chrome"` before the same command (Chrome; writes `axe-results-chrome.json`).

## 7. Objective pass/fail checklist
| # | Item | Pass when |
|---|---|---|
| 1 | Setup | Followed only the README and runbook; missing or wrong steps recorded |
| 2 | `python -m pytest backend/tests -q`, `python -m pytest tests -q`, frontend typecheck, lint, test, `python scripts/secret_scan.py` | Zero failures; summary lines pasted; differences from the README table reported |
| 3 | `demo.py smoke --ingestion --rest --compare --backup` | Ends with `smoke PASSED` and a report with no failed check |
| 4 | `python scripts/container_smoke.py` | Passes, or the reason is recorded |
| 5 | Apex scenario (section 3) | Every step matches or its deviation is recorded |
| 6 | Meridian scenario | Same |
| 7 | REST, CSV, webhook (section 4) | Every listed response code observed |
| 8 | Isolation and approval (section 5) | Every refusal observed; no cross-tenant read or write possible |
| 9 | Keyboard review | All tasks completable, or each blocker recorded |
| 10 | Screen-reader review | Performed with a named reader, or recorded as not done |
| 11 | Cleanup | `demo.py down` leaves no `eaop_demo_*` database or recorded process |
Any item not done is recorded as "not done", never left empty.

## 8. Cleanup and troubleshooting
Cleanup: `.venv\Scripts\python scripts\demo.py down` (safe to repeat; resumable). Backups stay in git-ignored `backups\demo\`; delete only those files if you want them gone. Do not run global Docker cleanup, never touch the shared `eaop` database, and do not remove containers or volumes other than this project's. Troubleshooting: [troubleshooting guide](07-troubleshooting-guide.md) and [local runbook section 9](../operations/local-runbook.md). Common causes: an occupied port (8000, 8101 to 8105, 5173; the launcher never stops a process it did not start), `.env` exported into the shell, Docker not running, an `up` repeated while a run is recorded (run `down` first), tests rewriting `evaluation/customer-acceptance` and `evaluation/observability` (restore with `git checkout --`).

## 9. Same-author dry run (not independent)
On 2026-11-14 the author ran `demo.py smoke --rest --no-browser --backup`: PASSED in 82.5 s, report `evaluation/demo-runs/20261114-011642-f5c8/report.md`, database dropped. The Chrome axe run above is also same-author. Neither counts as independent review.

## 10. Report
Use [the review record template](../../evaluation/independent-review/review-record-template.md), which now includes the sections for these checklist items. Copy it to `evaluation/independent-review/<date>-<reviewer>.md`.

## EAOP 08A corrective changes

The owner-conducted Gate C run against `6739de46705d937b365402275a1b0a5eedcfa174` remains a historical **FAIL**. Its raw results, runner and review records were retained as issued. This subsection records the historical corrective work. The current acceptance path and retained 08A, 08B and FI-10 results are documented in the [EAOP 08E owner decision](../planning/eaop-08e-owner-governance.md).

- The root `data/` ignore rule hid `backend/tests/data/apex_builtin_golden.json`, which the Apex test reads at collection. The two available local copies matched each other. All 32 distinct reports were independently replayed from the committed Phase 4 rules blob at `44b1083a01505f8703337c9c7144c39d7f0bc45f`. Every parsed field and priority matched, the fixture's rules SHA-256 matched the blob, and the candidate uses the same rules blob. The verified fixture is tracked byte for byte through a path-specific ignore exception. Its SHA-256 is `cff4c7a27a5bfa66c4c45237920f07dc7da7a9b4329c614504d0088259ddda33`. Fresh checkouts supply it directly, and the compatibility assertions are unchanged.
- The original owner's service-row regex expected the service name immediately after whitespace. The launcher emits a `[demo HH:MM:SS]` prefix. The [corrected owner runner](../../scripts/gate_c_owner_runner.py) recognizes the prefix and checks the eight service identifiers expected for `demo up`, each process state, and the API and UI HTTP results. It checkpoints status stdout, stderr and exit code before parsing. The report also records the expected and observed services, missing or stopped services, HTTP results, parse errors and health disposition. Other commands retain their previous output handling.

### Resume the owner session

Use the corrected commit on `feat/apex-vertical-slice` from a Windows PowerShell session with Docker Desktop running, the local `desktop-linux` endpoint accessible and the pgvector image already cached. Run from the corrected candidate checkout. Set `$dependencySource` to the local checkout containing the installed `.venv` and `frontend/node_modules`, with dependency manifests matching the corrected commit.

```powershell
$candidate = git rev-parse HEAD
$evidence = Join-Path $env:TEMP ("eaop-08a-" + [guid]::NewGuid().ToString("N") + ".json")
& (Join-Path $dependencySource '.venv/Scripts/python.exe') scripts/gate_c_owner_runner.py --candidate $candidate --dependency-source $dependencySource --output $evidence
```

The runner makes its own disposable checkout and uses an isolated Compose project. Review the new evidence for four Apex tests collected and passed, a clean backend regression, passing parser tests, and a healthy status with all eight services and both HTTP probes returning 200. Then complete any outstanding manual scenarios, refusals, accessibility observations and cleanup checks in this guide, and retain the new record separately. Stay in 08A until technical closure and the required review and disposition. EAOP 08B remains on hold.
