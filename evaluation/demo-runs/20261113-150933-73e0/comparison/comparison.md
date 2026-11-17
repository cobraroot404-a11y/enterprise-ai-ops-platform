# Manual versus automated workflow comparison

**No real productivity gain is claimed: fictional scenarios, synthetic tasks, same-author measurement.**

## A. Measured automated (measured automated system time)

20 equivalent synthetic tasks; backend: `{"ai": "deterministic", "llm": "deterministic", "embedding": "deterministic", "note": "deterministic test-only backends: CI/functional only"}`. Excluded: human think and reading time, network distance, real external systems (local mocks are used).

| Step | n | median s | p95 s | min s | max s |
|---|---|---|---|---|---|
| extract_incident | 20 | 0.0432 | 0.0655 | 0.0376 | 0.0713 |
| review_incident | 15 | 0.0289 | 0.0305 | 0.0277 | 0.0305 |
| draft_ticket | 20 | 0.0245 | 0.0266 | 0.024 | 0.027 |
| request_approval | 20 | 0.0228 | 0.0238 | 0.0217 | 0.0241 |
| approve | 20 | 0.0318 | 0.039 | 0.0308 | 0.0496 |
| worker_submission | 20 | 0.9133 | 0.9577 | 0.5142 | 1.0139 |
| **end to end (system time)** | 20 | 1.0659 | 1.115 | 0.6549 | 1.1606 |

Human touchpoints that remain in the automated workflow (not timed here): engineer: writes the fault report; engineer: reviews the structured incident; supervisor: reviews incidents the platform routes to human review; engineer: drafts the ticket and requests approval; supervisor: reviews and decides the approval.

## B. Observed manual (observed human performance)

no observed human data exist; no comparison is made.

## C. Simulated manual (simulated, hypothetical baseline)

no assumptions were supplied; nothing is simulated.

