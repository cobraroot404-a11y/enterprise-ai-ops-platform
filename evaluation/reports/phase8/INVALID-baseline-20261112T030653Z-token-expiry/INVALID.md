# INVALID run: baseline-20261112T030653Z (evaluation-harness failure: authentication expiry)

**Status: INVALID. No metric from this run may be reported or compared.** The raw files are preserved exactly as written for the record; `status_summary.json` was added afterwards and only tabulates the HTTP status codes in them.

| Item | Value |
|---|---|
| Failure class | **Evaluation-harness failure** (not an AI-quality or infrastructure failure) |
| Cause | The runner logged in once; the short-lived access token expired during the run. The API correctly answered `401 token_expired`. |
| Effect | `qa_rep1`: 90 of 118 requests succeeded before expiry, 28 returned 401; `qa_rep2`, `qa_rep3`: 118 of 118 returned 401; `extraction_rep1..3`: 34 of 34 returned 401 in every repetition. |
| Secondary failure | The workflow phase then raised `KeyError: 'review_status'` (an error body was treated as an incident) and the run aborted before `results.json` and `manifest.json` were written. |
| Detection | Post-run inspection of status codes before scoring (the scorer was never run on it). |
| What it does not show | Nothing about model quality. Requests that returned 401 never reached the model. |
| Remediation | `FreshHeaders` re-authenticates before the token can expire (max age 8 minutes); workflow errors are recorded rather than aborting. Commit `49d3c92`. Model, prompts, retrieval, citation verification and incident validation were not changed (verified in `docs/evaluation/phase8-baseline-integrity.md`). |
| Replacement run | `baseline-20261112T035539Z` (see the baseline report). |

Retrieval records in this run (`retrieval.jsonl`, `retrieval_repeat.jsonl`) were produced before the token expired and do not use HTTP auth; they are not used either, to keep the run wholly invalid and avoid cherry-picking.
