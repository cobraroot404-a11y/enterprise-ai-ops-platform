# Resource requirements (V41-02.04)

The core platform needs **no paid software, API, subscription or hosting**; `tests/test_no_paid_services.py` scans the requirements files, compose files, Dockerfiles and the workflow for paid-service SDKs and endpoints. This document keeps the separate resource costs the specification asks for. Figures are measured on the development machine unless marked as an estimate.

| Resource | Requirement | Basis |
|---|---|---|
| CPU | 4 cores / 8 threads minimum (Intel i7-1165G7 used); inference is CPU-only | `scripts/capture_hardware.py` |
| Memory | 16 GB RAM (15.7 GB present); the 1.5B model uses about 2 GB while loaded, PostgreSQL and services about 1 GB | observed |
| Storage | about 2 GB for the repository, Python and Node dependencies; about 1 GB for the Ollama model and the embedding model; container images 276 MB and 94 MB plus base images (Docker image storage grew 3.16 to 3.53 GB); evaluation evidence is small text and JSON | Batch 12 record |
| Bandwidth | one-time downloads only: Python and Node packages, the Ollama runtime and model, the embedding model, two container base images, the Terraform CLI (38.7 MB). Day-to-day operation sends nothing outside the machine | download record in the final report |
| Electricity | **estimate, not measured**: a laptop under CPU inference load draws roughly 25 to 45 W; a full Phase 8 evaluation run took about 55 minutes (3,289 s), which is therefore on the order of 20 to 40 Wh. No power meter was used | stated as an estimate |
| Money | 0 | no paid dependency (test above) |
