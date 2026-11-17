# Test credentials and environment isolation

## What exists
- **Unit and integration tests** (`backend/tests`, `tests/`): the constant `Test-Passw0rd!` for synthetic users created in the throwaway database `eaop_test`.
- **End-to-end stack** (`scripts/e2e_stack.py`, Playwright): the constant `E2e-Test-Passw0rd!` and mock-service keys `e2e-ticketing-key` and `e2e-servicedesk-key`, for users in the throwaway database `eaop_e2e` (or `eaop_e2e_real`).
- **Development demos**: seeded users share `SEED_PASSWORD` from the git-ignored `.env`; the real value is never printed or committed.

These constants are public by construction (they are in the repository). They protect nothing and must never exist outside an isolated test stack.

## Controls
| Control | Where | Proof |
|---|---|---|
| The E2E launcher refuses production, any database other than `eaop_e2e`/`eaop_e2e_real`, any non-local DB host and any port outside 8210-8215 and 8220, **before** creating or starting anything | `scripts/e2e_guard.py` | `tests/test_environment_guards.py` (including running the real script with `EAOP_ENV=production`) |
| E2E ports and databases are disjoint from development (8000, 8101-8105, 5173; `eaop`, `eaop_test`, `eaop_bench`, `eaop_smoke`) | same | same |
| E2E accounts do not exist in the development database | n/a | test queries the dev database (skipped if absent) |
| The E2E password appears only in an allow-listed set of test files | n/a | test greps tracked files |
| In production the API **refuses to start** with deterministic AI backends, a weak or test-looking JWT secret, placeholder database passwords or `EGRESS_DEV_MOCKS` set | `backend/app/core/production_guard.py`, called by `create_app` | same test file |
| In production a known test password is **never accepted at sign-in**, even for a valid account | `reject_test_credentials` in the login route | same test file |
| No real secret value from `.env` appears in tracked files, reports, logs, junit files, screenshots (raw bytes) or Playwright artifacts; no private keys, cloud/VCS tokens, JWT-shaped strings or long literal credentials in code | `scripts/secret_scan.py` (free, no dependency; never prints a value) | `python scripts/secret_scan.py` and a regression test that also proves it detects planted secrets |

## Limits
- The guard cannot know every credential a deployer might reuse; it blocks the repository's own test constants and obviously weak configuration.
- Credentials could still be used against the development environment if someone creates those accounts there on purpose; nothing in the repository does, and a test checks the development database today.
- The scan is pattern- and known-value-based; it is not a substitute for a dedicated scanner with history analysis before publication.
- Unrelated credentials were not rotated or deleted.
