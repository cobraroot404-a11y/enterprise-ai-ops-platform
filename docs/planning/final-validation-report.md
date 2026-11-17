# V4.1 final implementation and validation report (deliverable 31, refreshed 2026-11-15)

Supersedes the status figures in `docs/planning/final-completion-report.md` (written at tag `v4.1.0-local-rc1`; its counts are historical). All evidence is same-author and same-machine; nothing here is independent certification. **Full V4.1 acceptance is NOT achieved.** Nothing was pushed, published or released; no CI ever ran.

## Requirement status (regenerated from `scripts/v41_requirements_data.py`)
> The current register and scoped Gate C decision are recorded in the [active plan](PLAN.md) and the [Gate C owner disposition](gate-c-owner-disposition.md). The validation results below retain their original execution scope.

Of 238 original requirements: **203 verified, 28 partial, 3 missing, 4 not evaluable** (`docs/specification/v4.1-reconciliation-matrix.md`, `docs/planning/requirement-closure-plan.json`, 35 open). At the report's previous validation checkpoint the counts were 202, 29, 3, 4. At the local engineering checkpoint tag `v4.1.0-local-rc1` the counts were 159, 67, 6, 6. Open items by blocker:
- AI quality targets (V41-13.xx, 21.xx): NOT MET. Held-out citation correctness 89.8%, grounded coverage 59.3%, raw model validity 18 of 20 (`docs/evaluation/phase8-heldout-report.md`); development failure taxonomy and rejected experiment D1 in `docs/evaluation/ai-failure-taxonomy-and-d1.md`. Needs an owner-approved larger model and fresh independent data.
- Remaining assurance evidence: compatible-hardware walkthrough, one observed 27-step demonstration, and manual keyboard and Windows Narrator observations. The scoped Gate C decision preserves the V41-14.02 frozen 63/64 FAIL alongside the accepted current PASS.
- Needs the owner: OpenTelemetry packages, remote CI, publication or release, observed human timings.
- Not implemented by decision: optional RabbitMQ broker adoption (`docs/architecture/optional-infrastructure-decision.md`).

## Validation evidence (last verified runs; rerun the command for current results)
| Check | Result | Command | Evidence |
|---|---|---|---|
| Registry and API contracts | 97 passed | `python -m pytest backend/tests/test_evaluation_registry.py backend/tests/test_ops_routes.py backend/tests/test_meridian.py backend/tests/test_api_contract.py backend/tests/test_api_error_contract.py backend/tests/test_api_namespace_security.py backend/tests/test_api_response_schemas.py -q` | Local `registry-api-retry.log` (outside the repository) |
| Backend regression | 1,068 passed, 18 skipped, 0 failed, 0 errors | `python -m pytest backend/tests -q` | Local `backend-regression-retry.log` (outside the repository) |
| Root suite | 203 passed, 28 fault-injection tests deselected, 0 failed, 0 skipped; 109.40 s | `python -m pytest tests -vv --deselect tests/fault_injection --maxfail=1 -o faulthandler_timeout=120 -o console_output_style=classic --durations=10 -ra` | Local `eaop-root-diagnostic-confirm.log` (outside the repository) |
| Fault injection | 15 of 15 (simulated faults) | `python -m pytest tests/fault_injection -q` | `evaluation/failure-reports/phase7/fi-report.json` |
| Customer acceptance | 15 of 15 (deterministic backends) | `python -m pytest tests/acceptance -q` | `evaluation/customer-acceptance/deterministic/uat-report.json` |
| API quality | 9 of 9 properties | `python scripts/api_quality_report.py` | `evaluation/api-quality/api-quality-evidence.json` |
| Accessibility (axe) | 0 violations across 43 Edge states and 44 Chrome states. Screen-reader audit pending | `E2E_BROWSER_CHANNEL=chrome npx playwright test e2e/accessibility.spec.ts` | `evaluation/reports/phase6-closure/axe-results-chrome.json` |
| Clean-environment reproduction | 19 of 19, same machine, not independent | see skill `clean-environment-check` | `evaluation/clean-environment/20261113-183717` |
| Demonstration checkpoint | PASSED | `python scripts/demo.py smoke --rest --backup` | `evaluation/demo-runs/20261114-011642-f5c8` |
| Local Terraform | Passed with AWS provider 5.100.0 on Windows amd64 | `terraform validate` and `terraform providers schema -json` in a backend-disabled copy | [Provider validation](../../evaluation/terraform/provider-validation.md) |
| Full Compose backup and restore | PASSED | Custom-format dump and fresh-database restore in separate disposable projects | [Owner-session evidence](../operations/full-compose-backup-restore.md) |
| Optional-layer isolation | core workflow survives failed optional components | `python -m pytest backend/tests/test_core_survives_optional_components.py -q` | `docs/planning/progress-tracker.md` |

### Isolated PostgreSQL regression at `1d9954c7f82ebd9dbddb2aacbfb1959be6dcf3c8`

The registry/API, backend and root results above were recorded on the feat/apex-vertical-slice branch on 2026-11-15. Alembic head `0017` was verified on isolated PostgreSQL 16.15 with pgvector. Across the three runs, tests exercised row-level security (RLS), authentication and authorization, Apex and Meridian visibility, tenant isolation, and database lifecycle operations including create, drop, backup and restore. `RUN_REAL_AI` remained unset. The shared `eaop` database and frozen evaluation evidence were untouched. Generated acceptance and observability reports stayed in disposable checkouts.

The 1,068-pass backend result supersedes the historical baseline of 850 passed and 18 skipped at `dfbd8ec`. The root confirmation supersedes the 199-pass result at `2301702`.

An earlier root run reported 190 passed, 13 failed and 28 deselected. The 13 failures were environment/setup issues involving local database configuration, Docker Compose availability and Windows process queries. All 13 passed in the isolated confirmation. The first verbose diagnostic stopped at `test_generated_files_are_up_to_date` in `tests/test_third_party_notices.py` because the disposable checkout lacked frontend/node_modules. The test passed after copying the existing dependency tree into the confirmation checkout. The interrupted quiet run that exceeded 90 minutes provides insufficient evidence to identify a stalled test or its cause. The confirmation run showed no stall.

## Known defects and limits
`docs/planning/reliability-defect-register.md` (REL-01 intermittent start-up stall, open, not reproduced in 12 further cycles). Provenance exception PROV-01 stays recorded in `docs/planning/provenance-exceptions.json`. Pending: remote CI, Grafana dashboard import, and any real cloud deployment. The Grafana dashboard queries are checked against recorded metrics. Simulated: external ticketing and sources (local mocks), injected faults.

## No-unreproducible-figure audit (requirement P1L37)
Every figure in the README Verified Engineering Results table and in this report is tied to a command and an artifact or a rerun instruction. `tests/test_readme_results.py` checks README figures against their evidence, and `tests/test_final_validation_report.py` checks this report's requirement counts and cited repository paths. The registry/API, backend and root logs are local artifacts outside the repository. The table gives the commands to reproduce their counts.
