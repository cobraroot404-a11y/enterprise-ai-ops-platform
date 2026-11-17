# Phase 8 integrated development candidate: results (dev split, not held-out)

Candidate configuration `evaluation/phase8/configs/candidate_v1.json`, **configuration hash `4e24e63f3f2d06c31946d07e52d6f3a5c6c378a1f47b9b0535d8750368268e03`** (SHA-256 of the canonical effective settings; code commit recorded in the run manifest: `d5a7e41`). Run `exp-CAND1-20261112T090552Z`: 3 repetitions of the 118 dev queries and 34 dev incident cases plus the workflow checks, real Ollama `qwen2.5:1.5b` (digest 65ec06548149) and MiniLM; the model, prompts, evidence threshold, citation verification rules and review gate are the baseline's. These are development-split measurements on synthetic, author-labelled data; the parameters of the accepted changes (identifier boost 0.02, override-gate patterns) were chosen on this same split, so the figures are optimistic relative to a held-out evaluation. The held-out and challenge splits were not run or inspected.

## Candidate = which changes

| Component | Role | Experiment |
|---|---|---|
| Identifier boost 0.02 (assets resolved to models through the register) | retrieval | E3 |
| Entity gate: refuse when an identifier in the question is absent from every cited passage | abstention | E8 |
| Query-override gate: refuse questions that try to override evidence, tenant or approval rules | abstention | E8b (addition to E8) |
| Citation completion: cite the retrieved passage that actually contains a value the answer states (verbatim sentence, entity-relevant only) | grounding | C3 (added after diagnosis, not an E1-E10 experiment) |
| Numeric measurement audit: values not stated in the report are not used by the priority rules, are preserved as `unsupported` and force human review | extraction safety | priority 1 / E10a |
| Incident guidance query includes the asset's own register name (equipment family) | review burden | E10d (refinement of E10c after diagnosis) |

Rejected after measurement: E1, E2, E4, E5, E6 (3 variants), E7, E9, E10b, E10c, and the additional C1 and C2 (see `phase8-optimization-log.md`). Every switch defaults to the baseline behaviour; the candidate is selected by `EAOP_TUNING`, it is not the shipped default.

## Baseline versus candidate (repetition 1; 95% Wilson interval in brackets)

| Metric | Baseline | Candidate | Target | Observed-target class (candidate) |
|---|---|---|---|---|
| Grounded-answer coverage | 54/87 = 62.1% (51.6-71.5) | 58/87 = 66.7% (56.2-75.7) | 75% (floor 60%) | OBSERVED TARGET NOT MET interval overlaps target |
| Answer coverage | 65/87 = 74.7% (64.7-82.7) | 70/87 = 80.5% (70.9-87.4) |  |   |
| False refusals | 0/87 = 0.0% (0.0-4.2) | 0/87 = 0.0% (0.0-4.2) |  |   |
| Withheld by verification | 22/87 = 25.3% (17.3-35.3) | 17/87 = 19.5% (12.6-29.1) |  |   |
| Citation correctness (answerable) | 66/77 = 85.7% (76.2-91.8) | 79/86 = 91.9% (84.1-96.0) | 95% | OBSERVED TARGET NOT MET interval overlaps target |
| Citation tenant ownership | 93/93 = 100.0% (96.0-100.0) | 93/93 = 100.0% (96.0-100.0) | 100% |   |
| Claim support | 130/133 = 97.7% (93.6-99.2) | 143/148 = 96.6% (92.3-98.6) | 95% | OBSERVED TARGET MET interval overlaps target |
| Correct abstention | 14/23 = 60.9% (40.8-77.8) | 22/23 = 95.7% (79.0-99.2) | 90% | OBSERVED TARGET MET interval overlaps target |
| Unsupported-answer rate | 21/74 = 28.4% (19.4-39.5) | 12/71 = 16.9% (9.9-27.3) |  |   |
| Raw extraction schema validity | 34/34 = 100.0% (89.8-100.0) | 34/34 = 100.0% (89.8-100.0) | 100% | OBSERVED TARGET MET |
| Priority accuracy | 28/34 = 82.3% (66.5-91.6) | 30/34 = 88.2% (73.4-95.3) | improve |  |
| Category accuracy | 25/34 = 73.5% (56.9-85.4) | 25/34 = 73.5% (56.9-85.4) |  |  |
| Incidents with grounded evidence | 8/34 = 23.5% (12.4-40.0) | 25/34 = 73.5% (56.9-85.4) |  |  |
| Human-review rate | 27/34 = 79.4% (63.2-89.6) | 13/34 = 38.2% (23.9-55.0) | reduce safely |  |
| Unsafe automatic acceptance (must-review cases) | 0/4 = 0.0% (0.0-49.0) | 0/4 = 0.0% (0.0-49.0) | 0 |  |
| Unsupported numeric values accepted as verified | 3 of 9 proposed | 0 of 9 proposed | 0 | GATE MET (dev) |
| p95 `/ai/ask` latency | 12.4 s | 11.4 s | 15 s | OBSERVED TARGET MET |

Paired on the identical 87 answerable / 23 unanswerable dev queries: grounded-correct improved 10, regressed 6, unchanged 71; correct refusal improved 8, regressed 0. Run-to-run noise between identical configurations is about three queries (see the optimisation log), so the abstention and review-burden gains are well beyond noise while the grounded-coverage gain (+4 net) is modest and close to it. The three repetitions are repeated measurements of the same queries (counts identical across repetitions: True); they are not independent samples and Wilson intervals use one repetition's counts.

**Targets not met on the dev split:** grounded-answer coverage 66.7% (target 75%, above the 60% floor) and citation correctness 91.9% (target 95%). The 90% abstention, 95% claim-support and 100% raw-schema-validity targets are *observed* met, but the intervals overlap their targets (n = 23, 148 and 34), so none of them is established.

## Per tenant

| Tenant | Metric | Baseline | Candidate |
|---|---|---|---|
| apex | Grounded coverage | 26/43 = 60.5% (45.6-73.6) | 31/43 = 72.1% (57.3-83.2) |
| apex | Citation correctness | 36/43 = 83.7% (70.0-91.9) | 45/46 = 97.8% (88.7-99.6) |
| apex | Claim support | 77/79 = 97.5% (91.2-99.3) | 78/80 = 97.5% (91.3-99.3) |
| apex | Correct abstention | 8/10 = 80.0% (49.0-94.3) | 10/10 = 100.0% (72.2-100.0) |
| apex | Priority accuracy | 15/17 = 88.2% (65.7-96.7) | 17/17 = 100.0% (81.6-100.0) |
| apex | Review rate | 14/17 = 82.3% (59.0-93.8) | 7/17 = 41.2% (21.6-64.0) |
| apex | Grounded evidence | 3/17 = 17.6% (6.2-41.0) | 12/17 = 70.6% (46.9-86.7) |
| meridian | Grounded coverage | 28/44 = 63.6% (48.9-76.2) | 27/44 = 61.4% (46.6-74.3) |
| meridian | Citation correctness | 30/34 = 88.2% (73.4-95.3) | 34/40 = 85.0% (70.9-92.9) |
| meridian | Claim support | 53/54 = 98.2% (90.2-99.7) | 65/68 = 95.6% (87.8-98.5) |
| meridian | Correct abstention | 6/13 = 46.2% (23.2-70.9) | 12/13 = 92.3% (66.7-98.6) |
| meridian | Priority accuracy | 13/17 = 76.5% (52.7-90.4) | 13/17 = 76.5% (52.7-90.4) |
| meridian | Review rate | 13/17 = 76.5% (52.7-90.4) | 6/17 = 35.3% (17.3-58.7) |
| meridian | Grounded evidence | 5/17 = 29.4% (13.3-53.1) | 13/17 = 76.5% (52.7-90.4) |

**Reading the per-tenant table:** the gains are concentrated in Apex (grounded coverage 60.5% -> 72.1%, citation correctness 83.7% -> 97.8%). For Meridian the abstention (46.2% -> 92.3%) and review-burden gains are large, but grounded coverage (63.6% -> 61.4%) and citation correctness (88.2% -> 85.0%) did not improve; the differences are within run-to-run noise, so there is no evidence of improvement for Meridian answers, and the combined figures should not be read as uniform across tenants. Meridian priority accuracy is unchanged (76.5%) because its category extraction (58.8% correct) is unchanged and no experiment targeted it.

## Retrieval (87 answerable dev queries with labelled passages)

| Scope | Recall@1 | Recall@5 | Recall@10 | MRR | nDCG@5 | p95 latency | foreign passages |
|---|---|---|---|---|---|---|---|
| combined baseline | 0.5057 | 0.8851 | 0.9119 | 0.7843 | 0.7918 | 42 ms | 0 |
| combined candidate | 0.7625 | 0.9387 | 0.9579 | 0.9521 | 0.9413 | 58 ms | 0 |
| apex baseline | 0.4961 | 0.8837 | 0.8915 | 0.8023 | 0.8058 | 40 ms | 0 |
| apex candidate | 0.7829 | 0.9457 | 0.9535 | 0.9884 | 0.9741 | 48 ms | 0 |
| meridian baseline | 0.5152 | 0.8864 | 0.9318 | 0.7667 | 0.7781 | 44 ms | 0 |
| meridian candidate | 0.7424 | 0.9318 | 0.9621 | 0.9167 | 0.9092 | 60 ms | 0 |

Recall@5 combined 0.9387 (bootstrap 95% CI [0.9004, 0.9693]). Hybrid retrieval was not shown to beat its components in the baseline; the gain here comes from identifier handling, not from fusion tuning.

## Numeric extraction safety

The model proposed 9 numeric values in the 34 dev cases, 3 of them not stated in the report (a model failure that remains: the model still hallucinates). With the audit, 0 of those reached the priority rules or were recorded as verified; 3 of 3 such incidents were routed to human review and 0 had a wrong priority (baseline: 2 wrong, 2 routed). Genuine stated values keep their evidence span and status `verified`; the regression tests pin the three observed hallucinated cases and show a stated 12.5 mm/s still yields P1.

## Human-review workload

Review rate 27/34 = 79.4% (63.2-89.6) -> 13/34 = 38.2% (23.9-55.0). Reviews required by the safety labels (unregistered asset, injected instructions): 4 raised, 0 missed. The other 9 reviews are cases the safety labels did not require but the system's own rules held: unsupported numeric proposed, ambiguous category, or no grounded guidance (grounded evidence now 73.5% vs 23.5%). Review remains mandatory before any ticket; nothing was auto-submitted (workflow below).

## Workflow and safety

- Workflow cases: 6; submitted 6; submission before approval accepted: 0; approval by the engineer accepted: 0; external tickets {'ticketing_tickets': 3, 'servicedesk_tickets': 3} (no duplicates).
- Cross-tenant: 0 foreign passages in 1,000+ retrieved; citation tenant ownership 100%; the cross-tenant probes were refused by the entity gate (the single heuristic flag in the baseline was a false positive, see the baseline report).
- Prompt-injection: the four override/injection prompts in dev are refused by the override gate (0 false positives on 87 answerable dev queries). Injected instructions inside retrieved records and incident reports did not change approvals or submissions; injection-case priority behaviour is reported in the baseline report.

## Remaining failures (candidate, rep 1)

- Answerable queries not grounded-correct: {'incomplete evidence: required fact missing from answer': 5, 'withheld: incorrect quotation': 10, 'wrong passage: sibling/hard-negative page': 6, 'withheld: numeric mismatch': 7, 'wrong passage: unlabelled or unrelated': 1}.
- Unanswerable queries still answered: [('E2-M-0086', ['gap_in_manual'])] (an attribute mix-up: the right model but the wrong parameter; the entity gate cannot catch it).
- Citations to unlabelled passages: 7 (mostly conflicting-record queries where an informal note is cited instead of the manual).
- Largest remaining lever: 10 answers withheld for a non-verbatim quotation. Quote snapping (E7) recovers them but raised the unsupported-answer rate, so it is not in the candidate; a variant that snaps only when the snapped sentence also contains every number the answer states is untested and would need approval as an additional experiment.

## Latency and resources (documented CPU-only laptop)

`/ai/ask` p50 4.30 s, p95 11.36 s (baseline p95 12.4 s; identical configurations vary between about 10 and 14 s, so the difference is not significant). `/incidents/extract` p95 10.5 s (baseline 7.8 s; one extra retrieval and register lookup). Retrieval p95 58 ms (baseline 42 ms). Ingestion 25.6 s for 1,447 passages. Resource samples (coarse): {'qa_rep1': (62.3, 2088.7, 859.7), 'extraction_rep1': (62.8, 2039.9, 884.7), 'workflow': (63.9, 2057.2, 1055.5)} as (mean CPU %, Ollama MB peak, Python MB peak). Concurrency was not re-measured for the candidate; the baseline's limiter behaviour (429 at 4 concurrent requests) is unchanged. Tokens per second and model load are unchanged (same model, prompts and options).

## Record accounting (raw outputs)

| File | Records | Expected | Duplicate ids | HTTP statuses |
|---|---|---|---|---|
| qa_rep1 | 118 | 118 | 0 | [200] |
| qa_rep2 | 118 | 118 | 0 | [200] |
| qa_rep3 | 118 | 118 | 0 | [200] |
| extraction_rep1 | 34 | 34 | 0 | [201] |
| extraction_rep2 | 34 | 34 | 0 | [201] |
| extraction_rep3 | 34 | 34 | 0 | [201] |

## Security, workflow and regression results

- recorded_utc: 2026-11-12
- code_commit_for_full_suites: a14bbb4
- note: Full backend suites were run at the final code state; fault injection, real-AI, UAT and frontend suites were run at d5a7e41 plus test-only edits (no application code changed afterwards).
- Backend full suite, default settings: 356 passed, 13 skipped (12 real-AI, opt-in FI-10), 0 failed
- Backend full suite, candidate settings (EAOP_TUNING=candidate_v1): 356 passed, 13 skipped, 0 failed
- Fault injection FI-01..FI-10, FI-09b, REL-01..04 under candidate, RUN_DISRUPTIVE=1 (incl. PostgreSQL stop/restart): 15 passed, 0 failed
- Real-AI backend tests under candidate (Ollama + MiniLM): 12 passed
- UAT-A01..A08 and UAT-B01..B07 + end-to-end reliability + observability evidence, real Ollama, under candidate: 21 passed (15 UAT scenarios)
- Security suites (SSRF/egress, RLS, RBAC, JWT, identity, review gate, control mutations, environment guards): included in both full suites: all passed
- Frontend (default settings): typecheck clean, lint clean, Vitest 43 passed, Playwright 47 passed / 1 skipped (opt-in screenshots) incl. accessibility and keyboard specs
- Secret scan: 0 findings in 642 files
- Dataset freeze verification: frozen hashes OK (git diff c0d19c9..HEAD on eval-v2 empty)
- Baseline integrity (15 checks): ALL PASS (re-verified; check 8 reproduces every stored metric exactly, additive v1.2 metrics noted)
- Phase 8 unit tests: metrics 9, scorer 4, dataset integrity 4, quality/safety 18 (backend/tests/test_phase8_quality.py) passed
- Known behavioural difference under the candidate: a legacy fixture test whose scripted model always cites passage [1] withholds a supported answer under the candidate's identifier boost (safe direction); the test was made independent of ambient tuning and the difference is recorded in the report

## Readiness

**Candidate frozen** (hash above). It is ready for the independent held-out evaluation **only in the sense that** the code and configuration are frozen and every safety gate and regression suite passes on the dev split; **two quality targets (grounded coverage, citation correctness) are expected to remain unmet** on held-out data, and the optimism from dev-tuned parameters should be expected. It is not production-ready: single synthetic dataset, author-generated labels, a 1.5B model that still hallucinates numbers and quotes, application-level controls only, local CPU measurements. Held-out evaluation requires your explicit approval.
