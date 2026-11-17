# Technical walkthrough (10 to 15 minutes)

A script for presenting the platform using its **actual behaviour**. Customers are fictional; all external systems are local mocks. Everything shown can be reproduced with the commands given. Targets about 13 minutes.

**Before starting (not timed):** `python scripts/demo.py up` (disposable database; `down` afterwards), open the UI at http://127.0.0.1:5173, and keep `python scripts/demo.py smoke --rest --no-browser --backup` output from an earlier run (`evaluation/demo-runs/<run id>/report.md`) at hand.

| Time | Topic | What to show and say |
|---|---|---|
| 0:00 | Customer problem | Apex (plant maintenance) and Meridian (fleet service) are fictional; engineers lose time finding evidence and re-keying tickets. Show [customer discovery](../customer-discovery/README.md): "assumed, not interviewed" |
| 1:30 | Requirements | The 238-requirement register and its honest status counts ([progress tracker](../planning/progress-tracker.md)); the matrix [02](02-requirements-to-solution-matrix.md) maps each major requirement to a need, a component, a test, an acceptance criterion and evidence |
| 3:00 | Architecture | [Diagrams](../architecture/diagrams.md): modular monolith, worker, PostgreSQL with forced row-level security, local AI. Say what is not built: no cloud, no container images |
| 4:30 | Workflow automation (live, Apex) | Sign in as the engineer: ask a question and show the **citations** and an "insufficient evidence" answer; extract an incident; note numeric readings are **unverified** until a supervisor verifies; draft a ticket; sign in as the supervisor and approve; show the external ticket id and the audit trail |
| 7:00 | Second customer | Sign in as Meridian: same pages, different service-desk contract and priorities, no code change; show that Apex users see nothing of Meridian (404/empty) |
| 8:00 | Integrations | `POST /connectors/{id}/sync` for a REST or CSV source and a **signed webhook** delivery (see [integration specification](04-integration-specification.md)); show 202 means queued, then the job completing; replay of the same delivery id returns 409 |
| 9:30 | Security | Forced RLS even with application filters bypassed; roles and separation of duties; SSRF allow-list; webhook HMAC, window and replay ledger; secrets only as variable names |
| 10:30 | Failure recovery | Show an injected failure (the live report's retry of a 503 burst; `docs/reliability/fault-injection-results.md` for FI-01 to FI-10): retry with backoff, no duplicate tickets, deletion races. State that faults are **simulated** |
| 12:00 | Measured outcomes | Real numbers only: backend 747 passed, 18 skipped; root 130 passed; frontend 72 unit and 52 browser tests passed; the final live checkpoint passed for both tenants; AI quality **partly unmet** (citation correctness 89.8% held-out vs 95% target; grounded coverage 59.3%) |
| 13:00 | Deployment tradeoffs | [Deployment tradeoffs](../architecture/deployment-tradeoffs.md): local-first, cloud portability analysed but never deployed; known limits (per-process rate limits, REL-01) |

**Do not say:** that a customer used it, that it is production-ready, that a cloud deployment exists or that the container stack runs real AI, or that the evidence is independent.
