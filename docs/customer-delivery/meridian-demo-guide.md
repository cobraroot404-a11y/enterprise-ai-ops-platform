# Meridian Fleet demonstration guide (fictional customer)

Meridian Fleet Logistics is a fictional truck fleet operator. It is added to the same running platform through configuration and the public API only. Everything below uses fictional data and mock external systems.

**How this guide was verified.** The API steps were **executed** on 2026-11-13 against a freshly migrated database on the local stack, with Meridian onboarded by `python scripts/dev.py onboard-meridian` (deterministic AI backends: workflow, isolation and security evidence only). UI steps were **not** executed in this verification; they come from the page source and the earlier Playwright suite. Real-AI behaviour is evidenced only by the real-mode acceptance run. Meridian category extraction and multi-hop answers are weak in the held-out evaluation, and there is no Meridian AI-quality benchmark (its corpus is 15 synthetic chunks).

## Customer problem
A driver or depot technician reports "Vehicle VH-2101 shows low brake pressure of 52 psi with a hissing noise at the rear axle." Meridian needs this turned into a prioritised work order in its own service-desk system (a different contract from Apex's), approved by a supervisor, without any Apex data being visible and without code written for Meridian.

## Fastest path (Batch 6; see also the [handover package](demo-handover.md))
`.venv\Scripts\python scripts\demo.py up` creates a disposable database, seeds Apex, starts every service, onboards Meridian and starts the UI at http://127.0.0.1:5173 (accounts and password rule below). Stop with `.venv\Scripts\python scripts\demo.py down`. `scripts\demo.py smoke` runs the checks of this guide automatically (API for both tenants, browser for both tenants) and writes `evaluation/demo-runs/<run id>/report.md`. The manual steps below remain valid; the preconditions below are what the launcher automates.

## Preconditions
1. Platform running as in the Apex guide, with Apex seeded and the stack up (ticketing :8101, inventory :8102, fleet :8103, CRM :8104, service desk :8105).
2. `.env` has `MOCK_SERVICEDESK_API_KEY` and `MERIDIAN_SERVICEDESK_KEY` set to the same value, and `EGRESS_DEV_MOCKS` lists the Meridian origins (already in `.env.example`).
3. `python scripts/dev.py onboard-meridian` completed (**observed:** tenant, four members, three connectors, profile, five documents; re-running is idempotent).

## Accounts (tenant `meridian-fleet`)
`admin@`, `supervisor@`, `engineer@`, `auditor@` with `meridian.example.test`; password is `SEED_PASSWORD` from `.env`. Roles and permissions are identical to Apex (support engineer creates, supervisor approves, auditor reads).

## Walkthrough
| # | Action (role) | UI or API | Expected result |
|---|---|---|---|
| 1 | Check onboarding (admin) | UI **Customer Onboarding**; API `GET /onboarding/health`, `GET /tenant-profile` | **Observed:** 8 of 8 checks pass; profile shows asset label `vehicle`, categories (brake_system, engine_cooling, tire_wheel, refrigeration_unit, electrical_fault, leak, noise_vibration) and signal rules (brake pressure psi, coolant C) |
| 2 | Review data sources (admin) | UI **Data Sources**, **Integration Health**; API `GET /connectors`, `/connectors/health` | Connectors `meridian-service-desk` (ticketing), `meridian-fleet-telematics`, `meridian-crm`; health reflects configuration and recent outcomes, no live probe |
| 3 | List documents (engineer) | UI **Document Library**; API `GET /documents` | Fleet register, MX300 maintenance manual, depot inspection, service history, telematics alerts (**observed** 5, none of Apex's) |
| 4 | Report the fault (engineer) | UI **Incident Explorer**, "Report a fault"; API `POST /incidents/extract` | **Observed:** asset `VH-2101` verified, category `brake_system`, priority `P3`, `review_status: pending_review`, `review_urgency: urgent`; the 52 psi reading is an UNVERIFIED candidate (class A), not eligible for priority |
| 5 | Draft, request approval (engineer), approve (supervisor) | UI Incident detail, **Support Tickets**, **Approval Queue**; API `POST /tickets`, `/tickets/{id}/request-approval`, `/approvals/{id}/decision` | `DRAFT`, `PENDING_APPROVAL`, `APPROVED`; auditor gets 403 on create and engineer gets 403 on approve (**observed**) |
| 6 | Read the result (engineer) | UI Tickets, **Workflow History**; API `GET /tickets/{id}` | `SUBMITTED` with a work-order id (**observed** `WO-7001`, produced by the Meridian service-desk mock at `/api/v2/work-orders` with its own field names) |
| 7 | Cross-tenant check (Meridian engineer with an Apex incident id; Apex engineer with a Meridian ticket id) | API `GET /incidents/{id}`, `/tickets/{id}` | Both **observed** 404 `not_found`. A Meridian search for an Apex pump term returns only Meridian documents |
| 8 | Structured observation and human verification (UI since Batch 5) | Same UI steps as the Apex guide, step 11, with asset `VH-2101`, type Brake pressure, unit psi; or API `POST /incidents/extract` with `observations`, then `POST /incidents/{id}/measurements/brake_pressure_psi/verify` with `expected_trust_status":"VALIDATED"` | Class C `VALIDATED` (not eligible); engineer refused; after supervisor verification `HUMAN_VERIFIED`, class D, eligible, priority recomputed by the server (**observed** P3 to P2 through the API on 2026-11-13, and through the browser by the Batch 6 smoke run on `meridian-fleet`) |
| 9 | Audit (auditor or admin) | UI **Audit Logs**; API `GET /audit` | **Observed** actions include `tenant.created`, `member.added`, `connector.created`, `profile.updated`, `document.created`, `incident.extracted`, `incident.priority_decided`, `ticket.drafted`, `approval.approved`, `ticket.submitted`; platform-administrator access to the tenant is itself audited (`platform.tenant_access`) |

## Evidence locations
`evaluation/customer-acceptance/deterministic/uat-report.md` (UAT-B01 to B07, all pass), `evaluation/customer-acceptance/real/uat-report.json`, `evaluation/reports/phase5-meridian-smoke`, `docs/architecture/phase5-meridian.md`, `docs/operations/tenant-onboarding.md`, `onboarding/meridian.json`.

## Security controls on display
Separate tenant under row-level security; server-side egress allow-list (a tenant administrator cannot add a destination); connector secrets referenced by name only; same role matrix as Apex; authorship and verification separation of duties; audit trail.

## Known functional limitations
- Meridian runs on a separate execution path for some profile-driven logic (documented technical debt); the UI is only partly profile-driven.
- Category extraction can pick a near-miss category with the real model; the deterministic backend used for the observed run is test-only.
- Observations can only be added when a report is analysed; the Batch 5 browser acceptance ran on the Apex e2e tenant; since Batch 6 `scripts/demo.py smoke` also drives the Meridian tenant through the browser (sign-in, observation, verification, server priority, refusals; two reports under `evaluation/demo-runs/` show it passing). External systems are mocks; no live connector probe.
- Meridian has no AI-quality benchmark; its isolation and workflow are validated, not its answer quality.
