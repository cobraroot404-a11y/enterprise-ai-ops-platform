# What runs in CI and what needs local hardware (V41-27.04)

The private engineering source commit passed all six CI jobs. This portfolio workflow runs the product checks on the separate snapshot with read-only repository permissions and standard hosted runners.

| Suite | Command | Where it can run | Needs |
|---|---|---|---|
| Backend lint | `ruff check backend mock-services workers scripts tests` | CI and local | Python |
| Backend tests (deterministic AI backends) | `python -m pytest backend/tests -q` | CI and local | PostgreSQL with pgvector (service container in CI) |
| Root suites (traceability, documents, acceptance, comparison) | `python -m pytest tests -q` | CI and local | PostgreSQL |
| Fault injection (opt-in) | `python -m pytest tests/fault_injection -q` | CI and local | PostgreSQL |
| Frontend type check, lint, unit tests, build | `npm run typecheck`, `npm run lint`, `npm test`, `npm run build` (in `frontend`) | CI and local | Node 20+ |
| Dependency and licence check | `python scripts/generate_third_party_notices.py --check` | CI and local | installed packages |
| Secret scan | `python scripts/secret_scan.py` | CI and local | none |
| Docker build validation | `docker build -f infrastructure/docker/Dockerfile.backend .` | local; CI possible | Docker |
| Container smoke | `python scripts/container_smoke.py` | local | Docker, about 4 GB free disk, minutes |
| Browser tests (Playwright) | `npx playwright test` (in `frontend`) | local | Edge or Chromium, isolated stack |
| Live demonstration checkpoint | `python scripts/demo.py smoke --ingestion --rest --compare --backup` | local | database, browser |
| Real-AI tests and Phase 8 evaluations | `RUN_REAL_AI=1 python -m pytest backend/tests/test_real_ai.py`; evaluation scripts under `evaluation/` | **local only** | Ollama, a 1.5B model, CPU time (up to about an hour) |
| Terraform formatting | `terraform fmt -check -recursive infrastructure/terraform` | local | Terraform or OpenTofu CLI (schema validation needs a provider download that was not authorised) |

Workflow jobs (`.github/workflows/ci.yml`): `backend`, `acceptance`, `frontend`, `dependency-and-security`, `docker-build`, `release-validation`. A separate smoke job is deliberately absent: the live demonstration needs a browser and several minutes and is run locally (table above).

The acceptance job checks the portfolio snapshot's own Git provenance. The private engineering ancestry and protected local checkpoint are outside this checkout.

The expensive suites (real AI, Phase 8, container smoke, browser) are excluded from the workflow on purpose; the workflow runs the deterministic subset only. `tests/test_ci_workflow.py` parses the workflow and fails if a job lacks least-privilege permissions or if this table omits a job the workflow runs.
