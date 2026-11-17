# Clean-environment check 20261113-183650: FAILED

Commit: `e7b15801b64f15e89ce5144f34cd867dbdc779d6`. **Scope: same machine, user, Docker daemon, image cache and network as the author: NOT a fresh-machine reproduction.**

| Step | Result | Seconds | Detail |
|---|---|---|---|
| clone the committed state | ok | 1.7 | 1098 files; .env present: False; node_modules present: False |
| create a new virtual environment | ok | 5.7 | 3.10.0 |
| bootstrap pip with Windows system trust | FAILED | 0.8 | Windows system trust bootstrap requires host Python 3.10+ and pip 24.2+ |

Cleanup: removed eaop-clean-n71iane9 (the temporary directory this script created)
