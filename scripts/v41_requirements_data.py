"""Requirement baseline extracted from the ORIGINAL V4.1 master specification (docs/specification/ORIGINAL_MASTER_SPECIFICATION_V4.1.txt).

Each entry is an atomic, checkable requirement (or a closely coupled group stated as one sentence/list in the specification) with the exact specification
line range it comes from. `scripts/generate_v41_reconciliation.py` extracts the source wording from those lines (so wording cannot drift), checks that every
referenced implementation, test and evidence path exists, and renders the five specification documents.

Status: V verified (implemented AND an automated test or reproducible check AND evidence), P partial, M missing, N not evaluable now.
Kind: M mandatory ("must", imperative list, or deliverable), O optional ("Optional", "where practical", "if available"), T proposed target (Part 21),
      X prohibition/process rule, D deliverable/definition-of-done item.
Class: C critical security or workflow safety | Q Phase 8 AI-quality limitation | I Phase 9 infrastructure and cloud portability |
       D Phase 10 documentation, release and handover | A separate approval required | - nothing outstanding.
Catalogue ids (R<part>.<n>) refer to the provisional 85-item catalogue (scripts/traceability_data.py); entries without one are newly discovered requirements.
"""

BT = "backend/tests/"
FE = "frontend/e2e/"
UAT = ["evaluation/customer-acceptance/deterministic/uat-report.json", "evaluation/customer-acceptance/real/uat-report.json"]
FI = ["evaluation/failure-reports/phase7/fi-report.json"]
HO = "docs/evaluation/phase8-heldout-report.md"
CAND = "docs/evaluation/phase8-candidate-report.md"
BASE = "docs/evaluation/phase8-baseline-report.md"
AUD = "docs/specification/v4.1-audit-check-results.json"
FIT = "tests/fault_injection/test_fault_injection.py"
UATA = "tests/acceptance/test_uat_customer_a.py"
UATB = "tests/acceptance/test_uat_customer_b.py"

E: list[dict] = []


def r(part, lines, title, kind, status, cat=(), impl=(), tests=(), evid=(), gap="", cls="-", phase="complete", accept=""):
    E.append({"part": part, "lines": lines, "title": title, "kind": kind, "status": status, "cat": list(cat), "impl": list(impl), "tests": list(tests),
              "evidence": list(evid), "gap": gap, "cls": cls, "phase": phase, "accept": accept or title})


# ---- Part 1 -------------------------------------------------------------------------------------------------------------------------------
r(1, (14, 15), "Design, implement, test, document and prepare for publication a complete enterprise AI operations platform", "M", "P", [], ["backend/app/main.py", "frontend/src/App.tsx"], [], [HO],
  "Built and tested locally; documentation, delivery, cloud and release deliverables are incomplete and nothing is published", "D", "Phase 9/10", "A working platform exists and every stage is documented")
r(1, (16, 32), "Demonstrate the complete FDE lifecycle (15 listed capabilities)", "M", "P", ["R9.1"], ["docs/architecture/phase5-meridian.md"], [], [HO],
  "Missing: customer discovery (1), cloud portability (12), customer acceptance handover documents (14), business outcome measurement beyond synthetic runs (11), clear technical communication documents (15)", "D", "Phase 9/10", "All 15 capabilities are demonstrated by working artifacts")
r(1, (34, 36), "One coherent product serving two fictional customers; functioning reproducible application, not scaffolding", "M", "V", ["R7.1", "R8.1"], ["backend/app/main.py", "onboarding/meridian.json"],
  [UATA + "::test_uat_a06_approved_ticket_submission", UATB + "::test_uat_b_meridian_uses_the_same_application_and_no_customer_code"], UAT, "", "-", "complete", "Both customer workflows pass end to end on one application")
r(1, (37, 37), "Do not fabricate features, test results, benchmarks, deployments, security guarantees, customer feedback or GitHub activity", "X", "P", [], ["scripts/generate_traceability.py", "evaluation/phase8/verify_baseline.py"],
  ["tests/test_traceability.py::test_matrix_references_resolve_and_verified_requires_evidence"], ["docs/evaluation/errata/apex-eval-v1-manifest-erratum.md", "evaluation/reports/phase8/INVALID-baseline-20261112T030653Z-token-expiry/INVALID.md"],
  "Reports are generated from artifacts and consistency-checked, failed runs are preserved, but README results are hand-maintained and compliance cannot be exhaustively tested", "D", "Phase 10", "No reported figure lacks a reproducible artifact")

# ---- Part 2 -------------------------------------------------------------------------------------------------------------------------------
r(2, (39, 53), "Repository ownership: sole owner Gautham; no organization repo, collaborators, bot collaborators, unnecessary write access, publication without authorization, or overwrite; verify the GitHub account before creation; prepare locally with publication instructions if unauthenticated", "X", "P", ["R33.1"], [],
  [], [AUD], "No remote or collaborator exists (verified by inspection); publication instructions are not written and the GitHub-account verification has not been needed yet", "D", "Phase 10", "No collaborators; publication instructions provided")
r(2, (54, 70), "Git authorship Gautham with the verified email, conventional commits, no inaccurate co-author trailers, no history rewriting or fabrication", "X", "V", ["R2.2"], [], [], [AUD],
  "", "-", "complete", "git log shows one author, zero trailer lines, conventional prefixes (29 commits at audit time)")
r(2, (71, 90), "No AI assistant branding, promotional watermarks or generated-by promotional footers anywhere", "X", "V", ["R2.2"], [], [], [AUD],
  "Matches found are technical ('Generated by <script>' provenance lines, a .gitignore entry, a CSS cursor property), none promotional", "-", "complete", "Repository search finds no promotional attribution")
r(2, (91, 109), "Core platform operates without mandatory paid software, APIs, subscriptions or hosting; do not silently activate paid services; document hardware, electricity, storage and bandwidth separately", "M", "P", ["R2.1"], ["docker-compose.yml", "docs/operations/real-ai-setup-windows.md"],
  [BT + "test_real_ai.py"], [HO], "No automated dependency/cost check; hardware and storage documented, electricity and bandwidth requirements not documented", "D", "Phase 10", "Local operation with free software only; separate resource documentation")

# ---- Part 3 -------------------------------------------------------------------------------------------------------------------------------
r(3, (111, 208), "Root-level LICENSE copied exactly from the specification text (not an open-source license)", "M", "V", ["R3.1"], ["LICENSE"], [], [AUD],
  "The proposed license has not been legally reviewed (stated in the specification itself)", "-", "complete", "LICENSE text identical to specification lines 115-207")
r(3, (210, 212), "THIRD_PARTY_NOTICES.md preserving third-party license requirements; audit dependencies, models, datasets, container images and assets", "M", "P", [], ["THIRD_PARTY_NOTICES.md"], [], [],
  "Working inventory only; licenses are marked 'to verify' and the full audit is deferred", "D", "Phase 10", "Complete audited notices file")

# ---- Part 4 -------------------------------------------------------------------------------------------------------------------------------
r(4, (215, 217), "Priority 0: two fully functioning end-to-end customer scenarios", "M", "V", ["R7.1", "R8.1"], ["frontend/src/pages/IncidentsPage.tsx"], [FE + "workflows.spec.ts"], UAT, "", "-", "complete", "Two end-to-end scenarios work")
r(4, (218, 229), "Priority 1: authentication, authorization, tenant isolation, human approval, validated inputs, transactional state, idempotency, auditability", "M", "V", ["R16.1", "R16.2", "R15.1", "R16.5"],
  ["backend/app/core/rbac.py", "backend/app/workflows/state_machine.py"], [BT + "test_api_namespace_security.py", BT + "test_control_mutations.py", BT + "test_membership_rls.py"], FI, "", "-", "complete", "All eight controls implemented and tested")
r(4, (230, 239), "Priority 2: retries, timeouts, recovery, fault injection, error classification, duplicate prevention, observability", "M", "P", ["R15.4", "R11.2", "R22.2"], ["backend/app/workflows/worker.py", "backend/app/observability/metrics.py"],
  [FIT], FI, "Observability is partial (no trace ids, process-scoped metrics)", "D", "Phase 10", "All seven implemented")
r(4, (241, 249), "Priority 3: automated tests, acceptance tests, retrieval evaluation, workflow benchmarks, failure recovery reports, reproducible results", "M", "P", ["R21.1", "R21.2"], ["evaluation/phase8/run_experiment.py"],
  ["tests/test_phase8_metrics.py"], [HO], "Retrieval and grounding evaluations exist but several quality targets are NOT MET; workflow benchmarks are partial; no recovery-rate computation", "Q", "Phase 8", "Measured evidence for all six")
r(4, (251, 260), "Priority 4: customer discovery, requirements traceability, onboarding, deployment scripts, runbooks, troubleshooting, technical handover", "M", "P", ["R6.1", "R6.2", "R10.1"], ["docs/operations/tenant-onboarding.md", "scripts/onboard_tenant.py"], [], [],
  "Onboarding and traceability exist; discovery, deployment scripts for containers, runbooks, troubleshooting and handover are missing", "D", "Phase 10", "All seven delivered")
r(4, (262, 268), 'Priority 5: cloud-ready architecture, Terraform/OpenTofu validation, deployment tradeoff documentation, optional Kubernetes examples', 'M', 'P', ['R24.1'], [], [], ['docs/specification/v4.1-audit-check-results.json', 'infrastructure/terraform/README.md', 'infrastructure/terraform/main.tf', 'infrastructure/terraform/variables.tf', 'infrastructure/terraform/outputs.tf', 'infrastructure/terraform/versions.tf', 'docs/architecture/cloud-portability.md', 'docs/architecture/deployment-tradeoffs.md'],
  'Cloud-readiness is documented and Terraform examples exist, but nothing was validated or deployed', 'I', 'Phase 9/10', 'Portability artifacts present and validated')
r(4, (270, 270), "Do not sacrifice working core functionality to add optional technologies", "X", "N", [], [], [], [], "A principle with no test; core was prioritised in the delivery order", "-", "complete", "")

# ---- Part 5 -------------------------------------------------------------------------------------------------------------------------------
r(5, (273, 285), "Backend stack Python, FastAPI, Pydantic, SQLAlchemy, Alembic; PostgreSQL with pgvector", "M", "V", ["R5.1"], ["backend/app/main.py", "backend/migrations/versions/0001_initial_schema.py"], [BT + "test_smoke_and_ingestion.py"], [HO], "", "-", "complete", "Preferred stack in use")
r(5, (286, 296), "AI stack Ollama, Sentence Transformers, locally runnable LLM; frontend React, TypeScript, Vite", "M", "V", ["R5.1", "R13.6"], ["backend/app/ai/ollama_llm.py", "backend/app/ai/embeddings.py", "frontend/src/App.tsx"], [BT + "test_real_ai.py"], [HO], "", "-", "complete", "Preferred stack in use")
r(5, (298, 301), "Workflow: PostgreSQL-backed state machine and background workers", "M", "V", ["R9.1"], ["backend/app/workflows/state_machine.py", "backend/app/workflows/worker.py"], [BT + "test_workflow.py"], FI, "", "-", "complete", "State machine and worker operate")
r(5, (303, 305), "Infrastructure: Docker Compose", "M", "P", ["R23.1"], ["docker-compose.yml", "docker-compose.app.yml"], [], [AUD, "evaluation/container-smoke/20261113-145441/report.md"], "Batch 12: docker-compose.app.yml runs the whole stack in containers and was smoke-tested twice (deterministic AI backends only)", "I", "Phase 9/10", "Compose runs the stack")
r(5, (307, 311), "Testing: Pytest, Vitest, Playwright", "M", "V", ["R26.1"], ["frontend/playwright.config.ts"], ["frontend/src/pages/pages.test.tsx", FE + "workflows.spec.ts", BT + "test_workflow.py"], ["docs/evaluation/phase8-heldout-report.md"], "", "-", "complete", "All three frameworks used")
r(5, (313, 317), "Observability: structured JSON logging, OpenTelemetry, optional Prometheus/Grafana", "M", "P", ["R22.1", "R22.3"], ["backend/app/observability/logging.py"], [BT + "test_observability.py"], ["evaluation/observability/README.md"], "OpenTelemetry (and the optional stack) is not implemented", "D", "Phase 9/10", "JSON logging plus OpenTelemetry")
r(5, (319, 321), "CI/CD: GitHub Actions within free allowances", "M", "P", ["R27.1"], [".github/workflows/ci.yml"], [], [], "Workflow exists with backend and frontend jobs but has never run (no remote)", "A", "Phase 10 / approval", "CI runs and passes")
r(5, (323, 325), 'Infrastructure as Code: Terraform or OpenTofu', 'M', 'P', ['R24.1'], [], [], ['docs/specification/v4.1-audit-check-results.json', 'infrastructure/terraform/README.md', 'infrastructure/terraform/main.tf', 'infrastructure/terraform/variables.tf', 'infrastructure/terraform/outputs.tf', 'infrastructure/terraform/versions.tf'],
  'See V41-24.02', 'I', 'Phase 9/10', 'IaC present and validated')
r(5, (327, 329), "Support CPU-only inference; inspect hardware before choosing the local model; no hardware purchase", "M", "V", ["R5.2"], ["scripts/capture_hardware.py", "scripts/ollama_ctl.py"], ["tests/test_hardware_capture.py"], ["docs/evaluation/phase3-method.md"], "", "-", "complete", "CPU-only model chosen after inspection")

# ---- Part 6 -------------------------------------------------------------------------------------------------------------------------------
r(6, (331, 349), 'docs/customer-discovery/ with business background, workflow, pain points, stakeholders, systems, data sources, security and deployment constraints, success criteria, assumptions, open questions; fictional assumptions labelled', 'M', 'V', ['R6.1'], [], [], ['docs/specification/v4.1-audit-check-results.json', 'docs/customer-discovery/README.md', 'docs/customer-discovery/apex-industrial.md', 'docs/customer-discovery/meridian-fleet.md'],
  'Written (Batch 12 documentation package). Both customers are fictional and every statement is labelled an assumption; no real interviews are claimed. Same-author documents', '-', 'complete', 'All eleven sections written and labelled fictional')
r(6, (350, 358), "Requirements-to-solution traceability matrix mapping every major requirement to need, implementation, component/API, test, acceptance criterion, evidence", "M", "P", ["R6.2"], ["scripts/generate_traceability.py", "scripts/traceability_data.py"], ["tests/test_traceability.py"], ["docs/traceability/requirements-traceability-matrix.md"],
  "The matrix is provisional (85 catalogue items vs the reconciliation baseline) and has no 'customer need' column", "D", "Phase 10", "Every original requirement mapped with all six elements")

# ---- Part 7 and 8 -------------------------------------------------------------------------------------------------------------------------
r(7, (362, 371), "Apex data sources: manuals, inspection reports, maintenance CSVs, incident histories, mock inventory API, mock maintenance ticket API", "M", "V", ["R7.1"], ["sample-data/customer-a", "mock-services/inventory", "mock-services/ticketing"], [UATA + "::test_uat_a01_document_ingestion"], UAT, "", "-", "complete", "All six sources present")
r(7, (373, 390), "Apex 14-step workflow: report vibration, identify equipment, retrieve manual passages, find history, grounded explanation, citations, structured issue, ticket draft, supervisor approval, approve, submit to mock API, store external id, audit trail, update metrics", "M", "V", ["R7.1"],
  ["backend/app/api/v1/domain_routes.py", "backend/app/workflows/ticket_service.py"], [UATA + "::test_uat_a06_approved_ticket_submission", "tests/acceptance/test_end_to_end_reliability.py::test_apex_end_to_end_reliability", FE + "workflows.spec.ts"], UAT, "Real-AI runs hold a large share of incidents for human review", "-", "complete", "All 14 steps demonstrated")
r(8, (393, 399), "Meridian data sources: vehicle inspection CSVs, service manuals, fleet maintenance records, mock fleet API, mock ticketing API", "M", "V", ["R8.1"], ["sample-data/customer-b", "mock-services/servicedesk", "mock-services/fleet"], [UATB + "::test_uat_b02_customer_specific_schema_mapping"], UAT, "", "-", "complete", "All five sources present")
r(8, (401, 413), "Meridian 11-step workflow: onboard as separate tenant, field mappings, ingest inspection records, identify issue, retrieve documentation, structured incident, ticket draft, approval, submit, record result, demonstrate tenant isolation", "M", "V", ["R8.1"],
  ["onboarding/meridian.json", "scripts/onboard_tenant.py"], [UATB + "::test_uat_b01_second_tenant_onboarding", UATB + "::test_uat_b06_cross_tenant_access_denied", "tests/acceptance/test_end_to_end_reliability.py::test_meridian_end_to_end_reliability"], UAT,
  "Meridian category extraction and multi-hop answers are weak in the held-out evaluation (quality, not workflow)", "Q", "Phase 8", "All 11 steps demonstrated")
r(8, (415, 415), "The same core platform supports both customers without code rewrites", "M", "V", ["R8.1", "R10.1"], ["backend/app/profile/engine.py"], [UATB + "::test_uat_b_meridian_uses_the_same_application_and_no_customer_code"], UAT,
  "Apex and Meridian still use two execution paths (documented technical debt)", "-", "complete", "No customer-specific code in shared services")

# ---- Part 9 and 10 ------------------------------------------------------------------------------------------------------------------------
r(9, (417, 433), "Modular monolith with background workers and the 13 listed core modules", "M", "P", ["R9.1", "R9.2"], ["backend/app", "workers/run_worker.py"], [BT + "test_ops_routes.py"], [AUD],
  "Evaluation exists as scripts plus a read-only dashboard, not a managed module; observability module partial", "D", "Phase 10", "All 13 modules present")
r(9, (434, 437), "PostgreSQL as authoritative workflow state; pgvector for retrieval; transactional outbox; avoid unnecessary microservices", "M", "V", ["R9.1"], ["backend/app/workflows/worker.py", "backend/migrations/versions/0001_initial_schema.py"], [BT + "test_workflow.py"], FI, "", "-", "complete", "Four design rules satisfied")
r(10, (439, 449), "Onboarding: tenant creation, membership, roles, data source registration, connector configuration, schema mapping, workflow policies, configuration validation, health checks", "M", "V", ["R10.1", "R10.2", "R10.3", "R10.4"],
  ["scripts/onboard_tenant.py", "backend/app/api/v1/profile_routes.py", "backend/app/api/v1/ops_routes.py"], [UATB + "::test_uat_b01_second_tenant_onboarding", BT + "test_profile_engine.py", BT + "test_membership_rls.py"], UAT, "", "-", "complete", "All nine onboarding capabilities work")
r(10, (451, 451), "A new customer is configurable without modifying the core application", "M", "V", ["R10.1"], ["backend/app/profile/service.py"], [UATB + "::test_uat_b_meridian_uses_the_same_application_and_no_customer_code", BT + "test_meridian.py"], UAT, "", "-", "complete", "Second tenant onboarded by configuration only")

# ---- Part 11 ------------------------------------------------------------------------------------------------------------------------------
r(11, (453, 460), "Reusable connectors for mock CRM, inventory, ticketing, CSV, REST APIs and webhooks", "M", "V", ["R11.1", "R11.4"], ["backend/app/connectors/clients.py", "backend/app/connectors/rest_records.py", "backend/app/ingestion/webhooks.py", "mock-services/crm", "mock-services/records"], [BT + "test_meridian.py", BT + "test_rest_connector.py", BT + "test_csv_connector.py", BT + "test_webhooks.py", BT + "test_rest_sync.py"], UAT + ["docs/planning/batch11a-report.md", "docs/planning/batch11b-report.md", "docs/architecture/rest-ingestion.md", "docs/architecture/webhooks-and-csv.md", "evaluation/demo-runs/20261113-140424-3fb1/report.json"],
  "VERIFIED (assessment of Batch 11B, recorded for owner review): the mock CRM, inventory and ticketing connectors (earlier batches), the REST records connector (11A), the CSV connector and the signed inbound webhook endpoint (11B) all work against local mocks and live checkpoints. Limits: the webhook is an inbound endpoint rather than an outbound client; all external systems are local mocks; same-author evidence", "-", "complete", "Six connector types work")
r(11, (462, 473), "Connector capabilities: authentication, pagination, rate limiting, timeouts, retries, exponential backoff, schema validation, error classification, idempotency, health checks", "M", "P", ["R11.2", "R11.3", "R11.4"],
  ["backend/app/connectors/http.py", "backend/app/connectors/rest_records.py", "backend/app/connectors/ratelimit.py", "backend/app/ingestion/webhooks.py", "backend/app/workflows/worker.py", "backend/app/api/v1/ops_routes.py"], [BT + "test_connector_egress.py", BT + "test_rest_connector.py", BT + "test_csv_connector.py", BT + "test_rest_sync.py", BT + "test_webhooks.py", FIT + "::test_fi01_http_503_outage", BT + "test_observability.py::test_connector_failures_retries_and_denials_are_classified"], FI + ["docs/planning/batch11a-report.md", "docs/planning/batch11b-report.md", "docs/architecture/rest-ingestion.md", "docs/architecture/webhooks-and-csv.md", "evaluation/demo-runs/20261113-140424-3fb1/report.json"],
  "Implemented and tested for the REST records, CSV and webhook connectors: HMAC and API-key authentication, pagination (cursor, offset, page), connector-scoped rate limiting with Retry-After, timeouts, bounded retries with exponential backoff, schema validation, fixed-code error classification, idempotency (content hash, delivery ledger) and an opt-in live health probe. Kept PARTIAL pending owner review because: the rate limiter is process-local (V41-16.04 stays Partial) and pagination, rate limiting and the live probe are not applied to the older ticketing, inventory, CRM and fleet clients (whose APIs do not paginate); webhook health is configuration-only (an inbound endpoint has no upstream to probe)", "A", "owner review", "All ten capabilities implemented and tested")
r(11, (475, 475), "Mock APIs support configurable failure responses", "M", "V", ["R11.1"], ["mock-services/ticketing/ticketing_app.py", "mock-services/servicedesk/servicedesk_app.py"], [FIT + "::test_fi02_http_429_rate_limiting"], FI, "", "-", "complete", "503/429/timeout/malformed/lost-response injectable")

# ---- Part 12 ------------------------------------------------------------------------------------------------------------------------------
r(12, (477, 483), "Support PDF, CSV, JSON, REST API records and webhook payloads", "M", "V", ["R12.1"], ["backend/app/ingestion/parsers.py", "backend/app/ingestion/sync.py", "backend/app/ingestion/webhooks.py", "backend/app/connectors/rest_records.py", "backend/migrations/versions/0012_rest_sync.py", "backend/migrations/versions/0013_webhooks_and_csv.py"], [BT + "test_smoke_and_ingestion.py", BT + "test_rest_sync.py", BT + "test_rest_connector.py", BT + "test_csv_connector.py", BT + "test_webhooks.py", BT + "test_migration_0012_rest_sync.py", BT + "test_migration_0013_webhooks_and_csv.py"], UAT + ["docs/planning/batch11a-report.md", "docs/planning/batch11b-report.md", "docs/architecture/rest-ingestion.md", "docs/architecture/webhooks-and-csv.md", "evaluation/demo-runs/20261113-140424-3fb1/report.json"],
  "VERIFIED (assessment of Batch 11B, recorded for owner review) for the documented local scope: PDF, CSV (uploads and the CSV connector), JSON, REST API records (under the owner-approved interpretation: pulling structured records from an authorised REST API into the tenant ingestion pipeline) and signed webhook payloads are each ingested through the real pipeline with provenance, idempotency and tombstones, demonstrated live on both tenants. Limits: basic UI only (Data Sources and Integration Health pages, Batch 12); the webhook receiver is not exposed publicly and has per-process rate limits; same-author evidence; the REST reading is an interpretation of a bare list item", "-", "complete", "Five source types ingested")
r(12, (485, 494), "Parsing, normalization, validation, metadata extraction, content hashing, duplicate detection, version tracking, idempotent ingestion", "M", "V", ["R12.1", "R12.2"], ["backend/app/ingestion/service.py"], [FIT + "::test_fi09_duplicate_ingestion", FIT + "::test_fi09b_forced_ingestion_race", BT + "test_resource_limits.py"], FI, "", "-", "complete", "Eight ingestion properties hold")
r(12, (495, 495), "Retry handling for ingestion", "M", "V", ["R12.5"], ["backend/app/ingestion/jobs.py", "backend/app/ingestion/sources.py", "backend/app/ingestion/service.py", "backend/migrations/versions/0010_ingestion_jobs.py", "backend/migrations/versions/0011_document_sources.py", "backend/app/workflows/worker.py", "backend/app/api/v1/domain_routes.py"], [BT + "test_ingestion_jobs.py", BT + "test_source_ingestion.py", BT + "test_document_sources.py", BT + "test_migration_0010_ingestion_jobs.py", BT + "test_migration_0011_document_sources.py", BT + "test_deletion_exposure_audit.py", BT + "test_api_error_contract.py", BT + "test_api_namespace_security.py", FIT + "::test_fi09_duplicate_ingestion"], ["docs/planning/batch9-report.md", "docs/planning/batch10-report.md", "docs/architecture/ingestion-jobs.md", "evaluation/demo-runs/20261113-075909-0569/report.json", "backend/tests/snapshots/openapi_contract.json"],
  "VERIFIED by owner decision (2026-11-13) for the documented local scope, after a check that the original specification attaches no further acceptance criteria to this line. Failed initial ingestion is recorded as a durable job and retried with bounded exponential backoff from the retained original; exhausted jobs can be re-queued. Limitation: originals kept for jobs that exhausted their retries have no automatic expiry; the failure modes exercised live were simulated injections, not real outages; same-author evidence", "-", "complete", "Failed ingestions are retried safely")
r(12, (496, 496), "Reprocessing", "M", "V", ["R12.4"], ["backend/app/ingestion/jobs.py", "backend/app/ingestion/sources.py", "backend/app/ingestion/service.py", "backend/migrations/versions/0010_ingestion_jobs.py", "backend/migrations/versions/0011_document_sources.py", "backend/app/workflows/worker.py", "backend/app/api/v1/domain_routes.py"] + ["backend/app/retrieval/reindex.py"], [BT + "test_ingestion_jobs.py", BT + "test_source_ingestion.py", BT + "test_document_sources.py", BT + "test_migration_0010_ingestion_jobs.py", BT + "test_migration_0011_document_sources.py", BT + "test_deletion_exposure_audit.py", BT + "test_api_error_contract.py", BT + "test_api_namespace_security.py", FIT + "::test_fi09_duplicate_ingestion"], ["docs/planning/batch9-report.md", "docs/planning/batch10-report.md", "docs/architecture/ingestion-jobs.md", "evaluation/demo-runs/20261113-075909-0569/report.json", "backend/tests/snapshots/openapi_contract.json"],
  "VERIFIED by owner decision (2026-11-13) for the documented local scope (no further acceptance criteria exist in the specification text). Genuine source-based reprocessing (checksum-verified original, supported parser re-run, new generation, atomic activation, previous generation kept until replacement succeeds) applies to documents with retained originals; documents uploaded before Batch 10 return the defined error 409 source_not_retained (the separate reindex tool still re-embeds their chunks). Limitation: old generations occupy storage until deletion; same-author evidence", "-", "complete", "Documents can be reprocessed")
r(12, (497, 497), "Deletion", "M", "V", ["R12.5"], ["backend/app/ingestion/lifecycle.py", "backend/app/ingestion/sources.py", "backend/migrations/versions/0009_document_lifecycle.py", "backend/app/api/v1/domain_routes.py", "backend/app/workflows/worker.py"],
  [BT + "test_document_lifecycle.py", BT + "test_migration_0009_document_lifecycle.py", BT + "test_source_ingestion.py", BT + "test_deletion_exposure_audit.py", BT + "test_api_error_contract.py", BT + "test_api_namespace_security.py"],
  ["docs/planning/batch8-report.md", "docs/planning/batch10-report.md", "docs/architecture/document-lifecycle.md", "backend/tests/snapshots/openapi_contract.json"],
  "VERIFIED by owner decision (2026-11-13) for the documented local scope (no further acceptance criteria exist in the specification text). Audited two-stage deletion: DELETE /api/v1/documents/{id} (tenant administrator or supervisor) removes application access at once (listings, direct access, search, citations, counts), cancels active ingestion jobs, and a worker cleanup removes chunks, embeddings, versions, retained original files and job payloads and verifies none remain. It does NOT guarantee erasure from historical backups, database pages awaiting VACUUM or external systems (copies already sent to tickets or other systems); file name and SHA-256 remain in audit events, job idempotency keys and the document tombstone (exposure register EXP-01 to EXP-04); no UI control; same-author evidence", "-", "complete", "Documents can be deleted with audit")
r(12, (498, 498), "Reindexing", "M", "V", ["R12.4"], ["scripts/reindex_embeddings.py", "backend/app/retrieval/reindex.py"], [BT + "test_embedding_profiles.py", BT + "test_real_ai.py::test_reindex_deterministic_tenant_to_minilm"], ["evaluation/reports/phase3/reindex-apex-industrial.json"], "", "-", "complete", "Atomic reindex with verification")
r(12, (500, 500), "Preserve source provenance including page numbers and record identifiers", "M", "V", ["R12.3"], ["backend/app/ingestion/parsers.py", "backend/app/retrieval/search.py"], [UATA + "::test_uat_a01_document_ingestion"], UAT, "", "-", "complete", "Every passage carries page or record id")

# ---- Part 13 ------------------------------------------------------------------------------------------------------------------------------
r(13, (502, 509), "Local inference with Ollama and Sentence Transformers; chunking, embeddings, vector index, PostgreSQL full-text search, hybrid retrieval", "M", "V", ["R13.1", "R13.6"], ["backend/app/retrieval/search.py", "backend/app/ai/ollama_llm.py"], [BT + "test_smoke_and_ingestion.py", BT + "test_real_ai.py"], [HO, "evaluation/reports/phase3/SUMMARY.md"],
  "Hybrid retrieval was not shown to beat its components; identifier handling (an opt-in switch) is what improved retrieval", "-", "complete", "Pipeline stages 1-5 implemented")
r(13, (510, 510), "Tenant-aware filtering of retrieval", "M", "V", ["R13.1", "R16.1"], ["backend/app/retrieval/search.py", "backend/migrations/versions/0001_initial_schema.py"], [BT + "test_security.py", FIT + "::test_fi05_unauthorized_cross_tenant_access"], FI, "", "-", "complete", "Zero foreign passages retrieved")
r(13, (511, 511), "Optional reranking", "O", "P", ["R13.5"], ["backend/app/retrieval/search.py"], [], ["evaluation/reports/phase8/exp-RETR-SWEEP-20261112T054053Z/retrieval_scores.json"], "A feature reranker exists only as an experimental switch and was not adopted; no neural reranker (no weights approved)", "A", "separate approval", "Optional; none required")
r(13, (512, 514), "Context assembly, local LLM inference, evidence-grounded answers", "M", "P", ["R13.2"], ["backend/app/ai/rag.py"], [BT + "test_rag_incidents.py", BT + "test_real_ai.py"], [HO, BASE],
  "Grounded-answer coverage 59.3% (held-out) against the later 75% target; the original specification states no coverage target", "Q", "Phase 8", "Answers grounded in retrieved evidence")
r(13, (515, 516), "Citation generation and citation verification", "M", "P", ["R13.2"], ["backend/app/ai/rag.py", "backend/app/ai/safeguards.py"], [BT + "test_ai_safeguards.py"], [HO],
  "100% id validity, tenant ownership and verbatim quotes, but citation correctness against labelled evidence is 89.8% (original target 95%: NOT MET)", "Q", "Phase 8", "Every citation verified and correct")
r(13, (517, 517), "Insufficient-evidence handling", "M", "P", ["R13.3"], ["backend/app/ai/rag.py"], [UATA + "::test_uat_a02_evidence_grounded_retrieval"], [HO],
  "Held-out correct abstention 94.1% baseline (16/17); development weaknesses (sibling-model answers) remain in the default configuration", "Q", "Phase 8", "Unsupported questions refused")
r(13, (519, 519), "Never fabricate citations", "X", "V", ["R13.2"], ["backend/app/ai/rag.py"], [BT + "test_ai_safeguards.py::test_citation_sources_must_be_current_and_tenant_owned"], [HO], "", "-", "complete", "Citation id validity and verbatim quote correctness 100% in all evaluations")
r(13, (520, 520), "Treat retrieved documents as untrusted input", "X", "V", ["R13.4"], ["backend/app/ai/safety.py"], [FIT + "::test_fi08_prompt_injection"], FI, "", "-", "complete", "Injected passages quarantined")
r(13, (521, 521), "Model-generated text cannot authorize external business actions", "X", "V", ["R13.4", "R15.1"], ["backend/app/workflows/ticket_service.py"], [UATA + "::test_uat_a05_unapproved_submission_blocked", BT + "test_review_gate.py"], UAT, "", "-", "complete", "No action reachable from model output without human approval")

# ---- Part 14 ------------------------------------------------------------------------------------------------------------------------------
r(14, (522, 535), "Validated Pydantic incident schema with tenant id, asset id, category, symptoms, related incidents, suggested priority, citations, recommended action, review status", "M", "V", ["R14.1"], ["backend/app/schemas/incident.py"], [UATA + "::test_uat_a04_structured_ticket_generation", BT + "test_rag_incidents.py"], UAT, "", "-", "complete", "Nine fields validated")
r(14, (536, 536), "Validate model output", "M", "V", ["R14.1", "R14.5"], ["backend/app/services/incident_service.py", "backend/app/ai/measurements.py"], ["tests/fault_injection/test_additional_reliability.py::test_rel03_invalid_structured_ai_output",
  "backend/tests/test_numeric_safety.py", "backend/tests/test_numeric_evidence.py", "backend/tests/test_numeric_structural_v6.py", "backend/tests/test_numeric_boundary_v7.py", "backend/tests/test_measurement_trust_v8.py", "backend/tests/test_provenance_closure_v8.py", "backend/tests/test_safety_acceptance_v8.py", "frontend/src/pages/measurements.test.tsx", "frontend/e2e/measurement-verification.spec.ts"], FI + ["docs/evaluation/numeric-safety-remediation.md", "docs/evaluation/numeric-safety-hardening-v5.md", "docs/evaluation/numeric-safety-hardening-v6.md", "docs/evaluation/numeric-safety-hardening-v7.md", "docs/evaluation/numeric-safety-architecture-v8.md", "docs/evaluation/numeric-safety-provenance-closure-v8.md", "evaluation/reports/safety/final-v7.json", "evaluation/reports/safety/final-v8.json", "docs/planning/batch5-report.md"],
  "Architecture changed (2026-11-12, V8): free-text and LLM-proposed numbers are UNVERIFIED candidates (class A) and never enter automated numeric priority; only a signed simulation-fixture observation (class F, labelled SIMULATED) or an observation approved through the human-verification workflow (class D; authorised reviewer, separation of duties, stale/duplicate-safe, audited) is eligible; authenticated submissions (class C) wait for a human; class E (authenticated sensor) is NOT implemented. Every priority decision is audited. The frozen safety-v8 confirmation (recorded as FAILED and kept unchanged) met every safety gate except complete priority-decision provenance (63/64, SAF8-A-040: a human-verified free-text candidate had no provenance object). A targeted closure (2026-11-12) now gives every numeric candidate a server-built provenance envelope (tenant, incident, observation id, source type, source document, span/offsets or an explicit unavailable-with-reason, origin, trust class, original status; it documents origin and never establishes truth), preserves it unchanged at approval with a separate verification block and audit-event link, and rejects client or LLM supplied provenance; verified by targeted and full regression tests only. The pinned candidate subsequently passed 150 deterministic tests and 18 criteria. The frozen failure remains historical evidence. Verified for the pinned local Gate C candidate. Gautham accepted the current deterministic evidence for Gate C technical purposes with the frozen shortfall retained. This acceptance does not establish production readiness or independent-human review. Behaviour change: numeric priority from a number in a free-text report is no longer automatic; no original V4.1 requirement mandates it, so no formal deviation is proposed. Batch 5 (2026-11-13) added frontend support only (structured observation entry while analysing a report; human verify or reject in the Incident Explorer; server-returned priority displayed), covered by Vitest and a live-stack Playwright test; no backend, policy or frozen-evidence change and no status change. Same-author evidence; see docs/evaluation/numeric-safety-architecture-v8.md and docs/evaluation/numeric-safety-provenance-closure-v8.md", "-", "complete for the scoped Gate C candidate", "Every model-proposed value is validated before it influences a decision")
r(14, (537, 537), "Deterministic business rules where appropriate", "M", "V", ["R14.3"], ["backend/app/ai/rules.py", "backend/app/profile/engine.py"], [BT + "test_apex_compat.py", BT + "test_profile_engine.py"], UAT,
  "Priority depends on model-extracted category and, in the default configuration, on unverified model numbers (fixed only in the unapproved candidate)", "Q", "Phase 8", "Priority never decided by the model")

# ---- Part 15 ------------------------------------------------------------------------------------------------------------------------------
r(15, (539, 549), "Nine states: DRAFT, PENDING_APPROVAL, APPROVED, REJECTED, SUBMITTING, SUBMITTED, FAILED, RETRY_PENDING, CANCELLED", "M", "V", ["R15.5"], ["backend/app/workflows/state_machine.py"], [BT + "test_workflow.py", BT + "test_control_mutations.py"], UAT, "", "-", "complete", "All nine states and transitions enforced")
r(15, (553, 554), "Human approval before external submission; role-based approval", "M", "V", ["R15.1", "R15.2"], ["backend/app/workflows/ticket_service.py", "backend/app/core/rbac.py"], [UATA + "::test_uat_a05_unapproved_submission_blocked", UATB + "::test_uat_b04_ticket_approval"], UAT, "", "C", "complete", "Zero unauthorized submissions")
r(15, (555, 557), "Editable drafts, recorded decisions, valid state transitions", "M", "V", ["R15.5"], ["backend/app/workflows/state_machine.py"], [BT + "test_workflow.py::test_edits_locked_after_submission_for_approval", BT + "test_control_mutations.py"], UAT, "", "-", "complete", "Drafts editable, decisions recorded")
r(15, (558, 560), "Idempotent submission, retry and recovery, duplicate prevention", "M", "V", ["R15.3", "R15.4"], ["backend/app/workflows/worker.py"], [UATA + "::test_uat_a07_duplicate_prevention", UATA + "::test_uat_a08_api_failure_recovery", FIT + "::test_fi04_malformed_response_after_server_side_create"], FI + UAT, "", "-", "complete", "At most one external ticket under retries")
r(15, (561, 561), "Audit history for ticket workflows", "M", "V", ["R15.5", "R16.5"], ["backend/app/audit/service.py"], [UATA + "::test_uat_a06_approved_ticket_submission"], UAT, "", "-", "complete", "Draft, approval and submission events recorded in order")
r(15, (563, 563), "Rejected tickets are never submitted", "X", "V", ["R15.1"], ["backend/app/workflows/worker.py"], [UATA + "::test_uat_a05_unapproved_submission_blocked"], UAT, "", "-", "complete", "Rejected ticket submit and retry refused")
r(15, (564, 564), "Retries must not bypass approval", "X", "V", ["R15.1"], ["backend/app/workflows/worker.py"], [BT + "test_workflow.py::test_retry_cannot_manufacture_approval"], FI, "", "-", "complete", "Retry cannot create an approval")
r(15, (565, 565), "Test concurrent approvals", "M", "V", ["R15.6"], ["backend/app/workflows/ticket_service.py"], [FIT + "::test_fi06_concurrent_approvals", BT + "test_workflow.py::test_concurrent_approvals_have_exactly_one_winner"], FI, "", "-", "complete", "One winner among eight concurrent approvals")

# ---- Part 16 ------------------------------------------------------------------------------------------------------------------------------
r(16, (568, 569), "Authentication and role-based access control", "M", "V", ["R16.2"], ["backend/app/core/rbac.py", "backend/app/api/deps.py"], [BT + "test_api_namespace_security.py", BT + "test_jwt_and_throttle.py"], ["docs/phase6/phase6-closure-gate.md"], "", "-", "complete", "Role x route matrix has zero violations")
r(16, (570, 572), "Tenant authorization and tenant-aware retrieval", "M", "V", ["R16.1"], ["backend/app/database/session.py"], [FIT + "::test_fi05_unauthorized_cross_tenant_access", BT + "test_security.py"], FI, "Tenant context is trusted application input (documented)", "-", "complete", "Zero successful cross-tenant accesses")
r(16, (573, 573), "Secure credential handling", "M", "V", ["R16.3"], ["scripts/secret_scan.py", "backend/app/core/production_guard.py"], ["tests/test_environment_guards.py"], ["docs/security/test-credentials.md"], "", "-", "complete", "No secrets committed; test credentials confined")
r(16, (574, 576), "Input validation, upload restrictions, rate limiting", "M", "P", ["R16.4"], ["backend/app/core/limits.py"], [BT + "test_resource_limits.py", BT + "test_jwt_and_throttle.py"], ["docs/security/rate-limiting-limitations.md"], "Limits and throttling are per process; distributed rate limiting is not implemented", "C", "Phase 9/10 (before production)", "Validated inputs and limits enforced")
r(16, (577, 577), "Audit logging", "M", "V", ["R16.5"], ["backend/app/audit/service.py"], [BT + "test_control_mutations.py"], UAT, "", "-", "complete", "Consequential actions recorded")
r(16, (578, 579), "Prompt-injection defenses and negative authorization tests", "M", "V", ["R16.7", "R16.2"], ["backend/app/ai/safety.py"], [FIT + "::test_fi08_prompt_injection", BT + "test_api_namespace_security.py"], FI, "Question-level override phrases are refused only by an opt-in gate (not default); retrieved-text injection is handled in the default", "Q", "Phase 8", "Poisoned content quarantined")
r(16, (581, 587), "Five roles: Platform Administrator, Tenant Administrator, Maintenance Supervisor, Support Engineer, Read-Only Auditor", "M", "V", ["R16.2", "R10.4"], ["backend/app/core/rbac.py"], [BT + "test_api_namespace_security.py"], [], "", "-", "complete", "Five roles enforced")
r(16, (589, 589), "PostgreSQL row-level security where practical", "O", "V", ["R16.1"], ["backend/migrations/versions/0002_memberships_rls.py"], [BT + "test_membership_rls.py", BT + "test_identity_security.py"], ["docs/security/identity-tables.md"], "", "-", "complete", "RLS enforced even when application filters are bypassed")
r(16, (590, 590), "Do not rely exclusively on frontend permission checks", "X", "V", ["R16.2"], ["backend/app/api/deps.py"], [BT + "test_api_namespace_security.py"], [], "", "-", "complete", "Backend enforces every permission")
r(16, (591, 591), "Do not commit secrets", "X", "V", ["R16.3"], ["scripts/secret_scan.py"], ["tests/test_environment_guards.py"], [AUD], "Pattern scan, not history-wide", "-", "complete", "Secret scan finds nothing; env files ignored")

# ---- Part 17 ------------------------------------------------------------------------------------------------------------------------------
r(17, (593, 593), "FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL and pgvector", "M", "V", ["R5.1"], ["backend/app/main.py"], [BT + "test_smoke_and_ingestion.py"], [], "", "-", "complete", "Stack in use")
r(17, (594, 608), "14 required API namespaces under /api/v1", "M", "V", ["R17.1"], ["backend/app/main.py", "backend/app/api/v1/core_routes.py", "backend/app/api/v1/domain_routes.py"], [BT + "test_api_namespace_security.py"], [AUD], "", "-", "complete", "All 14 namespaces mounted and covered by the route table")
r(17, (609, 619), "Typed contracts, validation, pagination, standardized errors, OpenAPI, migrations, transactions, constraints, indexes", "M", "V", ["R17.1", "R17.2"],
  ["backend/app/core/errors.py", "backend/app/main.py", "backend/app/api/v1/response_models.py", "backend/app/api/v1/error_contracts.py", "backend/app/api/v1/core_routes.py", "backend/migrations/versions/0008_tenant_leading_indexes.py"],
  [BT + "test_api_contract.py", BT + "test_api_response_schemas.py", BT + "test_api_response_contract.py", BT + "test_api_error_contract.py", BT + "test_migration_0008_indexes.py", BT + "test_api_namespace_security.py"],
  ["evaluation/api-quality/api-quality-evidence.json", "evaluation/api-quality/index-query-plans.json", "evaluation/api-quality/response-baseline-pre-batch3.json", "docs/api/api-quality.md", "docs/api/response-inventory.md", "docs/planning/batch3-report.md", "docs/planning/batch3_1-report.md", "docs/planning/batch4-report.md", "backend/tests/snapshots/openapi_contract.json"],
  "Owner-approved closure (Batch 4, 2026-11-13) for the documented local implementation and acceptance scope. Evidence: all nine properties verified by executed tests (api-quality-evidence.json, generated at commit 3bcfdf0 from a clean tree; Batches 1-3.1): typed request and success contracts for all 45 operations (39 return 200, 6 return 201) validated against every runtime response, error responses documented per operation and probed in both directions, pagination, validation, standardized errors, OpenAPI with bearer security and a committed contract snapshot, migrations through 0008, transactions, constraints and tenant-leading indexes. Caveats: the HTTP 413 size-limit body (code payload_too_large) has no correlation_id in the body (the header is set), unlike every other error; handlers return dictionaries validated at the framework boundary; error codes are an open vocabulary; the tests and evaluations are same-author, not externally certified",
  "-", "complete", "Nine API-quality properties verified")
r(17, (621, 639), "17 database entities: tenants, users, roles, memberships, connectors, documents, document versions, chunks, embeddings, ingestion jobs, incidents, tickets, approvals, workflow executions, outbox events, audit events, evaluation runs", "M", "V", ["R17.3"], ["backend/app/models/__init__.py", "backend/migrations/versions/0010_ingestion_jobs.py", "backend/migrations/versions/0014_evaluation_runs.py", "backend/app/evaluation_registry.py"], [BT + "test_membership_rls.py", BT + "test_ingestion_jobs.py", BT + "test_migration_0010_ingestion_jobs.py", BT + "test_evaluation_registry.py"], [AUD, "docs/architecture/ingestion-jobs.md", "docs/architecture/entity-model-decision.md"],
  "VERIFIED (assessment recorded for owner review; same-author evidence). 14 of 17 entities are tables of their own (ingestion_jobs since 0010, evaluation_runs since 0014). Roles (memberships.role plus the tested permission matrix), embeddings (a pgvector column of the chunk) and workflow executions (tickets, approvals, outbox events and audit events) are satisfied by documented equivalents rather than duplicate tables (docs/architecture/entity-model-decision.md). evaluation_runs is an index of the manifests under evaluation/ with a tamper check; the files remain the evidence. If the owner reads the list as one table per name, roles and workflow_executions remain to be added", "-", "complete", "All 17 entities exist")
# ---- Part 18 ------------------------------------------------------------------------------------------------------------------------------
r(18, (643, 657), "13 required pages", "M", "V", ["R18.1"], ["frontend/src/nav.ts", "frontend/src/pages"], [FE + "auth-and-roles.spec.ts", "frontend/src/pages/pages.test.tsx"], [AUD, "docs/phase6/phase6-closure-gate.md"], "", "-", "complete", "All 13 pages render against the backend")
r(18, (659, 669), "Responsive layout, form validation, loading/empty/error states, search, filtering, pagination", "M", "V", ["R18.2"], ["frontend/src/components/ui.tsx", "frontend/src/hooks/usePagedList.ts"], [FE + "admin-config-and-quality.spec.ts", FE + "documents-and-assistant.spec.ts"], ["docs/phase6/phase6-closure-gate.md"], "", "-", "complete", "States exist; no overflow at 375 px")
r(18, (659, 660), "Accessibility", "M", "P", ["R18.3"], ["frontend/src/components/ConfirmDialog.tsx"], [FE + "accessibility.spec.ts", FE + "keyboard-workflow.spec.ts"], ["evaluation/reports/phase6-closure/axe-results.json"], "Automated axe on 43 states in one browser and automated keyboard workflow evidence. The owner disposition retains the missing manual keyboard and Windows Narrator observations as accessibility-assurance limitations. No cross-browser audit or conformance claim", "D", "Phase 10", "No critical or serious violations; keyboard-operable workflow")
r(18, (671, 671), "Do not display fabricated metrics", "X", "V", ["R18.4"], ["backend/app/api/v1/ops_routes.py"], [BT + "test_ops_routes.py"], ["docs/phase6/phase6-review-report.md"], "", "-", "complete", "Figures come from artifacts or tenant records")

# ---- Part 19 ------------------------------------------------------------------------------------------------------------------------------
r(19, (673, 676), "docs/customer-acceptance/, tests/acceptance/ and evaluation/customer-acceptance/ exist", "M", "V", ["R19.1"], ["tests/acceptance/conftest.py"], [UATA], UAT + ["docs/customer-acceptance/uat-results.md"], "", "-", "complete", "Three locations populated")
r(19, (677, 689), "Each acceptance test records test id, requirement id, preconditions, test data, steps, expected, actual, pass/fail, evidence reference, timestamp", "M", "V", ["R19.1"], ["tests/acceptance/conftest.py"], [UATA], UAT, "", "-", "complete", "Ten fields recorded for every scenario")
for _n, (_t, _s) in enumerate([("Document ingestion", "a01_document_ingestion"), ("Evidence-grounded retrieval", "a02_evidence_grounded_retrieval"), ("Historical incident matching", "a03_historical_incident_matching"),
                               ("Structured ticket generation", "a04_structured_ticket_generation"), ("Unapproved submission blocked", "a05_unapproved_submission_blocked"), ("Approved ticket submission", "a06_approved_ticket_submission"),
                               ("Duplicate prevention", "a07_duplicate_prevention"), ("API failure recovery", "a08_api_failure_recovery")], 1):
    r(19, (692 + _n - 1, 692 + _n - 1), f"UAT-A0{_n}: {_t}", "M", "V", ["R19.1"], [UATA], [UATA + f"::test_uat_{_s}"], UAT, "AI-dependent scenarios rest on thresholds in real-model mode" if _n in (2, 3, 4) else "", "-", "complete", "Scenario passes in deterministic and real-AI modes")
for _n, (_t, _s) in enumerate([("Second-tenant onboarding", "b01_second_tenant_onboarding"), ("Customer-specific schema mapping", "b02_customer_specific_schema_mapping"), ("Fleet issue extraction", "b03_fleet_issue_extraction"),
                               ("Ticket approval", "b04_ticket_approval"), ("Correct customer API submission", "b05_correct_customer_api_submission"), ("Cross-tenant access denied", "b06_cross_tenant_access_denied"), ("Failure recovery", "b07_failure_recovery")], 1):
    r(19, (703 + _n - 1, 703 + _n - 1), f"UAT-B0{_n}: {_t}", "M", "V", ["R19.2"], [UATB], [UATB + f"::test_uat_{_s}"], UAT, "", "-", "complete", "Scenario passes in deterministic and real-AI modes")
r(19, (711, 711), "All critical security, approval and isolation tests must pass", "M", "V", ["R19.1", "R26.1"], ["tests/acceptance"], [BT + "test_api_namespace_security.py", BT + "test_review_gate.py", BT + "test_membership_rls.py"], ["evaluation/reports/phase8/candidate-regression/summary.json"], "", "-", "complete", "358 backend tests pass at the final state")
r(19, (712, 712), "Machine-readable JSON and human-readable Markdown acceptance reports", "M", "V", ["R19.1"], ["tests/acceptance/conftest.py"], [UATA], UAT + ["evaluation/customer-acceptance/deterministic/uat-report.md"], "", "-", "complete", "Both formats generated")

# ---- Part 20 ------------------------------------------------------------------------------------------------------------------------------
r(20, (714, 718), "tests/fault_injection/, docs/reliability/ and evaluation/failure-reports/ exist", "M", "V", ["R20.1"], [FIT], [FIT], FI + ["docs/reliability/fault-injection-results.md"], "", "-", "complete", "Three locations populated")
for _n, (_t, _s) in enumerate([("HTTP 503 outage", "fi01_http_503_outage"), ("HTTP 429 rate limiting", "fi02_http_429_rate_limiting"), ("Network timeout", "fi03_network_timeout"), ("Malformed API response", "fi04_malformed_response_after_server_side_create"),
                               ("Unauthorized cross-tenant access", "fi05_unauthorized_cross_tenant_access"), ("Concurrent approvals", "fi06_concurrent_approvals"), ("Worker interruption", "fi07_worker_interruption"),
                               ("Prompt injection", "fi08_prompt_injection"), ("Duplicate ingestion", "fi09_duplicate_ingestion"), ("Database interruption", "fi10_database_interruption")], 1):
    r(20, (719 + _n, 719 + _n), f"FI-{_n:02d}: {_t}", "M", "V", [f"R20.{_n}"], [FIT], [FIT + f"::test_{_s}"], FI, "FI-10 is disruptive and opt-in (RUN_DISRUPTIVE=1); latest run under the Phase 8 candidate and defaults: pass" if _n == 10 else "", "-", "complete", "Scenario passes with zero duplicates and no unauthorized action")
r(20, (731, 739), "Record initial state, injected fault, expected, actual, recovery action, final state, pass/fail for every scenario", "M", "V", ["R20.1"], ["tests/fault_injection/conftest.py"], [FIT], FI, "", "-", "complete", "Seven fields recorded")
r(20, (741, 742), "Demonstrate safe recovery without unauthorized actions or duplicate submissions using local mocks", "M", "V", ["R20.11", "R15.4"], ["tests/fault_injection/test_additional_reliability.py"], [FIT, "tests/fault_injection/test_additional_reliability.py::test_rel04_recovery_after_api_process_restart"], FI, "", "C", "complete", "Zero duplicate external actions in every scenario")

# ---- Part 21 ------------------------------------------------------------------------------------------------------------------------------
r(21, (744, 748), "evaluation/datasets, evaluation/benchmarks, evaluation/reports and docs/performance", "M", "P", ["R21.1"], ["evaluation/datasets/eval-v2", "evaluation/benchmarks/run_phase3.py"], [], [AUD], "docs/performance is an empty placeholder", "D", "Phase 10", "Four locations populated")
r(21, (749, 764), "Measure Recall@5, Precision@5, citation correctness, groundedness, structured validity, ticket creation accuracy, workflow completion, integration success rate, failure recovery rate, isolation outcomes, API/retrieval/LLM/end-to-end latency", "M", "P", ["R21.1", "R21.3", "R21.2"],
  ["evaluation/phase8/score_baseline.py", "evaluation/phase8/metrics.py"], ["tests/test_phase8_metrics.py", "tests/test_phase8_scorer.py"], [HO], "Integration success rate and failure recovery rate are not computed as rates with defined suites", "Q", "Phase 8", "All 14 measures reported with denominators")
r(21, (768, 768), "Target: Recall@5 at least 85%", "T", "V", ["R21.1"], ["evaluation/phase8/score_baseline.py"], ["tests/test_phase8_scorer.py"], [HO], "Observed met on dev (88.5%) and held-out baseline (89.5%); the interval overlaps the target, so attainment is not statistically established", "-", "complete", "Recall@5 >= 85%")
r(21, (769, 769), "Target: citation correctness at least 95%", "T", "P", ["R13.2", "R21.1"], ["evaluation/phase8/score_baseline.py"], ["tests/test_phase8_scorer.py"], [HO, BASE], "NOT MET: baseline 85.7% dev / 95.1% held-out (point estimate met, interval overlaps); candidate 91.9% dev / 89.8% held-out", "Q", "Phase 8", "Citation correctness >= 95%")
r(21, (770, 770), "Target: structured ticket schema validity 100%", "T", "P", ["R14.1"], ["backend/app/schemas/incident.py"], ["tests/fault_injection/test_additional_reliability.py::test_rel03_invalid_structured_ai_output"], [HO],
  "Post-validation validity 100% (invalid output never creates an incident); raw model validity 100% on dev (34/34) but 90% (18/20) on the held-out split: NOT MET at the model level", "Q", "Phase 8", "100% schema validity of stored incidents and, as stated, of model output")
r(21, (771, 771), "Target: zero successful unauthorized cross-tenant access in the defined suite", "T", "V", ["R16.1", "R20.5"], ["backend/app/database/session.py"], [FIT + "::test_fi05_unauthorized_cross_tenant_access", UATB + "::test_uat_b06_cross_tenant_access_denied"], FI + UAT, "", "C", "complete", "Zero successful attempts")
r(21, (772, 772), "Target: zero unauthorized ticket submissions", "T", "V", ["R15.1"], ["backend/app/workflows/worker.py"], [UATA + "::test_uat_a05_unapproved_submission_blocked"], [HO] + UAT, "", "C", "complete", "Zero unauthorized submissions")
r(21, (773, 773), "Target: zero duplicate tickets during tested retries", "T", "V", ["R15.3"], ["backend/app/workflows/worker.py"], [UATA + "::test_uat_a07_duplicate_prevention", "tests/acceptance/test_end_to_end_reliability.py::test_apex_end_to_end_reliability"], [HO] + FI, "", "C", "complete", "Zero duplicates")
r(21, (774, 774), "Target: critical UAT pass rate 100%", "T", "V", ["R19.1", "R19.2"], [UATA, UATB], [UATA, UATB], UAT, "", "-", "complete", "15 of 15 UAT scenarios pass")
r(21, (775, 775), "Target: transient failure recovery at least 95% in the defined suite", "T", "P", ["R15.4"], ["backend/app/workflows/worker.py"], [UATA + "::test_uat_a08_api_failure_recovery", FIT + "::test_fi01_http_503_outage"], FI, "All injected transient failures recovered, but no recovery-rate denominator or suite definition exists", "A", "separate approval (define the suite)", "Recovery rate >= 95% over a defined suite")
r(21, (777, 779), "Targets are not results; define denominators and methodology; report actual measurements", "X", "V", ["R21.1"], ["evaluation/phase8/metrics.py"], ["tests/test_phase8_metrics.py"], ["docs/evaluation/phase8-metric-definitions.md", "docs/evaluation/phase8-evaluation-protocol-v1.1.md"], "", "-", "complete", "Formulas, denominators and uncertainty documented")
r(21, (780, 793), "Record CPU, RAM, GPU if available, OS, Python, PostgreSQL, Ollama, LLM, embedding model, dataset size, repetitions, date", "M", "V", ["R21.3"], ["scripts/capture_hardware.py"], ["tests/test_hardware_capture.py"], ["evaluation/reports/phase8/heldout/hardware.json", "evaluation/reports/phase8/baseline-20261112T035539Z/manifest.json"], "", "-", "complete", "Every run manifest records the environment")
r(21, (795, 795), "Report median and p95 latency where feasible", "M", "V", ["R21.3"], ["evaluation/phase8/metrics.py"], ["tests/test_phase8_metrics.py::test_percentiles"], [HO], "Measured on one laptop; no p99 (n < 200)", "-", "complete", "p50 and p95 reported")
r(21, (796, 798), 'Compare manual and automated workflows using equivalent synthetic tasks, distinguishing simulated baselines; no claimed productivity gains', 'M', 'P', ['R21.4'], ['scripts/workflow_comparison.py'], ['tests/test_workflow_comparison.py'], ['evaluation/comparison/protocol.md', 'evaluation/demo-runs/20261113-150933-73e0/comparison/comparison.json'],
  'Batch 12: a transparent protocol and harness exist (evaluation/comparison/protocol.md, scripts/workflow_comparison.py, `demo.py smoke --compare`) and class A (measured automated system time, 20 equivalent synthetic tasks, median and p95 per step) was measured; classes B (observed manual) and C (simulated manual) are structurally separate and EMPTY because no human was observed and no assumptions were supplied (the code refuses to invent them). The comparison itself therefore has not been made. To complete it: record real observed times in observed-manual.csv and re-run', 'Q', 'owner input (observed manual data)', 'Labelled simulated comparison exists')
# ---- Part 22 ------------------------------------------------------------------------------------------------------------------------------
r(22, (800, 814), "Structured JSON logging, correlation ids, trace ids, request latency, ingestion duration, retrieval latency, inference duration, workflow completion time, external API failures, retry counts, dead-letter counts, approval turnaround time", "M", "P", ["R22.1", "R22.2"],
  ["backend/app/observability/logging.py", "backend/app/observability/metrics.py", "backend/app/api/v1/ops_routes.py"], [BT + "test_observability.py"], ["evaluation/observability/README.md"], "No trace ids; metrics are process-scoped and reset on restart", "D", "Phase 10", "All twelve signals available")
r(22, (815, 815), "Use OpenTelemetry where practical", "O", "M", ["R22.3"], [], [], ["docs/architecture/optional-infrastructure-decision.md"], "Owner-requested review (Batch 12): not a mandatory criterion ('where practical'); JSON logs, correlation ids and in-process metrics exist; the OpenTelemetry SDK and a collector were deliberately not added; trace ids across processes remain a gap", "I", "optional (decision recorded)", "OpenTelemetry traces exported")
r(22, (816, 819), "Optional Prometheus and Grafana", "O", "M", ["R22.3"], [], [], ["docs/architecture/optional-infrastructure-decision.md"], "Optional; deliberately not implemented (decision recorded: metrics are process-local, so a scraper would see misleading history)", "I", "optional (decision recorded)", "")
r(22, (821, 821), "Do not log secrets or sensitive content", "X", "V", ["R22.1"], ["backend/app/observability/logging.py"], [BT + "test_observability.py"], ["evaluation/observability/README.md"], "", "-", "complete", "Redaction verified; no document text logged")

# ---- Part 23 ------------------------------------------------------------------------------------------------------------------------------
r(23, (822, 834), "Docker Compose core services: backend, frontend, PostgreSQL+pgvector, worker, mock CRM, mock inventory, mock ticketing, local Ollama integration", "M", "P", ["R23.1"], ["docker-compose.yml", "docker-compose.app.yml", "infrastructure/docker/Dockerfile.backend", "infrastructure/docker/Dockerfile.frontend", "scripts/dev.py", "scripts/container_smoke.py"], [], [AUD, "evaluation/container-smoke/20261113-145441/report.md"], "Batch 12: backend (API, worker, migrate, seed), mock CRM, inventory and ticketing (plus fleet and service desk), PostgreSQL with pgvector and the web UI run in containers with one command (python scripts/container_smoke.py), smoke-tested twice. Local Ollama integration from inside a container is NOT tested (a host Ollama on 127.0.0.1 is unreachable from a container), and the images run the deterministic test-only AI backends", "I", "Phase 9/10", "One command starts all services")
r(23, (835, 839), "Optional RabbitMQ, Prometheus, Grafana", "O", "M", [], [], [], ["docs/architecture/optional-infrastructure-decision.md"], "Optional; deliberately not implemented (decision recorded: the database outbox and job queue already give atomic enqueue; Prometheus and Grafana as above)", "I", "optional (decision recorded)", "")
r(23, (841, 855), "Provide .env.example, startup scripts, migrations, seed data, health checks, smoke tests, acceptance/fault-injection/benchmark commands, backup, restore and shutdown instructions", "M", "P", ["R23.1"], [".env.example", "scripts/dev.py", "scripts/seed_apex.py", "scripts/migrate.py", "scripts/demo.py"], ["evaluation/smoke/meridian_smoke.py", "tests/test_demo_ownership.py"], ["docs/operations/configurations.md", "docs/planning/batch7-report.md", "docs/operations/local-runbook.md"],
  "Batch 7: a tested backup and restore-check procedure exists for disposable demonstration databases only (scripts/demo.py backup and restore-check, with restore, integrity, row-level-security and secret checks), plus consolidated start, smoke and shutdown commands in the local runbook. Still missing: backup and restore instructions for the shared development database and for any non-demo deployment (deliberately not offered), and the other consolidated commands (acceptance, fault injection, benchmarks) are documented elsewhere", "D", "Phase 10", "Twelve items provided")
r(23, (856, 857), "Support CPU-only operation; a reviewer can reproduce the main demonstration on compatible hardware", "M", "P", ["R23.1", "R30.1"], ["docs/operations/real-ai-setup-windows.md", "scripts/demo.py", "scripts/demo_smoke.py"], [FE + "workflows.spec.ts", "tests/test_demo_launcher.py", "tests/test_demo_ownership.py", FE + "demo-smoke.spec.ts"], ["docs/evaluation/phase8-heldout-report.md", "docs/planning/batch6-report.md", "docs/planning/batch7-report.md", "docs/customer-delivery/demo-handover.md", "evaluation/demo-runs/negative-scenarios.json", "evaluation/demo-runs/negative-scenarios-batch7.json"], "CPU-only works. Batch 6 added a one-command launcher (scripts/demo.py up, down, smoke) that creates a disposable database, starts the existing services and verifies both customer workflows through the API and the browser; it passed repeatedly on this machine with deterministic AI backends (real-AI mode only preflight-checked). Batch 7 repeated the checkpoint (three sequential full smoke runs with backup and restore proof: 2 passed, 1 failed with an unexplained, unreproduced API readiness stall; six diagnostic start cycles passed) and added state locking, resumable teardown and diagnostics. Level A (existing-environment) reproducibility only. Still missing: Level B (fresh local installation: new virtual environment, dependency install, new database volume) and Level C (an independent reviewer reproduction)", "D", "Phase 10", "Reviewer reproduces the demonstration")

# ---- Part 24 ------------------------------------------------------------------------------------------------------------------------------
r(24, (859, 867), "Primary implementation local and free; no paid cloud provisioning; design adaptable to AWS, Azure, GCP and Kubernetes", "X", "P", ["R24.1"], [], [], [AUD], "Nothing is provisioned (met); adaptability is a design property that is not yet documented", "I", "Phase 9", "No cloud resources; portability documented")
r(24, (868, 880), 'infrastructure/terraform/ with Terraform/OpenTofu configuration, variables, outputs, provider constraints, example configuration, validation instructions; run local fmt/validate where feasible; no billable provisioning', 'M', 'P', ['R24.1'], [], [], ['docs/specification/v4.1-audit-check-results.json', 'infrastructure/terraform/README.md', 'infrastructure/terraform/main.tf', 'infrastructure/terraform/variables.tf', 'infrastructure/terraform/outputs.tf', 'infrastructure/terraform/versions.tf'],
  'Illustrative AWS Terraform files exist (variables, outputs, provider constraints, example tfvars, validation instructions). The official Terraform CLI v1.17.2 was installed with checksum and signature verified, and `terraform fmt -check` passes (evaluation/terraform/fmt-check.txt), but `terraform validate` was NOT run: it needs the AWS provider download, which was not authorised. Never initialised, planned or applied', 'I', 'Phase 9/10', 'Configuration validates locally')
r(24, (881, 881), "No cloud credentials required for ordinary local operation", "X", "V", ["R24.1"], ["docs/deployment/accepted-limitations.md"], ["tests/test_environment_guards.py"], [], "", "-", "complete", "Local operation uses no cloud credentials")
r(24, (882, 884), 'Cloud architecture documents for AWS, Azure, GCP; one detailed illustrative blueprint, others at comparison level', 'M', 'V', ['R24.1'], [], [], ['docs/architecture/cloud-portability.md', 'docs/architecture/deployment-tradeoffs.md'],
  'Analysis only: AWS detailed illustrative blueprint, Azure and Google Cloud at comparison level; no deployment was performed or claimed', '-', 'complete', 'Three provider documents')
r(24, (885, 898), 'Explain compute, database, storage, networking, identity, secrets, observability, scaling, availability, security, cost', 'M', 'V', ['R24.1'], [], [], ['docs/architecture/cloud-portability.md', 'docs/architecture/deployment-tradeoffs.md'],
  'Compute, database, storage, networking, identity, secrets, observability, scaling, availability, security and cost are addressed for the AWS blueprint; cost is discussed qualitatively, not estimated', '-', 'complete', 'Eleven topics explained')
r(24, (899, 900), "Optional Kubernetes examples after the local platform works; do not claim cloud deployment without actual deployment", "O", "M", ["R24.1"], [], [], [AUD], "Not implemented; no deployment claim is made (met)", "I", "Phase 9 (optional)", "")
r(24, (901, 912), 'docs/architecture/deployment-tradeoffs.md comparing monolith vs microservices, Compose vs Kubernetes, local vs hosted inference, pgvector vs managed vector DB, workers vs managed queues, local vs cloud (cost, complexity, reliability, scalability, security, operations)', 'M', 'V', ['R24.1'], [], [], ['docs/architecture/cloud-portability.md', 'docs/architecture/deployment-tradeoffs.md'],
  'Monolith versus microservices, cloud portability and Kubernetes compared', '-', 'complete', 'Six comparisons documented')
# ---- Part 25 ------------------------------------------------------------------------------------------------------------------------------
r(25, (914, 928), 'docs/customer-delivery/ with ten documents (discovery summary, requirements matrix, solution proposal, integration specification, deployment plan, acceptance plan, troubleshooting guide, operational handover, tradeoff record, retrospective)', 'M', 'V', ['R25.1'], [], [], ['docs/specification/v4.1-audit-check-results.json', 'docs/customer-delivery/01-customer-discovery-summary.md', 'docs/customer-delivery/02-requirements-to-solution-matrix.md', 'docs/customer-delivery/03-solution-architecture-proposal.md', 'docs/customer-delivery/04-integration-specification.md', 'docs/customer-delivery/05-deployment-plan.md', 'docs/customer-delivery/06-customer-acceptance-plan.md', 'docs/customer-delivery/07-troubleshooting-guide.md', 'docs/customer-delivery/08-operational-handover.md', 'docs/customer-delivery/09-architecture-tradeoff-record.md', 'docs/customer-delivery/10-implementation-retrospective.md'],
  'All ten documents exist, for fictional customers; the matrix is generated from the traceability catalogue; same-author documents', '-', 'complete', 'Ten documents delivered')
r(25, (929, 930), "Use realistic fictional scenarios; do not claim real customer interviews", "X", "N", [], [], [], [], "No customer documents exist to assess", "D", "Phase 10", "")
r(25, (931, 943), 'Prepare a 10-15 minute technical walkthrough using actual application behavior covering problem, requirements, architecture, integrations, security, automation, recovery, measured outcomes, tradeoffs', 'M', 'V', ['R30.1'], [], [], ['docs/customer-delivery/technical-walkthrough.md'],
  'A 13-minute script using actual behaviour and measured results; it has not been recorded or presented to anyone', '-', 'complete', 'Walkthrough delivered')
# ---- Part 26 and 27 -----------------------------------------------------------------------------------------------------------------------
r(26, (945, 962), "16 test types: unit, integration, API contract, database, authentication, authorization, tenant isolation, RAG evaluation, workflow transition, retry, idempotency, frontend, end-to-end, acceptance, fault injection, deployment smoke", "M", "P", ["R26.1"],
  ["backend/tests", "frontend/e2e", "tests/acceptance", "tests/fault_injection"], [BT + "test_api_namespace_security.py", BT + "test_workflow.py", BT + "test_real_ai.py", FE + "workflows.spec.ts"], ["evaluation/reports/phase8/candidate-regression/summary.json"],
  "No deployment smoke tests (no containers); API contract testing is limited to the route/role table", "D", "Phase 10", "All sixteen types present")
r(26, (964, 966), "Use Pytest, Vitest and Playwright; deterministic synthetic fixtures; runnable locally without paid services", "M", "V", ["R26.1"], ["frontend/playwright.config.ts"], [BT + "test_workflow.py", FE + "workflows.spec.ts"], ["evaluation/reports/phase8/candidate-regression/summary.json"], "", "-", "complete", "All suites run locally")
r(27, (968, 982), "CI/CD with GitHub Actions: backend/frontend lint and tests, type checking, dependency checks, security checks, Docker build validation, smoke tests, lightweight acceptance tests, release validation", "M", "P", ["R27.1"], [".github/workflows/ci.yml"], [], [], "Workflow covers backend lint/tests and frontend typecheck/test/build; dependency, security, Docker, smoke, acceptance and release checks are absent; it has never executed", "A", "Phase 10 / approval (needs a remote)", "All eleven CI checks pass in GitHub Actions")
r(27, (983, 984), "Document which tests execute in CI and which require local hardware", "M", "P", ["R27.1"], ["docs/operations/real-ai-setup-windows.md"], [], [], "Stated informally in the README and CI file; no dedicated document", "D", "Phase 10", "A CI scope document exists")
r(27, (985, 987), "Least-privilege permissions, no paid runners, no unnecessary bot-authored commits", "X", "V", ["R27.1"], [".github/workflows/ci.yml"], [], [AUD], "Verified by inspection of the workflow file (contents: read; ubuntu-latest)", "-", "complete", "Permissions minimal")

# ---- Part 28 and 29 -----------------------------------------------------------------------------------------------------------------------
r(28, (989, 1067), "Repository structure and root files exactly as listed", "M", "P", [], ["backend/app", "frontend/src"], [], [AUD], "Audit: frontend/src/layouts and frontend/tests absent (tests live beside sources and in frontend/e2e); infrastructure/terraform, kubernetes, monitoring and docs/customer-discovery, customer-delivery, customer-onboarding, integrations, performance are empty placeholders; all 11 root files exist", "D", "Phase 9/10", "Structure present with content")
r(28, (1068, 1068), "Create optional directories only when needed", "X", "V", [], [], [], [AUD], "", "-", "complete", "")
r(29, (1070, 1092), "README with 21 sections (overview, business problem, capabilities, architecture diagram, stack, scenarios, screenshots, setup, demo, API docs, security model, acceptance results, fault-injection results, benchmarks, hardware, test commands, CI status, cloud portability, tradeoffs, limitations, license)", "M", "P", ["R29.1"], ["README.md"], [], [AUD],
  "README has five sections (verified results table, what exists, run locally, known limitations, license); the other sections and an architecture diagram are absent; Phase 8 results are not yet in it", "D", "Phase 10", "All 21 sections present")
r(29, (1094, 1104), "'Verified Engineering Results' section with metric, actual, target, test command, evidence location; no invented results", "M", "P", ["R29.1"], ["README.md"], [], [], "Table exists and is hand-maintained; Phase 8 measurements not yet added; no README-vs-artifact consistency test", "D", "Phase 10", "Every row backed by a command and evidence path")

# ---- Part 30 and 31 -----------------------------------------------------------------------------------------------------------------------
r(30, (1106, 1136), "Reproducible 27-step end-to-end demonstration on the actual application", "M", "P", ["R30.1"], ["frontend/e2e/workflows.spec.ts", "scripts/dev.py", "scripts/onboard_tenant.py"], [FE + "workflows.spec.ts", "tests/acceptance/test_end_to_end_reliability.py::test_apex_end_to_end_reliability"], UAT,
  "Steps 1-25 are automated across suites; steps 26-27 (explain cloud portability and tradeoffs) and a single reproducible demo script do not exist", "D", "Phase 10", "A reviewer can follow all 27 steps")
r(31, (1138, 1227), "Implementation roadmap of ten phases", "M", "P", ["R32.1"], ["docs/phase6/phase6-closure-gate.md", "docs/phase7/phase7-gate.md"], [], ["docs/phase7/phase7-closure-gate.md", "docs/evaluation/phase8-heldout-disposition.md"], "Phases 1-8 executed under approval gates; Phase 9 (cloud portability) and Phase 10 (documentation and release) are outstanding", "D", "Phase 9/10", "All ten phases complete")
r(31, (1229, 1239), "At each phase end: run tests, fix failures, verify integration, review security, update documentation, commit accurately, record limitations; do not stop at scaffolding", "X", "P", [], [], [], ["docs/phase6/phase6-closure-gate.md", "docs/phase7/phase7-gate.md", "docs/evaluation/phase8-heldout-report.md"], "Gate documents exist for phases 5-8; earlier phases have per-phase notes of varying depth", "-", "complete", "")

# ---- Part 32 Definition of Done (37 items) ------------------------------------------------------------------------------------------------
_dod = [
    (1, "The platform runs locally", "V", "R7.1", "-", ""), (2, "No paid service is mandatory", "P", "R2.1", "D", "No automated check"), (3, "Both customer scenarios work end to end", "V", "R7.1", "-", ""),
    (4, "Tenant isolation is tested", "V", "R16.1", "-", ""), (5, "Enterprise connectors function", "V", "R11.1", "-", ""), (6, "Documents can be ingested", "V", "R12.1", "-", ""),
    (7, "RAG returns verifiable citations", "V", "R13.2", "-", "Verifiable (100% valid quotes); correctness target not met"), (8, "Structured incidents can be generated", "V", "R14.1", "-", ""), (9, "Human approval is enforced", "V", "R15.1", "-", ""),
    (10, "Approved tickets reach mock systems", "V", "R15.1", "-", ""), (11, "Failed workflows recover", "V", "R15.4", "-", ""), (12, "Duplicate tickets are prevented", "V", "R15.3", "-", ""), (13, "Audit history is available", "V", "R16.5", "-", ""),
    (14, "The frontend works", "V", "R18.1", "-", ""), (15, "Automated tests pass", "V", "R26.1", "-", "358 backend, 43 Vitest, 47 Playwright"), (16, "Customer acceptance tests pass", "V", "R19.1", "-", ""),
    (17, "Fault-injection tests are reproducible", "V", "R20.1", "-", ""), (18, "Evaluation reports contain actual measurements", "V", "R21.1", "-", "Measurements exist; several targets not met"),
    (19, "Hardware specifications are documented", "V", "R21.3", "-", ""), (20, "Docker deployment is reproducible", "P", "R23.1", "I", "Containers build and run (smoke-tested twice) with deterministic AI backends; Ollama integration inside a container untested"), (21, "CI checks pass", "N", "R27.1", "A", "CI has never run (no remote)"),
    (22, "Cloud portability is documented", "V", "R24.1", "-", "Analysis only; nothing deployed"), (23, "Terraform/OpenTofu examples are validated where feasible", "P", "R24.1", "I", "Examples exist and pass terraform fmt; schema validation needs a provider download that was not authorised"), (24, "Architecture tradeoffs are documented", "V", "R24.1", "-", ""),
    (25, "Customer discovery materials are complete", "V", "R6.1", "-", "Fictional customers; assumptions labelled"), (26, "Requirements traceability is available", "P", "R6.2", "D", "Provisional catalogue; this reconciliation supersedes it"), (27, "Technical handover documentation is complete", "V", "R25.1", "-", "Local system handover; not production"),
    (28, "The README contains verified results", "P", "R29.1", "D", "Phase 8 results not yet added"), (29, "The proprietary license is present", "V", "R3.1", "-", ""), (30, "Third-party notices are preserved", "P", "R3.1", "D", "Inventory only"),
    (31, "No unauthorized collaborators are invited", "V", "R33.1", "-", "No remote exists"), (32, "No unnecessary AI watermarks or promotional branding appear", "V", "R2.2", "-", ""), (33, "Git provenance remains accurate", "V", "R2.2", "-", ""),
    (34, "Repository permissions are reviewed", "N", "R33.1", "A", "No repository exists to review"), (35, "Publication is authorized", "N", "R33.1", "A", "Not authorized; nothing published"), (36, "A tested versioned release is published", "M", "R33.1", "A", "No release or tag"),
    (37, "The complete demonstration is reproducible", "P", "R30.1", "D", "No single reproducible demo script"),
]
for _n, _t, _s, _c, _k, _g in _dod:
    _g = _g or ("" if _s == "V" else f"See {_c}")
    r(32, (1241 + _n - 1, 1241 + _n - 1), f"Definition of done {_n}: {_t}", "D", _s, [_c], [], [], [AUD] if _n in (31, 32, 33) else [], _g, _k, {"-": "complete", "D": "Phase 10", "I": "Phase 9", "A": "approval"}[_k], _t)

# ---- Part 33 and 34 -----------------------------------------------------------------------------------------------------------------------
r(33, (1282, 1302), "Before publication, inspect repository owner, visibility, collaborators, app permissions, git author and committer, trailers, README, LICENSE, notices, Actions permissions, secrets, tracked files, documentation, screenshots, diagrams, reports, release notes", "M", "P", ["R33.1"], ["scripts/spec_audit_checks.py", "scripts/secret_scan.py"], [], [AUD],
  "Local items (author, committer, trailers, tracked files, secrets) are checked by script; GitHub-side items cannot be assessed until a repository exists", "A", "Phase 10 / approval", "All 18 inspected before publication")
r(33, (1303, 1305), "Search for assistant branding and watermarks; preserve provenance and legal notices; do not falsify activity metadata", "X", "V", ["R2.2"], ["scripts/spec_audit_checks.py"], [], [AUD], "", "-", "complete", "No promotional attribution found")
r(33, (1306, 1306), "Do not publish without explicit approval", "X", "V", ["R33.1"], [], [], [AUD], "No remote, no push, no release", "-", "complete", "Nothing published")
r(34, (1308, 1320), "Begin by verifying git, GitHub authentication, Git identity, Python, Node.js, Docker, CPU, RAM, GPU, disk, local model compatibility", "M", "P", ["R5.2"], ["scripts/capture_hardware.py"], ["tests/test_hardware_capture.py"], ["docs/evaluation/phase3-method.md"], "Hardware and runtime captured; GitHub authentication and Docker verification are not recorded in a repository artifact", "D", "Phase 10", "Environment verification recorded")
r(34, (1322, 1331), "Execution rules: request only essential information, work in increments, workflows before optional cloud, tests after every phase, no fabrication, no paid services, no collaborators, no copyright change, no publication without approval", "X", "P", [], [], [], [AUD], "Process rules; adherence evidenced by history and gates, not by tests", "-", "complete", "")
r(34, (1332, 1332), "If a requirement cannot be met, state the limitation and propose a compliant alternative", "X", "V", [], ["docs/deployment/accepted-limitations.md"], [], ["docs/deployment/accepted-limitations.md", "docs/specification/v4.1-gap-register.md"], "", "-", "complete", "Limitations stated with alternatives")
_deliv = [
    (1, "Complete source code", "V", "-"), (2, "Working backend", "V", "-"), (3, "Working frontend", "V", "-"), (4, "Database migrations", "V", "-"), (5, "Local RAG pipeline", "V", "-"), (6, "Enterprise connectors", "V", "-"),
    (7, "Human approval workflow", "V", "-"), (8, "Tenant security", "V", "-"), (9, "Audit logging", "V", "-"), (10, "Automated tests", "V", "-"), (11, "Customer acceptance reports", "V", "-"), (12, "Fault-injection reports", "V", "-"),
    (13, "Benchmark reports", "P", "Q"), (14, "Docker deployment", "P", "I"), (15, "CI/CD workflows", "P", "A"), (16, "Professional README", "P", "D"), (17, "Architecture diagrams", "V", "-"), (18, "Customer discovery documentation", "V", "-"),
    (19, "Requirements traceability matrix", "P", "D"), (20, "Deployment runbook", "V", "-"), (21, "Security documentation", "P", "D"), (22, "Troubleshooting guide", "V", "-"), (23, "Cloud portability documentation", "V", "-"),
    (24, "Terraform/OpenTofu examples", "P", "I"), (25, "Architecture tradeoff analysis", "V", "-"), (26, "Proprietary LICENSE file", "V", "-"), (27, "Third-party notices", "P", "D"), (28, "Authorized GitHub repository", "N", "A"),
    (29, "Tested versioned release", "M", "A"), (30, "Reproducible technical demonstration", "P", "D"), (31, "Final implementation and validation report", "P", "D"),
]
_deliv_cat = {1: "R5.1", 2: "R17.1", 3: "R18.1", 4: "R17.2", 5: "R13.1", 6: "R11.1", 7: "R15.1", 8: "R16.1", 9: "R16.5", 10: "R26.1", 11: "R19.1", 12: "R20.1", 13: "R21.1", 14: "R23.1", 15: "R27.1",
              16: "R29.1", 17: "R25.1", 18: "R6.1", 19: "R6.2", 20: "R25.1", 21: "R16.3", 22: "R25.1", 23: "R24.1", 24: "R24.1", 25: "R24.1", 26: "R3.1", 27: "R3.1", 28: "R33.1", 29: "R33.1", 30: "R30.1", 31: "R32.1"}
for _n, _t, _s, _k in _deliv:
    r(34, (1334 + _n, 1334 + _n), f"Final deliverable {_n}: {_t}", "D", _s, [_deliv_cat[_n]], [], [], [], {"P": "Partially delivered", "M": "Not delivered", "N": "Not assessable until a repository exists", "V": ""}[_s], _k,
      {"-": "complete", "D": "Phase 10", "I": "Phase 9", "A": "approval", "Q": "Phase 8"}[_k], _t)
r(34, (1368, 1387), "Final objective: demonstrate the 16 listed abilities (discovery, requirements engineering, integration, development, AI engineering, multi-tenant security, human-approved automation, reliability, fault recovery, customer-specific deployment, acceptance testing, measurable outcomes, cloud portability, tradeoff analysis, communication, handover)", "M", "P", [], [], [], [HO],
  "Abilities 4-11 are demonstrated; discovery, cloud portability, tradeoff analysis, communication and handover are not", "D", "Phase 9/10", "All 16 demonstrated")
r(34, (1389, 1393), "Maintain zero paid services, Gautham as sole owner, no collaborators, no promotional branding, accurate provenance and notices, use the complete proprietary license", "X", "V", ["R2.1", "R2.2", "R3.1"], ["LICENSE"], [], [AUD], "", "-", "complete", "Six maintenance rules hold")
r(34, (1395, 1395), "Begin with environment verification and Phase 1; implement and validate both customer workflows before optional cloud features; continue through testing, evaluation, documentation and authorized publication", "X", "P", [], [], [], [], "Sequence followed through Phase 8; documentation and publication outstanding", "D", "Phase 9/10", "")


# ---- Amendments after the release-candidate tag v4.1.0-local-rc1 (final completion directive). Each is justified by committed evidence; the original entries above are kept. -----------------
def amend(line: int, status: str | None = None, gap: str | None = None, impl=(), tests=(), evid=()) -> None:
    entry = next(e for e in E if e["lines"][0] == line)
    if status:
        entry["status"] = status
    if gap is not None:
        entry["gap"] = gap
    entry["impl"] += list(impl)
    entry["tests"] += list(tests)
    entry["evidence"] += list(evid)


NOTICE = dict(impl=["scripts/generate_third_party_notices.py"], tests=["tests/test_third_party_notices.py"], evid=["docs/security/third-party-license-inventory.json"])
README_ = dict(impl=["README.md"], tests=["tests/test_readme_results.py"])
DEMO = dict(impl=["scripts/demo.py", "docs/customer-delivery/demonstration-27-steps.md"], tests=["tests/test_demo_steps.py"], evid=["evaluation/demo-runs/20261113-152713-c19b/report.json"])
NO_PAID = dict(impl=["docs/operations/resource-requirements.md"], tests=["tests/test_no_paid_services.py"])
for _line in (210, 1270, 1361):
    amend(_line, "V", "Declared licences were read from installed package metadata (offline) for 71 Python and 275 Node packages plus models, images and tools; this is an inventory, not a legal review", **NOTICE)
for _line in (1070, 1094, 1268, 1350):
    amend(_line, "V", "README has the 21 required sections in order and a results table checked against its artifacts by a test; Phase 8 shortfalls are shown, not hidden", **README_)
amend(983, "V", "Documented job by job; the workflow has never executed (no remote)", impl=["docs/operations/ci-and-local-tests.md"], tests=["tests/test_ci_workflow.py"])
for _line in (91, 1242):
    amend(_line, "V", "Static check only (nothing in the repository requires a paid service); electricity is an estimate, not a measurement", **NO_PAID)
for _line in (1106, 1364):
    amend(_line, "V", "One entry point prints the 27 steps and `demo.py smoke` runs the automated ones on an isolated database; steps 26 and 27 are explanations; Level A reproducibility only (no independent reviewer)", **DEMO)
amend(775, "V", "Suite defined by the author (11 transient-failure cases against mock ticketing, plus two controls); 11 of 11 recovered; coarse, same-author, mock external system",
      impl=["tests/fault_injection/test_recovery_rate.py"], tests=["tests/fault_injection/test_recovery_rate.py"], evid=["evaluation/recovery/recovery-rate-report.json"])
amend(749, "V", "Recovery rate (11 of 11) and integration success rate (14 of 14) are computed over defined suites; both suites are coarse, same-author and use mock systems",
      impl=["backend/tests/test_integration_success_rate.py"], tests=["backend/tests/test_integration_success_rate.py"], evid=["evaluation/integration/integration-success-rate-report.json"])
amend(744, "V", "docs/performance now holds measured figures copied from committed artifacts and checked by a test; unmeasured items are listed",
      impl=["docs/performance/measured-performance.md"], tests=["tests/test_performance_docs.py"])
amend(241, gap="Quality targets are still NOT MET; recovery (11 of 11) and integration success (14 of 14) rates are now computed; workflow benchmarks beyond the synthetic runs are still partial")
amend(1347, gap="Partially delivered: Phase 8 reports, the recovery-rate and integration-success reports and docs/performance exist; quality targets are unmet and no independent confirmation set exists")
amend(230, gap="Trace ids now propagate API to job or outbox event to worker to connector call (tests/test_observability.py); metrics are still process-scoped and no OpenTelemetry SDK or exporter exists",
      impl=["backend/app/observability/tracing.py"], tests=["backend/tests/test_observability.py::test_trace_id_follows_a_ticket_from_the_api_through_the_outbox_to_the_connector_call"])
amend(800, gap="Trace ids exist (log field, X-Trace-ID, outbound traceparent); metrics are process-scoped and reset on restart",
      impl=["backend/app/observability/tracing.py"], tests=["backend/tests/test_observability.py::test_trace_id_follows_a_ticket_from_the_api_through_the_outbox_to_the_connector_call"])
amend(968, gap="The workflow now has backend, acceptance, frontend lint and tests, dependency and security, Docker build and release-validation jobs; it has never executed (no remote)", tests=["tests/test_ci_workflow.py"])
amend(319, gap="Workflow expanded and documented; it has never executed (no remote)", tests=["tests/test_ci_workflow.py"])
amend(1349, gap="Workflow delivered and tested as text; it has never executed (no remote)")
amend(37, gap="A README-versus-artifact consistency test now exists; compliance with a no-fabrication rule cannot be exhaustively tested", tests=["tests/test_readme_results.py"])


# ---- Amendments: shared rate limiting, durable metrics, trace ids, structure and optional examples (evidence in the listed tests and documents) -----------------------------------------
RL = dict(impl=["backend/app/connectors/ratelimit.py", "backend/app/core/request_limits.py", "backend/migrations/versions/0015_shared_rate_limits_and_metrics.py"],
          tests=["backend/tests/test_shared_rate_limits.py", "backend/tests/test_migration_0015_shared_state.py"], evid=["docs/security/rate-limiting-limitations.md"])
OBS = dict(impl=["backend/app/observability/metrics.py", "backend/app/observability/tracing.py"],
           tests=["backend/tests/test_durable_metrics.py", "backend/tests/test_observability.py::test_trace_id_follows_a_ticket_from_the_api_through_the_outbox_to_the_connector_call"],
           evid=["docs/operations/observability.md"])
amend(574, "V", "Rate limits are shared across API and worker processes through PostgreSQL (connectors, webhooks, every outbound client, per-tenant AI, extraction and upload rates, sign-in failures), "
      "tested with separate OS processes, threads, tenants, bounded waits and database unavailability. Concurrency limits (server_busy) remain per process and there is no IP-keyed or edge limit", **RL)
amend(462, "V", "All ten capabilities are implemented: authentication, pagination (REST and CSV; the older mock clients' APIs do not paginate, so it is not applicable to them), rate limiting now shared across processes "
      "and applied to every outbound client, timeouts, retries, exponential backoff, schema validation, error classification, idempotency and health checks (the live probe covers REST and CSV; webhook health is configuration-only)", **RL)
amend(800, "V", "Structured JSON logs, correlation ids, trace ids, request latency, ingestion duration, retrieval latency, inference duration, workflow completion time, external API failures, retry counts, "
      "dead-letter counts and approval turnaround time are recorded durably (flushed to PostgreSQL, summed across processes, surviving restarts); no OpenTelemetry SDK or exporter", **OBS)
amend(230, "V", "Retries, timeouts, recovery, fault injection, error classification, duplicate protection and observability are implemented and tested; observability is durable and traced (no spans or exporter)", **OBS)
amend(816, "P", "Prometheus text endpoint (/metrics, bearer-authenticated, tenant-scoped, cumulative histograms) and an example scrape configuration exist and the endpoint is tested; Prometheus itself was never run "
      "and no Grafana dashboards are provided", impl=["backend/app/api/v1/ops_routes.py", "infrastructure/monitoring/prometheus.yml"], tests=["backend/tests/test_durable_metrics.py", "tests/test_infrastructure_examples.py"], evid=["docs/operations/observability.md"])
amend(835, gap="Optional; RabbitMQ deliberately not implemented (decision recorded); the Prometheus text endpoint now exists, Grafana does not")
amend(313, gap="Structured JSON logging, trace ids and a Prometheus text endpoint exist; OpenTelemetry SDK and exporter and Grafana do not")
amend(899, "V", "Illustrative manifests (namespace, configuration, migration job, API, worker, UI) parsed and checked as text; never applied to a cluster and no cloud deployment is claimed",
      impl=["infrastructure/kubernetes/eaop.yaml"], tests=["tests/test_infrastructure_examples.py"])
amend(989, "V", "The Part 28 tree exists with tracked content in every listed directory and file (frontend layouts and tests added; kubernetes and monitoring examples added), checked by a test",
      impl=["frontend/src/layouts/AppLayout.tsx", "frontend/tests/setup.ts"], tests=["tests/test_repository_structure.py"])


# ---- Amendment: shared concurrency leases (migration 0016) extend the V41-16.04 evidence -----------------------------------------------------------------------------------------
amend(574, impl=["backend/app/core/limits.py", "backend/migrations/versions/0016_concurrency_leases.py"], tests=["backend/tests/test_shared_concurrency.py"],
      gap="Rate limits and the in-flight concurrency caps are shared across API and worker processes through PostgreSQL (limits, leases, tested with separate OS processes, threads, tenants, bounded waits, crashed holders and database unavailability). Remaining: no IP-keyed or edge limit, fixed-window sign-in counting, a crashed holder blocks its slot up to 330 s")


# ---- Amendments: provenance defect PROV-01 found by an automated history check (statuses LOWERED), and tests or evidence attached to requirements that had none recorded ----------------
PROV = ("PROV-01: an automated check of the whole history (scripts/provenance_check.py) found 52 commits whose messages carry an AI co-author trailer and 3 commits authored and committed "
        "under a tool's name instead of the owner's; all are recorded in docs/planning/provenance-exceptions.json. The earlier 'verified' assessment was wrong. No new violation is allowed "
        "(test), but existing ones can only be removed by rewriting history, which needs the owner's decision and would move the protected tag")
PROV_T = dict(impl=["scripts/provenance_check.py"], tests=["tests/test_repository_provenance.py"], evid=["docs/planning/provenance-exceptions.json"])
for _line in (54, 71, 1272, 1273, 1303):
    amend(_line, "P", PROV, **PROV_T)
amend(1389, "P", "Zero paid services, sole ownership, no collaborators and the licence hold; accurate provenance and no promotional branding do NOT hold in commit history (" + PROV + ")", **PROV_T)
for _line in (1271, 1306):  # no unauthorized collaborators; do not publish without approval
    amend(_line, impl=["scripts/provenance_check.py"], tests=["tests/test_repository_provenance.py::test_portfolio_history_has_no_provenance_violations"])
LICENSE_T = "tests/test_v41_reconciliation.py::test_license_matches_the_specification_text_exactly"
for _line in (111, 1269, 1360):
    amend(_line, tests=[LICENSE_T])
CLOUD_T = "tests/test_delivery_documents.py::test_cloud_and_infrastructure_documents_do_not_claim_a_deployment_or_validation_that_did_not_happen"
for _line in (882, 885, 901, 1262, 1264, 1357, 1359):
    amend(_line, tests=[CLOUD_T])
amend(983, evid=["docs/operations/ci-and-local-tests.md"])
amend(985, tests=["tests/test_ci_workflow.py"])
amend(1068, impl=["infrastructure/kubernetes/eaop.yaml", "infrastructure/monitoring/prometheus.yml"], tests=["tests/test_repository_structure.py"])
amend(1332, tests=["tests/test_documentation_consistency.py::test_readme_does_not_claim_production_readiness_or_full_compliance"])
FULL = dict(impl=["scripts/generate_full_traceability.py"], tests=["tests/test_full_traceability.py"], evid=["docs/traceability/v4.1-full-traceability-matrix.md"])
for _line in (350, 1266, 1353):
    amend(_line, "V", "All 238 original requirements are mapped to customer need (fictional), implementation, component or API, tests, acceptance criterion and evidence; cells with nothing "
          "recorded say so and are counted (requirements that are not verified, plus a few process rules)", **FULL)


# ---- Amendments: reassessment of entries whose recorded gap was stale (the documents and tests were added in earlier batches), each now tied to a test ------------------------------------
DELIVERY_T = "tests/test_delivery_documents.py"
amend(1308, "V", "All eleven items are recorded by a read-only script (identity and authentication as yes/no facts; no e-mail, account or token is written)",
      impl=["scripts/verify_environment.py"], tests=["tests/test_security_and_environment_docs.py"], evid=["evaluation/environment/verification.json"])
amend(1355, "V", "An index maps each control to its design, implementation and tests and lists what is not covered (no independent assessment, no threat model, PROV-01 open)",
      impl=["docs/security/README.md"], tests=["tests/test_security_and_environment_docs.py"], evid=["docs/security/README.md"])
amend(859, "V", "Nothing is provisioned; adaptability to AWS, Azure and Google Cloud is documented as analysis only (illustrative Terraform is formatted, not schema-validated)",
      impl=["docs/architecture/cloud-portability.md"], tests=[DELIVERY_T + "::test_cloud_and_infrastructure_documents_do_not_claim_a_deployment_or_validation_that_did_not_happen"],
      evid=["docs/architecture/cloud-portability.md"])
amend(929, "V", "Discovery documents exist for both customers, are labelled fictional and claim no interview",
      impl=["docs/customer-discovery/README.md"], tests=[DELIVERY_T + "::test_customer_discovery_documents_cover_every_required_heading_and_say_they_are_fictional"],
      evid=["docs/customer-discovery/apex-industrial.md", "docs/customer-discovery/meridian-fleet.md"])
amend(251, "V", "Customer discovery, traceability (all 238 requirements), onboarding, container deployment scripts, runbooks, troubleshooting and handover documents exist and are checked by tests; "
      "all same-author, fictional customers",
      impl=["docs/customer-onboarding/README.md", "docs/integrations/README.md", "docs/operations/deployment-runbook.md", "docs/customer-delivery/07-troubleshooting-guide.md",
            "docs/customer-delivery/08-operational-handover.md", "scripts/container_smoke.py"],
      tests=[DELIVERY_T, "tests/test_full_traceability.py", "tests/test_repository_structure.py"], evid=["docs/traceability/v4.1-full-traceability-matrix.md"])

CAP = dict(impl=["docs/customer-delivery/fde-capability-map.md"], tests=["tests/test_capability_map.py"], evid=["docs/customer-delivery/fde-capability-map.md"])
for _line in (16, 1368):
    amend(_line, "V", "Each listed capability is mapped to a working artifact with its limit stated: fictional customers, mocks, author-run acceptance, engineering measurements only "
          "(no productivity claim), cloud material as analysis only, AI-quality targets unmet", **CAP)
amend(945, "V", "All sixteen kinds of test exist and are mapped to example suites, including API contract tests against runtime responses and deployment smoke runs of the container stack",
      impl=["scripts/container_smoke.py"], tests=["tests/test_capability_map.py", "backend/tests/test_api_contract.py"], evid=["evaluation/container-smoke/20261113-170300/report.md"])

CLEAN = dict(impl=["scripts/clean_environment_check.py", "docker-compose.app.yml", "docker-compose.ollama.yml"], tests=["tests/test_delivery_documents.py::test_the_container_stack_is_defined_without_baked_secrets_and_its_smoke_evidence_exists"],
             evid=["evaluation/clean-environment/20261113-183717/report.md", "evaluation/clean-environment/20261113-183717/container-smoke-report.json"])
for _line in (303, 822, 1260, 1348):
    amend(_line, "V", "The container stack was built and run from a clean checkout with fresh secrets, its own database volume and lock-file-constrained dependencies; both customers' workflows passed (25 checks each), "
          "the UI proxied the API, a grounded answer came from the host's Ollama from inside the stack, and teardown removed only its own project. Same machine and image cache; embeddings in the image are the "
          "deterministic test-only ones", **CLEAN)
amend(1277, gap="Gate B on the same machine: the whole demonstration (both customers, ingestion, REST, CSV, webhooks, recovery, comparison, backup, browser) passed from a clean checkout with clean dependency installs "
      "(evaluation/clean-environment/20261113-183717). The complete 27-step demonstration was not observed in a single session. The owner disposition retains it as a Phase 10 and release-preparation item", impl=["scripts/clean_environment_check.py"], evid=["evaluation/clean-environment/20261113-183717/live-demo-report.md"])
amend(856, gap="CPU-only works and a clean-checkout reproduction passed on the author's machine; the owner disposition retains the outstanding compatible-hardware walkthrough as a reproducibility-assurance limitation", evid=["evaluation/clean-environment/20261113-183717/report.md"])


# Link the owner decision without replacing the underlying evidence.
for _line in (536, 659, 856, 1277):
    amend(_line, evid=["docs/planning/gate-c-owner-disposition.md"])


# ---- Amendments: spans (OpenTelemetry data model without the SDK) and the Grafana dashboard ---------------------------------------------------------------------------------------
SPANS = dict(impl=["backend/app/observability/tracing.py"], tests=["backend/tests/test_spans.py"], evid=["docs/operations/observability.md"])
amend(815, "P", "Spans (named, timed, parent-linked units of work inside a trace) are emitted as structured log events for requests, connector calls, outbox submissions and ingestion jobs, and W3C traceparent "
      "propagates across processes; the OpenTelemetry SDK, an exporter and a collector are NOT used (it is a data-model equivalent; 'where practical' was judged against a new dependency and a collector to run)", **SPANS)
amend(816, "V", "Optional items: a bearer-authenticated, tenant-scoped Prometheus text endpoint, an example scrape configuration and a Grafana dashboard whose every query is checked against the recorded metrics. "
      "Neither Prometheus nor Grafana was installed or run; the dashboard was never imported", impl=["infrastructure/monitoring/grafana-dashboard.json"], tests=["tests/test_grafana_dashboard.py"],
      evid=["infrastructure/monitoring/grafana-dashboard.json"])
amend(313, gap="Structured JSON logging, trace ids, spans (OpenTelemetry data model as log events), a Prometheus text endpoint and an illustrative Grafana dashboard exist; the OpenTelemetry SDK and exporter do not", **SPANS)


# ---- Amendment: development experiment on invented asset ids (statuses unchanged: confirmation needs fresh independent evidence) ----------------------------------------------------
NOASSET = dict(impl=["backend/app/ai/ollama_llm.py"], tests=["backend/tests/test_asset_identification.py"], evid=["docs/evaluation/dev-noasset-report.md"])
amend(770, gap="Held-out raw model validity was 18 of 20 (NOT MET at the model level). A development experiment (30 new reports) found the model invents an asset id for 16 of 16 reports naming none; the application "
      "now identifies the asset itself (30 of 30 correct on the development cases) and records the model's value, so the model-level metric will no longer count it; confirmation needs fresh independent data", **NOASSET)
amend(517, gap="Held-out correct abstention 94.1% baseline (16/17); development weaknesses (sibling-model answers) remain in the default configuration; reports naming no equipment are now refused deterministically "
      "(asset_not_identified) instead of depending on the model", **NOASSET)


# ---- Amendments: asset resolution tests, failure taxonomy and rejected experiment D1, optional-component degradation -----------------------------------------------------------------
TAX = dict(impl=["evaluation/phase8/failure_taxonomy.py"], tests=["tests/test_ai_failure_analysis.py"], evid=["docs/evaluation/ai-failure-taxonomy-and-d1.md"])
_TAX_GAP = ("Dev failure taxonomy: of 29 non-ok answerable dev queries only 2 are retrieval losses; 17 are answers withheld by the verifier (quotation or number mismatch) and 10 are wrong citation or an incomplete answer. "
            "Experiment D1 (answer multi-part questions part by part) was REJECTED (coverage 64.4% vs 66.7%, citation correctness 86.4% vs 91.9%). Targets remain NOT MET; the likely lever is a stronger local "
            "model (needs owner approval to download) and independent confirmation data")
for _line in (512, 515, 769):
    amend(_line, gap=_TAX_GAP, **TAX)
amend(517, impl=["backend/app/services/incident_service.py"], tests=["backend/tests/test_asset_resolution_security.py"],
      gap="Held-out correct abstention 94.1% baseline (16/17). Reports naming no equipment are refused deterministically; several written ids, ids registered only in another tenant, injected ids and model-invented ids are tested "
          "(a report naming several ids is routed to human review). Development weaknesses (sibling-model answers) remain in the default configuration")
amend(270, "V", "No optional layer is on the critical path: with the shared limiter store down, durable metrics failing, the metrics flusher pointed at a dead database, the log sink failing and the Prometheus endpoint "
      "raising, the core workflow (ask, extract, ticket, approval, submission) still completes; the delivery order put the core first (batches 1 to 8 before any optional item)",
      impl=["backend/app/connectors/ratelimit.py", "backend/app/observability/metrics.py"], tests=["backend/tests/test_core_survives_optional_components.py"], evid=["docs/planning/progress-tracker.md"])
amend(815, gap="Span events in the OpenTelemetry data model and W3C propagation exist; the SDK, an OTLP exporter and any receiver do not. Exact needs (docs/operations/observability.md): opentelemetry-sdk==1.45.2 and "
      "opentelemetry-exporter-otlp-proto-http==1.45.2 (small PyPI packages; the API 1.45.2 is already locked) and, only for a live demonstration, a collector or backend image. Owner approval required")
amend(659, gap="Automated axe (critical/serious/moderate/minor = 0) on 43 states in Microsoft Edge and 44 states in Google Chrome (2026-11-14, same author, same machine); no screen-reader audit; no conformance claim",
      evid=["evaluation/reports/phase6-closure/axe-results.json", "evaluation/reports/phase6-closure/axe-results-chrome.json"])


# ---- Amendment 2026-11-14: final validation report refreshed; no-unreproducible-figure audit ---------------------------------------------------------------------------------------
FVR = dict(tests=["tests/test_final_validation_report.py", "tests/test_readme_results.py"], evid=["docs/planning/final-validation-report.md"])
amend(37, "V", "Published figures (README results table, final validation report) are each tied to a command and an artifact or a labelled rerun instruction, and tests fail on drift; the rule itself cannot be tested exhaustively",
      impl=["scripts/generate_traceability.py", "evaluation/phase8/verify_baseline.py"], **FVR)
amend(1365, "V", "Final implementation and validation report refreshed (same-author evidence; full acceptance not achieved); counts checked against the register by test", impl=["scripts/generate_v41_reconciliation.py"], **FVR)
# 2026-11-14: module 12 (Evaluation) gains a read-only registry endpoint; the requirement stays PARTIAL (observability has no trace ids)
amend(417, None, "Evaluation is now a read-only module endpoint (GET /api/v1/evaluation/registry over the evaluation_runs index, SELECT-only for application roles, metrics:read, paged, platform evidence not tenant data) beside the artifact report view; the Observability module is still partial (no trace ids; metrics are process-scoped)",
      impl=["backend/app/api/v1/ops_routes.py", "backend/app/evaluation_registry.py"], tests=[BT + "test_ops_routes.py::test_evaluation_registry_is_read_only_paged_and_authenticated", BT + "test_evaluation_registry.py"])
# 2026-11-14: benchmark reports index maps every Priority 3 item to a command and stored artifact (same-author evidence; targets NOT MET stay reported as such)
BRI = dict(tests=["tests/test_benchmark_reports_index.py"], evid=["docs/performance/benchmark-reports-index.md", "docs/performance/measured-performance.md"])
amend(241, "V", "Measured evidence exists for all six items (indexed with commands and artifacts); quality targets remain NOT MET and the manual-versus-automated comparison has no human timings; evidence is same-author", impl=["scripts/generate_v41_reconciliation.py"], **BRI)
amend(1347, "V", "Benchmark reports exist and are indexed (Phase 8, performance, recovery-rate, integration-success); results include unmet targets and are same-author", impl=["evaluation/phase8/run_experiment.py"], **BRI)
# 2026-11-14 correction: the earlier "no trace ids" wording was stale. X-Trace-ID, trace_id log field, W3C traceparent and parent-linked span events exist (docs/operations/observability.md; backend/tests/test_observability.py, test_spans.py). The OpenTelemetry SDK/exporter belongs to the optional L815, not here.
amend(417, None, "Evaluation is a read-only module endpoint (GET /api/v1/evaluation/registry plus the artifact report view; platform-wide evidence, metrics:read) and Observability has trace ids (X-Trace-ID, W3C traceparent), parent-linked span events and metrics; remaining: no module-by-module evidence mapping for all 13 modules, evaluation runs are not managed through the API, and no OpenTelemetry SDK or exporter (optional, L815)",
      tests=[BT + "test_observability.py", BT + "test_spans.py"], evid=["docs/operations/observability.md", "docs/performance/benchmark-reports-index.md"])
# 2026-11-14: module-by-module evidence map covers all 13 core modules (code, tests, stored evidence); L417 only lists the modules and the modular-monolith shape. Evaluation runs stay offline scripts (documented limit); OpenTelemetry is the optional L815.
amend(417, "V", "All 13 modules present and mapped (docs/architecture/core-modules-evidence-map.md); limits documented: evaluation runs are offline scripts with a read-only registry, no OpenTelemetry SDK (optional L815); same-author evidence",
      impl=["backend/app", "workers/run_worker.py"], tests=["tests/test_core_modules_evidence_map.py"], evid=["docs/architecture/core-modules-evidence-map.md"])
# 2026-11-14: retrospective gate records for Phases 1-4 added (labelled reconstruction, not contemporaneous approval); L1229 stays PARTIAL because Phase 1 has no stored test/review evidence and no phase has a recorded formal approval
amend(1229, None, "Retrospective records for Phases 1-4 exist (docs/planning/retrospective-phase-gates-1-4.md; reconstruction, not contemporaneous approval). Phases 2-4 have stored test manifests and documents; Phase 1 has no stored test or review evidence; no formal phase-end approval was recorded for any phase; Phases 5-8 gate documents exist separately; Phases 9-10 outstanding",
      tests=["tests/test_retrospective_phase_gates.py"], evid=["docs/planning/retrospective-phase-gates-1-4.md"])

# 2026-11-15: reconcile existing evidence without changing requirement status.
# L659 starts two requirements. Match the complete range for Accessibility.
_accessibility = next(e for e in E if e["lines"] == (659, 660))
_accessibility["gap"] = "Automated axe found zero violations across 43 Edge states and 44 Chrome states. A manual keyboard and screen-reader walkthrough is pending. The owner may conduct it under EAOP 08E."
_accessibility["evidence"].append("evaluation/reports/phase6-closure/axe-results-chrome.json")
amend(835, gap="Optional RabbitMQ was deliberately omitted. The Prometheus text endpoint, example scrape configuration and Grafana dashboard exist. Dashboard queries were checked against recorded metrics. Neither service was run and the dashboard was never imported.",
      evid=["docs/operations/observability.md", "infrastructure/monitoring/grafana-dashboard.json", "tests/test_grafana_dashboard.py"])
amend(1276, gap="The local v4.1.0-local-rc1 tag marks an engineering checkpoint. A tested versioned release has yet to be published.",
      evid=["docs/planning/final-completion-report.md"])
amend(1363, gap="The local v4.1.0-local-rc1 tag marks an engineering checkpoint. A tested versioned release has yet to be published.",
      evid=["docs/planning/final-completion-report.md"])

# 2026-11-15: local publication and validation procedures. External and deployment evidence remains outstanding.
_HANDOFF = "docs/planning/publication-handoff.md"
amend(39, gap="The local publication handoff is complete. It records the owner approval, identity, permissions, publication and release procedures. Account verification and repository-side controls remain pending.",
      evid=[_HANDOFF])
amend(841, gap="The local runbook consolidates all twelve items, including acceptance, fault injection and benchmarks. Backup and restore were validated for disposable demo databases. Equivalent backup and restore evidence for the full container deployment remains outstanding.",
      evid=["docs/operations/local-runbook.md", "docs/planning/final-validation-report.md"])
amend(1282, gap="The publication handoff records the local and remote pre-publication audit steps. The repository-side checks require an authorized GitHub repository.",
      evid=[_HANDOFF])

# 2026-11-15: owner-session validation of backup and clean restore for the full disposable Compose stack.
amend(841, "V", "The local runbook covers all twelve operational items. The full Compose drill restored a checksummed backup into a clean database on a separate disposable project and verified revision 0017, tenant counts, API state, restricted-role grants, forced RLS, and cleanup.",
      impl=["docker-compose.app.yml"], tests=["tests/test_delivery_documents.py"],
      evid=["docs/operations/full-compose-backup-restore.md"])

# 2026-11-15: reconcile the Phase 9-10 exit evidence without changing either status.
PHASE_EXIT = "docs/planning/phase-9-10-exit-evidence.md"
amend(1138, None,
      "Roadmap outputs exist through Phase 8 and local portions of Phases 9-10. Open: GitHub identity and CI execution, the manual business comparison, "
      "Phase 9 provider validation, and the Phase 10 candidate security disposition, GitHub audit and tested versioned release. See the exit evidence matrix.",
      evid=[PHASE_EXIT, "docs/architecture/cloud-portability.md", "evaluation/terraform/fmt-check.txt",
            "docs/planning/publication-handoff.md", "docs/planning/final-validation-report.md"])
amend(1229, None,
      "Local technical gates exist for Phases 2-8 with varying coverage. No Phase 1 exit test, integration or security record or separate Phase 2-3 exit "
      "security review was located. Phase 9-10 exits are incomplete. Retrospective notes and later validation cannot establish earlier actions, and scoped "
      "technical gates do not establish formal owner approval. Part 31 requires the actions at each phase end and does not prescribe universal signatures.",
      evid=[PHASE_EXIT, "docs/security/phase5-closure-gate.md", "docs/phase7/phase7-closure-gate.md",
            "docs/evaluation/phase8-heldout-disposition.md"])


# 2026-11-15: validate the unchanged Terraform example with the owner-approved AWS provider.
_TERRAFORM_EVIDENCE = "evaluation/terraform/provider-validation.md"
_TERRAFORM = dict(
    impl=["infrastructure/terraform"],
    tests=["tests/test_delivery_documents.py::test_cloud_and_infrastructure_documents_do_not_claim_a_deployment_or_validation_that_did_not_happen"],
    evid=[_TERRAFORM_EVIDENCE],
)
_TERRAFORM_RESULT = "Terraform 1.17.2 passed local formatting and schema validation with AWS 5.100.0 on Windows amd64. No cloud plan or deployment was attempted."
for _line in (262, 323, 868, 1263, 1358):
    amend(_line, "V", _TERRAFORM_RESULT, **_TERRAFORM)
amend(859, gap="No cloud resources were provisioned. AWS, Azure and Google Cloud adaptation is documented as design analysis. The illustrative AWS example also passed local schema validation.",
      evid=[_TERRAFORM_EVIDENCE])
amend(1138, gap="Phase 9 Terraform validation passed locally. GitHub identity and CI, the manual business comparison, and Phase 10 candidate security disposition, GitHub audit and tested versioned release remain open.",
      evid=[_TERRAFORM_EVIDENCE])
amend(1229, gap="Phases 2-8 have scoped local gates and Phase 9 Terraform validation passed. Phase 1 exit test, integration and security records and separate Phase 2-3 exit security reviews remain missing. "
      "Complete Phase 9-10 exit records are outstanding. Current checks do not establish historical actions or complete phase approval.",
      evid=[_TERRAFORM_EVIDENCE])

# 2026-11-15: document the local security disposition for the Phase 10 candidate.
_PHASE_10_SECURITY = "docs/planning/phase-10-candidate-security-disposition.md"
amend(1138, gap="Phase 9 Terraform validation passed locally. The Phase 10 candidate security review is documented with a NOT READY disposition. "
      "GitHub identity and CI, the manual business comparison, GitHub audit and tested versioned release remain open.",
      evid=[_PHASE_10_SECURITY])
amend(1229, gap="The Phase 10 candidate has a documented local security review. Phase 1 exit test, integration and security records, "
      "separate Phase 2-3 exit security reviews and complete Phase 9-10 exit evidence remain outstanding. "
      "Current checks do not establish historical actions, independent acceptance or owner approval.",
      evid=[_PHASE_10_SECURITY])
