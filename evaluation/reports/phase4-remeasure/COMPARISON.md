# Phase 3 vs Phase 4 (real Ollama + MiniLM, frozen apex-eval-v1 held-out test split)

Dataset identical across all runs: **True** (sha256 e7401e1b86e88f26...).
Phase 3 runs: 3; Phase 4 runs: 3. Ranges are min-max across runs. Generated from raw per-query files by `python evaluation/benchmarks/compare_phase3_phase4.py`.

| Metric | Phase 3 | Phase 4 |
|---|---|---|
| Recall@5 | 100.0-100.0% | 100.0-100.0% |
| MRR | 0.917-0.917 | 0.917-0.917 |
| Citation correctness | 89.3-92.6% | 89.3-92.6% |
| Unsupported-answer rate | 14.3-17.2% | 14.3-17.2% |
| Correct refusal rate (unanswerable) | 75.0-75.0% | 75.0-75.0% |
| Answer coverage (answerable) | 75.0-77.8% | 75.0-77.8% |
| Grounded-answer correctness | 85.7-88.9% | 85.7-88.9% |
| Structured model-output validity | 95.8-95.8% | 95.8-95.8% |
| LLM inference median (s) | 3.26-4.13 | 3.38-3.71 |
| LLM inference p95 (s) | 5.7-6.7 | 5.66-6.36 |
| Question wall-clock median (s) | 2.81-3.59 | 3.14-3.35 |
| Question wall-clock p95 (s) | 5.1-6.5 | 5-5.89 |
| E2E workflow median (s) | 5.52-6.21 | 6.16-6.29 |

E2E completion: 20261111T191232: 5/5 submitted, 0 duplicates; 20261111T191943: 5/5 submitted, 0 duplicates; 20261111T192730: 5/5 submitted, 0 duplicates; 20261111T213143: 5/5 submitted, 0 duplicates; 20261111T213808: 5/5 submitted, 0 duplicates; 20261111T214410: 5/5 submitted, 0 duplicates

Phase 4 incident review (structured set, 24 reports): run 1: 4 pending_review, 19 needs_review, 1 rejected at extraction; run 2: 5 pending_review, 18 needs_review, 1 rejected at extraction; run 3: 5 pending_review, 18 needs_review, 1 rejected at extraction

E2E runs needing human review: 4, 4, 4
