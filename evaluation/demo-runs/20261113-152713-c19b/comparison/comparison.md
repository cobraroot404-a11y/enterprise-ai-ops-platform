# Manual versus automated workflow comparison

**No real productivity gain is claimed: fictional scenarios, synthetic tasks, same-author measurement.**

## A. Measured automated (measured automated system time)

20 equivalent synthetic tasks; backend: `{"ai": "deterministic", "llm": "deterministic", "embedding": "deterministic", "note": "deterministic test-only backends: CI/functional only"}`. Excluded: human think and reading time, network distance, real external systems (local mocks are used).

| Step | n | median s | p95 s | min s | max s |
|---|---|---|---|---|---|
| extract_incident | 20 | 0.044 | 0.0655 | 0.0379 | 0.0683 |
| review_incident | 15 | 0.0297 | 0.0474 | 0.0281 | 0.0474 |
| draft_ticket | 20 | 0.0249 | 0.0287 | 0.024 | 0.029 |
| request_approval | 20 | 0.0224 | 0.0256 | 0.0219 | 0.028 |
| approve | 20 | 0.032 | 0.0336 | 0.0308 | 0.0349 |
| worker_submission | 20 | 0.9166 | 1.034 | 0.5147 | 1.0383 |
| **end to end (system time)** | 20 | 1.0679 | 1.1799 | 0.6647 | 1.1842 |

Human touchpoints that remain in the automated workflow (not timed here): engineer: writes the fault report; engineer: reviews the structured incident; supervisor: reviews incidents the platform routes to human review; engineer: drafts the ticket and requests approval; supervisor: reviews and decides the approval.

## B. Observed manual (observed human performance)

no observed human data exist; no comparison is made.

## C. Simulated manual (simulated, hypothetical baseline)

no assumptions were supplied; nothing is simulated.

