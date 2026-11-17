"""Requirements catalogue for the V4.1 specification: the single source for the traceability matrix.

Each entry: id (R<part>.<n>), spec part, title, category, acceptance criterion, implementation components, test cases,
evidence artifacts, status and an outstanding defect or limitation. Status vocabulary:
  verified            implemented AND covered by at least one automated test AND backed by an evidence artifact
  partially verified  implemented, but verification is incomplete, indirect or only of part of the requirement
  implemented         code exists but there is no (or no adequate) automated verification
  not implemented     not built yet (planned phase noted)
`scripts/generate_traceability.py` refuses to mark a requirement verified without a test and an evidence path, and checks that
every referenced file and test function exists. Existence of code alone never makes a requirement complete.
"""

UAT_A = "tests/acceptance/test_uat_customer_a.py"
UAT_B = "tests/acceptance/test_uat_customer_b.py"
E2E_REL = "tests/acceptance/test_end_to_end_reliability.py"
FI = "tests/fault_injection/test_fault_injection.py"
REL = "tests/fault_injection/test_additional_reliability.py"
BT = "backend/tests/"
FE = "frontend/e2e/"
UAT_REP = ["evaluation/customer-acceptance/deterministic/uat-report.json", "evaluation/customer-acceptance/real/uat-report.json"]
FI_REP = ["evaluation/failure-reports/phase7/fi-report.json"]
GATE = "evaluation/reports/phase7-gate/manifest.json"
P3 = "evaluation/reports/phase3/SUMMARY.md"
P4 = "evaluation/reports/phase4-remeasure/README.md"

V, PV, IM, NI = "verified", "partially verified", "implemented", "not implemented"


def R(id_, part, title, cat, accept, impl, tests, evid, status, note=""):
    return {"id": id_, "part": part, "title": title, "category": cat, "acceptance": accept, "implementation": impl,
            "tests": tests, "evidence": evid, "status": status, "limitation": note}


REQUIREMENTS = [
    # ---- Part 2 / 3 / 33: non-negotiable rules, license, provenance ---------------------------------------------------------------
    R("R2.1", 2, "Zero mandatory paid services; local-first operation", "project rules", "Core platform runs with local PostgreSQL, Ollama and Sentence Transformers only",
      ["docker-compose.yml", "backend/app/ai/ollama_llm.py", "backend/app/ai/embeddings.py", "docs/deployment/accepted-limitations.md"], [BT + "test_real_ai.py"],
      ["evaluation/reports/phase7-gate/manifest.json"], PV, "No automated check asserts the absence of paid dependencies; verified by inspection of requirements files and the Phase 7 manual end-to-end runs."),
    R("R2.2", 2, "Accurate Git authorship, no AI watermarks or co-author trailers", "project rules", "All commits authored by the verified identity; no promotional attribution",
      ["README.md", "CHANGELOG.md"], [], ["evaluation/reports/phase7-gate/manifest.json"], PV, "Verified by git log inspection at each gate, not by an automated test."),
    R("R3.1", 3, "Proprietary source-visible license present", "project rules", "LICENSE file matches the approved text", ["LICENSE", "THIRD_PARTY_NOTICES.md"], [], ["LICENSE"], PV,
      "Presence verified by inspection; the license has not been legally reviewed."),
    # ---- Part 4/5: priorities, stack ----------------------------------------------------------------------------------------------
    R("R5.1", 5, "Preferred stack (FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL+pgvector, React/TypeScript/Vite, Pytest/Vitest/Playwright)", "architecture",
      "Components in use and runnable", ["backend/app/main.py", "backend/migrations/versions/0001_initial_schema.py", "frontend/src/App.tsx", "frontend/playwright.config.ts"],
      [BT + "test_smoke_and_ingestion.py", "frontend/src/pages/pages.test.tsx", FE + "auth-and-roles.spec.ts"], [GATE], V),
    R("R5.2", 5, "CPU-only inference chosen after hardware inspection", "AI", "Hardware recorded; model fits CPU/RAM", ["scripts/capture_hardware.py", "scripts/ollama_ctl.py"],
      ["tests/test_hardware_capture.py"], [P3], V, "One hardware profile (i7-1165G7, 15.7 GB) only."),
    # ---- Part 6: customer discovery ---------------------------------------------------------------------------------------------------
    R("R6.1", 6, "Fictional customer discovery documents", "delivery", "docs/customer-discovery complete with fictional assumptions labelled",
      ["docs/customer-discovery/apex-industrial.md", "docs/customer-discovery/meridian-fleet.md"], ["tests/test_delivery_documents.py"], ["docs/customer-discovery/README.md"], V,
      "Fictional by design and labelled as assumptions; no real interviews exist; same-author documents."),
    R("R6.2", 6, "Requirements-to-solution traceability matrix", "delivery", "Every major requirement maps to need, implementation, component, test, acceptance criterion, evidence",
      ["scripts/generate_traceability.py", "scripts/traceability_data.py"], ["tests/test_traceability.py"],
      ["scripts/traceability_data.py", "docs/customer-delivery/02-requirements-to-solution-matrix.md"], PV, "'Customer need' is expressed through the specification part; the fictional discovery documents (R6.1) that would supply real needs, now exist (docs/customer-discovery), but the matrix is generated from the 85-item provisional catalogue, not from all 238 requirements."),
    # ---- Parts 7/8: customer scenarios ----------------------------------------------------------------------------------------------------
    R("R7.1", 7, "Apex end-to-end workflow (report -> evidence-grounded explanation -> structured issue -> ticket -> approval -> mock submission -> external id -> audit -> metrics)", "UAT",
      "All 14 workflow steps demonstrated through the real API and UI", ["backend/app/api/v1/domain_routes.py", "backend/app/workflows/ticket_service.py", "frontend/src/pages/IncidentsPage.tsx"],
      [UAT_A + "::test_uat_a06_approved_ticket_submission", E2E_REL + "::test_apex_end_to_end_reliability", FE + "workflows.spec.ts"], UAT_REP + [GATE], V,
      "Real-AI runs show the review gate sends a large share of incidents to a human (about 75% in the Phase 3/4 data)."),
    R("R8.1", 8, "Meridian end-to-end workflow as a separate tenant through configuration only", "UAT", "All Meridian workflow steps demonstrated; no Meridian-specific code in shared services",
      ["onboarding/meridian.json", "scripts/onboard_tenant.py", "backend/app/profile/engine.py"], [UAT_B + "::test_uat_b_meridian_uses_the_same_application_and_no_customer_code", E2E_REL + "::test_meridian_end_to_end_reliability", BT + "test_meridian.py"],
      UAT_REP, V, "Apex and Meridian retain two execution paths (documented technical debt)."),
    # ---- Part 9: architecture ---------------------------------------------------------------------------------------------------------------
    R("R9.1", 9, "Modular monolith with background worker; PostgreSQL authoritative state; pgvector retrieval; transactional outbox", "architecture", "Single deployable API + worker; outbox events drive submission",
      ["backend/app", "workers/run_worker.py", "backend/app/workflows/worker.py"], [BT + "test_workflow.py", REL + "::test_rel04_recovery_after_api_process_restart"], FI_REP, V),
    R("R9.2", 9, "Core modules: auth, tenants, configuration, connectors, ingestion, retrieval, AI, incidents, workflow, audit, observability, evaluation, dashboard", "architecture",
      "Each module exists and is exercised", ["backend/app/api/v1", "backend/app/profile", "backend/app/observability", "frontend/src/pages"], [BT + "test_ops_routes.py", BT + "test_observability.py"],
      [GATE], PV, "Evaluation is a set of scripts and artifacts plus a read-only dashboard, not a managed service (see R21.x)."),
    # ---- Part 10: onboarding ------------------------------------------------------------------------------------------------------------------
    R("R10.1", 10, "New customer configurable without modifying the core application", "onboarding", "Tenant onboarded through public APIs and configuration only",
      ["scripts/onboard_tenant.py", "backend/app/profile/service.py", "backend/app/api/v1/profile_routes.py"], [UAT_B + "::test_uat_b01_second_tenant_onboarding", BT + "test_meridian.py"], UAT_REP, V),
    R("R10.2", 10, "Customer-specific schema/field mappings and workflow policies", "onboarding", "CSV/JSON mappings, categories, signals, priority rules and ticketing contract configured per tenant",
      ["backend/app/profile/schema.py", "backend/app/connectors/clients.py"], [UAT_B + "::test_uat_b02_customer_specific_schema_mapping", BT + "test_profile_engine.py"], UAT_REP, V),
    R("R10.3", 10, "Configuration validation and onboarding health checks", "onboarding", "Invalid profiles rejected; health checks derived from real configuration",
      ["backend/app/api/v1/ops_routes.py", "frontend/src/pages/OnboardingPage.tsx"], [BT + "test_ops_routes.py", BT + "test_profile_engine.py", FE + "admin-config-and-quality.spec.ts"], UAT_REP, V),
    R("R10.4", 10, "Tenant creation, membership and role assignment", "onboarding", "Platform admin creates tenants; tenant admins manage members; no self-escalation",
      ["backend/app/api/v1/core_routes.py", "backend/migrations/versions/0002_memberships_rls.py"], [BT + "test_membership_rls.py", BT + "test_identity_security.py"], ["docs/security/identity-tables.md"], V),
    # ---- Part 11: integrations ---------------------------------------------------------------------------------------------------------------------
    R("R11.1", 11, "Reusable connectors for mock CRM, inventory, ticketing and REST APIs; mock APIs with configurable failures", "integration",
      "Connectors work against local mocks; mocks inject 503/429/timeout/malformed/lost-response/400", ["backend/app/connectors", "mock-services"],
      [BT + "test_meridian.py", UAT_B + "::test_uat_b05_correct_customer_api_submission", FI], UAT_REP + FI_REP, V),
    R("R11.2", 11, "Timeouts, retries, exponential backoff, error classification", "integration", "Transient vs permanent classification; bounded timeouts; backoff and dead-letter",
      ["backend/app/connectors/http.py", "backend/app/workflows/worker.py"], [FI, BT + "test_workflow.py", BT + "test_observability.py::test_connector_failures_retries_and_denials_are_classified"], FI_REP, V),
    R("R11.3", 11, "Idempotency", "integration", "A lost response and replays create exactly one external ticket", ["backend/app/workflows/worker.py", "mock-services/ticketing/ticketing_app.py"],
      [BT + "test_control_mutations.py", UAT_A + "::test_uat_a07_duplicate_prevention", FI + "::test_fi04_malformed_response_after_server_side_create"], FI_REP + UAT_REP, V),
    R("R11.4", 11, "CSV, webhook connectors, connector authentication, pagination, rate limiting, schema validation, health checks", "integration",
      "Each capability implemented and tested", ["backend/app/connectors", "backend/app/api/v1/ops_routes.py"], [BT + "test_ops_routes.py"], [], PV,
      "Connector health reports configuration and delivery results, not a live probe. CSV/webhook connector kinds exist as names only; pagination and per-connector rate limiting are not implemented; authentication is an API-key header."),
    # ---- Part 12: document ingestion ---------------------------------------------------------------------------------------------------------------------
    R("R12.1", 12, "Ingestion of PDF, CSV and JSON with parsing, normalization and validation", "retrieval", "Supported types ingested into passages; unsupported types and oversize files refused",
      ["backend/app/ingestion/parsers.py", "backend/app/ingestion/service.py"], [BT + "test_smoke_and_ingestion.py", UAT_A + "::test_uat_a01_document_ingestion", BT + "test_resource_limits.py"], UAT_REP, V,
      "REST API records and webhook payloads as ingestion sources are not implemented."),
    R("R12.2", 12, "Content hashing, duplicate detection, version tracking, idempotent concurrent ingestion", "retrieval", "Identical content reported duplicate; changed content becomes a new version; races resolve safely",
      ["backend/app/ingestion/service.py"], [FI + "::test_fi09_duplicate_ingestion", FI + "::test_fi09b_forced_ingestion_race"], FI_REP, V),
    R("R12.3", 12, "Source provenance (page numbers, record identifiers)", "retrieval", "Every passage carries page or record id and is cited with it", ["backend/app/ingestion/parsers.py", "backend/app/retrieval/search.py"],
      [UAT_A + "::test_uat_a01_document_ingestion", UAT_B + "::test_uat_b02_customer_specific_schema_mapping"], UAT_REP, V),
    R("R12.4", 12, "Reprocessing and reindexing", "retrieval", "Atomic reindex between embedding models with verification", ["scripts/reindex_embeddings.py", "backend/app/retrieval/reindex.py"],
      [BT + "test_embedding_profiles.py", BT + "test_real_ai.py::test_reindex_deterministic_tenant_to_minilm"], ["evaluation/reports/phase3/reindex-apex-industrial.json"], V),
    R("R12.5", 12, "Document deletion and retry handling for ingestion jobs", "retrieval", "Documents can be deleted; ingestion jobs retried",
      ["backend/app/ingestion/lifecycle.py", "backend/app/ingestion/jobs.py", "backend/app/ingestion/sources.py"],
      [BT + "test_document_lifecycle.py", BT + "test_ingestion_jobs.py", BT + "test_source_ingestion.py"],
      ["docs/planning/batch8-report.md", "docs/planning/batch9-report.md", "docs/planning/batch10-report.md", "evaluation/demo-runs/20261113-075909-0569/report.json"], V),
    # ---- Part 13: RAG ---------------------------------------------------------------------------------------------------------------------------------------
    R("R13.1", 13, "Chunking, embeddings, vector index, full-text search, hybrid retrieval, tenant-aware filtering", "retrieval", "Hybrid retrieval returns only the tenant's current passages",
      ["backend/app/retrieval/search.py", "backend/migrations/versions/0001_initial_schema.py"], [BT + "test_smoke_and_ingestion.py", BT + "test_security.py", UAT_A + "::test_uat_a02_evidence_grounded_retrieval"], UAT_REP + [P3], V,
      "Recall@5 saturates on the small synthetic corpus; optional reranking (R13.5) is not implemented."),
    R("R13.2", 13, "Evidence-grounded answers with citation generation and verification", "AI", "Every citation is a verbatim quote of a current tenant-owned passage; unsupported identifiers and numbers are withheld",
      ["backend/app/ai/rag.py", "backend/app/ai/safeguards.py"], [BT + "test_ai_safeguards.py", BT + "test_rag_incidents.py", BT + "test_real_ai.py"], UAT_REP + [P3, P4], PV,
      "Citation correctness: 89.3-92.6% (Phase 3/4, 95% target NOT MET); on the Phase 8 development split 85.7% baseline and 91.9% with the development candidate (NOT MET); held-out evaluation not yet run."),
    R("R13.3", 13, "Insufficient-evidence handling; never fabricate citations", "AI", "Out-of-scope questions get an insufficient-evidence response with no citations", ["backend/app/ai/rag.py"],
      [UAT_A + "::test_uat_a02_evidence_grounded_retrieval", BT + "test_real_ai.py::test_real_unanswerable_question_is_not_fabricated"], UAT_REP + [P3], PV, "6 of 8 unanswerable questions refused in the Phase 3/4 measurements; on the Phase 8 development split correct abstention 60.9% baseline and 95.7% (22/23) with the development candidate (dev only, observed target met, interval overlaps); held-out evaluation not yet run."),
    R("R13.4", 13, "Retrieved documents treated as untrusted; model text cannot authorize actions", "security", "Prompt-injection passages quarantined; no action created from document text",
      ["backend/app/ai/safety.py"], [FI + "::test_fi08_prompt_injection", BT + "test_ai_safeguards.py"], FI_REP, V),
    R("R13.5", 13, "Optional reranking", "retrieval", "Reranker available", [], [], [], NI, "Deliberately not built; a reranker needs approval (governance) and an evaluation."),
    R("R13.6", 13, "Local inference with Ollama and Sentence Transformers", "AI", "Approved models run locally and are pinned", ["backend/app/ai/ollama_llm.py", "backend/app/ai/embeddings.py", "scripts/fetch_models.py"],
      [BT + "test_real_ai.py"], UAT_REP + [P3], V, "Only qwen2.5:1.5b and all-MiniLM-L6-v2 were evaluated."),
    # ---- Part 14: incident intelligence ---------------------------------------------------------------------------------------------------------------------------
    R("R14.1", 14, "Validated structured incident schema (tenant, asset, category, symptoms, related incidents, priority, citations, recommended action, review status)", "AI",
      "Model output must validate; invalid output falls back or is rejected", ["backend/app/schemas/incident.py", "backend/app/services/incident_service.py"],
      [UAT_A + "::test_uat_a04_structured_ticket_generation", REL + "::test_rel03_invalid_structured_ai_output", BT + "test_rag_incidents.py"], UAT_REP + FI_REP, V,
      "Extraction schema validity 23/24 on the Phase 3/4 report set (one hallucinated asset rejected)."),
    R("R14.2", 14, "Related (historical) incident matching", "AI", "Same-asset history listed first from the tenant's own records", ["backend/app/services/incident_service.py"],
      [UAT_A + "::test_uat_a03_historical_incident_matching"], UAT_REP, V),
    R("R14.3", 14, "Deterministic business rules for priority", "AI", "Priority never decided by the model", ["backend/app/ai/rules.py", "backend/app/profile/engine.py"],
      [BT + "test_apex_compat.py", BT + "test_profile_engine.py"], UAT_REP, V, "Priority depends on the model-extracted category (observed to change priority in the Meridian smoke run)."),
    R("R14.5", 14, "Numeric measurements used for priority are traceable to the report (value, unit, source, evidence span, status); unsupported values are never accepted as verified", "AI safety",
      "V8 trust policy (supersedes the V7 wording below): free-text and LLM values are unverified candidates; only signed-simulation or human-verified observations are eligible. Earlier V7 layer: a model-proposed measurement is used only when the report states it with the right unit for the incident's own asset, without a contradicting reading and outside instruction-like text; otherwise it is quarantined with the reason recorded and the incident is held for human review; genuine values and real P1 incidents are unchanged",
      ["backend/app/ai/measurements.py", "backend/app/services/incident_service.py", "backend/migrations/versions/0007_incident_measurements.py"],
      [BT + "test_numeric_safety.py", BT + "test_numeric_evidence.py", BT + "test_numeric_structural_v6.py", BT + "test_numeric_boundary_v7.py", BT + "test_measurement_trust_v8.py", BT + "test_provenance_closure_v8.py", BT + "test_phase8_quality.py::test_extraction_drops_unsupported_numbers_and_routes_to_review", BT + "test_phase8_quality.py::test_a_genuine_p1_is_not_suppressed"],
      ["docs/evaluation/numeric-safety-remediation.md", "docs/evaluation/numeric-safety-hardening-v5.md", "docs/evaluation/numeric-safety-hardening-v6.md", "docs/evaluation/numeric-safety-hardening-v7.md", "docs/evaluation/numeric-safety-architecture-v8.md", "docs/evaluation/numeric-safety-provenance-closure-v8.md", "evaluation/reports/safety/final-v8.json"], PV,
      "Author-built evidence only: V8 architecture: only signed-simulation or human-verified observations drive numeric priority; the frozen safety-v8 run (kept as FAILED) met every safety gate except complete priority-decision provenance (63/64); a targeted provenance-envelope closure was then verified by targeted and regression tests only; class E (authenticated sensor) not implemented; the model itself still hallucinates numbers."),
    R("R13.7", 13, "Questions that name an identifier absent from the cited evidence, or that try to override the evidence/tenant/approval rules, are refused", "AI safety",
      "Entity gate and override gate refuse such questions without raising false refusals", ["backend/app/ai/rag.py", "backend/app/ai/safety.py", "backend/app/retrieval/entities.py"],
      [BT + "test_phase8_quality.py::test_question_override_gate_refuses_rule_override_attempts_only", BT + "test_phase8_quality.py::test_identifier_extraction_and_model_field"],
      ["evaluation/reports/phase8/exp-E8b-20261112T075317Z/qa_rep1.jsonl", "docs/evaluation/phase8-optimization-log.md"], PV,
      "Development split only (23 unanswerable queries, 0 false refusals on 87 answerable); gate patterns were written against dev phrasing; off by default; attribute mix-ups (right model, wrong parameter) are not caught."),
    R("R14.4", 14, "Review status and human-review gate", "workflow", "needs_review blocks ticketing; acceptance never verifies unsupported claims; unregistered assets blocked before release",
      ["backend/app/workflows/ticket_service.py", "backend/app/workflows/worker.py", "backend/app/api/v1/domain_routes.py"], [BT + "test_review_gate.py", UAT_B + "::test_uat_b03_fleet_issue_extraction"], UAT_REP, V,
      "About 75% of incidents require human review with the approved model (operational limitation, intentionally not relaxed)."),
    # ---- Part 15: approval workflows ---------------------------------------------------------------------------------------------------------------------------------
    R("R15.1", 15, "Human approval before external submission; rejected tickets never submitted; retries cannot bypass approval", "workflow",
      "No external call without a recorded approval; worker re-verifies", ["backend/app/workflows/ticket_service.py", "backend/app/workflows/worker.py"],
      [UAT_A + "::test_uat_a05_unapproved_submission_blocked", BT + "test_workflow.py", BT + "test_control_mutations.py"], UAT_REP + FI_REP, V),
    R("R15.2", 15, "Role-based approval and separation of duties", "security", "Only supervisors/admins decide; authors cannot approve their own ticket", ["backend/app/core/rbac.py", "backend/app/workflows/ticket_service.py"],
      [UAT_B + "::test_uat_b04_ticket_approval", BT + "test_api_namespace_security.py"], UAT_REP, V),
    R("R15.3", 15, "Idempotent submission and duplicate prevention", "workflow", "At most one external ticket per ticket under retries, lost responses and concurrency", ["backend/app/workflows/worker.py"],
      [UAT_A + "::test_uat_a07_duplicate_prevention", FI + "::test_fi06_concurrent_approvals", E2E_REL], UAT_REP + FI_REP, V),
    R("R15.4", 15, "Retry and recovery", "reliability", "Transient failures recover automatically; permanent failures are reported and manually retryable", ["backend/app/workflows/worker.py"],
      [UAT_A + "::test_uat_a08_api_failure_recovery", UAT_B + "::test_uat_b07_failure_recovery", FI + "::test_fi01_http_503_outage", FI + "::test_fi07_worker_interruption"], FI_REP + UAT_REP, V),
    R("R15.5", 15, "Nine ticket states, valid transitions, editable drafts, recorded decisions, audit history", "workflow", "State machine enforced; every transition audited", ["backend/app/workflows/state_machine.py", "backend/app/audit/service.py"],
      [BT + "test_workflow.py", BT + "test_control_mutations.py"], UAT_REP, V),
    R("R15.6", 15, "Concurrent approvals tested", "reliability", "Eight simultaneous approvals produce one winner", [FI], [FI + "::test_fi06_concurrent_approvals"], FI_REP, V),
    # ---- Part 16: security -------------------------------------------------------------------------------------------------------------------------------------------------
    R("R16.1", 16, "Tenant authorization, tenant-aware retrieval, row-level security", "security", "Zero successful cross-tenant accesses across APIs, retrieval, workflows and external systems", ["backend/migrations/versions/0001_initial_schema.py", "backend/app/database/session.py"],
      [FI + "::test_fi05_unauthorized_cross_tenant_access", UAT_B + "::test_uat_b06_cross_tenant_access_denied", BT + "test_security.py", BT + "test_api_namespace_security.py"], FI_REP + UAT_REP, V,
      "The tenant context is trusted application input; a fully compromised application process could set it (documented in identity-tables.md)."),
    R("R16.2", 16, "Authentication, RBAC for the five roles, negative authorization tests on every route", "security", "Role x route matrix has zero violations", ["backend/app/api/deps.py", "backend/app/core/rbac.py"],
      [BT + "test_api_namespace_security.py", BT + "test_jwt_and_throttle.py", BT + "test_security.py"], ["docs/phase6/phase6-closure-gate.md"], V),
    R("R16.3", 16, "Secure credential handling and no committed secrets", "security", "Secrets only by environment reference; secret scan clean; test credentials confined and refused in production", ["scripts/secret_scan.py", "backend/app/core/production_guard.py"],
      ["tests/test_environment_guards.py"], ["docs/security/test-credentials.md"], V, "Pattern/known-value scan only, not a history-wide scanner."),
    R("R16.4", 16, "Input validation and upload restrictions; rate limiting", "security", "Typed validation, size and type limits, bounded concurrency, login throttle", ["backend/app/core/limits.py", "backend/app/api/v1/core_routes.py"],
      [BT + "test_resource_limits.py", BT + "test_jwt_and_throttle.py"], ["docs/security/rate-limiting-limitations.md"], PV, "Throttling and limits are per process; distributed rate limiting is required before production."),
    R("R16.5", 16, "Audit logging (append-only)", "security", "Every consequential action recorded; trail cannot be altered", ["backend/app/audit/service.py"], [BT + "test_control_mutations.py", UAT_A + "::test_uat_a06_approved_ticket_submission"], UAT_REP, V),
    R("R16.6", 16, "Outbound connector security (SSRF)", "security", "No tenant-configurable connector can reach an unauthorized destination on any execution path", ["backend/app/connectors/egress.py"],
      [BT + "test_connector_egress.py"], ["docs/security/connector-egress.md", "docs/phase6/phase6-closure-gate.md"], PV,
      "Application-level only; network-level egress restrictions are required in production."),
    R("R16.7", 16, "Prompt-injection defenses", "security", "Poisoned passages quarantined", ["backend/app/ai/safety.py"], [FI + "::test_fi08_prompt_injection"], FI_REP, V),
    # ---- Part 17: backend ----------------------------------------------------------------------------------------------------------------------------------------------------------
    R("R17.1", 17, "Required API namespaces, typed contracts, pagination, standardized errors, OpenAPI", "architecture", "All required namespaces exist and are covered by the route table", ["backend/app/main.py", "backend/app/api/v1"],
      [BT + "test_api_contract.py", BT + "test_api_response_schemas.py", BT + "test_api_response_contract.py", BT + "test_api_error_contract.py", BT + "test_api_namespace_security.py"],
      [GATE, "evaluation/api-quality/api-quality-evidence.json", "docs/api/response-inventory.md"], V),
    R("R17.2", 17, "Migrations, transactions, constraints, indexes", "architecture", "Alembic migrations 0001-0008 apply cleanly (0008 verified up/down/reapply on a disposable database); constraints prove invariants; every tenant-scoped table has a tenant-leading index", ["backend/migrations/versions"], [BT + "test_api_contract.py", BT + "test_migration_0008_indexes.py", BT + "test_control_mutations.py", BT + "test_membership_rls.py"], [GATE, "evaluation/api-quality/api-quality-evidence.json", "evaluation/api-quality/index-query-plans.json"], V),
    R("R17.3", 17, "Required database entities (including ingestion jobs, evaluation runs, workflow executions, roles table)", "architecture", "All listed entities exist", ["backend/app/models/__init__.py"], [], [], PV,
      "Implemented: tenants, users, memberships, connectors, documents, versions, chunks (embeddings), incidents, tickets, approvals, outbox events, audit events, profiles. Not implemented as tables: roles (string column), ingestion jobs, evaluation runs (file artifacts), workflow executions (outbox events serve)."),
    # ---- Part 18: frontend -----------------------------------------------------------------------------------------------------------------------------------------------------------
    R("R18.1", 18, "13 required pages on React/TypeScript/Vite using real backend data", "frontend", "All 13 pages render against the real backend without console errors", ["frontend/src/nav.ts", "frontend/src/pages"],
      [FE + "auth-and-roles.spec.ts", "frontend/src/pages/pages.test.tsx"], ["docs/phase6/phase6-closure-gate.md", "docs/phase6/phase6-review-report.md"], V),
    R("R18.2", 18, "Responsive layout, loading/empty/error states, search, filtering, pagination, form validation", "frontend", "States exist and no horizontal overflow at 375 px", ["frontend/src/components/ui.tsx", "frontend/src/hooks/usePagedList.ts"],
      [FE + "admin-config-and-quality.spec.ts", FE + "documents-and-assistant.spec.ts", "frontend/src/pages/pages.test.tsx"], ["docs/phase6/phase6-closure-gate.md"], V),
    R("R18.3", 18, "Accessibility", "frontend", "No critical or serious automated violations; keyboard-operable critical workflow", ["frontend/src/components/ConfirmDialog.tsx"],
      [FE + "accessibility.spec.ts", FE + "keyboard-workflow.spec.ts"], ["evaluation/reports/phase6-closure/axe-results.json"], PV,
      "43 states audited with axe (0 violations), Edge only; no screen-reader audit; WCAG conformance is not claimed."),
    R("R18.4", 18, "No fabricated metrics displayed", "frontend", "Evaluation and overview figures come from artifacts or tenant records; targets labelled as targets", ["backend/app/api/v1/ops_routes.py", "frontend/src/pages/EvaluationPage.tsx"],
      [BT + "test_ops_routes.py", FE + "admin-config-and-quality.spec.ts"], ["docs/phase6/phase6-review-report.md"], V),
    # ---- Part 19: UAT -------------------------------------------------------------------------------------------------------------------------------------------------------------------
    R("R19.1", 19, "Customer A acceptance tests UAT-A01 to UAT-A08 with JSON and Markdown reports", "UAT", "All eight pass in deterministic and real-AI modes", [UAT_A, "tests/acceptance/conftest.py"],
      [UAT_A], UAT_REP + ["evaluation/customer-acceptance/deterministic/uat-report.md", "evaluation/customer-acceptance/real/uat-report.md"], V,
      "AI-dependent acceptance (A02-A04) rests on the real-model run, which uses an explicit threshold (2 of 3 grounded answers)."),
    R("R19.2", 19, "Customer B acceptance tests UAT-B01 to UAT-B07", "UAT", "All seven pass in deterministic and real-AI modes", [UAT_B], [UAT_B],
      UAT_REP + ["evaluation/customer-acceptance/deterministic/uat-report.md", "evaluation/customer-acceptance/real/uat-report.md"], V, "Meridian has no AI-quality benchmark (Phase 8)."),
    # ---- Part 20: fault injection ----------------------------------------------------------------------------------------------------------------------------------------------------------
    R("R20.1", 20, "FI-01 HTTP 503 outage", "reliability", "Retried automatically, one external ticket", [FI], [FI + "::test_fi01_http_503_outage"], FI_REP, V),
    R("R20.2", 20, "FI-02 HTTP 429 rate limiting", "reliability", "Retried automatically, one external ticket", [FI], [FI + "::test_fi02_http_429_rate_limiting"], FI_REP, V),
    R("R20.3", 20, "FI-03 Network timeout", "reliability", "Timeout classified transient; no duplicate", [FI], [FI + "::test_fi03_network_timeout"], FI_REP, V),
    R("R20.4", 20, "FI-04 Malformed API response", "reliability", "Replay with the idempotency key creates no second ticket", [FI], [FI + "::test_fi04_malformed_response_after_server_side_create"], FI_REP, V),
    R("R20.5", 20, "FI-05 Unauthorized cross-tenant access", "reliability", "40 attempts, 0 successes", [FI], [FI + "::test_fi05_unauthorized_cross_tenant_access"], FI_REP, V),
    R("R20.6", 20, "FI-06 Concurrent approvals", "reliability", "One winner among 8 concurrent approvals", [FI], [FI + "::test_fi06_concurrent_approvals"], FI_REP, V),
    R("R20.7", 20, "FI-07 Worker interruption", "reliability", "Lease expiry lets another worker resume; one external ticket", [FI], [FI + "::test_fi07_worker_interruption"], FI_REP, V),
    R("R20.8", 20, "FI-08 Prompt injection", "reliability", "Poisoned content quarantined; nothing created", [FI], [FI + "::test_fi08_prompt_injection"], FI_REP, V),
    R("R20.9", 20, "FI-09 Duplicate ingestion", "reliability", "One stored copy under sequential and concurrent uploads", [FI], [FI + "::test_fi09_duplicate_ingestion", FI + "::test_fi09b_forced_ingestion_race"], FI_REP, V),
    R("R20.10", 20, "FI-10 Database interruption", "reliability", "API 503, no external call, replay after restart, one ticket", [FI], [FI + "::test_fi10_database_interruption"], FI_REP, V,
      "Disruptive: stops the project's own PostgreSQL container; opt-in (RUN_DISRUPTIVE=1)."),
    R("R20.11", 20, "Additional dependency failures: LLM timeout/failure, embedding failure, invalid structured output, API restart", "reliability", "Honest withholding, 503 not 500, human-review fallback, no state lost", [REL],
      [REL], FI_REP, V, "These are REL-01 to REL-04, separate from the specification's FI identifiers."),
    # ---- Part 21: evaluation -----------------------------------------------------------------------------------------------------------------------------------------------------------------
    R("R21.1", 21, "Retrieval and generation metrics on labelled data (Recall@5, precision, citation correctness, groundedness, structured validity)", "AI", "Reported with denominators, methodology and actual measurements", ["evaluation/benchmarks/run_phase3.py", "evaluation/datasets/apex-eval-v1"],
      ["tests/test_hardware_capture.py"], [P3, P4], PV, "Single small synthetic dataset, author-written labels, no confidence intervals; 95% citation target NOT MET; harder multi-tenant dataset planned for Phase 8."),
    R("R21.2", 21, "Workflow, integration, recovery and isolation measures", "reliability", "Workflow completion, duplicates, recovery and isolation reported", ["evaluation/failure-reports", "evaluation/customer-acceptance"], [FI, UAT_A, UAT_B], FI_REP + UAT_REP, V),
    R("R21.3", 21, "Latency measurements (API, retrieval, LLM, end-to-end) with hardware recorded", "AI", "Median and p95 reported with hardware, model and repetitions", ["evaluation/benchmarks/run_phase3.py", "backend/app/observability/metrics.py"],
      [BT + "test_observability.py"], [P3, P4], PV, "Local single-machine measurements; the observability metrics are process-scoped."),
    R("R21.4", 21, "Manual-versus-automated comparison labelled as a simulated baseline", "AI", "Comparison with clear labelling", [], [], [], NI, "Not produced; planned for Phase 8."),
    # ---- Part 22: observability -------------------------------------------------------------------------------------------------------------------------------------------------------------------
    R("R22.1", 22, "Structured JSON logging, correlation ids, no secrets or sensitive content in logs", "observability", "Every request line has a correlation id; credentials, tokens and document text never appear", ["backend/app/observability/logging.py", "backend/app/main.py"],
      [BT + "test_observability.py"], ["evaluation/observability/README.md"], V),
    R("R22.2", 22, "Tenant-aware operational metrics (latency, retries, failures, review rate, submission outcomes, error classes)", "observability", "Metrics scoped to the tenant; no sensitive content", ["backend/app/observability/metrics.py", "backend/app/api/v1/ops_routes.py"],
      [BT + "test_observability.py"], ["evaluation/observability/README.md"], PV, "Process metrics reset on restart and cover only the API process; worker activity is durable only through the database and logs. Not production telemetry."),
    R("R22.3", 22, "OpenTelemetry traces; optional Prometheus and Grafana", "observability", "Trace ids exported", [], [], [], NI, "Correlation ids exist; no OpenTelemetry or Prometheus exporter is implemented (optional per the specification)."),
    # ---- Part 23-27: deployment, cloud, communication, testing, CI ---------------------------------------------------------------------------------------------------------------------
    R("R23.1", 23, "Reproducible local deployment with Docker Compose", "delivery", "A single documented command starts the stack", ["docker-compose.yml", "docker-compose.app.yml", "scripts/dev.py", "scripts/container_smoke.py"], ["tests/test_environment_guards.py"], ["evaluation/container-smoke/20261113-145441/report.md"], PV,
      "docker-compose.yml runs PostgreSQL for development; docker-compose.app.yml builds and runs the whole stack in containers (smoke-tested twice) with the deterministic AI backends only. Ollama integration from inside a container is untested."),
    R("R24.1", 24, "Cloud portability documentation and Terraform/OpenTofu examples", "delivery", "Documented and validated where feasible",
      ["docs/architecture/cloud-portability.md", "docs/architecture/deployment-tradeoffs.md", "infrastructure/terraform/main.tf"],
      ["tests/test_delivery_documents.py::test_cloud_and_infrastructure_documents_do_not_claim_a_deployment_or_validation_that_did_not_happen"],
      ["docs/architecture/cloud-portability.md", "infrastructure/terraform/README.md", "evaluation/terraform/provider-validation.md"], V,
      "The Terraform example passed local schema validation with AWS 5.100.0 on Windows amd64. Cloud portability mappings are design analysis. No cloud deployment was attempted."),
    R("R25.1", 25, "Customer-facing technical communication", "delivery", "Delivery documents complete",
      ["docs/customer-delivery/technical-walkthrough.md", "docs/architecture/diagrams.md", "docs/operations/deployment-runbook.md"], ["tests/test_delivery_documents.py"], ["docs/customer-delivery/01-customer-discovery-summary.md", "docs/customer-delivery/10-implementation-retrospective.md"], V,
      "Ten delivery documents, walkthrough script, diagrams and runbook for FICTIONAL customers; same-author documents; the walkthrough has not been presented."),
    R("R26.1", 26, "Automated tests: backend, frontend, e2e, security, fault injection, acceptance", "reliability", "All suites pass", ["tests", "backend/tests", "frontend/src", "frontend/e2e"], ["tests/test_traceability.py"], [GATE], V),
    R("R27.1", 27, "CI/CD with GitHub Actions within free allowances", "delivery", "Workflow runs and passes in CI", [".github/workflows/ci.yml"], [], [], PV, "The workflow file exists but has never run: nothing is pushed."),
    # ---- Parts 28-34: repository, README, demo, roadmap, definition of done, audit ----------------------------------------------------------------------------------------------------
    R("R29.1", 29, "README with a verified-results table (metric, actual, target, command, evidence)", "delivery", "Every row is a measured result with a command and an evidence path", ["README.md"], [], ["README.md"], PV, "Updated at each phase gate by hand; not machine-checked against the artifacts."),
    R("R30.1", 30, "Complete end-to-end demonstration reproducible", "delivery", "Scripted demo reproducible by a third party", ["docs/operations", "frontend/e2e/workflows.spec.ts"], [FE + "workflows.spec.ts", E2E_REL], [GATE], PV, "The 27-step demo script is a Phase 10 deliverable; the same flows are automated."),
    R("R33.1", 33, "Final GitHub audit and publication", "delivery", "Authorized publication of a tested release", [], [], [], NI, "Publication is a separate approval gate; nothing has been pushed or released."),
    R("R32.1", 32, "Definition of done checklist", "project rules", "All 37 items satisfied", [], ["tests/test_traceability.py"], [GATE], PV,
      "Items 20-25, 27, 35-37 and parts of 18, 21, 28 remain open (Docker deployment, CI, cloud portability, discovery and handover documents, publication)."),
]
