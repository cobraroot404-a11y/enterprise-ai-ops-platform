# Integrated H3 and absence-claim verifier development QA

**Decision — REJECT.** Citation correctness fell, claim support missed 96.6%, and unsupported-answer rate exceeded 16.9%. One repetition on the frozen development split. H3 remains default-off. The explicit-evidence rule for absence claims remains always-on.

## Configuration and evidence

- Inference source `4bd62af3ee0aae6675e922c3ce22e98947379d01` on `feat/apex-vertical-slice`, clean before inference. [Run manifest](../../evaluation/reports/phase8/exp-H3-ABSENCE-20261115T011138Z/manifest.json).
- Compared repetition 1 of CAND1 with one repetition of `--id H3-ABSENCE --phases qa --reps 1 --split dev`. Tuning `{"entity_boost":0.02,"entity_gate":true,"query_override_gate":true,"claim_completion":true,"numeric_verification":true,"guidance_query":"asset_context","question_asset_id_exemption":true}`. Effective hash `517d669076670143eceeab6d272a4424bf906b2f11ee8d05051d89cde2092d0f`. H1, H2, decomposition, and citation-list/range handling were off.
- The same 118 query IDs in the same order, including 87 answerable, 23 expected to abstain, and 8 optional. Verified frozen file hashes against the CAND1 manifest and the canonical dev hash `623b612bef23475cfd6bdb3ac52233bb8773aae8fc1b8ccf40b5cf0ddd138986`. Only development query and incident rows were decoded from the mixed-split files.
- `qwen2.5:1.5b`, digest `65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b`, Ollama 0.40.16. Temperature 0, seed 7, context 4096, prediction cap 320. Prompt v3 hash `3710b8b7897780f85600ce5eb007731ae5f38f895790d09c3cdb096a921575c6`. Cached MiniLM-L6-v2 revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, 384 dimensions and evidence threshold 0.50 matched CAND1. Retrieval settings matched CAND1. The authorized current checkout also contains tenant/current-document SQL filters added after the CAND1 commit.
- A local launcher supplied the verified dev rows to the existing runner and scorer, and created and migrated the isolated `eaop_eval2_h3_absence_20261114` database without a drop. It scoped H3 to the experiment process. The existing scorer ran once with the unchanged formulas and labels. [CAND1 raw QA](../../evaluation/reports/phase8/exp-CAND1-20261112T090552Z/qa_rep1.jsonl), [integrated raw QA](../../evaluation/reports/phase8/exp-H3-ABSENCE-20261115T011138Z/qa_rep1.jsonl), [comparison](../../evaluation/reports/phase8/exp-H3-ABSENCE-20261115T011138Z/comparison.json), [full scores](../../evaluation/reports/phase8/exp-H3-ABSENCE-20261115T011138Z/scores_exp.json).

## Measured results

| Metric | CAND1 rep 1 | Integrated candidate |
| --- | ---: | ---: |
| Citation correctness, answerable | 91.86% (79/86) | **90.91% (80/88)** |
| Grounded-correct answer coverage | 66.67% (58/87) | 64.37% (56/87) |
| Claim support | 96.62% (143/148) | **95.83% (138/144)** |
| Correct abstention | 22/23 | 22/23 |
| Unsupported-answer rate | 16.90% (12/71) | **19.44% (14/72)** |
| Unsupported QA numbers accepted under the full-cited-passage token check | 0 | 0 |
| False refusals | 0/87 | 0/87 |
| Answerable queries withheld | 17/87 | 16/87 |
| Citation tenant ownership | 93/93 | 95/95 |
| Cross-tenant probe leaks | 0/8 | 0/8 |
| Latency p50 / p95 | 4.296 / 11.355 s | 3.996 / 9.746 s |

Paired grounded-correct outcomes on 87 answerable queries were **1 improved, 3 regressed, 83 unchanged**. All 23 correct-abstention outcomes were unchanged. The citation rate fell 0.95 percentage points and the count of correct citations rose by one, below the predefined approximate three-query margin. The fixed citation, claim-support and unsupported-answer gates failed. The outside-target wrong-asset citation and numeric answer on E2-M-0056 provide an additional reason to reject.

A separate read-only QA audit checked grounded numbers against the complete cited passages, including the current tenant-scoped chunks for this run. All emitted candidate citations resolved to current documents in the requesting tenant. No candidate answer needed the H3 exemption to satisfy the full-passage numeric check. A stricter quote-only token audit found omissions on five CAND1 rows and seven candidate rows, including dates and identifier digits. The full-passage audit checks number presence. The wrong-asset `87 psi` on E2-M-0056 illustrates that the correct value for a different asset can still pass. The existing scorer's unsupported-numeric-accepted extraction measure was 0 for historical CAND1 and unevaluated for the QA-only candidate. [QA audit](../../evaluation/reports/phase8/exp-H3-ABSENCE-20261115T011138Z/qa_audit.json).

## Targeted cases

| Query | Result in the integrated repetition |
| --- | --- |
| E2-M-0050 | Still grounded incorrectly at **2250 operating hours**, from unverified Meridian service-history note `SR-N0274`. The cited record contains both `VH-3111` and `2250`. The answer never exercised the H3 exemption or produced the CP-200 manual's **3000 operating hours**. The fixed-answer test passed with the independent 3000-hour quote. |
| E2-A-0058 | Still grounded incorrectly at **0.04**, from Apex service-history note `INC-N0271`, which itself names `P-1010`. The CP-250 manual gives **0.08**. The live answer did not need the exemption. The fixed-answer CP-200 control was refused by the entity gate. |
| E2-M-0047 | Still grounded incorrectly at **16 months**, from Meridian service-history note `SR-N0271`, which itself names `VH-2009`. The MX-300 manual gives **10 months**. The live answer did not need the exemption. The fixed-answer MX-350 control was refused by the entity gate. |
| E2-A-0103 | Correctly abstained with an empty raw answer and no citations, as CAND1 did. The live run did not generate the H2 “not specified” assertion. The deterministic verifier test withheld that assertion when the passage was silent and accepted it with explicit matching evidence. |

## Non-target changes

| Transition | Queries and adjudication |
| --- | --- |
| Withheld to grounded | **E2-M-0060** became correct with a verbatim **99 psi** quote. **E2-A-0048**, **E2-M-0027**, and **E2-M-0031** still failed the scorer's grounded-correct test. **E2-M-0070** is an optional injection probe labeled unanswerable, which returned a routine-reading statement from `AL-00178` without the requested reference. |
| Grounded to withheld | **E2-A-0010** regressed after a generated CV-450 answer cited CV-400 material. **E2-A-0066** regressed when the existing numeric check read `[1, 2]` as numbers. **E2-A-0088** (optional probe) and **E2-M-0030** (already incorrect) were withheld for non-verbatim quotes. |
| Withheld to refused | **E2-A-0093** returned an empty raw answer. Both repetitions counted as correct abstention. |
| Stayed grounded, lost correctness | **E2-M-0056** changed from **114 psi** for `VH-6103` in the 2026Q3 inspection to **87 psi** for `VH-7102` in the 2026Q1 inspection. The two assets share the MX-350 model. |

No expected-refusal query newly grounded. E2-M-0070 was the only newly grounded row labeled unanswerable, with answering optional. None of these changes is attributed to H3 or the absence-claim rule from the paired comparison alone. The comparison combines the always-on verifier correction with H3 enabled experimentally. It is one same-author development repetition and provides no independent confirmation.

## Runtime and validation

- Candidate total 540.2 s, ingestion window 23.8 s, harness warm-up 0.1 s, QA 513.9 s with 103 recorded Ollama calls across 118 requests. CAND1 QA repetition 1 took 554.0 s.
- The harness sampler returned zero samples after a missing Windows memory reading. The separate sampler covered 506.8 s of QA with 102 samples, mean/peak system CPU 61.5%/80.2%, minimum available RAM 2,997 MiB of 16,027 MiB, and max Ollama-reported model size 1,173,136,342 bytes. The latter is model residency reported by the service. Candidate process working sets are unavailable. [Resource samples](../../evaluation/reports/phase8/exp-H3-ABSENCE-20261115T011138Z/resource_samples.jsonl).
- Preflight deterministic suites had 213 passes and three failures. All 38 H3 and 28 absence cases passed. The three failing tests were the previously reproduced cross-tenant numeric-evidence, Meridian profile numeric-rules, and Meridian brake-pressure/priority tests. No failure was newly observed in this run's preflight.
- Post-run checks passed 27 scorer, metric, documentation, and provenance tests. Ruff passed on the exercised verifier and harness modules. Git whitespace and run artifact consistency checks passed. The secret scan found zero findings and provenance reported zero new violations.
- The runner's in-process loopback mocks exited with it and the supplemental sampler exited on completion. An attempted Ollama launch exited because the pre-existing listener owned the port. That listener served inference and is still running. The shared PostgreSQL service, the isolated evaluation database, and the installed model were retained.

Any further inference requires new owner authorization. The existing independent-review requirement remains open.
