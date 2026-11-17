# Phase 6 review report: the full 13-page frontend

Branch `feat/apex-vertical-slice`. Phase 5 closure gate: **PASS**, committed before any frontend work (closure commit `9f6b667`,
hash record `0a60c7f`; [phase5-closure-gate.md](../security/phase5-closure-gate.md)). Phase 6 commit: see the final report
(a commit cannot contain its own hash). Nothing merged, pushed or published; no remote.

## What was built
One shared React + TypeScript application serves both customers. Pages follow the V4.1 specification (Part 18) in order:
Overview, Customer Onboarding, Data Sources, Document Library, AI Knowledge Assistant, Incident Explorer, Support Tickets,
Approval Queue, Workflow History, Integration Health, Evaluation Dashboard, Audit Logs, Administration. Everything is wired to the real
API; there is no hard-coded data (the Evaluation Dashboard reads the committed evaluation artifacts through a new endpoint).

| Cross-cutting requirement | Implementation |
|---|---|
| Session and expiry | login stores token, role, tenant and `exp`; a 401 from the server or the token's own expiry returns to sign-in with an explanation; a warning appears two minutes before expiry |
| Role-aware navigation | `nav.ts` and `services/rbac.ts` (usability only; pages the role cannot use explain that the server enforces access; platform admins see only Administration) |
| Provenance vocabulary | `components/provenance.tsx`: AI-generated, Retrieved evidence, Verified (verbatim quote, register entry), Human-reviewed, Approved, Submitted (only with a confirmed external id), Pending, Failed |
| Never claim success early | tickets show "Approved · not yet submitted" until the backend reports SUBMITTED **and** an external id; pages poll while a worker submission is in flight; server refusals (for example an unregistered asset) are shown verbatim |
| Consequential actions | accessible confirmation dialogs (focus management, Escape, no double submit) for review, approvals, cancel/retry, connector and profile changes, member changes, tenant creation |
| Tables | server-side search, filters, sorting (`aria-sort`) and pagination; loading, empty, error (with retry) and success states |
| Forms | labels, inline validation messages tied with `aria-describedby`, client-side file checks before upload |
| Responsive | sidebar collapses behind a Menu button; tables scroll inside their container; no horizontal page scroll at 375 px (tested) |

New backend support (all tested in `test_ops_routes.py`, 10 tests): list filters/sorting, ticket and incident history, richer metrics,
`/connectors/health` (authorization of destinations, secret presence on the server and recent delivery results; **no fake live probe**),
`/onboarding/health` (checklist from real configuration), `/evaluation/reports` (verbatim artifacts; targets scored only where evidence exists).

## Test results (this machine)
| Check | Command | Result |
|---|---|---|
| Backend functional (includes the 79 SSRF tests, review-gate, isolation, Apex compatibility) | `python -m pytest -q` | **275 passed, 0 failed, 13 skipped** (12 real-AI, 1 opt-in outage test) |
| Backend real Ollama + MiniLM | `RUN_REAL_AI=1 python -m pytest backend/tests/test_real_ai.py -q` | 12 passed |
| Frontend typecheck / lint | `npm run typecheck`, `npm run lint` | clean / clean |
| Frontend unit and component tests | `npm test` | **43 passed** (api client, expiry, RBAC navigation, dialogs, status vocabulary, tickets, approvals, review gate, upload validation, login) |
| Production build | `npm run build` | clean |
| Playwright, deterministic stack | `npx playwright test` | **39 passed, 0 failed** (1 opt-in screenshot test skipped) |
| Playwright, real AI (Ollama + MiniLM) | `E2E_REAL_AI=1 npx playwright test --project=real-ai` | **3 passed**, evidence in `evaluation/reports/phase6-gate/real-ai-e2e.json` |
| Security regressions | included in the backend run | SSRF, RLS, identity, authorization matrix, review gate all pass |

Playwright covers authentication and validation, session rejection, role navigation for all four tenant roles on **both** tenants, platform admin,
all 13 pages rendering against the real backend without console errors, document ingestion/versioning/duplicate/validation/sort, assistant
(answer, refusal, evidence-only), the full Apex incident-to-submitted-ticket flow across three users, the human-review gate (blocked, justified
acceptance, still unreleasable for an unregistered asset, rejection), permanent and transient submission failure and retry, the Meridian flow
ending in Meridian's service desk only, tenant isolation by API and UI, administration, connector rejection of unauthorized destinations,
onboarding and profile validation, the evaluation dashboard, phone layout, and keyboard use.
The deterministic suite uses the deterministic **test-only** AI backends: it validates UI behaviour, **not** AI quality. The three real-AI UI tests
are labelled smoke tests with invariant assertions (in the recorded run: Apex produced a grounded, cited answer and needed no review; Meridian
needed a human review and was then submitted to its own service desk; retrieval stayed inside each tenant). They are not quality metrics.
The browser is the Microsoft Edge already installed on the machine; no browser was downloaded.

## Defects found by the tests and fixed
1. A ticket page did not refresh while the background worker was sending, so an approved ticket looked stuck (found by the Playwright run). Fixed with polling while the state is in flight; also applied to Workflow History.
2. Horizontal page overflow on phones (Documents, Evaluation, Overview): tables outside the scroll container and grid children without `min-width: 0`. Fixed and now asserted for six pages at 375 px.
3. Several Playwright selectors were wrong (case-insensitive text matches on `<option>` elements, form/label name collisions); these were test defects and are fixed.

## Screenshots
The engineering review captured the Meridian overview, onboarding, review controls, cited answers, submitted tickets, mobile layout, and evaluation dashboard against synthetic data. The captures are omitted from this snapshot.

## Outstanding limitations
- Accessibility was built in (landmarks, labels, focus management, `aria-sort`, live regions, keyboard-tested dialogs and skip link) and spot-checked by tests, but **no automated audit tool (such as axe) or screen-reader pass was run**.
- End-to-end tests ran in one browser (Edge). Routing is hash-based. The phone layout is tested for overflow, not for every interaction.
- Integration Health shows configuration and delivery results, deliberately not a live probe of external systems.
- The Evaluation Dashboard shows server-local committed artifacts (synthetic `apex-eval-v1`, Meridian smoke only); the 95% citation target is **NOT MET**; no Meridian benchmark exists.
- Roughly three in four incidents still need human review with the 1.5B model; this is an operational limitation the UI makes visible, not something it hides or reduces.
- Creating a tenant's first administrator still goes through the members API/onboarding script (the UI creates the tenant only).
- Per-process rate limits and the two Apex/Meridian execution paths remain as documented in the Phase 5 closure.
- CI has not run (nothing is pushed). The Vitest/Playwright fixtures use test-only constants; the e2e stack refuses to run with `EAOP_ENV=production`.
