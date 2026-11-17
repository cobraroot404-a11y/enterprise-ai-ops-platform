# Experiment Q3I4B: qwen3:4b-instruct against the CAND1 baseline (development split)

**Decision: REJECT (not eligible for independent validation as run).** Development evidence, same author, 118 dev queries (87 answerable, 31 not) and 34 extraction cases; nothing here is a confirmation. Held-out and challenge splits were not used; held-out figures stay 89.8% / 59.3% / 90%. The default model stays `qwen2.5:1.5b`; no code, configuration or numeric trust policy changed.

## Setup
- Hypothesis: a 4B model reduces the generation-side failures (verifier withholds, citation and completeness errors) without hurting abstention or schema validity.
- Model: `qwen3:4b-instruct`, digest `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`, 2.5 GB, Q4_K_M, 4.0B parameters, Apache-2.0, Ollama 0.40.16. Smoke test: valid JSON-schema output, no thinking field, no `<think>` text.
- Run `evaluation/reports/phase8/exp-Q3I4B-20261114T074346Z` (1 repetition, phases qa and extraction, duration 1505 s), reference `exp-CAND1-20261112T090552Z` (`qwen2.5:1.5b`, digest `65ec06548149`, repetition 1). Identical tuning (CAND1), prompts, retrieval, scorer and denominators; dataset hashes verified by the runner (manifest `42fec8bc...`, frozen splits `31d18132...`).
- Command: `OLLAMA_MODEL=qwen3:4b-instruct python evaluation/phase8/run_experiment.py --id Q3I4B --tuning <CAND1 tuning> --phases qa,extraction --reps 1`; score: `python evaluation/phase8/score_experiment.py <dir> --baseline <CAND1 dir>` (output `comparison.json`; its "baseline" column is CAND1).
- Criteria fixed before the run: ACCEPT only if citation correctness rises above CAND1 by more than the run-to-run noise (about 3 queries) and there is no regression in abstention, schema validity, unsupported numeric accepted or unsupported-answer rate; p95 latency above 3x CAND1 (about 34 s) is an operational blocker.

## Results (dev, repetition 1)
| Metric | CAND1 (1.5B) | Q3I4B (4B) |
|---|---|---|
| Citation correctness (answerable) | 91.9% (79/86) | 93.6% (73/78) |
| Grounded answer coverage | 66.7% (58/87) | 72.4% (63/87) |
| Claim support | 96.6% | 99.1% (111/112) |
| Correct abstention | 95.7% (22/23) | 95.7% (22/23) |
| False refusals | 0/87 | 19/87 (21.8%) |
| Withheld by verifier | 17/87 | 0/87 |
| Unsupported-answer rate | 16.9% (12/71) | 8.7% (6/69) |
| Raw schema validity (extraction) | 100% (34/34) | 100% (34/34) |
| Unsupported numeric accepted as verified | 0 | 0 |
| Priority accuracy / final category accuracy | 88.2% / 73.5% | 79.4% / 91.2% |
| Review rate / evidence completeness | 38.2% / 73.5% | 91.2% / 11.8% |
| Latency p50 / p95 (QA) | 4.3 s / 11.4 s | 8.6 s / 15.3 s |
| Extraction latency p95 | 10.5 s | 22.5 s |
| Peak Ollama working set | (1.5B: about 1.5-2.5 GB per setup doc) | 5.1 GB (system free RAM minimum 130 MB of 16 GB) |

Paired per query (grounded-correct): 12 improved, 7 regressed, 68 unchanged (net +5, near the noise of about 3 queries, one repetition, no interval claimed). Correct-refusal: 23 unchanged.

## Decision
- Citation correctness: +1.7 points, within noise; fails the first criterion. The 95% target is not met.
- Abstention was not worse, but the model itself declared insufficient evidence on 19 answerable queries (false refusals 0 -> 19) while the verifier withholds fell to 0; that is a new regression in answering rate and is not offset by the unsupported-answer fall.
- Extraction: review rate rose to 91% and evidence completeness fell to 12% (CAND1 74%), priority accuracy fell by 3 cases; the machine-assisted workflow gains of CAND1 were largely lost.
- Operational: p95 within the 3x limit, but peak memory 5.1 GB drove system free RAM to about 130 MB on this 16 GB machine, and the run took 1505 s against about 660 s.

**REJECT.** Positives worth recording: claim support, unsupported-answer rate and final category accuracy improved, and no unsupported number was accepted. The refusal behaviour suggests a prompt interaction (the prompts were tuned for the 1.5B model); investigating it would be new tuning and needs another owner decision. No rerun or tuning was done.

## Limitations
One repetition; same-author dev split; prompts tuned for the baseline model; interval widths not computed; memory is a working-set sample, not a controlled benchmark.

## Rollback
`ollama rm qwen3:4b-instruct` removes the model (2.5 GB); nothing else was changed. Ollama was stopped after the run.
