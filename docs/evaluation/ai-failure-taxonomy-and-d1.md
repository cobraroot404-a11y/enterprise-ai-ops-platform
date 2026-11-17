# AI-quality failure taxonomy (development split) and experiment D1

**Status: development evidence, same author, 118 dev queries (87 answerable, 31 not); every figure has a wide interval. Nothing here is a confirmation and no acceptance threshold changed.** The consumed held-out and challenge splits were not used. Held-out reference figures stay as measured: citation correctness 89.8% against the 95% target, grounded coverage 59.3%, raw model validity 90% against 100%.

## 1. Where the candidate configuration loses answerable queries (run `exp-CAND1-20261112T090552Z`, repetition 1)
Tool: `python evaluation/phase8/failure_taxonomy.py <run> --out ...` (offline, dev only; refuses other splits). One primary class per query; outputs in `evaluation/reports/phase8/taxonomy/`.

| Class (the directive's categories) | Answerable dev queries (of 87) | Share of the 29 non-ok |
|---|---|---|
| ok: grounded, labelled citations, every required fact present | 58 | - |
| 1 Relevant document not retrieved | 1 | 3% |
| 2 Relevant document retrieved, labelled page missed from the top 5 | 0 | 0% |
| 3 Incorrect ranking (a hard negative above the relevant page) | 1 | 3% |
| 5 Incorrect citation association (cites an unlabelled or sibling page) | 5 | 17% |
| 6 Missing citations | 0 | 0% |
| 7 Unnecessary abstention (refused although evidence was retrieved) | 0 | 0% |
| 7b Withheld by the verifier: quotation not verbatim | 10 | 34% |
| 7c Withheld by the verifier: number not in the cited text | 7 | 24% |
| 8 Incomplete: a required fact absent from the answer | 5 | 17% |
| 9 Structured-output failure of the model call | 0 | 0% |
| 4 Unsupported claims, 10 multi-hop, 11 tenant or provenance error | see below | |

Unanswerable queries: 24 of 31 correctly refused, 7 wrongly answered.
- **Multi-hop** (a two-part question whose parts live in different documents): 12 of the 29 failures (12 of the 13 dev multi-hop queries fail: 6 are withheld by the verifier, 5 answer only the first part, 1 other).
- **Tenant-scoping or provenance error: 0** citations from another tenant's files.
- **Class 4** (a number in the answer absent from the cited quotes) is only a heuristic flag here (23 hits, many false) and is not used for decisions; claim support is measured by the scorer.

**Reading.** Retrieval is not the problem on this split: 2 of 87 answerable queries are lost before generation. The losses are at the generation and verification step of a 1.5B model: 17 answers (20%) are withheld because the model's quotation is not verbatim or its numbers are not in the cited text, and 10 more are answered with the wrong citation or half the facts. The verifier is doing its job (the earlier quote-snap experiment E7 recovered some withheld answers and raised the unsupported-answer rate from 16.7% to 23.4%, which is why it was rejected).

## 2. Experiment D1: answer a multi-part question part by part
Justification: multi-hop questions are 12 of 29 failures, and the "incomplete" class (5) is exactly an answer that addresses only the first part. D1 (`decompose_answers`, off by default) splits the question with the existing rule-based splitter, answers each part with its own retrieval, answer and verification, and releases a combined answer only if every part is grounded (no partial answers); citation markers are renumbered. Unit tests: `backend/tests/test_decompose_answers.py`.

Run `exp-D1-20261114T050707Z`: the CAND1 configuration plus `decompose_answers`, same dev queries, one repetition (about 11 minutes).

| Metric (dev, paired with CAND1) | CAND1 | D1 |
|---|---|---|
| Grounded answer coverage | 66.7% | 64.4% (56/87) |
| Citation correctness (answerable) | 91.9% | 86.4% (70/81) |
| Claim support | 96.6% | 93.9% |
| Correct abstention | 95.7% (22/23) | 95.7% (22/23) |
| Unsupported-answer rate | 16.9% | 27.9% |
| Withheld by the verifier | 19.5% | 23.0% |
| p95 latency | 11.4 s | 10.4 s |
| Paired grounded-correct | | +2 / -4 |

Per class: "incomplete" fell from 5 to 0 (the decomposition does fix its target), but citation association errors rose from 5 to 9 and verifier withholding from 17 to 20: each part's single-question answer more often cites a sibling page or a quotation that is not verbatim.

**Decision: REJECTED; the flag stays off.** It trades a fixed class for worse citation correctness and unsupported-answer rate, which is the wrong direction for the target that is furthest from met. The difference is within the measured run-to-run noise (about three queries), so it is not evidence of harm either; it is simply not an improvement and not promotable. The run is preserved.

## 3. What this means for the 95% target
- Citation correctness 95% is **not met** and was not approached by this work; the development figure (91.9% for CAND1) did not replicate on held-out (89.8%), the earlier lesson that dev-tuning on 118 queries overfits.
- The measured losses are model-bound (verbatim quotation, number handling, picking the right sibling page), not retrieval-bound. Further prompt and pipeline iteration on this 1.5B model has shown diminishing returns across about thirty dev experiments.
- **A stronger local model is the untested lever.** It needs the owner's approval because it is a download (for example a 3B or 7B instruction model through Ollama; a 7B quantised model needs about 5 GB of RAM and would run about three to five times slower on this CPU). No model was downloaded.
- Independent acceptance needs fresh, independently labelled queries (see the independent review package, Track 3); the author cannot supply those.
