# Container smoke 20261113-145441: PASSED

| Step | Result | Seconds | Detail |
|---|---|---|---|
| build the web UI on the host (npm run build: typecheck and production bundle) | ok | 4.3 | [39m[1m[2m  8.37 kB[22m[1m[22m[2m │ gzip:  2.58 kB[22m [2mdist/[22m[36massets/index-BJUsEzo0.js   [39m[1m[2m252.20 kB[22m[1m[22m[2m │ gzip: 76 |
| docker compose build (pulls base images, installs dependencies) | ok | 6.3 | lt   Image eaop-app-backend:local Built   Image eaop-app-backend:local Built   Image eaop-app-backend:local Built   Image eaop-app-backend:local Built   Image e |
| start db, migrate, seed Apex, API, worker, mocks and UI | ok | 17.1 | Started   Container eaop-app-inventory-1 Started   Container eaop-app-fleet-1 Started   Container eaop-app-crm-1 Started   Container eaop-app-ui-1 Started   Con |
| wait for the API (container health) | ok | 0.0 | GET /api/v1/health 200 on 127.0.0.1:18000 |
| onboard Meridian through the public API (inside the API container) | ok | 1.7 | ed (3 chunks) document meridian_depot_inspection_2026q3.pdf: created (1 chunks) document service_history.csv: created (4 chunks) document telematics_alerts.csv: |
| Apex and Meridian workflow checks against the containerised API | ok | 6.0 | {'external_systems': 'simulated: local mock ticketing (8101) and service desk (8105)', 'tenants': {'apex-industrial': [{'tenant': 'apex-industrial', 'step': 'si |
| web UI container serves the app and proxies /api | ok | 0.0 | True |

New images: []; built image sizes: {'eaop-app-backend:local': '276MB', 'eaop-app-ui:local': '94MB'}
Docker disk (images) before: 3.534GB, after build: 3.534GB
Workflow checks per tenant: {'apex-industrial': 25, 'meridian-fleet': 25}
Cleanup: {'compose_down_exit': 0, 'scope': 'project eaop-app only (its containers, network and volume)'}
