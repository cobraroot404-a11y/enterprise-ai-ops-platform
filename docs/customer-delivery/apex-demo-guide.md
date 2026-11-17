# Apex Industrial demonstration guide (fictional customer)

Apex Industrial Manufacturing is a fictional pump and rotating-equipment plant. Everything below uses fictional data and mock external systems.

**How this guide was verified.** The API steps were **executed** on 2026-11-13 against a freshly migrated and seeded disposable database on the local stack (deterministic AI backends, so the answers prove workflow and security, not AI quality). The UI steps were **not** executed by this verification; they are derived from the page source (`frontend/src/pages`) and are covered by the earlier Playwright suite ([Phase 6 report](../phase6/phase6-review-report.md)). Real-AI behaviour is evidenced only by the real-mode acceptance run (`evaluation/customer-acceptance/real/uat-report.json`).

## Customer problem
A technician reports "Pump P-101 shows abnormal vibration at the drive end, measured at 8.4 mm/s, with a grinding noise since this morning." The plant needs the relevant manual guidance, the pump's history, a correctly prioritised maintenance ticket in its ticketing system, and a supervisor's approval before anything is sent, with a full audit trail and without trusting a number the model may have misread.

## Fastest path (Batch 6; see also the [handover package](demo-handover.md))
`.venv\Scripts\python scripts\demo.py up` creates a disposable database, seeds Apex, starts every service, onboards Meridian and starts the UI at http://127.0.0.1:5173 (accounts and password rule below). Stop with `.venv\Scripts\python scripts\demo.py down`. `scripts\demo.py smoke` runs the checks of this guide automatically (API for both tenants, browser for both tenants) and writes `evaluation/demo-runs/<run id>/report.md`. The manual steps below remain valid; the preconditions below are what the launcher automates.

## Preconditions
1. PostgreSQL running, migrations at head, Apex seeded: `python scripts/dev.py up`, `migrate`, `seed` ([runbook](../operations/local-runbook.md)).
2. `python scripts/dev.py stack` running (API :8000, worker, ticketing mock :8101, inventory :8102); UI `npm run dev` for the UI path.
3. Password is `SEED_PASSWORD` from your `.env` (never shown here). Real AI is optional: set `LLM_BACKEND=ollama` and `EMBEDDING_BACKEND=sentence_transformers` and run `python scripts/ollama_ctl.py start`; a tenant indexed with one embedding backend must be reindexed before using the other.

## Accounts (tenant `apex-industrial`)
| Role | Sign-in | Can |
|---|---|---|
| Support engineer | `engineer@apex.example.test` | upload documents, ask, create incidents and tickets, request approval; cannot approve or review |
| Maintenance supervisor | `supervisor@apex.example.test` | review incidents, verify measurements, approve or reject tickets, retry failures |
| Tenant administrator | `admin@apex.example.test` | everything tenant-scoped, audit, connectors, members, profile |
| Read-only auditor | `auditor@apex.example.test` | read, audit log; cannot write |

## Walkthrough
UI sign-in fields: Tenant, Email, Password. API: `POST /api/v1/auth/login` with `{"email", "password", "tenant"}`; use the returned `access_token` as a Bearer token (Swagger UI at http://127.0.0.1:8000/docs, Authorize). Expected results marked **observed** were seen on 2026-11-13.

| # | Action (role) | UI or API | Expected result |
|---|---|---|---|
| 1 | Open **Document Library** (engineer) | UI `/documents`; API `GET /documents` | Five Apex documents (manual PDF, inspection report PDF, equipment register, incident history, maintenance log); **observed** total 5. Upload form: file (PDF, CSV, JSON, TXT, MD, max 10 MB) and Kind. Re-uploading an unchanged file reports `duplicate` (UAT-A01) |
| 2 | Ask an out-of-scope question, "What is the chief executive's favourite colour?" (engineer) | UI **AI Knowledge Assistant** (Ask); API `POST /ai/ask` | `grounded: false`, no citations (**observed**). Answerable questions return citations with page numbers (PDF) or record ids (CSV); with the deterministic backend the "answer" often quotes headings |
| 3 | Report the fault: paste the vibration report (engineer) | UI **Incident Explorer**, "Report a fault"; API `POST /incidents/extract` `{"report_text": ...}` | HTTP 201. **Observed:** asset `P-101` verified against the register, category `mechanical_vibration`, priority `P3` from rules, `review_status: pending_review`, `review_urgency: urgent`. The vibration reading is an **UNVERIFIED candidate (class A)** with `eligible_for_numeric_priority: false`: it did not influence priority |
| 4 | Create the ticket draft (engineer) | UI Incident detail, draft action, then **Support Tickets**; API `POST /tickets` `{"incident_id"}` | `DRAFT`, title `[P3] mechanical vibration on P-101`. If the incident were `needs_review`, this returns 409 until a supervisor accepts or rejects it (UAT-A04) |
| 5 | Auditor attempts to create a ticket | API `POST /tickets` as auditor | 403 `insufficient_role` (**observed**) |
| 6 | Request approval (engineer) | UI Tickets, "Request approval…"; API `POST /tickets/{id}/request-approval` | `PENDING_APPROVAL` |
| 7 | Engineer attempts to approve | API `POST /approvals/{id}/decision` as engineer | 403 `insufficient_role` (**observed**); authors also cannot approve their own tickets (separation of duties) |
| 8 | Approve (supervisor) | UI **Approval Queue**, Approve…; API `POST /approvals/{id}/decision` `{"decision":"approved","comment":...}` | `APPROVED`; approval, audit event and outbox event commit together |
| 9 | Wait for the worker (a few seconds), read the ticket (engineer) | UI Tickets / **Workflow History**; API `GET /tickets/{id}`, `/tickets/{id}/history` | `SUBMITTED` with an external id (**observed** `MNT-1001` from the ticketing mock); history events `ticket.drafted`, `approval.approved`, transitions, `ticket.submitted` |
| 10 | Review the trail (auditor or admin) | UI **Audit Logs**; API `GET /audit` | Events for extraction, priority decision, drafting, approval, submission |
| 11 | Enter a structured observation and verify it (UI since Batch 5; engineer then a different supervisor) | UI **Incident Explorer**: in "Report a fault" choose "Add a structured observation" (type, asset, value with a decimal point, unit, optional observation time, source reference), then Analyse report. As the supervisor open the incident, read **Numeric measurements**, write a justification (10 to 500 characters), **Verify measurement…** or **Reject measurement…**, confirm. API equivalent: `POST /incidents/extract` with `observations`, then `POST /incidents/{id}/measurements/vibration_mm_s/verify` | The observation shows **Submitted · awaiting verification** (class C, not used for priority). Engineers, auditors and the incident's creator see no verify controls and the server refuses them (403 `insufficient_role` / `separation_of_duties`). After a supervisor other than the creator verifies: **Human-verified** (class D), **Used for priority**, the incident priority and a "Priority P3 → P2 (rule …)" line come from the server's response, and History shows "Measurement verified by a human reviewer". Reject keeps it excluded. A repeated decision returns 409. **Observed through the UI** in the live browser acceptance test (Batch 5) and again by `scripts/demo.py smoke` (Batch 6); API behaviour also observed on 2026-11-13 |

## Evidence locations
`evaluation/customer-acceptance/deterministic/uat-report.md` (UAT-A01 to A08, all pass), `evaluation/customer-acceptance/real/uat-report.json` (real Ollama + MiniLM mode), `evaluation/failure-reports/phase7/fi-report.md` (fault injection), `evaluation/reports/phase3/SUMMARY.md` (AI quality), `docs/architecture/system-architecture.md` (flows).

## Security controls on display
Row-level security and 404 for other tenants' ids; role permissions on every route; incident review gate; separation of duties; approval re-verified by the worker; idempotency keys (no duplicate tickets); audit log append-only; unverified numbers never drive priority; connector destinations restricted by a server-side allow-list.

## Known functional limitations
- Deterministic backends are test-only; with real AI (1.5B model, CPU) about three in four incidents stop for human review, citation correctness is below the 95% target, and answers take seconds.
- Observations can only be added when a report is analysed (the API has no endpoint to add one to an existing incident); there is no UI to edit or withdraw an observation. No document deletion or reprocessing.
- The verification response should carry an `audit_event_id`; the live API omitted it, so the UI shows "recorded in the audit history" instead of an event number.
- External systems are mocks; the integration health page reflects configuration and recent outcomes, not a live probe.
- Apex-specific demo accounts and data are fictional and share one password; do not reuse that pattern for real systems.
