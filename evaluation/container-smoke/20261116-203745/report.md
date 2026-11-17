# Container smoke 20261116-203745: PASSED

| Step | Result | Seconds | Detail |
|---|---|---|---|
| build the web UI on the host (npm run build: typecheck and production bundle) | ok | 5.7 | [39m[1m[2m  8.39 kB[22m[1m[22m[2m │ gzip:  2.59 kB[22m [2mdist/[22m[36massets/index-4CEpiNSY.js   [39m[1m[2m261.89 kB[22m[1m[22m[2m │ gzip: 79 |
| docker compose build (pulls base images, installs dependencies) | ok | 5.6 | l Built   Image eaop-app-backend:local Built   Image eaop-app-backend:local Built   Image eaop-app-backend:local Built   Image eaop-app-backend:local Built   Im |
| check that Ollama and the model are already running on the host | ok | 0.0 | host Ollama running with 1 model(s) installed, including qwen2.5:1.5b |
| start db, migrate, seed Apex, API, worker, mocks and UI | ok | 16.8 | Started   Container eaop-app-crm-1 Started   Container eaop-app-ticketing-1 Started   Container eaop-app-fleet-1 Started   Container eaop-app-ui-1 Started   Con |
| wait for the API (container health) | ok | 0.0 | GET /api/v1/health 200 on 127.0.0.1:18000 |
| onboard Meridian through the public API (inside the API container) | ok | 1.9 | ed (3 chunks) document meridian_depot_inspection_2026q3.pdf: created (1 chunks) document service_history.csv: created (4 chunks) document telematics_alerts.csv: |
| Apex and Meridian workflow checks against the containerised API | ok | 39.9 | {'external_systems': 'simulated: local mock ticketing (8101) and service desk (8105)', 'tenants': {'apex-industrial': [{'tenant': 'apex-industrial', 'step': 'si |
| a question answered by the host's Ollama from inside the container stack | ok | 3.9 | HTTP 200, llm_backend=ollama, grounded=True, citations=1 |
| web UI container serves the app and proxies /api | ok | 0.0 | True |

New images: []; built image sizes: {'eaop-app-backend:local': '285MB', 'eaop-app-ui:local': '94MB'}
Docker disk (images) before: 3.545GB, after build: 3.545GB
Workflow checks per tenant: {'apex-industrial': 25, 'meridian-fleet': 25}
Cleanup: None
