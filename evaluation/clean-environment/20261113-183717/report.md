# Clean-environment check 20261113-183717: PASSED

Commit: `2324745a68192b17aa26a43b6de8fc9cd1a56746`. **Scope: same machine, user, Docker daemon, image cache and network as the author: NOT a fresh-machine reproduction.**

| Step | Result | Seconds | Detail |
|---|---|---|---|
| clone the committed state | ok | 1.7 | 1100 files; .env present: False; node_modules present: False |
| create a new virtual environment | ok | 5.7 | 3.10.0 |
| bootstrap pip with Windows system trust | ok | 10.5 | pip 26.2.1 installed offline after download with pip 26.2.1 |
| install backend/requirements-dev.txt constrained by the lock file | ok | 48.4 | venv size 140.1 MB |
| pip check | ok | 0.9 | No broken requirements found. |
| compare the clean install with the lock file (version pinning) | ok | 0.8 | 42 packages are in both the clean install and the lock file; 0 resolved to a different version than the lock file (installed, locked): {} |
| exact lock file: create a second virtual environment | ok | 6.6 | 3.10.0 |
| exact lock file: bootstrap pip with Windows system trust | ok | 7.4 | pip 26.2.1 installed offline after download with pip 26.2.1 |
| exact lock file: install backend/requirements.lock.txt | ok | 225.4 | venv size 1077.8 MB |
| exact lock file: pip check | ok | 1.1 | No broken requirements found. |
| exact lock file: installed versions equal the lock file | ok | 0.8 | all 71 locked packages installed at exactly the locked version; installed but not in the lock file: none |
| exact lock file: the application imports under the locked versions | ok | 25.5 | 0.162.4 3.3.8 2.14.1+cpu |
| generate .env from .env.example with fresh random secrets | ok | 0.0 |  |
| secret scan | ok | 2.5 | secret scan: 0 finding(s) in 1100 files |
| documentation and structure tests from the clean checkout | ok | 5.0 | 32 passed, 1 warning in 0.60s |
| npm ci from the lock file | ok | 15.0 | node_modules 134.6 MB |
| frontend typecheck, lint and unit tests | ok | 32.1 | ['\x1b[2m Test Files \x1b[22m \x1b[1m\x1b[32m6 passed\x1b[39m\x1b[22m\x1b[90m (6)\x1b[39m', '\x1b[2m      Tests \x1b[22m \x1b[1m\x1b[32m72 passed\x1b[39m\x1b[22m\x1b[90m (72)\x1b[39m', '\x1b[2m   Start at \x1b[22m 18:43: |
| host processes from the clone on an isolated PostgreSQL container: both customers, ingestion with a simulated outage, REST, CSV, signed webhooks, recovery, comparison, backup and restore, browser | ok | 159.2 | [demo 18:46:24] smoke PASSED in 151.4s; report: evaluation/demo-runs/20261113-184353-92a7/report.md |
| containerised stack built and run from the clone (own database volume, fresh secrets) | ok | 138.8 | ["ok   a question answered by the host's Ollama from inside the container stack (7.2s)", 'ok   web UI container serves the app and proxies /api (0.0s)', 'report: <local-path> |

Cleanup: removed eaop-clean-gkonlfeh (the temporary directory this script created)
