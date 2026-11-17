# Benchmark reports and measured evidence index (spec Part 4 Priority 3; final deliverable 13)

One place that maps each Priority 3 item to a command, a stored artifact and the honest result. All evidence is same-author, local, CPU-only, with mock external systems; none of it is independent validation. Results are reported as measured, including targets that are NOT MET.

| Priority 3 item | Command | Artifact | Result as measured |
|---|---|---|---|
| Automated tests | `python -m pytest backend/tests -q`; `python -m pytest tests -q --deselect tests/fault_injection` | not archived as a file; rerun the commands | see README results table for current counts |
| Customer acceptance tests | `python -m pytest tests/acceptance -q` | `evaluation/customer-acceptance/deterministic/uat-report.json`, `evaluation/customer-acceptance/real/uat-report.json` | 15 of 15 scenarios pass (deterministic backends) |
| Retrieval evaluation | `python evaluation/phase8/score_experiment.py <dir> --baseline <dir>` | `docs/evaluation/phase8-heldout-report.md`, `docs/evaluation/phase8-baseline-report.md`, `evaluation/reports/phase8/` | held-out citation correctness 89.8% (target 95%: NOT MET); retrieval and grounding figures in the report |
| Workflow benchmarks | `python scripts/demo.py smoke --compare` | `docs/performance/measured-performance.md`, `evaluation/reports/phase4-remeasure/` | automated system time per step, median and p95; observed-manual and simulated-manual classes are empty (no human timings) |
| Failure recovery reports | `python -m pytest tests/fault_injection -q`; `RECOVERY_REPORT=1 python -m pytest tests/fault_injection/test_recovery_rate.py -q` | `evaluation/failure-reports/phase7/fi-report.json`, `evaluation/recovery/recovery-rate-report.json` | 15 of 15 scenarios; recovery 11 of 11 (coarse suite) |
| Reproducible results | `python scripts/clean_environment_check.py` workflow (skill `clean-environment-check`) | `evaluation/clean-environment/` | 19 of 19 on the same machine; not an independent reproduction |
| Integration success rate | `INTEGRATION_REPORT=1 python -m pytest backend/tests/test_integration_success_rate.py -q` | `evaluation/integration/integration-success-rate-report.json` | 14 of 14 (coarse suite) |

Not claimed: productivity gains, independent confirmation, held-out improvement beyond the recorded figures. See `docs/planning/final-validation-report.md` for the overall status.

## Evaluation registry visibility (`GET /api/v1/evaluation/registry`)
Intended as platform-wide evidence: every tenant role with `metrics:read` sees the same rows, as with `/api/v1/evaluation/reports`. The table has no tenant column and the application roles hold SELECT only. Limits of the current checks: the test `test_exposed_registry_fields_of_every_committed_manifest_carry_no_personal_or_tenant_identifiers` scans only the committed manifests (38 at the time of writing) with a pattern for emails, UUIDs and absolute paths, so it does not prove the absence of other sensitive text in a future manifest; run labels, commands and dataset names (which include the fictional customer names Apex and Meridian) are visible to every tenant; and the indexer, not the endpoint, decides what enters the table. If a real multi-customer deployment needed per-tenant evaluation visibility, a tenant column and RLS would be required; no such need is demonstrated.
