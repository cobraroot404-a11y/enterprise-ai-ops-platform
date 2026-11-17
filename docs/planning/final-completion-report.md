# V4.1 final completion report (local development, same-author evidence)

Scope: the authorised local work. **Full V4.1 acceptance was NOT achieved** (item 28). Nothing was pushed, merged, deployed, published or released; no remote exists; no paid or cloud service was used; the shared `eaop` database was never touched (revision `0006`). Same-author evidence throughout: nothing here is independent certification, and nothing is claimed production-ready.

## 1 and 2. Repository and state
Branch `feat/apex-vertical-slice`. Final full HEAD: the commit that contains this file (printed by `git rev-parse HEAD`; a file cannot name its own commit). A local annotated tag `v4.1.0-local-rc1` marks the integrated acceptance checkpoint (no release, no push). Working tree clean at the final commit.

## 3. Specification integrity
`docs/specification/ORIGINAL_MASTER_SPECIFICATION_V4.1.txt`, SHA-256 `b1c573e2c209ac68712b36851d56af0fb4c464509b422f96899761b6427760da`, verified at the start of every work package. The 238 original requirements, the 13 additional discovered requirements and the five catalogue-only additions stay distinguishable in `docs/specification/`; no original wording was rewritten.

## 4 to 8. Reconciliation (238 original requirements, regenerated from `scripts/v41_requirements_data.py`)
| Status | Count |
|---|---|
| Verified | **159** |
| Partial | **67** |
| Missing | **6** |
| Not evaluable | **6** |
Missing (6): OpenTelemetry (V41-22.02), Prometheus/Grafana (22.03), RabbitMQ/Prometheus/Grafana (23.02) (all optional, deliberately not implemented, see `docs/architecture/optional-infrastructure-decision.md`), optional Kubernetes examples (24.06), the tested versioned release as a published release (32.36, 34.32; needs owner approval to publish: only a local tag exists). Not evaluable (6): items that need a remote repository or a reviewer who does not exist (CI never ran, repository permissions, publication). "Verified" is the implementing engineer's assessment against the written criteria with the evidence cited per requirement.

## 9. Components implemented
Multi-tenant FastAPI backend and worker, PostgreSQL with forced row-level security, local RAG with citation verification, structured incidents with numeric-evidence trust boundaries, human verification and approvals, outbox ticket submission, audited deletion, durable ingestion with retained originals and source reprocessing, REST pull, CSV and signed-webhook ingestion, React UI (13 pages, including connector, webhook-endpoint and live-probe screens), mock external systems, one-command demonstration launcher, containerised stack, evaluation registry, comparison protocol, documentation and customer-facing delivery package.

## 10. Major architectural decisions
Modular monolith plus worker; database-level isolation; database queues instead of a broker; originals in PostgreSQL; permanent deletion tombstones against upstream changes; HMAC webhooks with a durable replay ledger and a single narrow pre-authentication lookup function; process-local rate limits (not distributed); equivalents instead of duplicate tables for roles, embeddings and workflow executions. Recorded in `docs/customer-delivery/09-architecture-tradeoff-record.md`, `docs/architecture/entity-model-decision.md` and `docs/architecture/optional-infrastructure-decision.md`.

## 11. Database migration state
Code head `0014`: 0009 lifecycle, 0010 ingestion jobs and chunk generations, 0011 retained originals, 0012 REST sync, 0013 webhooks and CSV provenance, 0014 evaluation runs registry. Each of 0009 to 0014 is tested on a disposable database (upgrade, constraints, RLS and privileges, refuse-to-downgrade guard, re-apply). The shared `eaop` database is at `0006` and was deliberately not migrated.

## 12 and 13. Connectors and backend
REST records (cursor, offset, page pagination with hard bounds, connector-scoped rate limit with `Retry-After`, opt-in live probe, SSRF allow-list, no redirects), CSV (bounded, deterministic, row provenance), signed webhooks (HMAC over timestamp, delivery id and raw body; constant-time comparison; replay ledger; 256 KiB limit; secret rotation; tenant from the endpoint id only). All through the same ingestion jobs, per-record idempotency and tombstones. API: 55 operations, typed responses and a standard error contract; the two exceptions for the signed receiver (signature authentication, raw signed body) are limited to that one operation and pinned by tests.

## 14. Frontend
13 pages; Data Sources now synchronises REST and CSV connectors, manages webhook endpoints (create, disable or enable, rotate and drop secrets; only the variable NAME is entered) and shows recent synchronisations and deliveries as counts; Integration Health runs the opt-in live probe. Vitest 72 passed; Playwright 52 passed (deterministic project, including a real signed-delivery test); typecheck and lint clean.

## 15. AI quality (not met, preserved)
Phase 8 results are unchanged and were not tuned against: citation correctness 89.8% on the consumed held-out split against a 95% target, grounded-answer coverage 59.3%, raw model structured validity 90% on the held-out split. No improvement work was performed in this session (it needs long CPU-only model runs and fresh independent confirmation data, neither available), and no failed target was marked verified. Real-AI and Phase 8 suites were not re-run in this checkpoint (no AI code changed).

## 16 and 17. Security and tenant isolation
Forced RLS with application filters bypassed in tests; role matrix pinned per route; separation of duties; SSRF defences (allow-list, pinned addresses, no redirects, metadata address refused); webhook authentication, replay, timestamp-boundary, tenant-binding, rotation and concurrency tests (8 simultaneous identical deliveries produce one job); secrets only as variable names, none in logs, errors, audit or reports (secret scan 0 findings in 1,043 files). Numeric evidence trust boundary unchanged; V41-14.02 stays PARTIAL.

## 18. Failure recovery
Fault injection FI-01 to FI-10 (root suite), crash and lease-expiry recovery for ingestion, sync and webhook jobs, retry exhaustion and manual re-queue, deletion races, a controlled 503 burst recovered live. All injected faults are simulated, not real outages. REL-01 (an intermittent start-up stall seen once) is OPEN: 12 of 12 further cold-start cycles were clean and nothing was changed.

## 19 and 20. API-quality and customer demonstrations
All nine V41-17.03 properties pass (`evaluation/api-quality/api-quality-evidence.json`). Final live checkpoint `evaluation/demo-runs/20261113-152713-c19b/` (PASSED in 147 s): both customers' workflows, ingestion with a simulated embedding outage, REST, CSV and signed-webhook integrations, the comparison protocol, a backup and restore proof, and the browser smoke. Container stack `evaluation/container-smoke/20261113-152949/` (PASSED, third passing run).

## 21 and 22. Setup and reproduction
Setup: `docs/operations/deployment-runbook.md`, `docs/operations/local-runbook.md`. Reproduce:
```
python -m pytest backend/tests -q          # 747 passed, 18 skipped
python -m pytest tests -q                  # 130 passed, 1 skipped
cd frontend && npx vitest run && npx playwright test --project=deterministic   # 72 and 52 passed
python scripts/demo.py smoke --ingestion --rest --compare --backup             # live checkpoint
python scripts/container_smoke.py          # containerised stack
python scripts/api_quality_report.py ; python scripts/secret_scan.py
```

## 23. Test and evidence paths
`evaluation/demo-runs/`, `evaluation/container-smoke/`, `evaluation/terraform/fmt-check.txt`, `evaluation/comparison/`, `evaluation/api-quality/`, `docs/planning/batch*-report.md`, `docs/planning/reliability-defect-register.md`, `docs/customer-delivery/`. Failed live runs are kept (several failed on defects in the checkpoint scripts themselves, described in the batch reports).

## 24. Open defects and limits
REL-01 open; V41-14.02 partial; AI-quality targets unmet; V41-11.02 partial (limiter process-local; older clients) and V41-16.04 distributed rate limiting partial; independent reproduction (V41-23.04) missing; CI written but never run (no remote); the manual-versus-automated comparison (V41-21.14) has class A measurements only (no observed human data, no assumptions: nothing invented); originals of exhausted jobs never expire; backups keep deleted content; legacy documents without originals cannot be reprocessed from source; the container images use deterministic AI backends only and Ollama from inside a container is untested; Terraform examples pass `terraform fmt` but are not schema-validated.

## 25. Environmental limits and downloads
CPU-only, 16 GB. Downloads this session (all authorised, recorded): Terraform CLI v1.17.2 (38.7 MB zip, 132 MB binary, installed outside the repository, checksum and PGP signature verified); Docker base images `python:3.12-slim` and `nginx:alpine` plus Python dependencies inside the build (Docker image storage grew from 3.16 GB to 3.53 GB; built images 276 MB and 94 MB). No models, no Terraform provider, no unrelated cleanup.

## 26. Remaining owner decisions
Publishing a release (not done); provision of a remote and CI execution; whether to validate Terraform with a provider download; observed human data for the comparison (or explicit hypothetical assumptions); retention and erasure policy for originals and backups; whether "Database entities" means one table per name (roles and workflow executions would then be added, roles needing an authorisation-policy decision); distributed rate limiting; the AI-quality plan with fresh independent evaluation data; an independent reviewer for reproduction.

## 27. Portfolio-readiness
Suitable as a local, evidence-backed demonstration of forward-deployed-engineering skills: two fictional customers, secure multi-tenant design, durable integrations, honest failure and limit reporting, a written delivery package and a reproducible one-command demonstration. Not production-ready and not independently validated.

## 28. Full V4.1 acceptance
**Not achieved.** 159 of 238 requirements are assessed verified; 67 partial, 6 missing and 6 not evaluable remain, including unmet AI-quality targets and items that need approvals or external parties.

## 29. Authorisation boundaries
No remote, cloud, paid, publication or release operation occurred. A local annotated tag was created only after the final integrated acceptance checkpoint, as authorised.
