# H3 identifier verification and E2-A-0103 diagnostic

H3 is implemented and deterministically validated. Experimental acceptance is pending. The `question_asset_id_exemption` tuning flag defaults to false and preserves the existing verifier behavior and configuration hash when off.

## H3 scope and verifier order

1. Retrieval scopes documents and chunks to the requesting tenant under RLS. Quote verification checks indexes and whitespace-normalized verbatim quotes against the supplied passages. An empty answer follows the existing insufficient-evidence path.
2. With H3 and the entity gate enabled for the request, a case-sensitive whole-token copy from the original question is eligible only when the tenant's configured register has exactly one active, current, non-suspicious row and one distinct model. Partial matches, model-only codes, parts, and incident IDs cannot qualify. Question decomposition cannot create an eligible token.
3. Optional citation completion and claim support both ignore only numeric spans wholly inside the eligible answer token. Unsupported-identifier checking still receives the original answer and question. All other numbers, including an identical standalone number, still go through the evidence check.
4. Citation source verification checks for current chunks and active documents owned by the tenant. If support and source checks pass, the existing entity gate checks whether cited evidence names each required identifier or its resolved model.
5. An answer that still has a missing number under the original check can become grounded only if it states a single positive recurring maintenance interval and a verified quote contains a complete matching statement from the resolved model's manual. This conservative limit keeps wrong-topic citations, additional properties, and unsupported prose from entering through H3. Other answer forms retain strict behavior when identifier digits would otherwise be missing.

The fixed-answer regression for E2-M-0050 verifies `VH-3111 → CP-200` and the manual's `3000 operating hours`. With H3 off, `3111` blocks the answer. With H3 on, the supported answer passes. E2-A-0058 (`P-1010 → CP-250`, cites CP-200) and E2-M-0047 (`VH-2009 → MX-300`, cites MX-350) both reach and fail the entity gate.

The focused run passed all 100 tests, including 38 H3 cases, with coverage for Phase 8 quality, asset identification, measurement trust, and membership RLS. The H3 integration cases exercised both default equipment and profiled fleet registers in `eaop_test`. An earlier, broader targeted run reported 22 failures and one setup error. The same test IDs failed with the pre-H3 verifier modules at `7bc7f6e`.

## E2-A-0103 — JUSTIFIED FIX

Question from [the eval-v2 dev record](../../evaluation/datasets/eval-v2/queries.jsonl)

> What is the bearing grease interval for the EM-75 motor?

Generated answer and the claim accepted by H2

> The bearing grease interval for the EM-75 motor is not specified.

The only cited passage was marker 4, [`apex_inspection_2026q3.pdf`](../../evaluation/datasets/eval-v2/corpus/apex/apex_inspection_2026q3.pdf) page 1, version 1, chunk `5fd7d4bb-27f8-4f79-b307-b02ff8f06fb7`.

```text
Inspection 2026Q3 - M-202
M-202 (EM-75): drive-end vibration measured 3.1 mm/s RMS and bearing temperature 81 C.
Inspector note: keep under observation.
```

Verified quote from the [H2 run record](../../evaluation/reports/phase8/exp-H2-20261114T231340Z/qa_rep1.jsonl)

> M-202 (EM-75): drive-end vibration measured 3.1 mm/s RMS and bearing temperature 81 C. Inspector note: keep under observation.

- **Quotation and citation.** Index 4 points to a supplied passage and the quote appears verbatim after whitespace normalization. No inline answer marker needed verification. The H2 record shows that the live citation source check accepted the chunk. The deterministic replay used the committed PDF through the ingestion parser and a tenant-scoped session stub for the recorded citation source, yielding verified indexes `[4]` and zero errors.
- **Claim support and completion.** The verifier extracts no semantic claim. It detects the identifier `EM-75`, which appears in both question and evidence. The only number extracted from the answer is `75`, which appears inside the model code in the evidence. Identifier and numeric checks therefore reported no missing tokens and completion left the citation list unchanged.
- **Entity applicability.** The required model `EM-75` is present in the cited inspection. This verifies an entity mention independently of the topic of the claim.
- **Absence of evidence.** The cited passage gives vibration and temperature readings and an instruction to keep the motor under observation. It is silent on the interval's existence, specification, and availability. The answer presents that silence as a factual conclusion. The verifier accepts either silence or an explicit negative statement when identifier and numeric checks are satisfied. The replay explains the false acceptance. The cause of the generation change remains unresolved. CAND1 and H1 returned empty raw answers and correctly abstained.

## Proposed follow-up

Add an absence-claim support check to `check_answer_support` in [`safeguards.py`](../../backend/app/ai/safeguards.py). When an answer asserts that a requested property is absent, unspecified, inapplicable, or unavailable, require a cited sentence that explicitly attests to the same property's absence for the applicable subject. Route unsupported non-empty answers through the existing withhold path and preserve the empty-answer abstention path.

Test the E2-A-0103 replay, explicit same-subject negatives, silence, negatives about a different property or model, positive claims unchanged, and ordinary empty abstention. Narrow wording detection may withhold valid paraphrases or explicit evidence split across sentences. Treat this as a verifier correctness fix after owner review and deterministic validation. Any integrated development QA run should be separately authorized after that validation.
