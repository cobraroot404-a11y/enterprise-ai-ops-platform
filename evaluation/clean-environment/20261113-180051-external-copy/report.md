# Clean-environment check 20261113-180051: PASSED

Commit: `f38de83f62c0501feff8cad9538d17a4c86b9dcc`. **Scope: same machine, user, Docker daemon, image cache and network as the author: NOT a fresh-machine reproduction.**

| Step | Result | Seconds | Detail |
|---|---|---|---|
| clone the committed state | ok | 1.5 | 1092 files; .env present: False; node_modules present: False |
| create a new virtual environment | ok | 5.4 | 3.10.0 |
| bootstrap pip with Windows system trust | ok | 8.9 | pip 26.2.1 installed offline after download with pip 26.2.1 |
| install backend/requirements-dev.txt | ok | 56.4 | venv size 132.3 MB |
| pip check | ok | 0.8 | No broken requirements found. |
| compare the clean install with the lock file (version pinning) | ok | 0.7 | 42 packages are in both the clean install and the lock file; 4 resolved to a different version than the lock file (installed, locked): {'fastapi': ('0.162.5', '0.162.4'), 'psycopg': ('3.3.9', '3.3.8'), 'psycopg-binary':  |
| generate .env from .env.example with fresh random secrets | ok | 0.0 |  |
| secret scan | ok | 3.6 | secret scan: 0 finding(s) in 1092 files |
| documentation and structure tests from the clean checkout | ok | 5.9 | 32 passed, 1 warning in 0.50s |
| npm ci from the lock file | ok | 15.2 | node_modules 134.6 MB |
| frontend typecheck, lint and unit tests | ok | 35.4 | [' Test Files  6 passed (6)', '      Tests  72 passed (72)', '   Start at  18:02:48', '   Duration  16.86s (transform 1.43s, setup 6.23s, collect 4.31s, tests 16.85s, environment 18.19s, prepare 1.49s)'] |
| containerised stack built and run from the clone (own database volume, fresh secrets) | ok | 52.2 | ['ok   Apex and Meridian workflow checks against the containerised API (6.1s)', 'ok   web UI container serves the app and proxies /api (0.0s)', 'report: <local-path>\\ |

Cleanup: removed eaop-clean-1hk33n5x (the temporary directory this script created)
