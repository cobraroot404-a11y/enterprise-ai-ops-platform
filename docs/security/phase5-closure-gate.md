# Phase 5 closure gate

Final gate status: **PASS**
Closure commit: **9f6b667** (branch `feat/apex-vertical-slice`, on top of Phase 5 commit `6d9217d`)
Date: 2026-11-11. Nothing merged, pushed or published; no remote exists.

## Requirements checklist
| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Connector SSRF mitigation and regression tests | PASS | `app/connectors/egress.py`, `connectors/http.py`, migration 0006, `test_connector_egress.py` (79 tests), [connector-egress.md](connector-egress.md) |
| 2 | Apex behavior preserved; paths, tests and unification plan documented | PASS | `test_apex_compat.py` (4), `test_profile_engine.py` (28), [apex-meridian-execution-paths.md](../architecture/apex-meridian-execution-paths.md) |
| 3 | Human-review and external-release gates preserved (approval, submission, retry, worker) | PASS | `test_review_gate.py` (8, now including the retry path), `test_meridian.py`, smoke checks S5a, S5b, S6a |
| 4 | Meridian real-AI smoke evaluation, raw outputs preserved, labelled as smoke | PASS (17 of 17 functional checks) | `evaluation/smoke/meridian_smoke.py`, `evaluation/reports/phase5-meridian-smoke/` |
| 5 | Per-process rate-limit limitations documented | PASS | [rate-limiting-limitations.md](rate-limiting-limitations.md), README, tenant onboarding doc |
| 6 | Closure verification | PASS | table below |

## Security controls implemented (requirement 1)
Per-tenant, server-side origin allow-list; scheme, credential, port and URL-hygiene checks; rejection of alternative IP
encodings; IPv4 and IPv6 address policy (loopback, private, link-local, multicast, reserved, CGNAT, cloud metadata,
IPv4-mapped IPv6); single resolution with all answers validated and the connection pinned to the validated address (DNS
rebinding and TOCTOU); enforcement on every request including worker retries and enrichments; no redirects; credentials
only to the pinned origin; connect and read timeouts and a 1 MiB response cap; development-only mock origins limited to
loopback, per tenant, and refused under `EAOP_ENV=production`; a save-time check that is explicitly not the protection.
Acceptance criterion: the only tenant-reachable outbound path is `HttpConnector.request`, which authorizes before sending;
`grep` shows no other tenant-influenced `httpx` use (Ollama uses a fixed server setting).

Relevant sources: `backend/app/connectors/{egress,http,clients,enrichment}.py`, `backend/app/api/v1/core_routes.py`
(`create_connector`), `backend/app/workflows/worker.py`, `backend/migrations/versions/0006_connector_tenant_slug.py`,
`backend/tests/support.py` (test policy), `.env.example` (`EAOP_ENV`, `EGRESS_ALLOWLIST`, `EGRESS_DEV_MOCKS`).

## Actual results (commands run on this machine, deterministic backends unless stated)
| Check | Command | Result |
|---|---|---|
| Lint | `python -m ruff check backend mock-services workers scripts tests evaluation conftest.py` | clean |
| Full backend functional suite | `python -m pytest -q` | **265 passed, 0 failed, 13 skipped** (12 real-AI tests, 1 opt-in database-outage test) |
| SSRF negative and positive | `python -m pytest -q backend/tests/test_connector_egress.py` | 79 passed |
| Security regression (JWT, throttle, RLS, memberships, all-route authorization matrix, mutation proofs, identity tables, resource limits) | 7 files, see run | 69 passed |
| Review gate, AI safeguards, workflow, release blockers | `test_review_gate.py test_ai_safeguards.py test_workflow.py` | 36 passed |
| Apex and Meridian integration, Apex compatibility, profile engine, RAG/incident | `test_meridian.py test_apex_compat.py test_profile_engine.py test_rag_incidents.py` | 54 passed |
| Real Ollama + MiniLM integration (Apex and Meridian) | `RUN_REAL_AI=1 python -m pytest backend/tests/test_real_ai.py -q` | 12 passed |
| Meridian real-AI smoke | `python evaluation/smoke/meridian_smoke.py` | 17 of 17 checks (not a benchmark) |
| Frontend | `npm run typecheck`, `npm test`, `npm run build` | clean; 3 tests passed |
| Unchanged built-in AI modules | `git diff 44b1083 HEAD -- backend/app/ai/rules.py backend/app/ai/safeguards.py backend/app/ai/rag.py` | empty |
| Historical evaluation evidence | `git status --short evaluation/reports/phase3 evaluation/datasets` | clean |
Subset counts overlap with the full-suite count; they are listed to show each area explicitly. The disruptive database-outage
test (FI-10) was **not** re-run for this closure because nothing it exercises changed since its last passing run in the Phase 5
gate (`evaluation/reports/phase5-gate/`); it only ever targets this project's own PostgreSQL container.

## Outstanding limitations
- Egress protection is application-level; operators must maintain the allow-list and should add network egress controls.
- Login throttle and resource limits are per process (see [rate-limiting-limitations.md](rate-limiting-limitations.md)).
- About 75% of extracted incidents go to human review with the 1.5B model (operational workload, intentionally not relaxed).
- The model's category choice can change deterministic priority (observed in the smoke run: 2 of 5 reports); sample too small for a rate.
- Two execution paths (built-in Apex, profile-driven Meridian) remain, covered by tests; unification is planned separately.
- Meridian has only smoke evidence, no AI-quality benchmark; the 95% citation target remains NOT MET (Phase 3/4 evidence).
- CI has not run; nothing is pushed.
