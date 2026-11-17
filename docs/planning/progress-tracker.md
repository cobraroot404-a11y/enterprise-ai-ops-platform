# Progress tracker and resume checkpoint (single authoritative file)

> **Current status.** [Gate C owner disposition](gate-c-owner-disposition.md) records technical acceptance complete and owner disposition closed for the pinned candidate, with the reproduction and accessibility evidence gaps retained. EAOP 09 is next. Phase 10 exit, publication, and release remain owner-gated. See the [EAOP 08E governance policy](eaop-08e-owner-governance.md).

Updated at the end of every work package. Authority for scope: the original V4.1 specification (`docs/specification/ORIGINAL_MASTER_SPECIFICATION_V4.1.txt`, SHA-256 `b1c573e2c209ac68712b36851d56af0fb4c464509b422f96899761b6427760da`). Standing execution authorisation: continuous local development; nothing is pushed, merged, deployed, published or released; no cost; the shared `eaop` database is never migrated without approval.

## Requirement counts (238 original requirements; `docs/specification/v4.1-requirements.json`)
Verified 203, Partial 28, Missing 3, Not evaluable 4. The closure plan has 35 open entries. At the tag `v4.1.0-local-rc1` the counts were 159, 67, 6, 6. Dated amendments in `scripts/v41_requirements_data.py` record the evidence since the tag.

## Checkpoint 2026-11-16 · EAOP 08F local evidence

EAOP 08F is closed locally under the owner's stop rule. The targeted browser retest passed for the skip-link landing and approval/rejection focus. The [local disposition](eaop-08f-local-disposition.md) classifies all 35 open requirements against the original V4.1 Definition of Done. Formal counts are unchanged. EAOP 09 release preparation is next, with remote actions subject to owner authorization.

The [27-step reconciliation and local evidence](../../evaluation/eaop-08f/2026-11-16.md) records live mock workflows for both tenants, same-machine reproduction scope, keyboard observations, the absence of Narrator and human timing evidence, and the consumed benchmark split. P32L1277, P23L856, P18L659, P31L1138 and P31L1229 remain Partial. Phase 10 local evidence remains incomplete.

## Checkpoint 2026-11-15 · Terraform provider validation

Terraform 1.17.2 validated the unchanged AWS example locally against the owner-approved AWS provider 5.100.0 on Windows amd64. [Package checksum, results and scope](../../evaluation/terraform/provider-validation.md). P4L262, P5L323, P24L868, P32L1263 and P34L1358 are Verified. P31L1138 and P31L1229 remain Partial. Next local work is the Phase 10 candidate-specific security disposition.

## Post-release-candidate work (final completion directive)
Closure plan for every unresolved requirement: [requirement-closure-plan.json](requirement-closure-plan.json) (type A to E, package, minimum change, acceptance test, local authority, external prerequisite; regenerate with `python scripts/generate_closure_plan.py`; 36 entries remain).
Done and committed: trace ids across API, job or outbox event, worker and connector calls; audited third-party notices (generated, tested); README rewritten to the 21 specified sections with a checked results table; CI workflow expanded and documented (never executed, no remote); no-paid-services test; 27-step demonstration document and `demo.py steps`; resource requirements; transient-failure recovery suite (11 of 11).
### Work after the owner's PROV-01 decision (history preserved; new commits carry no AI trailer)
Backend regression at `c6e9c10`: 815 passed, 18 skipped, 0 failed. Added: spans (OpenTelemetry data model as log events: requests, connector calls, outbox submissions, ingestion jobs, parent-linked; `test_spans.py`), an importable Grafana dashboard checked against recorded metrics, and a development experiment on invented asset ids (`docs/evaluation/dev-noasset-report.md`): the model invented an id for 16 of 16 reports naming none, a prompt fix did not help (1 of 16), so the application now identifies the asset itself (30 of 30 on 30 new development cases; `RUN_REAL_AI=1` tests pass). Statuses for the AI-quality requirements are unchanged: confirmation needs fresh independent data. V41-22.02 (OpenTelemetry) is Partial (no SDK or exporter); the optional Prometheus and Grafana item is Verified (never run).

### Checkpoint 2026-11-14 (HEAD at start `8303761f3f7028e9d204f50e2d30707c85a9fe4b`; migration head 0017)
- **Full backend regression after the asset-resolution change: 828 passed, 18 skipped, 0 failed** (665 s); after the ambiguity rule, D1 flag and optional-layer tests: **850 passed, 18 skipped, 0 failed** (540 s) at the final state (one guard test, the byte-identical rules.py check, caught a first version of the change and the helper was moved to a new module); root suites 186 passed. Targeted: asset, incident, numeric-safety, tenant, profile and acceptance suites 214 passed; `RUN_REAL_AI=1 test_real_ai.py` 12 passed (earlier in the day).
- **Asset resolution hardened:** several written ids (several valid, contradictory, a model number next to the asset, injected text naming another id) now force human review and list every id found; no id, malformed ids and model-invented ids are refused or ignored; an id registered only in another tenant is written-but-unverified (`test_asset_resolution_security.py`, 20 cases). The model's original output stays in the evidence (`asset_model_output`).
- **AI failure taxonomy (dev) and experiment D1:** `docs/evaluation/ai-failure-taxonomy-and-d1.md`. Retrieval is 2 of 29 failures; verifier withholding (17) and citation or completeness errors (10) dominate. D1 (decompose multi-part answers) **rejected**: coverage 64.4% vs 66.7%, citation correctness 86.4% vs 91.9%; flag stays off; run `exp-D1-20261114T050707Z` preserved. No acceptance threshold or denominator changed; held-out figures unchanged.
- **Optional layers cannot break the core** (V41-04.xx principle, now Verified): `test_core_survives_optional_components.py`.
- **OpenTelemetry:** still no SDK or exporter; exact packages and approval needed are written in `docs/operations/observability.md`. Grafana dashboard still never rendered.
- **Needs the owner:** approval to download a stronger local model (the only untested lever for the AI-quality targets) and, for OpenTelemetry, two small PyPI packages; fresh independently labelled evaluation data; PROV-01 decision (already taken: keep recorded).

**November 14 priorities (historical):** (1) done: integration success rate; (2) done: `docs/performance`; (3) durable metrics and a Prometheus text endpoint (V41-22.x); (4) database-backed distributed rate limiting (V41-11.02, V41-16.04); (5) repository structure reassessment and the remaining Phase 9/10 documents; (6) container reproduction with the Ollama profile (no new downloads); (7) AI-quality development-set work and a fresh independent confirmation set (needs an independent labeller); (8) reviewer package for V41-14.02 (stays PARTIAL until a reviewer accepts); (9) Gate B clean-environment and Gate C reviewer packages. Owner-gated and not started: Terraform provider download, neural reranker weights, remote, CI execution, release, observed human timings.

## Completed work packages (all committed locally on `feat/apex-vertical-slice`)
Final report: [final-completion-report.md](final-completion-report.md). Batches 1 to 8 (API quality, typed contracts, error contract, demo launcher, reliability, audited deletion); 9 (durable ingestion jobs, retry, chunk generations); 10 (retained originals, source reprocessing); 11A (REST pull ingestion, pagination, rate limiting, live probe); post-11A follow-ups (HTTP semantics, deletion tombstones); 11B (CSV connector, signed webhooks); Batch 12 (container stack, UI for connectors and webhooks, Terraform CLI fmt check, entity model and optional-infrastructure decisions, evaluation registry, comparison protocol, final acceptance); documentation package (customer discovery, ten customer-delivery documents, walkthrough, diagrams, deployment runbook, cloud portability and tradeoff analysis, illustrative unvalidated Terraform). Reports: `docs/planning/batch*-report.md`.

## Migration state
Code head `0017` (0015 shared rate limits and durable metrics, 0016 concurrency leases, 0017 lease sweep). Shared `eaop` database: `0006` (never migrated; needs owner approval). All tests use disposable databases.

## Missing requirements still open (6)
Optional observability stack items (OpenTelemetry 22.02, Prometheus/Grafana 22.03, RabbitMQ 23.02: deliberately not implemented, decision recorded), optional Kubernetes examples (24.06) and the published versioned release (32.36, 34.32: a local tag exists, publishing needs owner approval).

## Open items (nothing below is hidden)
* V41-14.02 accepted for scoped Gate C technical purposes, with frozen 63/64 FAIL retained; REL-01 intermittent API-readiness stall (OPEN, unreproduced: 12 of 12 further cold-start cycles clean, `evaluation/demo-runs/rel01-start-cycles.md`).
* Phase 8 AI-quality targets not met (citation correctness 89.8% held-out vs 95%; grounded coverage 59.3%; raw structured validity 90% held-out); frozen evidence must not be tuned against.
* V41-11.02 (limiter process-local, older clients) and V41-16.04 distributed rate limiting; 17.04 missing entity tables; Terraform examples written but never validated (tool not installed); Docker application images; CI never run (no remote); independent reproduction (23.04); the connector and webhook screens are basic.

## Next work packages (dependency order)
1. Core-functional gaps and missing entities (Workstream B) from `docs/specification/v4.1-gap-register.md` (the register is regenerated from the data file).
2. Reliability: REL-01 bounded investigation done (no recurrence; stays open). Remaining reliability work is the optional observability stack.
3. Local infrastructure and operational deliverables (Workstream D).
4. AI-quality work on valid development data with fresh independent confirmation (Workstream E; needs separate care).
5. Final acceptance, documentation and portfolio package (Workstream F).

## Exact restart commands
```
git status --short ; git log --oneline -5
python -m pytest backend/tests -q            # ~7 minutes, serial
python -m pytest tests -q                    # ~2.5 minutes
python scripts/demo.py smoke --rest --no-browser --backup   # live two-tenant checkpoint (isolated disposable database)
```


## Integration checkpoint of 2026-11-13 (migrations 0016 and 0017, lock file, clean environment)
Starting HEAD `21bd718b6f22f8c621dbf506da3f461126ba369e`; clean-environment runs were made at `2324745a68192b17aa26a43b6de8fc9cd1a56746` (code identical to `e7b15801b64f15e89ce5144f34cd867dbdc779d6` plus one evidence file); the ending HEAD is the commit containing this text. Tag `v4.1.0-local-rc1` unchanged at `f098cee`. Migration head `0017`; shared `eaop` database still `0006`.

| Check | Command | Result |
|---|---|---|
| Backend regression | `python -m pytest backend/tests -q` | **812 passed, 18 skipped, 0 failed** (488 s), a fresh full run after the refill-test correction and the 0016/0017 work |
| Root suites | `python -m pytest tests -q` (fault injection deselected) | **179 passed**, 0 failed (after the provenance, traceability, capability, security and environment tests were added) |
| Lint, secret scan | `ruff check ...`, `python scripts/secret_scan.py` | clean, 0 findings |
| Migrations | `backend/tests/test_concurrency_fairness.py`, `test_migration_0015_shared_state.py` | empty database to 0015, 0015 to 0016 to 0017, downgrade to 0015, re-upgrade: pass, in disposable databases |
| Concurrency (0016, 0017) | `test_shared_concurrency.py`, `test_concurrency_fairness.py` | cross-process atomic admission (4 OS processes), release, expiry after a crash, bounded wait, 429 `server_busy`, tenant share, per-process fallback, sweep, metrics, privileges: pass |
| Constrained install | harness step | 42 packages shared with the lock file, **0 differ** (the earlier differences in FastAPI, psycopg, psycopg-binary and Ruff were newer patch releases picked up because `requirements-dev.txt` uses ranges; installs and the backend image are now constrained by the lock file) |
| **Exact lock file** | harness: new environment, `pip install -r backend/requirements.lock.txt`, `pip check` | **pass**: all 71 locked packages at exactly the locked version, nothing extra, no broken requirements, the application imports (fastapi 0.162.4, psycopg 3.3.8, psycopg-binary 3.3.8, ruff 0.17.4, torch 2.14.1+cpu); environment 1,078 MB |
| Clean-environment harness | `python scripts/clean_environment_check.py --ollama` (system Python, pip 26.2.1) | **PASSED**, 19 of 19 steps: `evaluation/clean-environment/20261113-183717/` |
| Live checkpoint from the clone | harness step (own PostgreSQL container on port 15432, own volume) | PASSED in 151 s: both customers, ingestion with a simulated embedding outage, REST, CSV, signed webhooks, recovery, comparison, backup and restore, browser; project removed (exit 0) |
| Container stack from the clone | harness step with `--ollama` | PASSED: 25 workflow checks per customer, UI proxy, grounded answer from the host's Ollama; project removed (exit 0); the run's own image tags removed |
| Frontend from the clone | `npm ci` (lifecycle scripts enabled), typecheck, lint, Vitest | 72 passed |

TLS: certificate verification stayed enabled throughout. pip used the Windows system trust store (a pip 26.2.1 wheel downloaded by the system Python's pip over verified HTTPS, then installed offline into each new environment); npm used `NODE_USE_SYSTEM_CA=1` with `strict-ssl=true`. No `--trusted-host`, no certificate was installed, the Windows store was not modified.
Earlier runs are preserved: `20261113-174203` (TLS failure before the system-trust bootstrap existed), `20261113-183650` (failed: started with the project environment's old pip 21.2.3, which cannot use system trust), and `20261113-180051-external-copy` (a passing run of `f38de83` made by a separate tool session, copied in unchanged with a note of what it did not cover).

### What the gates mean now
- **Gate A (fresh application state): passed** repeatedly.
- **Gate B (clean local environment): passed on the same machine.** Demonstrated: clean checkout of committed state, no `.env`, `.venv`, `node_modules` or data; fresh Python and Node installs; exact lock file; generated secrets; isolated database, containers and volume; teardown. **Not demonstrated:** a different machine or operating-system installation, a cold Docker image cache (base images were already present), a network without the same trust configuration, another user account. Still depends on: Docker Desktop, the system Python with a recent pip, Node, Edge for the browser step, and Ollama with the model already installed.
- **Gate C technical acceptance complete. Owner disposition closed.** See the [Gate C owner disposition](gate-c-owner-disposition.md). The optional independent-human review package remains unused.

### Defect found during this checkpoint: PROV-01 (open, owner decision)
An automated check of the whole history (`python scripts/provenance_check.py`) found **52 commits whose messages carry an AI co-author trailer** (all reachable from the release-candidate tag) and **3 commits authored and committed under a tool's name** (`07648dc`, `8d88019`, `f38de83`). Both break the project's provenance rule, and the earlier "verified" assessment of V41-02.02 and V41-02.03 was wrong. They are recorded in `provenance-exceptions.json`; six requirements were lowered to Partial; a test now fails on any new violation. Nothing was rewritten: removing them needs a history rewrite, which would also move the protected tag, and is the owner's decision.

### Requirement changes in this checkpoint (net: 180 to 189 verified)
Lowered to Partial (PROV-01): V41-02.02, V41-02.03, V41-32.32, V41-32.33, V41-33.02, V41-34.x maintenance rule. Raised to Verified with new evidence: full 238-requirement traceability matrix (x3), environment verification, security documentation index, cloud adaptability, fictional discovery, Priority 4 delivery set, lifecycle capability map (x2), sixteen test kinds, container deployment (x4). All are listed as dated amendments in `scripts/v41_requirements_data.py`.

**Next priorities (restart here):** AI-quality work on development data with a fresh independent confirmation set; OpenTelemetry and Grafana (optional items); backup and restore for the container stack; cross-browser accessibility run; owner decisions (PROV-01, Terraform provider, remote and CI, release, observed human timings, independent reviewer).

## Gate B status (clean environment)
`python scripts/clean_environment_check.py` was run once (evaluation/clean-environment/20261113-174203): the clean clone and new virtual environment were created, then `pip install` failed with `SSL: CERTIFICATE_VERIFY_FAILED` (the machine's HTTPS is intercepted by a local security product, so Python cannot verify PyPI). Certificate verification was deliberately NOT disabled. **Gate B was not achieved in that run** (see the checkpoint above for the later passing run). Unblock by the owner supplying a trusted CA bundle (for example `pip config set global.cert <bundle>`) or by running the script on a machine without interception; the npm and container steps were not reached.

## 2026-11-14 P9L417 closed
13-module evidence map (`docs/architecture/core-modules-evidence-map.md`) + consistency test; P9L417 Verified (196 V / 35 P / 3 M / 4 N). Documented limits: evaluation runs are offline scripts with a read-only registry (not run management; L417 does not require it); no OpenTelemetry SDK (optional L815, owner-gated).

## 2026-11-14 P31L1229 retrospective gates
`docs/planning/retrospective-phase-gates-1-4.md` (labelled reconstruction) + `tests/test_retrospective_phase_gates.py`. L1229 stays PARTIAL: Phase 1 has no stored test/review evidence; no phase has a recorded formal approval, which a retrospective record cannot create. Register unchanged (196 V / 35 P / 3 M / 4 N).
