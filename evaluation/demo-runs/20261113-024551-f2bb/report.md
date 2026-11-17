# Demo smoke report 20261113-024551-f2bb

Result: **FAILED** in 139.2 s (mode smoke, AI backends: deterministic).
Git HEAD at run: `ae8fd5512c57e49d820a7fc26858a586d4031200`. Started 2026-11-13T02:45:52-05:00, finished 2026-11-13T02:48:11-05:00.

## Failures
- [startup] api was not ready after 90s 
    -> see its log under .demo/<run id>/logs/

## Timeline (executed)

| Step | Result | Seconds | Detail |
|---|---|---|---|
| preflight | ok | 4.1 | 7 checks passed |
| create disposable database eaop_demo_20261113_024551_f2bb | ok | 0.1 | created |
| apply migrations (alembic upgrade head) | ok | 1.4 | revision 0008 |
| seed Apex Industrial fixtures | ok | 1.4 | ok (log .demo\20261113-024551-f2bb\logs\seed-apex.log) |
| start ticketing and wait for readiness | ok | 1.9 | responds over HTTP |
| start inventory and wait for readiness | ok | 1.4 | responds over HTTP |
| start fleet and wait for readiness | ok | 2.3 | responds over HTTP |
| start crm and wait for readiness | ok | 1.4 | responds over HTTP |
| start servicedesk and wait for readiness | ok | 1.5 | responds over HTTP |
| start worker and wait for readiness | ok | 2.7 | logged 'worker started' |
| start api and wait for readiness | FAILED | 96.3 | [startup] api was not ready after 90s  |

## Cleanup

- process api (pid 22212): stopped
- process worker (pid 13872): stopped
- process servicedesk (pid 26312): stopped
- process crm (pid 32348): stopped
- process fleet (pid 27612): stopped
- process inventory (pid 32712): stopped
- process ticketing (pid 18512): stopped
- database eaop_demo_20261113_024551_f2bb: dropped

Secrets and credentials are redacted from this report. Logs are kept under `.demo/<run id>/logs` (git-ignored).
