# Phase 8 baseline report (dev split, current system unchanged)

Run `baseline-20261112T035539Z` (commit `49d3c92` at run time; application code identical to Phase 7 closure `0837a52`). Real Ollama `qwen2.5:1.5b` (digest `65ec06548149`, Ollama 0.40.16) and MiniLM `sentence_transformers:sentence-transformers/all-MiniLM-L6-v2@1110a243fdf4706b3f48f1d95db1a4f5529b4d41:384` on Intel64 Family 6 Model 140 Stepping 1, GenuineIntel; dataset eval-v2.0 dev split (118 queries, 34 incident cases) - the test and challenge splits were not used. All numbers below are produced by `score_baseline.py` from the raw files; integrity checks: `phase8-baseline-integrity.md` (all pass). A first attempt of this baseline is preserved as INVALID (token expiry; see `evaluation/reports/phase8/INVALID-baseline-20261112T030653Z-token-expiry/INVALID.md`).

**Reading the numbers.** Percentages are repetition 1 with 95% Wilson intervals (in brackets). The three repetitions are repeated measurements of the *same* queries, not independent samples: spread across repetitions is shown separately. The dev split is the data the optimisation will use, so these are baseline diagnostics, not held-out results. Labels are author-generated.

## 1. Retrieval (answerable queries with labelled passages; hybrid is the shipped mode)

| Scope | n | R@1 | R@3 | R@5 | R@10 | P@5 (ceiling) | MRR | nDCG@5 | nDCG@10 | latency p50/p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| combined | 87 | 0.5057 | 0.8391 | 0.8851 | 0.9119 | 0.2368 (0.2828) | 0.7843 | 0.7918 | 0.8013 | 30/42 ms |
| apex | 43 | 0.4961 | 0.8682 | 0.8837 | 0.8915 | 0.2512 (0.3023) | 0.8023 | 0.8058 | 0.8104 | 30/40 ms |
| meridian | 44 | 0.5152 | 0.8106 | 0.8864 | 0.9318 | 0.2227 (0.2636) | 0.7667 | 0.7781 | 0.7925 | 30/44 ms |

Recall@5 (combined, hybrid) 0.8851 with bootstrap 95% CI [0.8276, 0.9349]: target >= 0.85 is **OBSERVED TARGET MET** (the interval reaches below 0.85, so this is an observation, not an established pass).

Mode comparison on the same queries (combined):

| Mode | R@1 | R@5 | MRR | nDCG@5 |
|---|---|---|---|---|
| hybrid | 0.5057 | 0.8851 | 0.7843 | 0.7918 |
| vector | 0.5172 | 0.8851 | 0.79 | 0.796 |
| fts | 0.5441 | 0.8851 | 0.8058 | 0.8069 |

Hybrid retrieval is **not** shown to be better than either component on this dev set: recall@5 is identical across modes and text-only is slightly ahead on R@1/MRR/nDCG@5 (differences not tested for significance).
Cross-tenant leakage: 0 foreign passages of 3519 retrieved. Ranking repeatability (hybrid, two passes): {'identical': 118, 'different': 0}. Hybrid recall@5 by category: {'asset_confusion': {'n': 5, 'value': 0.8}, 'compare': {'n': 10, 'value': 1.0}, 'conflicting_record': {'n': 5, 'value': 0.8}, 'keyword': {'n': 16, 'value': 1.0}, 'multi_hop': {'n': 13, 'value': 0.6154}, 'paraphrase': {'n': 22, 'value': 0.8636}, 'procedure': {'n': 6, 'value': 1.0}, 'version_conflict': {'n': 10, 'value': 1.0}}.

## 2. Citation, grounding and abstention (repetition 1)

| Metric | Combined | Apex | Meridian | Target / class (combined) |
|---|---|---|---|---|
| Grounded-answer coverage | 54/87 = 62.1% (51.6-71.5%) | 26/43 = 60.5% (45.6-73.6%) | 28/44 = 63.6% (48.9-76.2%) | 75% OBSERVED TARGET NOT MET |
| Answer coverage (answer presented) | 65/87 = 74.7% (64.7-82.7%) | 33/43 = 76.7% (62.3-86.9%) | 32/44 = 72.7% (58.1-83.7%) |   |
| False refusals | 0/87 = 0.0% (0.0-4.2%) | 0/43 = 0.0% (0.0-8.2%) | 0/44 = 0.0% (0.0-8.0%) |   |
| Answers withheld by verification | 22/87 = 25.3% (17.3-35.3%) | 10/43 = 23.3% (13.2-37.7%) | 12/44 = 27.3% (16.4-41.9%) |   |
| Citation correctness (answerable) | 66/77 = 85.7% (76.2-91.8%) | 36/43 = 83.7% (70.0-91.9%) | 30/34 = 88.2% (73.4-95.3%) | 95% OBSERVED TARGET NOT MET |
| Citation correctness (all emitted) | 66/93 = 71.0% (61.1-79.2%) | 36/49 = 73.5% (59.7-83.8%) | 30/44 = 68.2% (53.4-80.0%) | 95% OBSERVED TARGET NOT MET |
| Citation id validity | 93/93 = 100.0% (96.0-100.0%) | 49/49 = 100.0% (92.7-100.0%) | 44/44 = 100.0% (92.0-100.0%) |   |
| Citation tenant ownership | 93/93 = 100.0% (96.0-100.0%) | 49/49 = 100.0% (92.7-100.0%) | 44/44 = 100.0% (92.0-100.0%) | 100%  |
| Verbatim quote correctness | 93/93 = 100.0% (96.0-100.0%) | 49/49 = 100.0% (92.7-100.0%) | 44/44 = 100.0% (92.0-100.0%) |   |
| Claim support | 130/133 = 97.7% (93.6-99.2%) | 77/79 = 97.5% (91.2-99.3%) | 53/54 = 98.2% (90.2-99.7%) | 95% OBSERVED TARGET MET |
| Correct abstention | 14/23 = 60.9% (40.8-77.8%) | 8/10 = 80.0% (49.0-94.3%) | 6/13 = 46.2% (23.2-70.9%) | 90% OBSERVED TARGET NOT MET |
| Unanswerable answered wrongly | 9/23 = 39.1% (22.2-59.2%) | 2/10 = 20.0% (5.7-51.0%) | 7/13 = 53.8% (29.1-76.8%) |   |
| Unsupported-answer rate | 21/74 = 28.4% (19.4-39.5%) | 9/35 = 25.7% (14.2-42.1%) | 12/39 = 30.8% (18.6-46.4%) |   |

Diagnostic floor (60%): grounded-answer coverage 54/87 = 62.1% (51.6-71.5%) -> OBSERVED TARGET MET (interval overlaps the floor).
Grounded-answer coverage by query category (answered correctly / answerable): {'asset_confusion': '4/5', 'compare': '8/10', 'conflicting_record': '4/5', 'keyword': '16/16', 'multi_hop': '2/13', 'paraphrase': '22/22', 'procedure': '0/6', 'version_conflict': '9/10'}.

Run-to-run spread (same queries): {'grounded_answer_coverage': {'per_rep': [0.6207, 0.6322, 0.6322], 'min': 0.6207, 'max': 0.6322}, 'citation_correctness_answerable': {'per_rep': [0.8571, 0.8816, 0.8784], 'min': 0.8571, 'max': 0.8816}, 'claim_support': {'per_rep': [0.9774, 0.9845, 0.9843], 'min': 0.9774, 'max': 0.9845}, 'correct_abstention': {'per_rep': [0.6087, 0.6087, 0.6087], 'min': 0.6087, 'max': 0.6087}}. Identical answer text, repetition 1 vs 2/3: {'rep1_vs_rep2': 107, 'rep1_vs_rep3': 106} of 118; identical extraction outcome (category, priority, review status): {'rep1_vs_rep2': 34, 'rep1_vs_rep3': 34} of 34.

## 3. Safety measurements on the dev split

- Cross-tenant: retrieval 0 foreign passages; citation tenant ownership 93/93 = 100.0% (96.0-100.0%). The scorer's cross-tenant probe heuristic flagged 1 of 8 probes; manual inspection of the flagged item (E2-M-0091) shows the answer came from Meridian's own CP-200 manual with a verified quote (the value 0.08 coincides with the Apex CP-250 value, which triggered the string heuristic). No foreign data was returned; the answer was nevertheless wrong (it answered about a different model), counted as an unanswerable query answered wrongly. The heuristic and labels were not changed (frozen).
- Prompt-injection effect heuristic: 0 flagged of 12 injection/bypass cases. Approval-bypass attempts through the assistant: no action path exists from `/ai/ask`.
- Workflow (6 cases): 6 submitted; unauthorised submission/approval accepted: 0; duplicate external actions: 0; reviews required: 6 of 6; external tickets {'ticketing_tickets': 3, 'servicedesk_tickets': 3}.

## 4. Structured extraction (repetition 1)

| Metric | Combined | Apex | Meridian |
|---|---|---|---|
| raw_schema_validity | 34/34 = 100.0% (89.8-100.0%) | 17/17 = 100.0% (81.6-100.0%) | 17/17 = 100.0% (81.6-100.0%) |
| raw_asset_correct | 34/34 = 100.0% (89.8-100.0%) | 17/17 = 100.0% (81.6-100.0%) | 17/17 = 100.0% (81.6-100.0%) |
| raw_category_correct | 25/34 = 73.5% (56.9-85.4%) | 15/17 = 88.2% (65.7-96.7%) | 10/17 = 58.8% (36.0-78.4%) |
| hallucinated_identifier_rate | 0/34 = 0.0% (0.0-10.2%) | 0/17 = 0.0% (0.0-18.4%) | 0/17 = 0.0% (0.0-18.4%) |
| hallucinated_numeric_signal_rate | 3/6 = 50.0% (18.8-81.2%) | 3/6 = 50.0% (18.8-81.2%) | N/A |
| post_validation_acceptance | 34/34 = 100.0% (89.8-100.0%) | 17/17 = 100.0% (81.6-100.0%) | 17/17 = 100.0% (81.6-100.0%) |
| final_asset_correct | 34/34 = 100.0% (89.8-100.0%) | 17/17 = 100.0% (81.6-100.0%) | 17/17 = 100.0% (81.6-100.0%) |
| final_category_accuracy | 25/34 = 73.5% (56.9-85.4%) | 15/17 = 88.2% (65.7-96.7%) | 10/17 = 58.8% (36.0-78.4%) |
| priority_accuracy | 28/34 = 82.3% (66.5-91.6%) | 15/17 = 88.2% (65.7-96.7%) | 13/17 = 76.5% (52.7-90.4%) |
| evidence_completeness | 8/34 = 23.5% (12.4-40.0%) | 3/17 = 17.6% (6.2-41.0%) | 5/17 = 29.4% (13.3-53.1%) |
| review_rate | 27/34 = 79.4% (63.2-89.6%) | 14/17 = 82.3% (59.0-93.8%) | 13/17 = 76.5% (52.7-90.4%) |
| review_routing_correct | 11/34 = 32.4% (19.1-49.2%) | 5/17 = 29.4% (13.3-53.1%) | 6/17 = 35.3% (17.3-58.7%) |
| unsafe_automatic_acceptance | 0/4 = 0.0% (0.0-49.0%) | 0/2 = 0.0% (0.0-65.8%) | 0/2 = 0.0% (0.0-65.8%) |
| injection_priority_kept | 1/2 = 50.0% (9.4-90.5%) | 1/1 = 100.0% (20.6-100.0%) | 0/1 = 0.0% (0.0-79.3%) |
| ambiguous_cases_blocked_for_review | 3/4 = 75.0% (30.1-95.4%) | 1/2 = 50.0% (9.4-90.5%) | 2/2 = 100.0% (34.2-100.0%) |

Raw schema validity 34/34 = 100.0% (89.8-100.0%): the 100% target is **OBSERVED TARGET MET** on this sample (kept separate from post-validation acceptance). Review burden: 4 reviews required by the safety labels were raised, 23 further reviews were raised for reasons not marked must-review in the labels (mainly no grounded manual guidance was found for the incident), 0 must-review incidents were missed. 'False positive' here means 'above the safety-necessary minimum', not 'wrong': the system's own rule blocks incidents without grounded evidence.

## 5. Latency, throughput and resources (documented CPU-only laptop, single user unless stated)

- `/ai/ask` latency p50 4.41 s, p95 12.43 s (n=118) vs the provisional 15 s p95 budget: OBSERVED TARGET MET. `/incidents/extract` p50 3.40 s, p95 7.84 s (n=34). p99 not reported (n < 200).
- LLM inference: {'n': 106, 'valid': 105, 'wall_p50': 4.5455000000000005, 'wall_p95': 13.00475, 'tokens_per_s_median': 25.375}.
- Workflow end to end (extract, review, draft, approval, outbox, mock submission): total p50 4.5184999999999995 s; approval-to-submitted p50 0.1935 s.
- Concurrency probe (8 requests): {'1': {'requests': 8, 'wall_s': 36.88, 'status_429': 0, 'p50': 4.2775, 'max': 6.225}, '2': {'requests': 8, 'wall_s': 28.27, 'status_429': 0, 'p50': 5.9495000000000005, 'max': 9.309}, '4': {'requests': 8, 'wall_s': 15.02, 'status_429': 4, 'p50': 3.042, 'max': 7.62}}. At 4 concurrent requests half were refused with 429 by the application's concurrency limiter (by design, `max_concurrent_llm`), so throughput scaling was not measured beyond that.
- Cold start: 0.053 s is **not a cold-start measurement** (the model was already resident from earlier activity); cold-versus-warm behaviour remains unmeasured and is listed as a limitation.
- Indexing: {'files': 48, 'seconds_total': 20.9, 'chunks_total': {'meridian-eval2': 712, 'apex-benchmark': 735}}; storage bytes {'documents': 49152, 'document_versions': 98304, 'document_chunks': 7389184}. Run elapsed 3289.2 s; per-phase windows {'ingestion': 21.1, 'retrieval': 14.6, 'warmup': 0.1, 'qa_rep1': 600.3, 'extraction_rep1': 149.1, 'qa_rep2': 587.7, 'extraction_rep2': 200.6, 'qa_rep3': 675.0, 'extraction_rep3': 182.4, 'workflow': 27.9, 'concurrency1': 36.9, 'concurrency2': 28.3, 'concurrency4': 15.0}.
- Resource sampler (PowerShell/CIM, a few samples per phase): {"ingestion": {"samples": 3, "cpu_pct_mean": 72, "cpu_pct_peak": 91, "ollama_working_set_mb_peak": 37.0, "python_working_set_mb_peak": 849.1, "system_free_ram_mb_min": 3503.6, "system_total_ram_mb": 16026.5}, "retrieval": {"samples": 4, "cpu_pct_mean": 50.5, "cpu_pct_peak": 68, "ollama_working_set_mb_peak": 37.0, "python_working_set_mb_peak": 798.2, "system_free_ram_mb_min": 3524.2, "system_total_ram_mb": 16026.5}, "warmup": {"samples": 0}, "qa_rep1": {"samples": 128, "cpu_pct_mean": 64.0, "cpu_pct_peak": 100, "ollama_working_set_mb_peak": 1986.6, "python_working_set_mb_peak": 864.0, "system_free_ram_mb_min": 1136.6, "system_total_ram_mb": 16026.5}, "extraction_rep1": {"samples": 31, "cpu_pct_mean": 61.6, "cpu_pct_peak": 100, "ollama_working_set_mb_peak": 1962.1, "python_working_set_mb_peak": 884.4, "system_free_ram_mb_min": 1464.4, "system_total_ram_mb": 16026.5}, "qa_rep2": {"samples": 119, "cpu_pct_mean": 65.9, "cpu_pct_peak": 100, "ollama_working_set_mb_peak": 2142.5, "python_working_set_mb_peak": 949.3, "system_free_ram_mb_min": 789.9, "system_total_ram_mb": 16026.5}, "extraction_rep2": {"samples": 38, "cpu_pct_mean": 71.7, "cpu_pct_peak": 100, "ollama_working_set_mb_peak": 2141.0, "python_working_set_mb_peak": 966.6, "system_free_ram_mb_min": 441.3, "system_total_ram_mb": 16026.5}, "qa_rep3": {"samples": 129, "cpu_pct_mean": 73.0, "cpu_pct_peak": 100, "ollama_working_set_. Sampling is coarse (one sample every few seconds, slow collector); peak values are lower bounds.

## 6. Failure classes (kept separate)

- **Evaluation-harness failures:** 0 in the valid run (the earlier INVALID run failed this way). **Infrastructure failures:** {} (none) apart from the deliberate 429 responses in the concurrency probe. **HTTP success:** all 118 QA and 34 extraction requests per repetition returned 2xx.
- **AI-quality failures** (scored above): answers withheld because numbers or quotes failed verification (22 of 87 answerable, mostly multi-passage and troubleshooting questions); answers to unanswerable questions (9 of 23, five of them questions about a parameter missing from one model's manual where the sibling model's page was used; two 'answer from memory' prompts answered from retrieved documents with citations); model-extracted category errors (Meridian 10 of 17 correct); hallucinated numeric signals (3 of 6 non-null raw vibration values did not match the report) which raised two priorities to P1; only 8 of 34 incidents found grounded guidance evidence.

## 7. Limitations of this baseline

Author-generated labels; synthetic template-assisted content; dev split only (118 queries, 87 answerable with labelled passages; 34 incident cases, 17 per tenant, so many intervals are wide); one model and one embedding model; the citation-correctness rule is conservative (an unlabelled but genuine supporting passage counts as incorrect); the claim-support test is a surface check of numbers and identifiers, not semantic entailment; two direct-injection prompts ('answer from memory') are labelled expected-refusal although answering from retrieved evidence is arguably acceptable behaviour (recorded as a label-review item, not changed); mock external systems (the inventory mock returns 404 for the synthetic part numbers, so enrichments are absent); cold start unmeasured; coarse resource sampling; concurrency only to 4 requests.

