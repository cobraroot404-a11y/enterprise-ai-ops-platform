# Phase 6 closure gate

Final status: **PASS**
Closure commit: **b911fbf** (branch `feat/apex-vertical-slice`, on top of Phase 6 commit `9f3b180`)
Date: 2026-11-11. Nothing merged, pushed or published; no remote exists.

## Requirements checklist
| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Automated accessibility audit (axe-core, dev-only dependency) of all 13 pages and representative states; critical/serious fixed | PASS | `frontend/e2e/accessibility.spec.ts`, `evaluation/reports/phase6-closure/axe-results.json` |
| 1b | Manual keyboard-navigation check of the critical workflow | PASS | `frontend/e2e/keyboard-workflow.spec.ts` and the checklist below |
| 2 | Test credentials and environment isolation reviewed; guards and regression tests; secret scan | PASS | [test-credentials.md](../security/test-credentials.md), `tests/test_environment_guards.py`, `scripts/secret_scan.py` |
| 3 | Connector egress restrictions verified; allow-list is operator-controlled | PASS | `backend/tests/test_connector_egress.py` (80), [connector-egress.md](../security/connector-egress.md) |
| 4 | 13-page frontend and critical workflows verified (Apex and Meridian) | PASS | Vitest, Playwright, real-AI Playwright (Phase 6 run), table below |
| 5 | Accepted limitations documented | PASS | [accepted-limitations.md](../deployment/accepted-limitations.md) |
| 6 | Closure verification | PASS | results below |

## 1. Accessibility audit
**Tool and scope:** `@axe-core/playwright` (dev dependency), rule tags WCAG 2.0 A/AA, 2.1 A/AA and best-practice, in Microsoft Edge, on the isolated
deterministic stack. **43 states audited, 0 violations at every impact level** after fixes (first run: 2 serious and 30 moderate).

| State group | States |
|---|---|
| Sign-in | default, validation errors, server error |
| All 13 pages, default rendering (tenant administrator) | 13 |
| Reduced-control views (read-only auditor, support engineer) | 10 |
| Loading, empty, filter form error | 3 |
| Forms with validation errors | documents upload, assistant, incident report, administration members, connector configuration, profile JSON |
| Dialogs | connector confirmation, incident-review confirmation, ticket-approval confirmation |
| Special screens | blocked-incident review, approval queue card, decided tab, citation inspection expanded, connector rejected by the server |

Fixed because of the audit: no page-level `h1` (added: product name in the top bar); scrollable table regions were not keyboard-focusable or named (focusable regions with
unique labels); insufficient contrast for links and active tab/primary buttons (darker link and button colours; a background-colour transition that made axe measure
mid-transition colours was removed).

**Manual keyboard-navigation check (critical workflow), performed with the keyboard only (no mouse, no programmatic focus) and automated as `keyboard-workflow.spec.ts`:**
Tab reaches Tenant, Email, Password and Enter signs in; focus moves to the page heading after navigation; Tab reaches the navigation link and Enter opens the Incident
Explorer; Tab reaches the fault-report field and the Analyse button, Enter submits; Tab reaches the review justification and the Accept button; Enter opens the confirmation
dialog; focus lands on Cancel, Tab cycles Cancel and Accept and stays inside the dialog; Escape closes it and returns focus to the control that opened it; Enter then Tab then Enter
confirms; the result is announced in a polite status region. Result: operable, no keyboard trap observed.

**Not claimed:** automated axe testing does **not** replace a full screen-reader accessibility audit and finds only a subset of issues. This project does **not** claim WCAG
conformance. No screen-reader pass was performed. Only Edge was used.

## 2. Security verification of test credentials and environment isolation
See [test-credentials.md](../security/test-credentials.md). Verified by `tests/test_environment_guards.py` (10 tests): the E2E launcher refuses production, any database other than
`eaop_e2e`/`eaop_e2e_real`, any non-local DB host and any port outside the isolated range, before touching anything (the real script is executed with `EAOP_ENV=production` and
exits non-zero); E2E accounts do not exist in the development database; the E2E password appears only in allow-listed files; in production the API refuses to start with test-only
configuration (deterministic backends, weak/test JWT secret, placeholder DB passwords, `EGRESS_DEV_MOCKS`) and never accepts a known test password at sign-in even for a valid
account. **Secret scan** (`python scripts/secret_scan.py`, free, no dependency, never prints values): 0 findings in 359 files including reports, junit files, logs, Playwright
artifacts and screenshots (raw bytes); the real values of every sensitive key in the local `.env` were searched for and not found; a regression test proves the scanner detects planted secrets
without printing them. No unrelated credential was rotated or deleted.

## 3. Connector egress verification
`backend/tests/test_connector_egress.py`: 80 passed, covering private, loopback and cloud-metadata destinations, IPv4 and IPv6 and alternative-encoding bypasses, DNS rebinding
(single resolution, pinned address, mixed answers refused), unsafe redirects (never followed), worker execution, retries revalidated, enrichment lookups, unauthorized connector
changes, unauthorized public domains and cross-tenant destinations, **and (new) that no API or connector configuration can modify the server-side allow-list**. The operator must authorize
each origin in `EGRESS_ALLOWLIST` before onboarding. **Application-level SSRF protection is not a substitute for network-level egress restrictions in production**; no paid infrastructure is provisioned.

## 4. Frontend verification
All 13 pages exist (Overview, Customer Onboarding, Data Sources, Document Library, AI Knowledge Assistant, Incident Explorer, Support Tickets, Approval Queue, Workflow History, Integration Health,
Evaluation Dashboard, Audit Logs, Administration), each calling the real API; a Playwright test opens all 13 against the real backend with no console errors.

| Area | Verified by |
|---|---|
| Authentication, validation, session expiry | `auth-and-roles.spec.ts`, Vitest `pages.test.tsx` |
| Role-aware navigation (four tenant roles on both tenants, platform admin) | `auth-and-roles.spec.ts`, `rbac.test.ts` |
| Tenant-specific data visibility and isolation | `workflows.spec.ts` (tenant isolation, vocabulary from configuration) |
| Document ingestion | `documents-and-assistant.spec.ts` |
| Retrieval and citations | `documents-and-assistant.spec.ts`, accessibility spec (citation inspection) |
| Incident review, ticket approvals (separation of duties, unregistered asset refused) | `workflows.spec.ts` |
| Connector status and configuration, unauthorized destinations rejected | `admin-config-and-quality.spec.ts` |
| External submission tracking, failure and retry, accurate workflow labels | `workflows.spec.ts`, Vitest |
| Audit history | `workflows.spec.ts`, `auth-and-roles.spec.ts` |
| Apex and Meridian end-to-end | `workflows.spec.ts`; real-AI UI smoke recorded in `evaluation/reports/phase6-gate/real-ai-e2e.json` |
Edge remains the primary E2E browser. **Chromium and Firefox are documented future compatibility targets**; no browser was downloaded.

## Test results (this machine)
| Check | Command | Result |
|---|---|---|
| Lint (backend) | `python -m ruff check backend mock-services workers scripts tests evaluation conftest.py` | clean |
| Secret scan | `python scripts/secret_scan.py` | 0 findings |
| Backend full suite | `python -m pytest -q` | **286 passed, 0 failed, 13 skipped** (12 real-AI, 1 opt-in outage test) |
| SSRF negative and positive | `python -m pytest -q backend/tests/test_connector_egress.py` | 80 passed |
| Environment guards | `python -m pytest -q tests/test_environment_guards.py` | 10 passed |
| Security regression set (JWT, RLS, memberships, authorization matrix, mutation proofs, identity, review gate) | 7 files | 71 passed |
| Real Ollama + MiniLM integration | `RUN_REAL_AI=1 python -m pytest backend/tests/test_real_ai.py -q` | 12 passed |
| Frontend typecheck, lint, build | `npm run typecheck`, `npm run lint`, `npm run build` | clean |
| Vitest | `npm test` | 43 passed |
| Playwright (deterministic stack, includes axe and keyboard specs) | `npx playwright test` | **47 passed, 0 failed, 1 skipped** (opt-in screenshots) |
| Axe | `evaluation/reports/phase6-closure/axe-results.json` | 43 states, 0 violations |
A first closure run showed one Playwright failure caused by test pollution (the accessibility spec left a pending approval that a later test selected by title). The accessibility spec now cancels
its ticket and approval helpers select a card by ticket id; the failure was in the tests, not the product. Two flaky-looking contrast results were traced to a CSS colour transition and fixed.

## Known limitations
See [accepted-limitations.md](../deployment/accepted-limitations.md): application-level SSRF protection needs network-level enforcement; per-process throttling is insufficient for distributed deployments;
Apex and Meridian retain two execution paths; roughly 75% of incidents still need human review with the approved model; full cross-browser and screen-reader validation is incomplete;
comprehensive multi-tenant AI-quality benchmarking is scheduled for Phase 8 (the 95% citation target remains NOT MET); CI has not run.
