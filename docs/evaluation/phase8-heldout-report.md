# Phase 8 held-out evaluation report (frozen candidate versus unchanged baseline, frozen test split)

**Status of this evidence.** One observational evaluation on the frozen `test` split (75 queries, 20 incident cases; challenge split not run), approved with conditions. Nothing was tuned, re-run or selected on these results. Labels are author-generated, content is synthetic, customers are fictional; this is not customer-deployment evidence and does not establish production readiness.

## 1. Candidate identity and configuration
- Candidate: `evaluation/phase8/configs/candidate_v1.json` = `{"entity_boost": 0.02, "entity_gate": true, "query_override_gate": true, "claim_completion": true, "numeric_verification": true, "guidance_query": "asset_context"}`; hash **`4e24e63f3f2d06c31946d07e52d6f3a5c6c378a1f47b9b0535d8750368268e03`** (equals the frozen value `4e24e63f...268e03`); enabled through `EAOP_TUNING` (`--tuning`); manifest-recorded tuning hash: baseline `2ff914dd6fc75694...` (defaults), candidate `4e24e63f3f2d06c31946d07e52d6f3a5c6c378a1f47b9b0535d8750368268e03`.
- Baseline: the unchanged defaults (`EAOP_TUNING` empty), i.e. the system as validated in Phases 3-7.
- Models: Ollama `qwen2.5:1.5b` digest `65ec06548149`, Ollama 0.40.16; MiniLM `sentence_transformers:sentence-transformers/all-MiniLM-L6-v2@1110a243fdf4706b3f48f1d95db1a4f5529b4d41:384`; options {'temperature': 0, 'seed': 7, 'num_ctx': 4096, 'num_predict': 320}; evidence threshold 0.5.

## 2. Git commit and environment
- Pre-flight HEAD `a2571a4`; run manifests record commits baseline `a2571a4`, candidate `a2571a4`; python 3.10.0; PostgreSQL 16.15 (Debian 16.15-1.pgdg12+2), pgvector 0.8.7; hardware `evaluation/reports/phase8/heldout/hardware.json` (Intel i7-1165G7, CPU-only, 15.7 GB RAM), system state before the runs `system_before.txt`, Ollama state `ollama_state_before.txt`.
- Execution order: baseline first (started 2026-11-12T19:09:15.129761+00:00, 1398.2 s), then candidate (started 2026-11-12T19:32:40.038620+00:00, 1465.7 s), sequentially on the same machine; each run re-creates the isolated database, re-onboards both tenants, ingests the same corpus (the superseded manual versions first), runs `ANALYZE`, then a warm-up question (model resident, cold start not measured), then 3 repetitions of QA and extraction, then the workflow checks. Three repetitions are repeated measurements of the same cases (counts identical across repetitions: baseline False, candidate False); headline = repetition 1.

## 3. Dataset, scorer and pre-execution integrity evidence
| # | Pre-execution check | Result |
|---|---|---|
| 1 | expected branch and clean working tree | PASS |
| 2 | HEAD commit and configuration hash recorded | PASS |
| 3 | candidate configuration hash equals the frozen value | PASS |
| 4 | frozen held-out dataset hash matches the recorded manifest | PASS |
| 5 | dataset, labels, metric definitions and protocol unchanged since freezing; scorer changes are additive | PASS |
| 6 | all 15 baseline integrity checks pass | PASS |
| 7 | baseline and candidate development evidence preserved | PASS |
| 8 | no held-out items inspected or used during optimisation | PASS |
| 9 | additive scorer keys do not alter historical metrics | PASS |
| 10 | candidate is enabled explicitly through EAOP_TUNING and recorded | PASS |

Frozen test split sha256 `19540a5c88eb7943a640f0fb802de6f40612c32a70e0a58c1ac4af2cb3e6893a` (75 queries, 20 incident cases), unchanged since `c0d19c9`. Scoring and candidate code were hashed before the run and re-checked after it (see section 12).
**Disclosure (check 8).** The held-out ids were never in any recorded run output and no run before this evaluation used the test split. However, the label-review worksheet generated at the Gate B checkpoint (before any model run or optimisation) displays the labels of 11 test-split items (E2-A-0019, E2-A-0050, E2-A-0070, E2-A-0084, E2-A-0087, E2-A-0098, E2-A-0115, E2-M-0024, E2-M-0038, E2-M-0065, E2-M-0071), and one test id is mentioned in the dataset methodology note. No model output for those items was seen and no tuning decision used them, but this is a partial exposure of labels and the evaluation should not be described as blind in the strictest sense.

## 4. Baseline versus candidate on the test split (repetition 1; numerator/denominator = percentage (Wilson 95%))

| Metric | Baseline | Candidate | Target | Candidate target attainment |
|---|---|---|---|---|
| Grounded-answer coverage | 35/54 = 64.8% (51.5-76.2) | 32/54 = 59.3% (46.0-71.3) | 75% | NOT MET (point estimate; interval below target) |
| Answer coverage | 39/54 = 72.2% (59.1-82.4) | 40/54 = 74.1% (61.1-83.9) |  |  |
| False refusals | 1/54 = 1.8% (0.3-9.8) | 0/54 = 0.0% (0.0-6.6) |  |  |
| Withheld by verification | 14/54 = 25.9% (16.1-38.9) | 14/54 = 25.9% (16.1-38.9) |  |  |
| Citation correctness (answerable) | 39/41 = 95.1% (83.9-98.7) | 44/49 = 89.8% (78.2-95.6) | 95% | NOT MET (point estimate; interval overlaps target) |
| Citation tenant ownership | 44/44 = 100.0% (92.0-100.0) | 51/51 = 100.0% (93.0-100.0) | 100% | MET (point estimate; interval overlaps target) |
| Claim support | 61/63 = 96.8% (89.1-99.1) | 67/70 = 95.7% (88.1-98.5) | 95% | MET (point estimate; interval overlaps target) |
| Correct abstention | 16/17 = 94.1% (73.0-99.0) | 17/17 = 100.0% (81.6-100.0) | 90% | MET (point estimate; interval overlaps target) |
| Unsupported-answer rate | 5/40 = 12.5% (5.5-26.1) | 8/40 = 20.0% (10.5-34.8) |  |  |
| Raw extraction schema validity | 18/20 = 90.0% (69.9-97.2) | 18/20 = 90.0% (69.9-97.2) | 100% | NOT MET (point estimate; interval below target) |
| Priority accuracy | 15/18 = 83.3% (60.8-94.2) | 16/18 = 88.9% (67.2-96.9) |  |  |
| Category accuracy | 11/18 = 61.1% (38.6-79.7) | 11/18 = 61.1% (38.6-79.7) |  |  |
| Incidents with grounded evidence | 2/18 = 11.1% (3.1-32.8) | 13/18 = 72.2% (49.1-87.5) |  |  |
| Human-review rate | 16/18 = 88.9% (67.2-96.9) | 5/18 = 27.8% (12.5-50.9) |  |  |
| Unsafe automatic acceptance (must-review cases) | N/A | N/A |  |  |
| Unsupported numeric values accepted as verified | 1 of 3 proposed | 0 of 3 proposed | 0 | GATE MET |
| p95 `/ai/ask` latency | 12.1 s (p50 4.63) | 11.5 s (p50 4.58) | 15 s | OBSERVED TARGET MET |
| p95 `/incidents/extract` latency | 8.0 s | 10.7 s | | |

Denominators: 54 answerable and 17 expected-refusal test queries (plus injection cases with optional answers), 20 incident cases: these are small, so every interval is wide and no target is statistically established either way unless the interval lies entirely on one side (stated in the last column). **Paired comparison** on the identical queries: grounded-correct improved 4, regressed 7, unchanged 43 (exact McNemar p = 0.548828125); correct refusal improved 1, regressed 0, unchanged 16 (exact McNemar p = 1.0). Development runs showed that identical configurations differ by about three queries from run to run, so paired differences of that size are not evidence of improvement. A point-estimate increase is not reported as established improvement unless the paired test supports it.

**Notes on specific rows.** (a) *Unsafe automatic acceptance* is **NOT EVALUABLE** on the test split: it contains no incident case labelled must-review (denominator 0), so the dev-split result (0 of 4) is the only evidence for that metric. (b) *Raw schema validity 90% (18/20)* in both configurations: the two invalid raw outputs are the two reports with no identifiable asset (`E2-A-X028`, `E2-M-X028`), where the model invented an asset id; the application rejected both (422 `asset_not_identified`), so no unsafe incident was created, but the 100% model-level target is **NOT MET**. (c) Baseline false refusal 1/54 and baseline unsupported numerics 1 (one hallucinated vibration value accepted by the baseline pipeline; the candidate's audit routed it to review).

## 5. Retrieval (answerable test queries with labelled passages)

| Scope | Config | n | R@1 | R@3 | R@5 | R@10 | P@5 (ceiling) | MRR | nDCG@5 | nDCG@10 | p50/p95 ms | foreign passages |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| combined | baseline | 54 | 0.5772 | 0.8704 | 0.8951 | 0.9259 | 0.2148 (0.263) | 0.79 | 0.803 | 0.8156 | 29/37 | 0 |
| combined | candidate | 54 | 0.787 | 0.9321 | 0.963 | 0.963 | 0.2407 (0.263) | 0.9367 | 0.9398 | 0.9398 | 56/83 | 0 |
| apex | baseline | 35 | 0.619 | 0.9524 | 0.9524 | 0.981 | 0.2171 (0.2343) | 0.8083 | 0.842 | 0.851 | 29/35 | 0 |
| apex | candidate | 35 | 0.7905 | 0.981 | 0.9905 | 0.9905 | 0.2286 (0.2343) | 0.9238 | 0.9403 | 0.9403 | 56/94 | 0 |
| meridian | baseline | 19 | 0.5 | 0.7193 | 0.7895 | 0.8246 | 0.2105 (0.3158) | 0.7561 | 0.7311 | 0.7503 | 30/39 | 0 |
| meridian | candidate | 19 | 0.7807 | 0.8421 | 0.9123 | 0.9123 | 0.2632 (0.3158) | 0.9605 | 0.9388 | 0.9388 | 56/73 | 0 |

Recall@5 combined: baseline 0.8951 (bootstrap 95% CI [0.821, 0.9568]), candidate 0.963 (CI [0.9321, 0.9877]); target 85%: baseline MET, candidate MET (point estimates). Paired bootstrap (candidate minus baseline): recall@5 {'n': 54, 'mean_diff': 0.06790123456790124, 'ci95': [0.018518518518518517, 0.12962962962962962]}, nDCG@5 {'n': 54, 'mean_diff': 0.13680477105851704, 'ci95': [0.08463040217062609, 0.19713758713126647]}.

## 6. Tenant-specific results (Apex and Meridian reported separately; aggregates do not replace them)

| Tenant | Metric | Baseline | Candidate |
|---|---|---|---|
| apex | Grounded coverage | 23/35 = 65.7% (49.1-79.2) | 21/35 = 60.0% (43.6-74.5) |
| apex | Answer coverage | 25/35 = 71.4% (54.9-83.7) | 26/35 = 74.3% (57.9-85.8) |
| apex | False refusals | 0/35 = 0.0% (0.0-9.9) | 0/35 = 0.0% (0.0-9.9) |
| apex | Citation correctness | 24/26 = 92.3% (75.9-97.9) | 27/31 = 87.1% (71.2-94.9) |
| apex | Claim support | 40/41 = 97.6% (87.4-99.6) | 44/44 = 100.0% (92.0-100.0) |
| apex | Correct abstention | 9/10 = 90.0% (59.6-98.2) | 10/10 = 100.0% (72.2-100.0) |
| apex | Unsupported-answer rate | 4/26 = 15.4% (6.2-33.5) | 4/26 = 15.4% (6.2-33.5) |
| apex | Raw schema validity | 9/10 = 90.0% (59.6-98.2) | 9/10 = 90.0% (59.6-98.2) |
| apex | Priority accuracy | 8/9 = 88.9% (56.5-98.0) | 9/9 = 100.0% (70.1-100.0) |
| apex | Category accuracy | 6/9 = 66.7% (35.4-87.9) | 6/9 = 66.7% (35.4-87.9) |
| apex | Review rate | 8/9 = 88.9% (56.5-98.0) | 3/9 = 33.3% (12.1-64.6) |
| apex | Grounded evidence | 1/9 = 11.1% (2.0-43.5) | 6/9 = 66.7% (35.4-87.9) |
| apex | Unsupported numerics accepted | 1 of 2 | 0 of 2 |
| meridian | Grounded coverage | 12/19 = 63.2% (41.0-80.8) | 11/19 = 57.9% (36.3-76.9) |
| meridian | Answer coverage | 14/19 = 73.7% (51.2-88.2) | 14/19 = 73.7% (51.2-88.2) |
| meridian | False refusals | 1/19 = 5.3% (0.9-24.6) | 0/19 = 0.0% (0.0-16.8) |
| meridian | Citation correctness | 15/15 = 100.0% (79.6-100.0) | 17/18 = 94.4% (74.2-99.0) |
| meridian | Claim support | 21/22 = 95.5% (78.2-99.2) | 23/26 = 88.5% (71.0-96.0) |
| meridian | Correct abstention | 7/7 = 100.0% (64.6-100.0) | 7/7 = 100.0% (64.6-100.0) |
| meridian | Unsupported-answer rate | 1/14 = 7.1% (1.3-31.5) | 4/14 = 28.6% (11.7-54.6) |
| meridian | Raw schema validity | 9/10 = 90.0% (59.6-98.2) | 9/10 = 90.0% (59.6-98.2) |
| meridian | Priority accuracy | 7/9 = 77.8% (45.3-93.7) | 7/9 = 77.8% (45.3-93.7) |
| meridian | Category accuracy | 5/9 = 55.6% (26.7-81.1) | 5/9 = 55.6% (26.7-81.1) |
| meridian | Review rate | 8/9 = 88.9% (56.5-98.0) | 2/9 = 22.2% (6.3-54.7) |
| meridian | Grounded evidence | 1/9 = 11.1% (2.0-43.5) | 7/9 = 77.8% (45.3-93.7) |
| meridian | Unsupported numerics accepted | 0 of 1 | 0 of 1 |

## 7. Safety gates

| Gate | Baseline | Candidate | Outcome |
|---|---|---|---|
| Cross-tenant data in retrieval (foreign passages / retrieved) | 0 / 750 | 0 / 750 | MET |
| Citation tenant ownership | 44/44 = 100.0% (92.0-100.0) | 51/51 = 100.0% (93.0-100.0) | MET |
| Cross-tenant probe heuristic flags (answer or citation carrying the other tenant's value) | 0 of 3 | 0 of 3 | flags are reviewed manually in section 9 |
| Unauthorized external submissions (submission before approval accepted / non-approver approval accepted) | 0 / 0 | 0 / 0 | MET |
| Duplicate external submissions | 0 | 0 | MET |
| Unsupported numerics accepted as verified | 1 | 0 | MET |
| Must-review incidents not held for review | 0 | 0 | MET |
| Workflow completion (authorized path: extract, review if needed, draft, approval, outbox, mock submission) | 6/6 | 6/6 | recovery from injected failures is covered by the fault-injection suite (section 12), not by this run |

Workflow errors recorded: baseline [], candidate []. Human approval is enforced by the platform (these checks attempt a pre-approval submission and a non-approver approval; both must be refused). The review gate, tenant-scoped retrieval, RLS, RBAC and egress controls are unchanged code paths verified by the full suites in section 12.

## 8. Failure analysis (candidate, test split, observational; the candidate was not modified)

- Answerable queries not grounded-correct: {'wrong passage: sibling/hard-negative page': 4, 'withheld: numeric mismatch': 7, 'withheld: incorrect quotation': 7, 'incomplete evidence: required fact missing from answer': 3, 'wrong passage: unlabelled or unrelated': 1} (Apex 14, Meridian 8).
- Unanswerable queries still answered: [].
- Citations to passages outside the labelled evidence: 5 ({'keyword': 1, 'paraphrase': 1, 'conflicting_record': 2, 'multi_hop': 1}).

Representative traceable cases (synthetic data; `evaluation/reports/phase8/exp-HELDOUT-CANDIDATE-*/failure_analysis.json` and `qa_rep1.jsonl` carry the full evidence):

- `E2-M-0029` (multi_hop): incomplete evidence: required fact missing from answer - What minimum battery voltage applies to VH-3001, and what reference was logged when that check was last carrie - missing ['12.1', 'REF-5364']; relevant needs 3 passages, cited 1
- `E2-M-0033` (multi_hop): withheld: numeric mismatch - What minimum brake pad thickness applies to VH-2002, and what reference was logged when that check was last ca - identifier(s) not found in the evidence: REF-7097; number(s) not found in the cited evidence: 02, 12, 7097
- `E2-M-0034` (multi_hop): incomplete evidence: required fact missing from answer - What low brake pressure warning threshold applies to VH-3002, and what reference was logged when that check wa - missing ['REF-9672']; relevant needs 3 passages, cited 2
- `E2-M-0035` (multi_hop): wrong passage: unlabelled or unrelated - What wheel nut torque applies to VH-5101, and what reference was logged when that check was last carried out o - [('meridian_service_history.csv', 'SR-2025-0153')]
- `E2-M-0036` (multi_hop): withheld: incorrect quotation - What minimum brake pad thickness applies to VH-7110, and what reference was logged when that check was last ca - citation [1] quote not found in the cited passage; answer marker [1] has no verified citation
- `E2-M-0043` (version_conflict): withheld: incorrect quotation - What is the low brake pressure warning threshold of the HX-410? - citation [1] quote not found in the cited passage
- `E2-M-0057` (asset_confusion): withheld: incorrect quotation - What service brake line pressure did the 2026Q2 inspection record for VH-7111? - citation [1] quote not found in the cited passage; answer marker [1] has no verified citation
- `E2-M-0067` (procedure): withheld: numeric mismatch - The depot transfer pump shows this problem: pump is noisy with warm bearings. What should be checked? - number(s) not found in the cited evidence: 1, 4

Meridian-specific investigation (sections 9-10 below) uses the same raw outputs.

## 9. Meridian investigation (no change to the candidate)

- Grounded-answer coverage 12/19 = 63.2% (41.0-80.8) -> 11/19 = 57.9% (36.3-76.9); citation correctness 15/15 = 100.0% (79.6-100.0) -> 17/18 = 94.4% (74.2-99.0); priority accuracy 7/9 = 77.8% (45.3-93.7) -> 7/9 = 77.8% (45.3-93.7); category accuracy 5/9 = 55.6% (26.7-81.1) -> 5/9 = 55.6% (26.7-81.1); unsupported-answer rate 1/14 = 7.1% (1.3-31.5) -> 4/14 = 28.6% (11.7-54.6); false refusals 0/19 = 0.0% (0.0-16.8).
- Numeric extraction: Meridian signals proposed/unsupported: 0 of 1; accepted as verified 0.
- By-category outcome counts (Meridian, candidate): {'asset_confusion': {'answerable': 2, 'not_answered': 1, 'grounded_correct': 1}, 'compare': {'answerable': 1, 'grounded_correct': 1}, 'keyword': {'answerable': 3, 'grounded_correct': 3}, 'multi_hop': {'answerable': 5, 'grounded_correct': 0, 'not_answered': 2}, 'paraphrase': {'answerable': 3, 'grounded_correct': 3}, 'procedure': {'answerable': 2, 'grounded_correct': 1, 'not_answered': 1}, 'unanswerable': {'unanswerable': 7, 'correct_refusals': 7}, 'version_conflict': {'answerable': 3, 'grounded_correct': 2, 'not_answered': 1}}.

## 10. Interpretation limits

Small denominators (see section 4); one synthetic dataset with author-generated labels; the candidate's accepted parameters and gate patterns were selected on the dev split of the same generator, so some optimism is expected and a smaller held-out gain than on dev would be unsurprising; the citation-correctness rule is conservative (an unlabelled genuine passage counts as incorrect) and claim support is a surface test of numbers and identifiers; mock external systems; a 1.5B model that still hallucinates numbers and quotes; CPU-only local latency, no extrapolation to cloud capacity; coarse resource sampling.

## 11. Latency and resources (single user, warm model, documented laptop; unreliable to better than about +/-15% run to run)

| Run | `/ai/ask` p50 / p95 | `/incidents/extract` p95 | Retrieval p95 | Ingestion | CPU mean (QA rep1) | Ollama peak RSS | Python peak RSS | Workflow wall time |
|---|---|---|---|---|---|---|---|---|
| baseline | 4.63 / 12.1 s | 8.0 s | 37 ms | 23.8 s | 63.3% | 1693.3 MB | 843.6 MB | 23.3 s |
| candidate | 4.58 / 11.5 s | 10.7 s | 83 ms | 33.2 s | 59.2% | 1877.2 MB | 804.3 MB | 43.1 s |

Tokens per second and model load are those of the unchanged model and options; concurrency was not re-measured (the application's inference limiter behaviour is unchanged). p99 not reported (n < 200).

## 12. Regression results and post-run integrity

- run_window_EST: 2026-11-12 14:58-15:16 (after the held-out runs; application and candidate code unchanged since pre-flight, hashes re-verified)
- Post-run check: scoring/candidate/harness code unchanged since the pre-flight (SHA-256 of 17 files): True
- Backend full suite, default settings: 358 passed, 13 skipped (12 real-AI, opt-in FI-10), 0 failed
- Backend full suite, candidate settings (EAOP_TUNING=candidate_v1): 358 passed, 13 skipped, 0 failed
- Fault injection FI-01..FI-10, FI-09b, REL-01..04 under candidate with RUN_DISRUPTIVE=1 (includes PostgreSQL stop/restart, failure recovery): 15 passed, 0 failed
- Real-AI backend tests under candidate (Ollama + MiniLM): 12 passed
- UAT-A01..A08, UAT-B01..B07, end-to-end reliability and observability evidence, real Ollama, under candidate: 21 passed
- Security suites (SSRF/egress, RLS, RBAC, JWT, identity, review gate, control mutations, environment guards): included in both full suites: all passed
- Frontend (default settings): typecheck clean, lint clean, Vitest 43 passed, Playwright 47 passed / 1 skipped (opt-in screenshots)
- Secret scan: 0 findings in 680 files
- Dataset freeze: frozen hashes OK; test split sha256 19540a5c88eb7943a640f0fb802de6f40612c32a70e0a58c1ac4af2cb3e6893a unchanged since c0d19c9
- Phase 7 evidence files rewritten by test runs: restored from git after each run (not part of this evidence)

## 13. Limitations and remaining requirements gaps

- The 85-requirement traceability catalogue is **provisional**; the original V4.1 specification is preserved but not reconciled (completeness UNVERIFIED). No claim of complete V4.1 compliance or production readiness is made; reconciliation is a separate mandatory checkpoint.
- Not implemented or only partial (see the matrix): ingestion deletion and jobs, reranking as a product feature, CSV/webhook connectors, OpenTelemetry/Prometheus, cloud portability, delivery documents, CI that has never run, publication. Network-level egress control, distributed rate limiting and independent security review are not provided.

## 14. Evidence paths and reproduction commands

- Pre-flight: `evaluation/reports/phase8/heldout/preflight.json` (`python evaluation/phase8/preflight_heldout.py`).
- Baseline run `exp-HELDOUT-BASELINE-20261112T190915Z`, candidate run `exp-HELDOUT-CANDIDATE-20261112T193240Z` (raw per-item outputs, manifests, retrieval, workflow, results).
- Reproduce: `bash evaluation/phase8/configs/run_heldout.sh` (requires explicit approval: it evaluates the frozen test split), then `python evaluation/phase8/score_experiment.py <run_dir>` and `python evaluation/phase8/make_heldout_report.py <summary.json>`.

## 15. Final recommendation

**What the evidence supports (test split, small samples, observational):** (1) retrieval improvement is real and robust: recall@5 0.895 -> 0.963, nDCG@5 0.803 -> 0.940, with the paired bootstrap interval for the nDCG@5 difference excluding zero, in both tenants and with no foreign passages; (2) the human-review burden fell from 88.9% to 27.8% with grounded evidence rising from 11.1% to 72.2% while no must-review case was missed and no unsupported numeric value was accepted (the baseline accepted one); (3) correct abstention was 17/17 (baseline 16/17) with no false refusals (baseline 1); (4) every safety gate held.
**What it does not support:** the development-split gains in grounded-answer coverage and citation correctness **did not replicate**. Grounded coverage was 59.3% (baseline 64.8%; paired +4/-7), citation correctness 89.8% (baseline 95.1%) and the unsupported-answer rate 20.0% (baseline 12.5%); with 54 answerable queries these differences are not statistically distinguishable from zero, but the point estimates point the wrong way, and in Meridian multi-hop questions (0 of 5 grounded-correct) and quotation failures dominate. This evaluation cannot attribute the regression to a component (no ablation on held-out data is allowed), and dev-tuned parameters and the answer-side citation-completion step are the obvious suspects.
**Targets:** NOT MET: grounded-answer coverage (75%), raw extraction schema validity (100%, 18/20), citation correctness (95% point estimate 89.8%). Point-estimate MET with intervals overlapping the target (not established): Recall@5, claim support, correct abstention, p95 latency. NOT EVALUABLE: unsafe automatic acceptance on this split. Safety gates: MET.
**Recommendation:** do not describe the candidate as an overall quality improvement or as production-ready. The retrieval, abstention, numeric-audit and review-burden changes are supported by both splits and are reasonable to keep as opt-in or default-candidate components after your review; the answer-side changes (in particular citation completion) are not supported by the held-out result and should be analysed on development data only (ablation of C3 and the entity gate, quotation failures, Meridian multi-hop) under a new approval before any further held-out use. The held-out split has now been consumed for the frozen candidate; any modified candidate would need a fresh, untouched evaluation set to claim an unbiased result. The V4.1 specification reconciliation and the 85-requirement catalogue remain provisional; completeness is UNVERIFIED.
