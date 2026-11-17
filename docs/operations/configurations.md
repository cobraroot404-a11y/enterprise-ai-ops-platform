# Configurations: development, CI, real-AI evaluation

Three configurations exist on purpose. They must not be confused.

| | Development (local demo) | Functional tests / CI | Real-AI evaluation |
|---|---|---|---|
| Purpose | Use the app, UI demos | Verify behaviour: authorization, approvals, state machine, idempotency, fault injection | Measure real AI quality and latency |
| `LLM_BACKEND` | `ollama` | `deterministic` (forced by the test fixtures regardless of `.env`) | `ollama` |
| `EMBEDDING_BACKEND` | `sentence_transformers` | `deterministic` (forced) | `sentence_transformers` |
| Database | `eaop` (dev tenants indexed with MiniLM) | `eaop_test`, rebuilt from migrations each session | `eaop_bench`, rebuilt every run |
| Ollama needed | yes (`python scripts/ollama_ctl.py start`) | no | yes |
| Where defined | local `.env` (git-ignored); template `.env.example` | `backend/tests/support.py` | flags of `evaluation/benchmarks/run_phase3.py` |
| Results mean | nothing measured | functional pass/fail only, never AI quality | the only source of AI performance claims |

## Rules
- Deterministic and real embeddings are never mixed in one tenant's active index. A tenant indexed with one embedding model is refused by the other (HTTP 409 `embedding_model_mismatch`) until `python scripts/reindex_embeddings.py --tenant <slug> --backend <backend>` re-embeds it. The dev database stays on MiniLM; do not reindex it back to deterministic.
- `.env` holds secrets and is never committed. Changing backends means editing only the two `*_BACKEND` lines.
- CI (`.github/workflows/ci.yml`) uses the deterministic backends only; real-AI tests are opt-in (`RUN_REAL_AI=1`) and run locally.

## Resource limits and Meridian mock services (all configurations)
`MAX_UPLOAD_BYTES` (10 MiB), `MAX_JSON_BYTES` (1 MiB), `MAX_CONCURRENT_INGEST` (2), `MAX_CONCURRENT_LLM` (2) and
`BUSY_WAIT_SECONDS` (2) bound request size and concurrency; they are per process, not a distributed rate limiter.
Meridian's mock service desk needs `MOCK_SERVICEDESK_API_KEY` (server) and `MERIDIAN_SERVICEDESK_KEY` (the connector's
`secret_ref`, read by API and worker) set to the same value; `dev.py stack` also starts the fleet (:8103), CRM (:8104)
and service-desk (:8105) mocks.

## Managing Ollama
Ollama uses about 1.5 GB of RAM while a model is loaded. Control it with `python scripts/ollama_ctl.py start|stop|status` (also `python scripts/dev.py ollama-start|ollama-stop`). Real-AI tests start it automatically if it is not running. Stopping only ends the processes; nothing is uninstalled, no model is removed and PATH is untouched.
