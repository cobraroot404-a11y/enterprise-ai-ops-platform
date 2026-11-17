# Independent review package (Gate C)

**Status: prepared, NOT performed.** This package provides optional independent-human assurance under the [EAOP 08E owner decision](../planning/eaop-08e-owner-governance.md). The [Gate C owner disposition](../planning/gate-c-owner-disposition.md) accepts the current V41-14.02 deterministic evidence for the pinned candidate. The compatible-hardware walkthrough and full demonstration stay **Partial** pending reproducibility evidence.

Hands-on checklist (start, scenarios, integrations, isolation, keyboard and screen-reader review, pass/fail table, cleanup): [gate-c-reviewer-guide.md](gate-c-reviewer-guide.md).

## Who and what
A reviewer who did not write the code or the tests, on a machine that is not the author's laptop if at all possible (record which). Plan on about two hours for Track 1, one hour for Track 2, and a half day for Track 3. Nothing here needs a paid service. Do not trust a number in this repository because the author wrote it: reproduce it or say you could not.

## Track 1: reproduce the platform (Gate B and C evidence)
1. Record the machine (CPU, RAM, OS, Docker version, Python and Node versions) and the commit you reviewed (`git rev-parse HEAD`; the tag `v4.1.0-local-rc1` is the earlier release candidate).
2. Follow only [README section 8](../../README.md#8-local-setup) and the [deployment runbook](../operations/deployment-runbook.md). Write down every step that was missing, wrong or ambiguous, and every hidden assumption you had to supply.
3. Run, and record the exact output of: `python -m pytest backend/tests -q`, `python -m pytest tests -q`, `cd frontend && npm run typecheck && npm run lint && npm test`, `python scripts/secret_scan.py`, `python scripts/demo.py smoke --ingestion --rest --compare --backup`, `python scripts/container_smoke.py`.
4. Compare with the figures in the README "Verified Engineering Results" table. A difference is a finding, not an error to explain away.
5. Walk the [27 demonstration steps](demonstration-27-steps.md); say which you could follow without help.

## Track 2: the numeric-safety requirement V41-14.02
Read [the v8 architecture](../evaluation/numeric-safety-architecture-v8.md) and [the provenance closure](../evaluation/numeric-safety-provenance-closure-v8.md), then answer in the record:
- Does the acceptance wording in the original specification (Part 14, "Validate model output") permit the architecture that was adopted after three frozen runs failed (free text and model numbers are never authoritative; only human-verified typed observations or signed simulation fixtures reach priority)? State your reading of the wording.
- The last frozen run failed one provenance count (63 of 64). Inspect `evaluation/safety/` and the closure document: do you agree with the stated cause and with the decision not to rewrite the frozen result?
- Try to break the boundary: submit numbers in free text, in the model's proposal, with a forged signature, as the report's creator, across tenants. The expected behaviour is in `backend/tests/test_numeric_boundary_v7.py` and `backend/tests/test_measurement_trust_v8.py`; anything that changes priority without human verification is a defect.

## Track 3: fresh evidence for the AI-quality targets
The held-out and challenge datasets under `evaluation/` are **consumed**: they were used once and must not be used for tuning or as confirmation again. Independent confirmation needs new material:
1. Receive documents and questions that the author has not seen the labels for (the author supplies unlabelled documents and a question list; you label which passage answers each question, which questions are unanswerable, and what a correct incident extraction contains).
2. Seal your labels (commit their SHA-256) before any system output is produced.
3. Run the evaluation commands recorded in `docs/evaluation/phase8-evaluation-protocol-v1.1.md` against your labels, once, and record the results whatever they are.

## Record
Copy [the template](../../evaluation/independent-review/review-record-template.md) to `evaluation/independent-review/<date>-<reviewer>.md`, fill every section (including "could not do"), and commit it. A record that says "I could not reproduce X" is as valuable as one that says "all reproduced".
