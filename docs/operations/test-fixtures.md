# Development-only test fixtures

## `meridian-uitest`
The Meridian counterpart for browser testing, created with the **public onboarding path** and a copy of
`onboarding/meridian.json` whose tenant is `meridian-uitest` (name `[TEST FIXTURE] Meridian Fleet Logistics (fictional)`,
users `*@meridian-uitest.example.test`) and an `ONBOARD_PASSWORD` you choose. It is a local development artifact: not
referenced by compose, CI or the default seed. The primary Meridian demo tenant is `meridian-fleet`
(`python scripts/dev.py onboard-meridian` with the stack running; its members share `SEED_PASSWORD` like the Apex demo users).

## `apex-uitest`
A tenant used only for manual/browser UI testing during development.

- **Synthetic only:** it holds the same fictional Apex sample files; no real data.
- **Clearly marked:** tenant name is `[TEST FIXTURE] Apex UI test tenant (synthetic, development only)`; users are `*@uitest.example.test`.
- **Deterministic and recreatable:** `UITEST_PASSWORD=<value> python scripts/seed_uitest.py` (or `python scripts/dev.py seed-uitest`). It is idempotent: same slug, names, users, connectors and documents every run. (Audit rows are append-only by design, so a fixture is re-seeded, not deleted; to start from nothing, drop the dev database volume.)
- **Isolated:** the primary demo is `apex-industrial` (`python scripts/dev.py seed`). Benchmarks never touch either tenant: `evaluation/benchmarks/run_phase3.py` drops and recreates its own database (`eaop_bench`) with a dedicated `apex-benchmark` tenant on every run, so fixture or demo activity cannot enter benchmark numbers.
- **Not in deployments:** it is not referenced by `docker-compose.yml`, CI, the Makefile or the default seed, and the script refuses to run when `EAOP_ENV=production`. Tests in `tests/test_uitest_fixture_isolation.py` enforce this.
