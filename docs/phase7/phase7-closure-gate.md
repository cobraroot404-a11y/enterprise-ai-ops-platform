# Phase 7 closure gate (Gate A of the Phase 8 instruction)

Executed 2026-11-11 on branch `feat/apex-vertical-slice` before any Phase 8 work. Environment: Python 3.10.0, Node 24.13.1, PostgreSQL 16.15 with pgvector 0.8.7,
Ollama 0.40.16 (`qwen2.5:1.5b`), Sentence Transformers 6.3.0 / torch 2.14.1+cpu with MiniLM `all-MiniLM-L6-v2` pinned to revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41` (`backend/app/core/config.py`). The Ollama model digest is read from the running server by the client
(`ollama_llm.py`) and is recorded in the Phase 3 manifests (`65ec06548149...`); it is re-captured in the Phase 8 baseline freeze.

| # | Check | Command / evidence | Result |
|---|---|---|---|
| 1 | Branch, working tree, history, remote | `git branch --show-current`; `git status`; `git log`; `git remote` | PASS: `feat/apex-vertical-slice`, clean tree, head `db3afc4`, Phase 7 at `d8a8f82`, no remote |
| 2 | Real-AI Playwright smoke (omitted in Phase 7) | `cd frontend && E2E_REAL_AI=1 npx playwright test --project=real-ai` | PASS: 3 of 3 (Apex, Meridian, real-embedding isolation) |
| 3 | FI-01..FI-10 evidence | `evaluation/failure-reports/phase7/fi-report.{json,md}` (committed) | PASS: 15 of 15 scenarios recorded (FI-01..10, FI-09b, REL-01..04); produced in Phase 7 with `RUN_DISRUPTIVE=1` |
| 4 | Apex and Meridian UAT evidence | `evaluation/customer-acceptance/{deterministic,real}/uat-report.{json,md}` (committed) | PASS: 15 of 15 in each mode |
| 5 | Traceability matrix | `docs/traceability/requirements-traceability-matrix.json`; `python -m pytest tests/test_traceability.py -q` | PASS: 83 requirements = 55 verified + 20 partially verified + 8 not implemented; consistency test passes |
| 6 | Historical reports preserved | `git diff b727887 HEAD --stat -- evaluation/reports/phase3 evaluation/reports/phase4-remeasure evaluation/failure-reports/phase4` | PASS: no differences |
| 7 | Ollama + MiniLM + database + application together | `RUN_REAL_AI=1 python -m pytest backend/tests/test_real_ai.py -q` | PASS: 12 passed |
| 8 | Security regressions | SSRF/egress, API namespace x role matrix, tenant isolation/RLS, identity tables, review gate, control mutations, JWT/throttle, environment guards, traceability | PASS: 164 passed, 0 failed |

Ollama was stopped after the run. Nothing was downloaded, pushed, merged or published.

**Gate A: PASS.** No unresolved critical security regression. Known limitations are unchanged from `docs/phase7/phase7-gate.md`.
