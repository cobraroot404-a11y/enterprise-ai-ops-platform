# The 27-step demonstration (specification Part 30)

One command runs the executable steps and prints all 27, marking each as automated, shown in the UI, or explained:

```bash
.venv/Scripts/python scripts/demo.py steps            # prints the 27 steps with the evidence of the last run
.venv/Scripts/python scripts/demo.py smoke --ingestion --rest --compare --backup   # executes the automated steps on an isolated database
```
Steps marked **explain** are presentations, not executable checks; they are not reported as passed tests.

| # | Step | How | Evidence or document |
|---|---|---|---|
| 1 | Start the platform | `demo.py up` (or `smoke`) | `evaluation/demo-runs/` |
| 2 | Authenticate | automated; UI login | demo smoke report |
| 3 | Onboard Apex | automated (seed) | demo smoke report |
| 4 | Configure integrations | automated; UI Data Sources | demo smoke report |
| 5 | Ingest equipment documents | automated; UI Document Library | demo smoke report |
| 6 | Ask a maintenance question | automated; UI AI Knowledge Assistant | demo smoke report |
| 7 | Inspect citations | automated (verbatim quote check); UI | `tests/acceptance/test_uat_customer_a.py` |
| 8 | Identify related incidents | automated | UAT-A |
| 9 | Generate a structured ticket | automated | UAT-A |
| 10 | Request approval | automated; UI | UAT-A |
| 11 | Approve the ticket (a different person) | automated; UI Approval Queue | UAT-A |
| 12 | Submit to the mock API | automated (worker) | UAT-A |
| 13 | Simulate an API outage | automated (failure injection on the mock) | `tests/fault_injection/` |
| 14 | Demonstrate recovery | automated | fault-injection report |
| 15 | Verify no duplicate ticket | automated (idempotency key) | fault-injection report |
| 16 | Display audit history | automated; UI Audit Logs | UAT-A |
| 17 | Onboard Meridian | automated (public API only) | demo smoke report |
| 18 | Configure custom mappings | automated | `onboarding/meridian.json` |
| 19 | Ingest fleet records | automated (REST, CSV, webhook) | demo smoke report |
| 20 | Generate and approve a fleet ticket | automated | UAT-B |
| 21 | Demonstrate tenant isolation | automated | demo negative checks, Phase 4 tests |
| 22 | Run customer acceptance tests | `pytest tests/acceptance` | `evaluation/customer-acceptance/` |
| 23 | Run fault-injection tests | `pytest tests/fault_injection` | `evaluation/failure-reports/phase7/` |
| 24 | Run evaluation benchmarks | recorded results shown; reruns need Ollama and up to an hour | `docs/evaluation/phase8-*-report.md` |
| 25 | Display verified results | README "Verified Engineering Results" | `README.md` |
| 26 | Explain cloud portability | **explain** | [cloud-portability.md](../architecture/cloud-portability.md) |
| 27 | Explain architecture tradeoffs | **explain** | [deployment-tradeoffs.md](../architecture/deployment-tradeoffs.md), [09-architecture-tradeoff-record.md](09-architecture-tradeoff-record.md) |

Limits: single author, mocks for every external system, deterministic AI backends unless Ollama is running, no independent reviewer has followed this script.
