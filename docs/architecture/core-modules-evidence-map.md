# Core modules evidence map (spec Part 9, line 417)

Maps each of the 13 core modules to existing code, tests and stored evidence. It states what exists; it does not add compliance claims. Evidence is same-author. The architecture is a modular monolith with a background worker (`workers/run_worker.py`); see [system-architecture.md](system-architecture.md).

| # | Module | Code | Tests | Stored evidence / docs |
|---|---|---|---|---|
| 1 | Authentication | `backend/app/auth/`, `backend/app/core/security.py`, `backend/app/api/v1/core_routes.py` | `backend/tests/test_jwt_and_throttle.py`, `backend/tests/test_identity_security.py` | `docs/security/` |
| 2 | Tenant Management | `backend/app/api/v1/core_routes.py`, `backend/app/core/rbac.py` | `backend/tests/test_membership_rls.py`, `backend/tests/test_security.py` | `docs/operations/tenant-onboarding.md` |
| 3 | Customer Configuration | `backend/app/profile/`, `backend/app/api/v1/profile_routes.py` | `backend/tests/test_profile_engine.py` | `docs/operations/configurations.md` |
| 4 | Enterprise Connectors | `backend/app/connectors/`, `backend/app/ingestion/webhooks.py` | `backend/tests/test_rest_connector.py`, `backend/tests/test_csv_connector.py`, `backend/tests/test_webhooks.py` | `docs/architecture/rest-ingestion.md`, `docs/architecture/webhooks-and-csv.md` |
| 5 | Document Ingestion | `backend/app/ingestion/` | `backend/tests/test_ingestion_jobs.py`, `backend/tests/test_document_lifecycle.py` | `docs/architecture/ingestion-jobs.md`, `docs/architecture/document-lifecycle.md` |
| 6 | Retrieval Engine | `backend/app/retrieval/` | `backend/tests/test_embedding_profiles.py`, `backend/tests/test_rag_incidents.py` | `docs/architecture/system-architecture.md` |
| 7 | AI Inference | `backend/app/ai/` | `backend/tests/test_real_ai.py`, `backend/tests/test_ai_safeguards.py` | `evaluation/phase8/run_experiment.py`, `docs/operations/real-ai-setup-windows.md` |
| 8 | Incident Intelligence | `backend/app/services/incident_service.py`, `backend/app/ai/rules.py` | `backend/tests/test_rag_incidents.py`, `backend/tests/test_asset_identification.py` | `docs/architecture/phase2-apex-slice.md` |
| 9 | Workflow Orchestration | `backend/app/workflows/`, `workers/run_worker.py` | `backend/tests/test_workflow.py`, `backend/tests/test_review_gate.py` | `docs/architecture/apex-meridian-execution-paths.md` |
| 10 | Audit Logging | `backend/app/audit/service.py` | `backend/tests/test_deletion_exposure_audit.py`, `backend/tests/test_control_mutations.py` | `docs/security/` |
| 11 | Observability | `backend/app/observability/` | `backend/tests/test_observability.py`, `backend/tests/test_spans.py`, `backend/tests/test_durable_metrics.py` | `docs/operations/observability.md`, `evaluation/observability/README.md` |
| 12 | Evaluation | `backend/app/evaluation_registry.py`, `backend/app/api/v1/ops_routes.py`, `evaluation/phase8/` | `backend/tests/test_evaluation_registry.py`, `backend/tests/test_phase8_quality.py`, `tests/test_phase8_metrics.py` | `docs/performance/benchmark-reports-index.md`, `evaluation/reports/` |
| 13 | Customer Dashboard | `frontend/src/pages/OverviewPage.tsx`, `frontend/src/pages/EvaluationPage.tsx` | `frontend/src/pages/pages.test.tsx`, `frontend/e2e/demo-smoke.spec.ts` | `evaluation/ui-acceptance/` |

## Limits (what this map does not claim)
- Module 12: evaluation **runs** are executed by offline scripts under `evaluation/phase8/`, not started or managed through the API. The API exposes only a read-only registry (`GET /api/v1/evaluation/registry`) over recorded runs. L417 lists Evaluation as a module and does not specify run management; the register keeps this as a documented limit, not a hidden claim.
- Module 11: trace ids, W3C `traceparent` and span events exist; an OpenTelemetry SDK/exporter does not (optional, owner-gated, spec L815).
- Modules 5/6/7 results are same-author measurements; quality targets recorded as NOT MET in the benchmark index remain NOT MET.
