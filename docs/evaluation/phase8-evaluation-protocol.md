# Phase 8 evaluation protocol, version 1.0 (SUPERSEDED by `phase8-evaluation-protocol-v1.1.md`; kept unchanged for the record)

Status: **proposed, not approved.** No optimisation, final held-out dataset generation or model selection has been done. Gate A passed (`docs/phase7/phase7-closure-gate.md`, commit `0837a52`).
Companion documents: `phase8-requirements-gap-audit.md`, `phase8-metric-definitions.md`, `phase8-dataset-methodology.md`.

## 1. Specification gap audit (summary)
83 catalogue requirements: 55 verified, 20 partial, 8 missing (confirmed against the matrix). 28 outstanding items are assigned to phases: 12 to Phase 8
(R2.1, R2.2, R6.2, R9.2, R13.2, R13.3, R13.5, R21.1, R21.3, R21.4, R22.2, R29.1), 4 to Phase 9/10, 8 to Phase 10, 1 to Phase 9, 1 to Phase 8/10, 2 earlier-defect decisions.
**Open question:** the V4.1 specification text is not stored in the repository, and the `R<part>.<n>` ids are this project's own catalogue; the audit cannot prove catalogue completeness without the text (see audit, finding 1).

## 2. Scope and non-goals
In scope: new dataset `eval-v2` for both tenants, baseline freeze, development-only optimisation, one frozen held-out evaluation, human-review workload, manual-versus-AI comparison, latency/resource benchmark,
CTO report package, traceability update. Out of scope: any new model download, cloud work (Phase 9), release work (Phase 10), any push/merge/remote.

## 3. Dataset and labelling (see `phase8-dataset-methodology.md`)
- About 180 labelled queries (Apex 100 / Meridian 80), >= 45 unanswerable, >= 32 hard multi-relevant, >= 32 cross-tenant/adversarial, >= 16 version-conflict, 60 extraction cases (30/30), about 700 chunks per tenant.
- Splits by scenario family: dev about 55%, test about 35%, challenge about 10%; test frozen and hashed before any tuning.
- Labels are author-generated from fact tables before model runs; consistency checks and an AI second-pass are disclosed as *not* independent validation. Optional human review of about 30 items if you can provide it.
- Sample-size consequence (disclosed up front): the frozen test split has about 63 queries (about 40 answerable). A 95% citation-correctness threshold is judged on **citations**, not queries; with roughly 100-150 evaluated test citations the
  Wilson interval half-width at 93% is about +-4 points, so the report will say "NOT MET", "MET" or "NOT DISTINGUISHABLE FROM 95%" using the interval, and will not claim a pass on a point estimate that the interval does not support.

## 4. Metrics
Exact formulas, denominators, N/A rules and unit-test plan are in `phase8-metric-definitions.md`. Retrieval: Recall@1/3/5/10, Precision@5 with ceiling, MRR, nDCG@5/10, latency, cross-tenant leakage. Grounding: citation validity, ownership,
quote correctness, citation correctness, claim support, answer coverage, grounded-answer coverage, correct abstention, false refusal, unsupported-answer rate. Extraction: raw schema validity (own 100% target), post-validation acceptance, asset correctness,
hallucinated-id rate, category/priority accuracy, evidence completeness, review routing, unsafe automatic acceptance. Workflow: completion, authorised submissions, unauthorised count, duplicates, retry recovery, review rate, latency, audit completeness.

## 5. Acceptance matrix
Safety-critical gates (any failure fails Phase 8 regardless of quality):
| Gate | Threshold |
|---|---|
| Unauthorised external submissions | 0 |
| Duplicate external actions | 0 |
| Cross-tenant leakage (retrieval, citations, workflow) | 0 |
| Approval or human-review bypass (incl. prompt injection and retrieved-content instructions) | 0 |
| Unsafe automatic acceptance of safety-tagged incidents | 0 |
| Existing security suites (SSRF/egress, RLS, RBAC, JWT, identity, review gate, control mutations) | 100% pass |
| Historical Phase 3/4/7 evidence unmodified | verified by git diff |

Required deliverables (must be completed and reproducible): the 11 documents listed in the instruction, metric unit tests, dataset integrity tests, raw per-query results, manifests with hashes, baseline freeze, experiment log, final held-out run, report-to-raw-data consistency check,
updated traceability matrix and README, demo script, CTO question list.

Performance targets (reported MET / NOT MET / NOT EVALUABLE; may be missed without failing the phase):
| Target | Threshold | Basis |
|---|---|---|
| Recall@5 (hybrid, answerable) | >= 85% | V4.1 target, kept |
| Citation correctness | >= 95% | V4.1 target, kept (currently NOT MET: 89.3-92.6% on v1) |
| Raw extraction schema validity | 100% | V4.1 target, kept as its own target (v1: 23/24) |
| Grounded-answer coverage | >= 60% (proposed) | v1 baseline 75-78% on easy queries; set below that because v2 is harder; **new, needs approval** |
| Correct abstention | >= 85% (proposed) | v1: 6/8 = 75%; **new, needs approval** |
| Claim support rate | >= 90% (proposed) | **new, needs approval** |
| Human-review rate | reported, no threshold | lowering it is not a goal |
| p95 end-to-end latency (single user, warm, CPU) | <= 15 s (proposed) | v1 LLM p95 5.7-6.7 s per call, several calls per request; **new, needs approval** |
Stretch: reranking improves nDCG@5 on dev and test without a latency penalty above 20%; review rate falls without any rise in unsafe acceptance.

## 6. Baseline freeze (after approval, before any change)
Record git commit, Python/Node, PostgreSQL 16.15 / pgvector 0.8.7, Ollama version, model digest (read from the server), MiniLM revision `1110a243...`, torch/sentence-transformers versions, prompt versions (hash of prompt text), retrieval weights, chunking config,
citation-verification and incident-validation rules, dataset hashes, hardware (i7-1165G7, 15.7 GB, CPU only), OS, and the exact commands. Baseline = current system, run on **dev and test** (test run once and sealed as the baseline report; not inspected for tuning),
three repetitions for model-dependent steps. Deterministic backends are run separately and never reported as AI quality.

## 7. Experiment plan (dev split only; every run logged, including failures)
| # | Hypothesis | Change | Primary measures |
|---|---|---|---|
| E1 | Chunking affects multi-relevant recall | chunk size {200,300,450 tokens} x overlap {0,15%} | Recall@5, nDCG@5, index size |
| E2 | Hybrid weight is not optimal on a harder corpus | vector/text weight grid with RRF vs weighted sum | nDCG@5, MRR |
| E3 | Metadata filters (asset id, doc version) reduce hard-negative confusion | exact-id and current-version filters | precision, version-conflict accuracy |
| E4 | Query reformulation (identifier extraction, deterministic) helps | no LLM, rules only | Recall@5, latency |
| E5 | Evidence-aware context selection (diverse top passages) improves grounding | selection rules | grounded coverage, claim support |
| E6 | Prompt variants reduce unsupported claims | 3 prompt versions, temperature fixed | claim support, false refusal |
| E7 | Stricter deterministic citation/quote verification raises correctness | verifier rules | citation correctness vs coverage trade-off |
| E8 | Calibrated abstention threshold improves refusal behaviour | threshold sweep on dev | correct abstention vs false refusal |
| E9 | A CPU feature-based reranker using the already installed MiniLM embeddings and lexical features helps | no new weights | nDCG@5, latency overhead |
| E10 | Extraction prompt and validation improvements | 3 prompt versions, asset-in-report check kept | raw schema validity, review routing |
Controlled comparison: identical dev inputs, paired per-query differences; effects attributed separately to retrieval, prompting, deterministic validation, reranking and abstention logic (ablations of each on the final configuration).
A neural cross-encoder reranker or any larger LLM would need new weights; **none is proposed**, and if dev evidence later suggests one, a separate approval request (model, licence, source, size, expected benefit) will be made.
Selection rule (declared now): pick the configuration with the best dev grounded-answer coverage subject to citation correctness >= baseline, no safety-gate regression and p95 latency within the proposed budget; ties broken by simplicity. Then freeze code, prompts and thresholds, record hashes, and run test once, then the challenge split once.

## 8. Statistics
Wilson intervals for proportions, bootstrap (10,000) over queries for retrieval metrics, paired bootstrap and McNemar for comparisons, 3 repetitions for model-dependent runs reported as run-to-run spread (not as extra samples), per-tenant and combined results, no significance
claims on differences inside the interval. Variation across queries, runs, tenants and load conditions is reported separately.

## 9. Human-review workload and manual comparison
Review rate overall and per tenant, split into true-positive safety reviews, false-positive reviews and missed unsafe incidents against labels; supervisor intervention counts. Review duration is **simulated/measured application time only** (no human participants).
Manual baseline: a scripted manual-procedure model (keyword search over the same corpus, manual classification by rule table, template ticket drafting) with measured script timings for the mechanical steps and **clearly labelled assumptions** for human reading/typing time with a sensitivity range.
No observed human productivity, cost savings, ROI or staffing claims; if any financial scenario is shown it is labelled assumption-based with sensitivity analysis.

## 10. Latency and resources
Warm versus cold model runs (documented warm-up), single-user and 2/4 concurrent requests, at least 30 timed repetitions per condition, p50/p95 (p99 only when n >= 200), tokens/s, CPU and peak memory (psutil sampling of the Ollama and Python processes), indexing time, database/index size,
reranker overhead and failure/retry overhead. Background load is recorded. No extrapolation to cloud capacity.

## 11. Resource budget (local, CPU-only; estimates from Phase 3 latencies of 3.3-4.1 s median per LLM call)
- Dataset generation and validation: minutes. Embedding about 1,400 chunks with MiniLM on CPU: a few minutes per index build.
- One answer pass (about 100 dev queries) about 7-10 min; one extraction pass (60 cases) about 4-6 min. Ten experiments plus ablations about 4-6 hours of wall-clock in total; baseline plus final runs (3 repetitions each) about 2-3 hours.
- Disk: well under 1 GB. No paid services, no downloads. Ollama is started and stopped by `scripts/ollama_ctl.py`; disruptive tests only against this project's own PostgreSQL container.

## 12. Risks
| Risk | Mitigation |
|---|---|
| Author-generated labels bias results | disclosure, consistency checks, optional human sample review |
| Small test split gives wide intervals | interval-based verdicts; challenge split; no point-estimate claims |
| 1.5B model cannot reach 95% citation correctness | trade-off reporting; grounded coverage reported beside it; target stays NOT MET if so |
| Overfitting to dev | frozen test, split by family, selection rule fixed in advance |
| Test exposure through debugging | disclosure rule; no second final run |
| Optimisation weakening a safety control | full security and UAT/FI re-run at the end; any regression fails the gate |
| Template-style synthetic text inflates scores | varied realisations per fact, hard negatives, near-duplicate similarity check |
| Latency growth from extra stages | trade-off table with overhead per change |
| Windows/CPU measurement noise | repetition, warm-up, background-load record |

## 13. Deliverables
The 11 documents and artifacts in section 23 of the instruction, plus `evaluation/phase8/` (generator, metrics, runner, scorer), `evaluation/datasets/eval-v2/`, `evaluation/reports/phase8/` (manifests, raw per-query results, aggregates),
`tests/test_phase8_metrics.py`, `tests/test_phase8_dataset_integrity.py`, `tests/test_phase8_report_consistency.py`.

## 14. Decisions requested at Gate B
1. Approve (or amend) protocol v1.0 as written, including the dataset sizes and the three-split design.
2. Approve or change the **new** thresholds (grounded coverage, abstention, claim support, p95 latency).
3. Provide the V4.1 specification text (or approve adding it under `docs/`) so the audit can map catalogue ids to exact clauses.
4. Optional: can a human review a sample of about 30 labels? If not, results will say "author-generated labels, no independent validation".
5. Confirm that no neural reranker or additional model is wanted; the feature reranker (E9) uses only installed models.
