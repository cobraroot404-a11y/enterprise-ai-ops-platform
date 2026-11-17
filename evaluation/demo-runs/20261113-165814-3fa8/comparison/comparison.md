# Manual versus automated workflow comparison

**No real productivity gain is claimed: fictional scenarios, synthetic tasks, same-author measurement.**

## A. Measured automated (measured automated system time)

20 equivalent synthetic tasks; backend: `{"ai": "deterministic", "llm": "deterministic", "embedding": "deterministic", "note": "deterministic test-only backends: CI/functional only"}`. Excluded: human think and reading time, network distance, real external systems (local mocks are used).

| Step | n | median s | p95 s | min s | max s |
|---|---|---|---|---|---|
| extract_incident | 20 | 0.0492 | 0.0745 | 0.0437 | 0.076 |
| review_incident | 15 | 0.029 | 0.0322 | 0.0281 | 0.0322 |
| draft_ticket | 20 | 0.0251 | 0.032 | 0.0243 | 0.0333 |
| request_approval | 20 | 0.0226 | 0.0248 | 0.0221 | 0.0293 |
| approve | 20 | 0.0323 | 0.041 | 0.031 | 0.0561 |
| worker_submission | 20 | 0.9269 | 1.0311 | 0.6552 | 1.0346 |
| **end to end (system time)** | 20 | 1.0837 | 1.1824 | 0.8055 | 1.1934 |

Human touchpoints that remain in the automated workflow (not timed here): engineer: writes the fault report; engineer: reviews the structured incident; supervisor: reviews incidents the platform routes to human review; engineer: drafts the ticket and requests approval; supervisor: reviews and decides the approval.

## B. Observed manual (observed human performance)

no observed human data exist; no comparison is made.

## C. Simulated manual (simulated, hypothetical baseline)

no assumptions were supplied; nothing is simulated.

