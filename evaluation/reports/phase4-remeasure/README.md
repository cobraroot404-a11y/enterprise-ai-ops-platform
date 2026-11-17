# Phase 4 re-measurement (real Ollama + MiniLM, frozen apex-eval-v1)

Phase 3 results (`evaluation/reports/phase3/`) are unchanged and are the baseline. These three runs repeat the
**same harness, dataset, models, prompts and dev-only threshold calibration** against the code as it stands after the
Phase 4 changes (AI safeguards, incident review gate, identity hardening, resource limits). Nothing was tuned on the
held-out test split.

## Reproduce
```bash
python scripts/ollama_ctl.py start
python evaluation/benchmarks/run_phase4.py --embedding sentence_transformers --llm ollama --e2e-runs 5 --qa-repeats 2   # x3
python evaluation/benchmarks/compare_phase3_phase4.py     # writes COMPARISON.md / COMPARISON.json from the raw files
python scripts/ollama_ctl.py stop
```
`run_phase4.py` imports `run_phase3.py` unchanged and only adds measurement: it records each incident's
`review_status` and runs the end-to-end step through the human-review gate (a supervisor review is recorded whenever
the platform demands one).

## Identity
- Backends: `ollama` + `sentence_transformers` (real AI, not deterministic stand-ins). Ollama 0.40.16, `qwen2.5:1.5b`
  (digest `65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b`), prompt v3, temperature 0, seed 7;
  MiniLM `sentence-transformers/all-MiniLM-L6-v2` @ `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, evidence threshold 0.50
  (calibrated on the dev split only, as in Phase 3). CPU only (Intel i7-1165G7, 15.7 GB RAM).
- Dataset: `apex-eval-v1` text-file SHA-256 `e7401e1b86e8...` identical in all six runs (checked by the comparison script).
- Per-run evidence: `<run>/manifest.json` (command, versions, hardware, timestamps), `results.json`, `qa_test.jsonl`,
  `retrieval_test.jsonl`, `structured.jsonl`. Runs: `20261111T213143Z`, `20261111T213808Z`, `20261111T214410Z`.

## Result: Phase 3 vs Phase 4 (min-max over 3 runs each; full table in COMPARISON.md)
| Metric | Phase 3 | Phase 4 |
|---|---|---|
| Recall@5 / MRR | 100% / 0.917 | 100% / 0.917 |
| Citation correctness | 89.3-92.6% | 89.3-92.6% (25 of 27-28 citations) |
| Unsupported-answer rate | 14.3-17.2% | 14.3-17.2% |
| Correct refusal (unanswerable) | 6 of 8 (75%) | 6 of 8 (75%) |
| Answer coverage (answerable) | 75.0-77.8% | 75.0-77.8% |
| Grounded-answer correctness | 85.7-88.9% | 85.7-88.9% |
| Structured model-output validity | 23/24 | 23/24 |
| LLM inference median / p95 (s) | 3.26-4.13 / 5.7-6.7 | 3.38-3.71 / 5.66-6.36 |
| E2E workflow median (s) | 5.52-6.21 | 6.16-6.29 |
| E2E completion | 15/15 submitted, 0 duplicates | 15/15 submitted, 0 duplicates |

**Citation correctness remains below the 95% target: the target stays NOT MET.**

Definitions (identical for both phases, computed from raw per-query files by the comparison script): *answer coverage*
= answerable questions that received a verified, grounded answer; *grounded-answer correctness* = grounded answers
whose key facts appear and whose citations all point at the labelled relevant unit; *unsupported-answer rate* = grounded
answers that are for an unanswerable question, have an incorrect citation, or lack the key facts; *correct refusal* =
unanswerable questions that received an insufficient-evidence response.

## New measurements (Phase 4 only)
- Incident review, 24 fault reports: **18-19 `needs_review`, 4-5 `pending_review`, 1 rejected at extraction** (the
  hallucinated asset ID). In the last run's database (the only one retained) all 18 `needs_review` incidents had a registered asset and the reason
  was *no grounded evidence*: the 1.5B model's troubleshooting answer was withheld by citation verification, so the guidance step produced
  no verified citation.
- End-to-end: in 4 of the 5 workflow runs of every benchmark run, the incident needed a human review before a ticket could
  be drafted (same cause). All 15 workflow runs completed and submitted once, with zero duplicates.

## Regression notes (honest reading)
1. **No change in AI quality metrics.** The Phase 4 safeguards (identifier/number support checks, citation source
   ownership) target failure modes found by probing, and none of them fired on this dataset: every withheld answer was
   a "quote not found in the cited passage" (13) or "no verified citations" (3) failure across the three runs; no
   unsupported-identifier or unsupported-number problem was reported. So this re-measurement shows **no
   regression and no improvement** in answer quality; it does not demonstrate that the new safeguards help here.
2. **Operational cost of the review gate is large with this model.** Roughly three in four incidents (18-19 of 24) now
   stop for human review because the small model rarely produces a verifiable grounded recommendation. That is the
   intended safe behaviour (missing evidence must block), but it means the human-in-the-loop workload is high. Reducing it
   requires better evidence generation (larger model or better prompting, which needs approval and a fresh evaluation
   on a non-test split), not relaxing the gate.
3. **Latency:** inference latency is unchanged within run-to-run variation. The end-to-end median is slightly higher
   (about 6.2 s vs 5.5-6.2 s) because it now includes the supervisor review call and the larger code path; the difference
   is within the Phase 3 range.
4. The 24 fault reports and 44 test queries are the same synthetic, author-labelled sets used in Phase 3 (no confidence
   intervals; one query is about 2.3 percentage points). Real-model output varies slightly even at temperature 0, which
   is why ranges, not single numbers, are reported.
