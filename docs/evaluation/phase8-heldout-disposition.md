# Phase 8 held-out disposition

**Decision recorded (2026-11-12, after the held-out evaluation):** the held-out evaluation evidence is **accepted for review**. Promotion of the evaluated candidate is **NOT APPROVED**. Further optimisation is **NOT APPROVED**. Phase 9 is **NOT YET APPROVED**.
This document records the frozen evidence and the engineering disposition; it changes no code, configuration, dataset, label, scorer or result.

## A. Frozen Phase 8 evidence (preserved; nothing below was modified by this checkpoint)

| Item | Identifier |
|---|---|
| Original baseline (dev, 3 repetitions) | `evaluation/reports/phase8/baseline-20261112T035539Z`, evidence commit `ad178d6`, run at code commit `49d3c92` |
| Invalid first baseline (token expiry) | `evaluation/reports/phase8/INVALID-baseline-20261112T030653Z-token-expiry` (preserved, marked INVALID) |
| Development experiments E1-E10 and additions C1-C3, E8b, E10d | `evaluation/reports/phase8/exp-*` (29 run directories), code commit `d5a7e41`, log `docs/evaluation/phase8-optimization-log.md` |
| Integrated development candidate, 3 repetitions | `evaluation/reports/phase8/exp-CAND1-20261112T090552Z`, commit `a14bbb4`, report `docs/evaluation/phase8-candidate-report.md` |
| Independent held-out evaluation (test split) | `exp-HELDOUT-BASELINE-20261112T190915Z`, `exp-HELDOUT-CANDIDATE-20261112T193240Z`, pre-flight `evaluation/reports/phase8/heldout/preflight.json`, harness commit `a2571a4`, evidence commit `0f9c954`, report `docs/evaluation/phase8-heldout-report.md` |
| Dataset | `eval-v2.0`, freeze commit `c0d19c9`; test split SHA-256 `19540a5c88eb7943a640f0fb802de6f40612c32a70e0a58c1ac4af2cb3e6893a` (75 queries, 20 incident cases); dev `623b612b...`, challenge `7d18b6bc...` (full hashes in `frozen_splits.json`) |
| Candidate configuration | `evaluation/phase8/configs/candidate_v1.json`; hash `4e24e63f3f2d06c31946d07e52d6f3a5c6c378a1f47b9b0535d8750368268e03`; enabled only through `EAOP_TUNING` |
| Scorer versions | scoring v1.1 formulas unchanged since the baseline; v1.2 adds only the numeric-audit metrics and per-query flags (36 additive keys, every stored baseline metric reproduces exactly). SHA-256 of the 17 scoring, harness and candidate files before and after the run: `preflight.json` (`code_sha256`), re-verified unchanged |
| Environment | `evaluation/reports/phase8/heldout/hardware.json`, `system_before.txt`, `system_after.txt`, `ollama_state_before.txt`; Ollama 0.40.16 `qwen2.5:1.5b` digest `65ec06548149`; MiniLM revision `1110a243...`; PostgreSQL 16.15 / pgvector 0.8.7; Python 3.10.0 |
| Raw reports | per-query JSONL, manifests, scores and failure analyses in each run directory |
| Historical results | Phase 3 and Phase 4 reports, Phase 7 evidence, unchanged |

Development results and held-out results are reported in separate documents and are never merged. The development results are optimistic for the candidate (parameters were selected on that split); the held-out results are observational.

**Test split status: CONSUMED for candidate_v1** (hash above), recorded 2026-11-12 in `evaluation/reports/phase8/heldout/TEST_SPLIT_CONSUMED.json`. Any further claim of an unbiased result requires a fresh, untouched evaluation set; the test split must not be used to select or tune any successor configuration.
**Blindness caveat:** the evaluation was not strictly blind. The Gate B label-review worksheet (generated before any model run or optimisation) displays the labels of 11 test-split items (`E2-A-0019, E2-A-0050, E2-A-0070, E2-A-0084, E2-A-0087, E2-A-0098, E2-A-0115, E2-M-0024, E2-M-0038, E2-M-0065, E2-M-0071`) and one test id is mentioned in `phase8-dataset-methodology.md`. No model output for them was seen and no tuning decision used them; the exposure is of labels only.

## B. Engineering disposition

**The candidate is not approved as the new default** because, on the held-out split (repetition 1, candidate against the unchanged baseline):
- grounded-answer coverage was 59.3% (baseline 64.8%) against the later 75% target: NOT MET, paired +4 / -7;
- citation correctness was 89.8% (baseline 95.1%) against the original 95% target: NOT MET for the candidate;
- the unsupported-answer rate rose to 20.0% (baseline 12.5%);
- Meridian multi-hop questions were answered correctly 0 of 5 times;
- raw extraction schema validity was 90% (18/20) against the original 100% target: NOT MET (identical for the baseline; the two failures are no-asset reports the application rejected).
With 54 answerable queries these differences are not statistically distinguishable from zero, but the point estimates do not support promotion and the development gains in grounding did not replicate.

**Findings preserved (supported by both splits; no recombined configuration has been validated):**
- retrieval: recall@5 0.895 -> 0.963 and nDCG@5 0.803 -> 0.940 (paired bootstrap intervals exclude zero), with no foreign passages;
- abstention: 17/17 correct refusals and no false refusals (baseline 16/17 and 1);
- numeric safety: 0 unsupported numeric values accepted as verified (baseline 1 on held-out, 3 on dev);
- review burden and workflow: human-review rate 88.9% -> 27.8% with grounded evidence 11.1% -> 72.2%, no must-review case missed, 6/6 workflow cases submitted with no unauthorized or duplicate external action;
- every safety gate held; the full suites pass under the candidate settings.

**Not done, by instruction:** no component is reverted or promoted automatically; the shipped default remains the baseline behaviour (every switch is off unless `EAOP_TUNING` enables it); the candidate is not recombined, ablated on held-out data or re-run. Any new integrated configuration needs separate authorization and an independent evaluation on fresh, untouched data.

## C. Effect on the V4.1 reconciliation
The specification reconciliation (`docs/specification/`) classifies the corresponding original requirements as Partial with their quality targets recorded as NOT MET where applicable (V41-13.04 grounded answers, V41-13.05 citation correctness, V41-13.06 insufficient-evidence handling, V41-21.04 citation-correctness target, V41-21.05 schema-validity target; V41-14.02 'validate model output' is Partial and classed as a critical workflow-safety gap: the shipped default still accepts unsupported model-proposed numeric values, which only the non-promoted candidate prevents); none is upgraded on the strength of development results.

## D. Decision this disposition leaves open
The numeric-measurement audit is the one candidate component whose purpose is safety rather than quality (it stops a hallucinated measurement from escalating an incident priority). Because no component may be promoted automatically, the default configuration continues to carry that weakness. Whether to authorise enabling it by default, and how to evaluate it on fresh untouched data, is a decision for the owner.
