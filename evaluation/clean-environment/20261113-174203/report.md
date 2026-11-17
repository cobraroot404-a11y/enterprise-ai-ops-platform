# Clean-environment check 20261113-174203: FAILED

Commit: `4ab33450112ed8d4c75f296c783c5da0780f8e52`. **Scope: same machine, user, Docker daemon, image cache and network as the author: NOT a fresh-machine reproduction.**

| Step | Result | Seconds | Detail |
|---|---|---|---|
| clone the committed state | ok | 2.6 | 1090 files; .env present: False; node_modules present: False |
| create a new virtual environment | ok | 8.0 | 3.10.0 |
| install backend/requirements-dev.txt | FAILED | 10.1 | pip install exited 1: ct=None, read=None, redirect=None, status=None)) after connection broken by 'SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local iss |

Cleanup: removed eaop-clean-vg1rciqa (the temporary directory this script created)
