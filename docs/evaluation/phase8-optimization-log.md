# Phase 8 optimisation log (development split only)

Baseline `baseline-20261112T035539Z`; defaults regression `exp-B0` (identical to the baseline on every metric and every query); accepted retrieval reference `exp-RSTAR` (E3 only). All runs, successful or not, are preserved under `evaluation/reports/phase8/exp-*`. Held-out test and challenge splits were never run or inspected. No model was downloaded.

## Run-to-run noise (measured, not assumed)
Two identical runs of the reference configuration (`RSTAR`, `RSTAR2`) differ in about 14% of answer texts (16 of 118) and in 4 of 118 grounded flags; paired grounded-correct changes were +1 / -1. A second pair with a deterministic ranking tie-break (`DET1`, `DET2`) was no better (12 of 118 answer texts differ), so that switch (C2) has no effect and is rejected. Three repetitions inside one run are identical. **Paired changes of about three queries or fewer are therefore treated as noise.** p95 latency of identical configurations varies between about 10.3 and 13.6 s.

## Retrieval experiments (87 answerable dev queries with labelled passages; no model calls)

| Experiment | Configuration | Result | Decision |
|---|---|---|---|
| baseline | hybrid, RRF k=60 | R@1 0.517, R@5 0.885, MRR 0.790, nDCG@5 0.796, p95 42 ms | reference |
| E1 index text with document context | embed `<kind> <file name>: <text>` | alone: R@1 0.544, R@5 0.900, MRR 0.810, nDCG@5 0.816, p95 46 ms; with E3: R@1 0.762, R@5 0.935, MRR 0.951, nDCG@5 0.941, p95 56 ms | **REJECT**: +1.5 points R@5 alone (one query), nothing on top of E3, and a re-embedding of the whole corpus; stored text and quotes were unchanged |
| E2 fusion weights / RRF constant | k in {20,100}, text weight 0.5-2.0, vector weight 1.5 | best single change `w_text=0.5`: R@1 0.596, R@5 0.897, MRR 0.842, nDCG@5 0.839, p95 45 ms | **REJECT**: modest; its benefit is subsumed by E3 |
| E3 identifier handling | boost passages naming query identifiers (assets resolved to models via the register); boost 0.005-0.05 | boost 0.02: R@1 0.762, R@5 0.939, MRR 0.952, nDCG@5 0.941, p95 53 ms (0.05 identical) | **ACCEPT** (boost 0.02): R@1 +0.245, R@5 +0.054, nDCG@5 +0.145, no foreign passages, p95 +15 ms |
| E4 rule-based question splitting | split multi-part questions, carry identifiers, fuse | R@1 0.506, R@5 0.885, MRR 0.773, nDCG@5 0.787, p95 105 ms; with E3: R@1 0.762, R@5 0.939, MRR 0.952, nDCG@5 0.935, p95 118 ms | **REJECT**: no gain; p95 105 ms |
| E9 feature reranker (existing MiniLM + lexical features, no new weights) | 7 weight sets fitted on dev; top 20 | best R@1 0.762, R@5 0.943, MRR 0.954, nDCG@5 0.945, p95 50 ms; with E3: R@1 0.762, R@5 0.943, MRR 0.954, nDCG@5 0.945, p95 53 ms | **REJECT**: equals E3 alone (+0.4 point R@5 is one query) with more machinery |

Remaining retrieval weakness: multi-hop queries (three relevant passages) reach recall@5 of about 0.67; conflicting-record queries 0.8.

## Generation and abstention experiments (QA over 118 dev queries, reference = E3 alone unless stated)

| Experiment | Grounded coverage | Citation correctness | Claim support | Correct abstention | False refusals | Withheld | Unsupported-answer rate | p95 s | Paired change |
|---|---|---|---|---|---|---|---|---|---|
| baseline | 54/87 (62.1%) | 66/77 (85.7%) | 130/133 (97.7%) | 14/23 (60.9%) | 0/87 (0.0%) | 22 | 21/74 (28.4%) | 12.4 | - |
| R* = E3 | 56/87 (64.4%) | 73/82 (89.0%) | 134/141 (95.0%) | 16/23 (69.6%) | 0/87 (0.0%) | 19 | 21/75 (28.0%) | 10.9 | gc +10/-8; refusal +2/-0 vs baseline |
| C1 citation marker formats | 56/87 (64.4%) | 76/98 (77.5%) | 127/135 (94.1%) | 16/23 (69.6%) | 0/87 (0.0%) | 16 | 24/78 (30.8%) | 11.6 | gc +1/-1; refusal +0/-0 vs R* |
| E5a diverse context (k=4) | 53/87 (60.9%) | 67/76 (88.2%) | 125/129 (96.9%) | 17/23 (73.9%) | 0/87 (0.0%) | 24 | 18/69 (26.1%) | 11.5 | gc +2/-5; refusal +1/-0 vs R* |
| E5b diverse context (k=6) | 55/87 (63.2%) | 68/76 (89.5%) | 131/133 (98.5%) | 17/23 (73.9%) | 0/87 (0.0%) | 21 | 16/72 (22.2%) | 10.3 | gc +3/-4; refusal +1/-0 vs R* |
| E6 prompt v4 (numbers verbatim) | 53/87 (60.9%) | 68/78 (87.2%) | 121/126 (96.0%) | 16/23 (69.6%) | 0/87 (0.0%) | 23 | 19/71 (26.8%) | 12.5 | gc +2/-5; refusal +0/-0 vs R* |
| E6 prompt v5 (+ one sentence per citation) | 51/87 (58.6%) | 68/83 (81.9%) | 117/123 (95.1%) | 15/23 (65.2%) | 0/87 (0.0%) | 23 | 23/72 (31.9%) | 12.5 | gc +4/-9; refusal +0/-1 vs R* |
| E6 prompt v6 (v5 without the worked example) | 27/87 (31.0%) | 40/50 (80.0%) | 63/65 (96.9%) | 20/23 (87.0%) | 0/87 (0.0%) | 54 | 8/36 (22.2%) | 8.7 | gc +4/-33; refusal +4/-0 vs R* |
| E7 quote snap | 58/87 (66.7%) | 74/81 (91.4%) | 130/139 (93.5%) | 16/23 (69.6%) | 0/87 (0.0%) | 19 | 21/75 (28.0%) | 11.4 | gc +3/-1; refusal +0/-0 vs R* |
| E8 entity gate | 56/87 (64.4%) | 69/74 (93.2%) | 126/131 (96.2%) | 20/23 (87.0%) | 0/87 (0.0%) | 23 | 13/67 (19.4%) | 11.5 | gc +1/-1; refusal +4/-0 vs R* |
| E8 + E8b override gate | 55/87 (63.2%) | 69/75 (92.0%) | 127/132 (96.2%) | 22/23 (95.7%) | 0/87 (0.0%) | 23 | 11/65 (16.9%) | 13.7 | gc +0/-1; refusal +6/-0 vs R* |
| E8 + E8b + C3 citation completion | 58/87 (66.7%) | 82/91 (90.1%) | 143/147 (97.3%) | 22/23 (95.7%) | 0/87 (0.0%) | 16 | 12/72 (16.7%) | 11.7 | gc +4/-1; refusal +0/-0 vs E8+E8b |
| E8 + E8b + C3 + E7 | 61/87 (70.1%) | 86/96 (89.6%) | 151/159 (95.0%) | 22/23 (95.7%) | 0/87 (0.0%) | 11 | 18/77 (23.4%) | 12.5 | gc +3/-0; refusal +0/-0 vs E8+E8b+C3 |

Decisions and reasons:

- **E5 (context assembly): REJECT.** Diverse context lowers or does not change grounded coverage (k=4: paired +2/-5; k=6: +3/-4, within noise); claim support rises but answered volume falls.
- **E6 (prompt wording): REJECT all three.** v4 +2/-5, v5 +4/-9 with citation correctness 81.9%, v6 (no worked example) collapses to 31% coverage (54 of 87 answers withheld). The validated prompt stays.
- **E7 (quote snap): REJECT.** Alone +3/-1 (noise) with claim support falling to 93.5%; on top of C3 it raises coverage to 70.1% but the unsupported-answer rate rises from 16.7% to 23.4% and claim support falls to 94.97%: that trades verification for coverage, which is not allowed.
- **E8 entity gate: ACCEPT.** Refuses when an identifier named in the question is absent from every cited passage (the sibling-model failure that explained 7 of the 9 wrongly answered unanswerable questions and 10 wrong-passage citations). Correct abstention 69.6% -> 87.0%, paired +4/-0, no false refusals.
- **E8b override gate: ACCEPT** (abstention work, an addition to E8 recorded as such). Refuses questions that try to override the evidence, tenant or approval rules; 0 false positives on the 87 answerable dev queries; correct abstention 95.7% (22 of 23), paired +6/-0. The patterns are generic phrases; the held-out split contains different wordings, so this result is a development observation.
- **C1 (citation marker formats): REJECT.** The diagnosis was right (6 withheld procedure answers cited `[1-3]`) but recovering them exposed citations to unlabelled passages: citation correctness fell from 89.0% to 77.6% with no coverage gain.
- **C3 (citation completion, evidence-driven, added after diagnosis; not one of E1-E10): ACCEPT.** The answer states a value found in another retrieved passage that the model did not cite; the passage is attached with a verbatim sentence only if it contains the value and names a question entity. Withheld 23 -> 16, answered 64 -> 71, unsupported-answer rate unchanged (16.7%), claim support 97.3%.
- **C2 (stable ranking tie-break): REJECT** (no effect on repeatability, see noise section).

## Incident extraction experiments (34 dev cases, reference = E3 alone)

| Experiment | Priority accuracy | Review rate | Evidence completeness | Unsupported numerics accepted | Hallucination cases routed to review | Must-review cases missed | Unsafe automatic acceptance |
|---|---|---|---|---|---|---|---|
| baseline | 28/34 (82.3%) | 27/34 (79.4%) | 8/34 (23.5%) | 3 of 9 proposed | 2 of 3 | 0 | 0/4 (0.0%) |
| R* = E3 | 28/34 (82.3%) | 27/34 (79.4%) | 8/34 (23.5%) | 3 of 9 proposed | 2 of 3 | 0 | 0/4 (0.0%) |
| E10a numeric verification | 30/34 (88.2%) | 28/34 (82.3%) | 8/34 (23.5%) | 0 of 9 proposed | 3 of 3 | 0 | 0/4 (0.0%) |
| E10b category cross-check | 28/34 (82.3%) | 29/34 (85.3%) | 8/34 (23.5%) | 3 of 9 proposed | 3 of 3 | 0 | 0/4 (0.0%) |
| E10c guidance query with model id | 28/34 (82.3%) | 28/34 (82.3%) | 8/34 (23.5%) | 3 of 9 proposed | 2 of 3 | 0 | 0/4 (0.0%) |
| E10d guidance query with asset name | 28/34 (82.3%) | 11/34 (32.4%) | 25/34 (73.5%) | 3 of 9 proposed | 1 of 3 | 0 | 0/4 (0.0%) |
| E10e = E10a + E10d | 30/34 (88.2%) | 13/34 (38.2%) | 25/34 (73.5%) | 0 of 9 proposed | 3 of 3 | 0 | 0/4 (0.0%) |
| E10 all (a+b+c) | 30/34 (88.2%) | 28/34 (82.3%) | 9/34 (26.5%) | 0 of 9 proposed | 3 of 3 | 0 | 0/4 (0.0%) |

- **Numeric verification (priority 1, E10a): ACCEPT.** Values not stated in the report are dropped from the rule inputs, preserved with status `unsupported` on the record, and the incident is routed to review. Accepted-unsupported numerics 3 -> 0, priority accuracy 82.4% -> 88.2% (Apex 100%), genuine values and genuine P1 incidents unchanged.
- **E10b category cross-check: REJECT** as a burden reducer: it only adds reviews (79.4% -> 85.3%) with no accuracy gain.
- **E10c guidance query with the model id: REJECT.** Evidence completeness unchanged (8/34): guidance lives in family-level troubleshooting pages that do not name models.
- **E10d guidance query with the asset's register name (equipment family) - refinement of E10c after the guidance diagnosis: ACCEPT only together with numeric verification.** Diagnosis (`diagnosis-guidance-*`): 24 of 34 guidance retrievals were below the evidence gate because the query ignored the equipment. E10d lifts evidence completeness to 73.5% and cuts the review rate to 32.4% with 0 must-review cases missed, but without numeric verification one hallucination-driven P1 incident was no longer held for review (2 of 3 routed instead of the previous 2 of 3 for the wrong reason): the two changes are interdependent. E10e (both) routes 3 of 3 to review.

## Integrated candidate

See `phase8-candidate-report.md`: configuration `evaluation/phase8/configs/candidate_v1.json` (E3 boost 0.02, E8 entity gate, E8b override gate, C3 citation completion, numeric verification, asset-context guidance query).
