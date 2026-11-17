# Forward-deployed engineering lifecycle: what demonstrates each capability

The specification (Part 1 and the final objective) lists the lifecycle capabilities the project must demonstrate, and Part 26 lists sixteen kinds of test. This page maps each to the artifact that demonstrates it and states its limit. `tests/test_capability_map.py` checks that every path exists. "Demonstrated" means a working artifact exists in this repository; it does not mean a real customer, a production system or an independent reviewer was involved. Both customers are fictional.

## Lifecycle capabilities
| # | Capability | Demonstrated by | Limit |
|---|---|---|---|
| 1 | Customer discovery and requirements engineering | `docs/customer-discovery/README.md`, `docs/traceability/v4.1-full-traceability-matrix.md` | fictional customers; no interviews took place |
| 2 | Enterprise software integration | `docs/integrations/README.md`, `backend/app/connectors/http.py`, `backend/app/ingestion/webhooks.py` | local mocks only |
| 3 | Backend and frontend development | `backend/app/main.py`, `frontend/src/App.tsx` | 13 pages, minimal styling |
| 4 | AI and retrieval-augmented generation | `backend/app/ai/rag.py`, `backend/app/retrieval/search.py`, `docs/evaluation/phase8-heldout-report.md` | quality targets not met on the held-out split |
| 5 | Multi-tenant security | `docs/security/README.md` | no independent security review; V41-14.02 partial; PROV-01 open |
| 6 | Human-in-the-loop workflow automation | `backend/app/workflows/ticket_service.py`, `frontend/src/pages/ApprovalsPage.tsx` | approvals by fictional users |
| 7 | Reliability and failure recovery | `tests/fault_injection/test_recovery_rate.py`, `evaluation/recovery/recovery-rate-report.json` | simulated faults against mocks; REL-01 open |
| 8 | Customer-specific deployment | `onboarding/meridian.json`, `docs/customer-onboarding/README.md` | second customer by configuration; local only |
| 9 | Troubleshooting and operational support | `docs/customer-delivery/07-troubleshooting-guide.md`, `docs/operations/local-runbook.md` | no support was actually provided to anyone |
| 10 | Reproducible testing | `scripts/clean_environment_check.py`, `docs/operations/ci-and-local-tests.md` | same machine; CI never executed; no independent reproduction |
| 11 | Business outcome measurement | `docs/performance/measured-performance.md`, `evaluation/comparison/protocol.md` | engineering measurements on synthetic tasks; no observed human baseline, so no productivity claim |
| 12 | Cloud deployment portability | `docs/architecture/cloud-portability.md`, `infrastructure/terraform/main.tf`, `infrastructure/kubernetes/eaop.yaml` | analysis and illustrative files; nothing deployed or schema-validated |
| 13 | Architecture tradeoff analysis | `docs/architecture/deployment-tradeoffs.md`, `docs/customer-delivery/09-architecture-tradeoff-record.md` | author's analysis |
| 14 | Customer acceptance and handover | `docs/customer-delivery/06-customer-acceptance-plan.md`, `docs/customer-delivery/08-operational-handover.md`, `docs/customer-acceptance/uat-results.md` | acceptance scenarios run by the author, not accepted by a customer |
| 15 | Clear technical communication | `README.md`, `docs/customer-delivery/technical-walkthrough.md`, `docs/architecture/diagrams.md` | the walkthrough has not been presented to anyone |

The final objective's sixteen abilities are the same list with "requirements engineering", "customer acceptance testing", "measurable engineering outcomes" and "operational handover" named separately; they map to rows 1, 14, 11 and 14.

## The sixteen kinds of test (Part 26)
| Kind | Example | Runs in |
|---|---|---|
| Unit | `tests/test_phase8_metrics.py`, `frontend/src/components/components.test.tsx` | pytest, Vitest |
| Integration | `backend/tests/test_rest_sync.py` | pytest with PostgreSQL and a local mock |
| API contract | `backend/tests/test_api_contract.py`, `backend/tests/test_api_response_schemas.py` | pytest |
| Database | `backend/tests/test_migration_0015_shared_state.py`, `backend/tests/test_concurrency_fairness.py` | pytest, disposable databases |
| Authentication | `backend/tests/test_jwt_and_throttle.py` | pytest |
| Authorization | `backend/tests/test_api_namespace_security.py` | pytest |
| Tenant isolation | `backend/tests/test_api_namespace_security.py`, `backend/tests/test_meridian.py` | pytest |
| RAG evaluation | `tests/test_phase8_scorer.py`, `backend/tests/test_real_ai.py` | pytest; the second needs Ollama (opt-in) |
| Workflow transition | `backend/tests/test_workflow.py` | pytest |
| Retry | `tests/fault_injection/test_recovery_rate.py` | pytest |
| Idempotency | `backend/tests/test_webhooks.py`, `backend/tests/test_ingestion_jobs.py` | pytest |
| Frontend | `frontend/src/pages/pages.test.tsx` | Vitest |
| End-to-end | `frontend/e2e/workflows.spec.ts` | Playwright against an isolated stack |
| Customer acceptance | `tests/acceptance/test_uat_customer_a.py`, `tests/acceptance/test_uat_customer_b.py` | pytest |
| Fault injection | `tests/fault_injection/test_fault_injection.py` | pytest (some scenarios opt-in) |
| Deployment smoke | `scripts/container_smoke.py`, `scripts/clean_environment_check.py` | Docker Compose, local; evidence under `evaluation/container-smoke/` |
