# Phase 8 evaluation protocol, version 1.1 (conditionally approved at Gate B; this revision awaits the next checkpoint approval)

Supersedes `phase8-evaluation-protocol.md` (v1.0, kept unchanged for the record). Companion documents: `phase8-metric-definitions.md` (v1.1), `phase8-dataset-methodology.md` (v1.1 note at top),
`phase8-requirements-gap-audit.md`, `phase8-baseline-report.md`, `phase8-experiment-plan.md`, `phase8-risk-register.md`, `errata/apex-eval-v1-manifest-erratum.md`.

## 1. Changes from v1.0 (instruction of the Gate B decision)
| # | Change |
|---|---|
| 1 | Thresholds updated: grounded-answer coverage >= 75% (diagnostic floor 60%), correct abstention >= 90% (was 85%), claim-level support >= 95% (was 90%). Retained: Recall@5 >= 85%, citation correctness >= 95%, raw schema validity 100%, p95 latency <= 15 s (provisional), zero leakage/unauthorised/duplicate actions. |
| 2 | Statistical reporting: every proportion reports numerator, denominator, percentage, 95% Wilson interval, sample size, split and tenant; classification uses OBSERVED TARGET MET / OBSERVED TARGET NOT MET / NOT EVALUABLE; an interval overlapping the target is never read as equivalence. |
| 3 | Labels: author-generated (disclosed). No AI second pass is performed or described as review. A 28-item stratified worksheet for independent human review is prepared (`phase8-label-review-sample.md`); no reviewer has been assigned. |
| 4 | Specification completeness is UNVERIFIED (specification text not in the repository); reconciliation framework prepared, catalogue not edited. |
| 5 | Erratum E-001 corrects the Gate B claim about `apex-eval-v1`: the manifest `queries` object (12+36+4+8) matches the 60 query lines; a different hash-algorithm naming inconsistency was found and documented. |
| 6 | Baseline is run on the DEV split only (the test and challenge splits stay sealed until the single final evaluation). |
| 7 | Every experiment carries hypothesis, configuration, expected benefit, safety impact, latency impact, measurement and rollback criteria (see `phase8-experiment-plan.md`). |

## 2. Threshold classes
**Safety-critical acceptance gates (any failure fails Phase 8):** cross-tenant leakage 0; unauthorised external submissions 0; duplicate external actions 0; approval or human-review bypass 0 (including through prompt injection and retrieved
content); unsafe automatic acceptance of incidents labelled must-review 0; existing security suites (SSRF/egress, RLS, RBAC, JWT, identity, review gate, control mutations) 100% pass; historical Phase 3/4/7 evidence unmodified.

**Engineering quality targets (reported OBSERVED MET / NOT MET / NOT EVALUABLE; may be missed without failing the phase):** Recall@5 >= 85%; citation correctness >= 95%; grounded-answer coverage >= 75%; correct abstention >= 90%;
claim support >= 95%; raw extraction schema validity 100% (kept as its own target, never replaced by post-validation safety); p95 end-to-end latency <= 15 s (provisional until baseline shows it is practical on the documented CPU).

**Diagnostic thresholds:** grounded-answer coverage floor 60% (below it the configuration is considered unusable for the workflow and is reported as such); precision reported with its ceiling; human-review rate reported with true/false-positive split (no threshold).

**Optional stretch goals:** reranking improves nDCG@5 on dev and test without more than 20% latency increase; review rate falls without any rise in unsafe acceptance.

## 3. Dataset (eval-v2.0, frozen)
215 labelled queries (152 answerable; 51 expected-refusal; 12 adversarial injection cases where an answer is optional), 60 incident-extraction cases, 717 current / 735 total passages (Apex) and 694 / 712 (Meridian), the superseded manual versions included.
Splits by scenario group: dev 118 queries + 34 cases, test 75 + 20, challenge 22 + 6. Counts, overlaps, hashes and validation results: `evaluation/datasets/eval-v2/validation_report.json`, `FROZEN.md`, `MANIFEST.sha256`, `frozen_splits.json`.
Known limitations: author-generated labels; synthetic, template-assisted text (several surface forms per fact, but a fixed fact vocabulary); superseded versions are not retrievable by design, so version-conflict queries test ingestion versioning more than ranking;
the paraphrase queries still share domain vocabulary with the sources. The test and challenge splits have not been inspected for tuning.

## 4. Baseline (dev split, current system unchanged)
Procedure and recorded configuration: `evaluation/phase8/run_baseline.py` and `evaluation/reports/phase8/baseline-*/manifest.json` (git commit, Python/Node, PostgreSQL/pgvector, Ollama version, model digest, MiniLM revision, prompt hashes, Ollama options, retrieval and
chunking behaviour, evidence threshold, dataset and split hashes, hardware, OS). Three repetitions for model-dependent steps; headline = repetition 1 with Wilson intervals, spread from the others; retrieval repeated once to test ranking determinism.
Scores are computed only by `evaluation/phase8/score_baseline.py` from the raw per-item files. Deterministic backends are not used for any baseline figure.

## 5. Optimisation, final evaluation and acceptance
Unchanged from v1.0 and the Gate B instruction: ten development-only experiments (see `phase8-experiment-plan.md`), no new model weights, no neural reranker, selection rule fixed in advance, freeze, then ONE held-out evaluation on test (then challenge).
If held-out information is exposed during optimisation the contamination is disclosed and instructions are requested before any claim of an unbiased evaluation. A safety-critical regression fails the gate regardless of quality improvements.
Execution gate: PASS / FAIL. Quality targets: MET / NOT MET / NOT EVALUABLE. Production readiness: NOT ASSESSED / NOT READY / PILOT CANDIDATE / READY with justification (nothing in Phase 8 will label the platform production-ready on local synthetic evidence alone).

## 6. Resource budget and known nondeterminism
Local CPU only, about 40-60 minutes per baseline (three repetitions on dev), Ollama `qwen2.5:1.5b` (temperature 0, fixed seed) and MiniLM; no downloads. Model outputs are expected to be repeatable at temperature 0 with a fixed seed but this is verified by the repetition spread, not assumed;
HNSW approximate search and tie ordering can make retrieval rankings differ between runs (measured by the repeated retrieval pass). Windows scheduling and background load add latency noise (documented per run).
