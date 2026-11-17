# Experiment H2: structured low-authority note suppression against the CAND1 baseline (development split)

**Decision: REJECT.** Development evidence, same author, one repetition, no confirmation value. Held-out/challenge data not used (no `--allow-heldout`). The flag `low_authority_suppression` stays default-off; default model stays `qwen2.5:1.5b`. Negative result preserved. No rerun without a new owner decision.

## Setup
- Hypothesis (after the deterministic diagnostic showed H1 reordering could not change context membership): removing a self-declared unverified service/incident note from the generation context, when a same-model authoritative manual passage on the same topic is also in context, fixes `conflicting_record` answers.
- Implementation commit `e4b670178101a76b546cb6c6fcb1a7b10d9eb6e4`: `backend/app/ai/suppression.py`, flag in `tuning.py`, one call in `rag.py` (applied after `context_k` selection, so "retained" means actually in the model's context; no refill). Tests `backend/tests/test_low_authority_suppression.py` (22).
- Suppression condition (all required): hit kind in {incident_history, service_history, maintenance_log}; parsed `category: note`; description self-declares low authority (unverified/unconfirmed/not verified/unofficial/hearsay); `equipment_id`/`vehicle_id` resolves through the register (`resolve_models`) to exactly one model; a retained `equipment_manual`/`fleet_manual` passage that is not itself low-authority names that model as a whole token; >=60% (min 2) of the note's claim words (plural-folded, authority/identifier words removed) occur in the manual; the note's non-asset identifiers occur in the manual and, if the note has a value, the manual also states a value. Any doubt keeps the note. No dataset-specific identifiers in code (tested). The 0.6 threshold was fixed before inference.
- Tuning = CAND1 tuning (`entity_boost 0.02, entity_gate, query_override_gate, claim_completion, numeric_verification, guidance_query asset_context`) plus `"low_authority_suppression": true`; tuning hash `c9ef06c2...6430cd`. Model `qwen2.5:1.5b` digest `65ec06548149`; same prompts, options, retrieval, scorer.
- Baseline `evaluation/reports/phase8/exp-CAND1-20261112T090552Z`; run `evaluation/reports/phase8/exp-H2-20261114T231340Z` (QA only, 1 rep, 619.6 s). Command: `python evaluation/phase8/run_experiment.py --id H2 --tuning <above> --phases qa --reps 1`; score with `score_experiment.py <run> --baseline <CAND1>`.
- Pre-inference no-LLM check (`evaluation/phase8/diag_context.py`): H2 triggered on all five targets, each time with the matching same-model manual passage and structured identity (P-1010 to CP-250, VH-2009 to MX-300, VH-1002 to LV-260, VH-2202 to RT-95, VH-3111 to CP-200).

## Results (CAND1 vs H2)
| Metric | CAND1 | H2 |
|---|---|---|
| Citation correctness (answerable) | 91.9% (79/86) | 95.4% (83/87) |
| Grounded answer coverage | 66.7% (58/87) | 65.5% (57/87) |
| Claim support | 96.6% (143/148) | 96.55% (140/145) |
| Correct abstention | 22/23 | **21/23** |
| Unsupported-answer rate | 16.9% (12/71) | 15.7% (11/70) |
| False refusals | 0/87 | 0/87 |
| Withheld by verifier | 17/87 | 19/87 |
| Latency p50 / p95 | 4.30 / 11.36 s | 4.20 / 10.97 s |

Paired grounded-correct: 2 improved, 3 regressed, 82 unchanged; correct refusal: 1 regressed. Unsupported-numeric-accepted is not reported by the harness for this run (not separately evidenced). Peak memory not measured.

Failed fixed criteria: correct abstention 21/23 (< 22/23); claim support 96.55% (< 96.6%, marginal). Citation gain (+4 queries by count) passed the approximate 3-query margin but any failing criterion means REJECT. Passed: unsupported-answer rate, false refusals.

## Five targets
| Query | Triggered / note suppressed / manual / identity | Outcome |
|---|---|---|
| E2-A-0058 | yes / yes / apex CP-250 manual p5 / P-1010 -> CP-250 | was wrong (note value 0.04); now withheld ("number 1010 not found in cited evidence"): not corrected |
| E2-M-0047 | yes / yes / MX-300 manual p2 / VH-2009 -> MX-300 | was wrong; now withheld (number 2009 not in cited evidence) |
| E2-M-0048 | yes / yes / LV-260 manual p5 / VH-1002 -> LV-260 | was wrong ("105 C"); now grounded but a different wrong answer (brake pressure/coolant 87 C from an inspection report): not corrected |
| E2-M-0049 | yes / yes / RT-95 manual p4 / VH-2202 -> RT-95 | **corrected**: "6.5 kg" cited to the manual |
| E2-M-0050 | yes / yes / CP-200 manual p1 / VH-3111 -> CP-200 | was wrong; now withheld (number 3111 not in cited evidence) |

Corrected 1, wrong-to-withheld 3 (fewer wrong answers, no gained coverage), still wrong 1. The mechanism is partly established: removing the note removed the only passage containing the asset id, so the model's restatement of the asset id fails the numeric/identifier check. That is a causal reading from the problem strings, not an isolated test.

## Non-target changes
Status changed on 10 non-target queries: improved E2-A-0048, E2-M-0027, E2-M-0031, E2-M-0060, E2-M-0070 (withheld to grounded; correctness not individually adjudicated), E2-A-0093 (withheld to refused); regressed E2-A-0053, E2-A-0071, E2-M-0054 (grounded to withheld), E2-A-0103 (unanswerable: refused to grounded, the abstention failure), E2-A-0088/E2-M-0068 (injection cases changed status). H2 suppresses only structured note records, so most of these shifts are likely generation variation, as in H1; per-query cause was not isolated.

## Limits and next step
One repetition; noise about 3 queries; same-author dev data. The identity of the suppressed passages per query was verified deterministically, not recorded by the run. A possible follow-up is verifier-side (do not require the asset id restated in the answer to appear in the cited evidence when the question supplied it); that is a new hypothesis and needs a new owner decision.
