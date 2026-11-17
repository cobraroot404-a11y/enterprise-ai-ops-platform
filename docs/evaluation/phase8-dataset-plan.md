# Phase 8 plan: a harder, more discriminating evaluation dataset (`apex-eval-v2`)

Status: PLAN ONLY. Nothing here is implemented. `apex-eval-v1` and its Phase 3 results stay unchanged for historical comparison.

## Why v1 is not enough
Single relevant unit per query caps Precision@5 at 0.2; an 86-chunk corpus saturates Recall@5 at 100%; paraphrase queries still share vocabulary with the sources, so text-only retrieval beat vector-only; no hard negatives, no version conflicts, and cross-tenant isolation is untested at the retrieval-metric level.

## Requirements for v2
1. **Multiple relevant passages per query** (2-4 units, e.g. a manual page, an inspection finding and an incident record), with graded relevance (essential / supporting) and explicit judgments in a `qrels` file.
2. **Hard negatives:** near-duplicate passages for different equipment models (CP-200 vs CP-250), same symptom with a different root cause, same equipment with a different threshold, and numerically similar but wrong values.
3. **Similar equipment and incident descriptions** across several assets so retrieval must discriminate on identifiers and context, not topic.
4. **Conflicting or outdated document versions:** v1 vs v2 of a manual with changed limits; queries whose correct answer exists only in the current version; superseded chunks must not be cited.
5. **Unanswerable questions** (about 25% of queries), including topically close but unsupported ones (the type that fooled the evidence gate in v1) and questions whose answer exists only in another tenant.
6. **Cross-tenant retrieval isolation cases:** a second synthetic tenant with overlapping equipment IDs and conflicting facts; metrics must show zero cross-tenant citations.
7. **Splits:** `dev` (threshold calibration and prompt iteration only) and a sealed `test` split, never used for tuning; the harness records dataset hash and refuses to tune on `test`.
8. **Size:** at least 500 chunks and 150 queries (about 100 test) so one query is about 1 percentage point; report confidence intervals (bootstrap) and repeated-run variance.
9. **Metrics:** Recall@5, graded nDCG@5, MRR, Precision@5 against a realistic ceiling, citation correctness against the qrels, answer-support rate, abstention precision/recall, version-conflict accuracy, cross-tenant leakage count.
10. **Reproducibility:** deterministic generator script, committed documents and qrels, manifest with hashes; labels written independently of model outputs; no larger LLM or reranker without explicit approval.

## Not in scope here
Implementation (Phase 8), model changes, and any claim that AI-quality targets pass.
