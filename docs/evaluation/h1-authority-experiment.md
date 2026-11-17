# Experiment H1: unverified-note authority ordering against the CAND1 baseline (development split)

**Decision: REJECT.** Development evidence, same author, one repetition; nothing here is a confirmation. Held-out and challenge data were not used (no `--allow-heldout`). The default behaviour is unchanged: the flag is off by default. The default model stays `qwen2.5:1.5b`. The negative result is preserved; the flag and tests stay in the code, disabled.

## Setup
- Hypothesis: five `conflicting_record` dev queries cite a self-declared unverified note instead of a retrieved manual page; ordering such notes behind same-subject unmarked passages before context selection fixes this without weakening grounding.
- Implementation commit `c619fab` (`backend/app/ai/authority.py`, `authority_demotion` in `tuning.py`, one call in `rag.py`; lint-only follow-up commit afterwards). Generic marker list (unverified, unconfirmed, not verified, unofficial, hearsay); subject = non-numeric content words of the note after removing authority words; a note is moved behind the unmarked passages when at least half of its subject words occur in one of them. Nothing is deleted; note-only retrieval is unchanged.
- Run `evaluation/reports/phase8/exp-H1-20261114T214610Z` (QA phase, 1 repetition, 653 s), baseline `exp-CAND1-20261112T090552Z` repetition 1. Same model (`qwen2.5:1.5b`, digest `65ec06548149`), prompts, options (temperature 0, seed 7, num_ctx 4096), retrieval, scorer and denominators. Tuning = CAND1 tuning plus `"authority_demotion": true`. Command: `python evaluation/phase8/run_experiment.py --id H1 --tuning <CAND1 tuning + flag> --phases qa --reps 1`; score with `score_experiment.py <dir> --baseline <CAND1 dir>`.
- Criteria fixed beforehand (task authorization): citation correctness up by more than about 3 paired queries; claim support >= 96.6%; correct abstention >= 22/23; unsupported-answer rate <= 16.9%; unsupported numeric accepted 0; false refusals 0; no tenant/numeric regression.

## Measured results
| Metric | CAND1 | H1 |
|---|---|---|
| Citation correctness (answerable) | 91.9% | 91.2% (83/91) |
| Grounded answer coverage | 66.7% | 65.5% (57/87) |
| Claim support | 96.6% | 96.7% (146/151) |
| Correct abstention | 22/23 | 22/23 |
| Unsupported-answer rate | 16.9% (12/71) | 19.2% (14/73) |
| False refusals | 0/87 | 0/87 |
| Withheld by verifier | 17/87 | 15/87 |
| Latency p50 / p95 | 4.30 s / 11.36 s | 4.57 s / 10.66 s |

Paired grounded-correct: 1 improved, 2 regressed, 84 unchanged; correct refusal 23 unchanged. Run wall time 653 s. Peak memory is not recorded by the harness for this run (not measured).

Failed criteria: citation correctness did not improve (it fell); unsupported-answer rate 19.2% > 16.9%. Passed: claim support, correct abstention, false refusals. The harness does not report an unsupported-numeric-accepted count for this run, so that criterion is not separately evidenced beyond the numeric-verification tests passing. Either failure alone means REJECT.

## Five targeted conflicting-record cases
All five were unchanged in the sense that matters: four (E2-A-0058, E2-M-0047, E2-M-0049, E2-M-0050) still answer "usually taken as ..." from the unverified note with the same marker, now citing a chunk from a freshly ingested copy. E2-M-0048 changed answer text ("105 C" became a service-record sentence for VH-1002) and is still grounded; whether it is now correct was not separately adjudicated here. Corrected: 0. Unchanged: 4 (cited-note behaviour). Changed but not shown to be corrected: 1. Regressed: 0.
Why the four did not change was not established: the run does not record which passages were given to the model, so it is unknown whether a relevant manual passage was among the retrieved hits or whether the subject-overlap rule matched. No causal claim is made.

## Non-target changes
Answer text or status changed for 28 queries in total (27 outside the target set) (the ordering of passages given to the model changes generation even at temperature 0). Net status changes outside the target set: regressed E2-A-0010 (identifier not in evidence), E2-A-0066 (numbers not found), E2-A-0088 (quote not found); improved E2-A-0048, E2-M-0027, E2-M-0031, E2-M-0060, E2-M-0070 (previously withheld, now answered; correctness was not individually adjudicated beyond the scorer's totals); E2-M-0062 stayed withheld (now invalid-JSON withhold). These shifts are consistent with evidence ordering affecting generation, but the mechanism per query was not isolated.

## Interpretation and limits
The rule as implemented did not fix the targeted mechanism and perturbed unrelated queries, raising the unsupported-answer rate. One repetition, noise about 3 queries, no significance test. A better-targeted attempt would first need a retrieval-only diagnostic of which passages the five queries retrieve (no model inference), which would need a new owner decision if it requires a run.

## Regression tests
`backend/tests/test_authority_demotion.py` 13 passed; targeted backend suites (safeguards, RAG, decompose, numeric, RLS, real-AI, quality, security, identity, asset resolution, review gate) 168 passed / 12 skipped and 73 passed before the run. No full backend or root suite was executed for this experiment.
