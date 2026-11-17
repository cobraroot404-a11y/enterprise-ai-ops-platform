# 6. Customer acceptance plan

For the two fictional customers. The criteria are the assumed success criteria in [customer discovery](../customer-discovery/README.md). Results below are from automated tests and live runs on a developer machine against local mocks, executed by the same engineer who built the system; they are **not** independent validation.

## Acceptance criteria, how they are checked, and where the evidence is
| Criterion | Check | Evidence |
|---|---|---|
| Cited, grounded answers; explicit refusal without evidence | Retrieval and citation tests; real-AI UAT scenarios | `tests/acceptance/test_uat_customer_a.py`, `evaluation/customer-acceptance/{deterministic,real}/uat-report.json`; Phase 8 reports in `docs/evaluation/` (quality targets partly unmet: see below) |
| Structured incident the human can accept or reject; numeric evidence trust | Extraction tests, human-verification tests, API and UI | `backend/tests` numeric-evidence suites, `docs/planning/batch5-report.md` |
| Approval gates, no self-approval, one ticket per approval, external id stored | Workflow transition and concurrency tests | UAT A/B tests, `tests/fault_injection` |
| Complete audit trail without content | Audit tests, live audit checks | live runs under `evaluation/demo-runs/` |
| Recovery from failing external systems without loss or duplicates | Fault injection FI-01 to FI-10 | `evaluation/failure-reports/phase7/fi-report.json`, `docs/reliability/fault-injection-results.md` |
| Zero cross-tenant visibility | RLS, namespace and retrieval isolation tests; live cross-tenant checks | `backend/tests` isolation suites; live runs |
| Document, REST, CSV and signed-webhook ingestion; deletion; reprocessing | Ingestion, lifecycle, connector and webhook tests; live checkpoints | `docs/planning/batch9-report.md` to `batch11b-report.md`; `evaluation/demo-runs/20261113-140424-3fb1/` |

## Procedure for an acceptance session
1. Run `python scripts/demo.py smoke --rest --no-browser --backup` (about 90 s; isolated database, dropped afterwards).
2. Read `evaluation/demo-runs/<run id>/report.md`: every check is listed with its detail; failed checks are shown, not hidden.
3. Run `python -m pytest backend/tests -q` and `python -m pytest tests -q`.
4. Walk the UI for each tenant (`python scripts/demo.py up`, then the UI at :5173) following [apex-demo-guide.md](apex-demo-guide.md) and [meridian-demo-guide.md](meridian-demo-guide.md).
5. Record deviations; the owner decides acceptance.

## Known unmet or partial items (disclosed)
Phase 8 AI-quality targets are not all met (citation correctness 89.8% held-out against a 95% target; grounded-answer coverage 59.3%; raw model structured validity 90% on the held-out split); the current numeric-safety deterministic PASS (V41-14.02) is accepted for scoped Gate C technical purposes with the frozen 63/64 FAIL retained in the [owner disposition](../planning/gate-c-owner-disposition.md); one intermittent API start-up stall (REL-01) is unexplained; rate limiting is per process; container images and cloud deployment do not exist. Details: [../planning/progress-tracker.md](../planning/progress-tracker.md).
