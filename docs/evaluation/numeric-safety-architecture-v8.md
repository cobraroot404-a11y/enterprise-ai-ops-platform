# Numeric safety architecture V8: evidence trust policy and structured-only numeric priority (V41-14.02)

Date: 2026-11-12 (EST). Starting HEAD `31b55ef182bfd1839b0bab74c781fabfa4e03527` (branch `feat/apex-vertical-slice`, clean; original specification SHA-256 `b1c573e2…760da` unchanged; start digests `evaluation/reports/safety/v8-start-hashes.txt`). safety-v1..v7 datasets, labels, scorers and every earlier result (including the failed V5, V6 and V7 confirmations) are preserved unchanged.
**Outcome:** the architecture removes the unsafe pathway. The frozen safety-v8 confirmation met every mandatory safety gate except *complete priority-decision provenance* (63 of 64), so **V41-14.02 remains PARTIAL**. Evidence is same-author, synthetic; nothing here supports a production-readiness claim.

## 1. Specification-compatibility review (done before the change)
- **Original required behaviour:** Part 14 requires the structured incident to carry a *suggested priority*, "validate model output" and "use deterministic business rules where appropriate"; Part 7 step 1 is "report abnormal pump vibration" (no number); Part 8 and the 14 and 11 workflow steps require the structured incident, draft ticket, approval and submission, all unchanged.
- **Existing behaviour:** a number found in free text was (after V5-V7) verified by pattern rules and fed the priority rules.
- **Proposed/implemented behaviour:** a number in free text or proposed by the model is an UNVERIFIED candidate; deterministic numeric rules run only on trust-eligible observations; a suggested priority is still produced from the category and safety rules and is never lowered by a verification.
- **Compatibility impact:** no explicit original requirement mandates priority from numbers in free text, so no mandatory capability is removed and **no formal specification deviation is proposed**. This is a documented behaviour change that reduces automation: a stated vibration or pressure no longer raises priority by itself; it raises an urgent-review flag and waits for a human verification (or signed simulation data). Affected project (not original-spec) acceptance expectations: the project's own UAT-A04, UAT-B03, UAT-B05 and a few functional tests asserted P2/high from the free-text figure; they were updated to the category-driven priority.

## 2. Trust policy (server-side, `backend/app/ai/measurement_trust.py`)
| Class | Source | Status | Eligible for numeric priority |
|---|---|---|---|
| A | free-text number or any LLM-proposed value (including LLM-structured output) | UNVERIFIED | never |
| C | typed observation from an authenticated, authorised submitter, validated (asset, type, unit, plausibility, timestamp, source label) | VALIDATED (status `submitted`) | not until a human verifies it |
| D | candidate approved through the human-verification workflow | HUMAN_VERIFIED | yes |
| E | independently authenticated sensor observation | SOURCE_AUTHENTICATED | **not implemented**: no telemetry authentication exists; not claimed |
| F | simulated observation from the approved fixture, with a valid HMAC signature over tenant and observation made with a server-held key (`EAOP_SIMULATION_FIXTURE_KEY`; with no key every claim is rejected) | SIMULATED_VALIDATED, labelled SIMULATED | yes, demonstration data only |
The caller cannot set a trust status: the request schema forbids every status/class/flag/tenant field (422), and a simulator claim without a valid signature is quarantined. The invariant is enforced where the numeric rules are fed (`incident_service._verify_numbers` → `apply_trust_policy`), not in prompts, regexes, the schema or the UI. The V6/V7 evidence verifier (`measurement_evidence.py`) remains as *candidate-quality* analysis (notation, units, asset attribution, context); it can no longer verify anything on its own.

## 3. Human-verification workflow
`POST /incidents/{id}/measurements/{name}/verify` (`incidents:review`: supervisor or tenant admin) with `decision`, a comment of at least 10 characters and the `expected_trust_status`. Server-controlled transition under a row lock: the reviewer must not be the incident's creator (separation of duties, 403), the decision must match the current state (stale or repeated decisions 409, one winner under concurrency), another tenant's incident is a 404, nothing to approve is a 409. Approval stores reviewer, time, comment and evidence reference, marks the observation HUMAN_VERIFIED/eligible and recomputes the numeric priority (the more urgent of the existing and the numeric result, never lower); rejection keeps it excluded. Audit events `measurement.verified` / `measurement.rejected` and `incident.priority_decided`. It does not submit anything externally; ticket approval and the incident review gate are unchanged.

## 4. Priority audit, urgency and free-text behaviour
Every extraction and every approval writes `incident.priority_decided` (tenant, incident, asset, observation ids, evidence class, verification status, provenance, type, value/unit, applied rule, resulting priority, authorisation, timestamp, reason); with no eligible observation it records that numeric rules did not execute and lists the excluded candidates. `review_urgency` (urgent/routine/none) is preserved and asset-scoped; a potentially critical unverified candidate (free text, submitted record, or a keyword-less unit-bearing figure) sets urgent but never raises the priority and never bypasses approval. Free text still yields candidates, summaries and notes. The numeric-notation/locale policy (`numeric_locale`, ambiguous `1.100` quarantined) and the asset/unit/temporal checks are unchanged.

## 5. Files changed
New `backend/app/ai/measurement_trust.py`; `backend/app/ai/measurement_evidence.py` (signature check for simulated claims); `backend/app/services/incident_service.py` (trust policy at the numeric-rule boundary, `verify_measurement`, priority audit, observation ids); `backend/app/api/v1/domain_routes.py` (verify route); `backend/app/schemas/incident.py` (signed simulation claim, verification body); tests `test_measurement_trust_v8.py` (new, 23 cases), migrated tests (`test_apex_compat`, `test_meridian`, `test_ops_routes`, `test_rag_incidents`, `test_workflow`, `test_api_namespace_security`, `test_numeric_*`, `tests/acceptance/test_uat_customer_a.py`, `test_uat_customer_b.py`, `test_real_ai.py`); harnesses `test_safety_acceptance_v8.py` and `test_safety_observational_real_model_v8.py`; `evaluation/safety/gen_safety_acceptance_v8.py`, `evaluation/datasets/safety-v8/*`, `evaluation/reports/safety/*`; `pyproject.toml` (E501 exemption for the new module). No migration (the existing `measurements` JSONB carries the new fields), no dependency, no model change; retrieval, citations, prompts and the Phase 8 candidate untouched.

## 6. Development test results
`test_measurement_trust_v8.py` covers V5/V6/V7 failures, free-text-only and LLM-only values, forged trust fields, forged simulator provenance (bad, tampered, wrong tenant, wrong key, no key), authenticated-but-unverified submissions, human approval, rejection, unauthorised reviewers, separation of duties, stale and duplicate approvals, concurrent approval (one winner), cross-tenant reviewer, wrong-asset, genuine critical, urgent review, simulated labelling, priority-audit completeness, ticket gating. With the earlier numeric suites: backend 434 passed, 18 skipped (final run). Historical datasets v1..v7 were not rerun: their labels predate the trust policy, so they are covered by regression tests instead.

## 7. Frozen confirmation: safety-v8 (single run)
70 cases (Apex 46 / Meridian 24): 14 with human-verification actions, 42 with structured records, 12 with eligible observations expected, 8 genuine critical, 32 expected-urgent, 6 expected API rejections; dataset hashes `evaluation/datasets/safety-v8/MANIFEST.sha256`; implementation commit, scorer and code digests `FROZEN.md` and `CODE_AND_SCORER_SHA256.txt`; result `evaluation/reports/safety/final-v8.json`. Same-author fresh frozen set, not external validation. One harness-driven fix (a missing audit-event field found with a different-wording smoke set) was made before freezing and is disclosed in `FROZEN.md`.

| Gate | Result |
|---|---|
| Free-text-only / LLM measurements eligible | 0 |
| Values influencing priority without eligibility (priority above label) | 0 |
| LLM or unsupported structured candidates promoted to trusted | 0 |
| Unauthorized verification transitions | 0 of 18 actions (all 18 had the expected outcome: authorised 200, unauthorised 403, stale/duplicate 409, other tenant 404) |
| Unauthorized / duplicate submissions | 0 / 0 |
| Cross-tenant evidence accepted; forged simulator provenance accepted | 0; 0 (of 7 forged-signature cases; 6 forged-field/tenant cases rejected 422) |
| Genuine critical priority correct / silently downgraded | 8 of 8 / 0 |
| Eligible observations correct; legitimate eligibility rejected | 64 of 64; 0 |
| Final priority correct; priority deflated | 64 of 64; 0 |
| Urgent reviews flagged (expected 32); missed; unnecessary | 32; 0; 0 |
| **Complete priority-decision provenance** | **63 of 64: GATE NOT MET** |
**The failure:** SAF8-A-040 (a free-text candidate, `M-201 drive-end vibration measured 11.8 mm/s`, approved by a supervisor). Its audit event is complete, but the underlying free-text record carries no `provenance` object (only structured and simulated records do), so the observation entry in `incident.priority_decided` has `provenance: null`. Priority and eligibility were correct. Not patched, per protocol. False rejections of legitimate eligibility: 0; priority disagreements: 0.

## 8. Real-model observational run (separate; `evaluation/reports/safety/observational-real-model-v8.json`)
Ollama `qwen2.5:1.5b` (digest `65ec06548149…`) with MiniLM, the v8 reports, the model's own proposals, scripted human actions: 64/70 extracted (6 expected 422s); the model's incident asset matched the label in 63/64; free-text or LLM measurements eligible **0**; verification actions with the expected outcome 18/18, unauthorized transitions 0; unauthorized submissions 0; priority matched the label in 52/64 (3 above the label: the real model's category choice, not a measurement); urgent flagged 33 (32/32 expected flagged, one extra); latency mean 5.4 s, max 15.0 s. The validator overhead is unchanged at about 0.5 ms per report. Not tuned against.

## 9. Full regression
Backend 434 passed, 18 skipped. Root suites 72 passed (+4 generated-document consistency tests that failed until the requirement and traceability documents were regenerated; pass afterwards). Real-AI and real-stack customer acceptance: the first run had 1 + 2 failures, all test expectations tied to the removed free-text priority (the real model's category now alone decides the non-numeric priority); expectations were updated (priority P3, or P2/P3 where the real model's category decides) and the rerun passed: real-AI 12 passed, real-stack customer acceptance 21 passed. Secret scan 0 findings (793 files). Lint 8 findings (7 pre-existing in frozen Phase 8 tooling and sample data, 1 unused loop variable in the frozen v7 generator), none new from V8. Frontend tests not rerun: no frontend file changed.

## 10. Remaining risks and limits
Class E is not implemented; class C and D depend on human diligence (a reviewer can approve a wrong value); simulated data is demonstration-only and its key is a server-held secret to be managed; the free-text candidate analysis is heuristic and only informs urgency and review; priority is never lowered by verification, so an over-severe category stays until a human changes it; the provenance object is absent on free-text records (the one failed gate); same-author, scripted evidence; no frontend support yet for the verify action (API only).

## 11. Status and recommendation
V41-14.02: **PARTIAL** (one mandatory gate short, by one record, plus class E not implemented). All 238 original requirements retained; the 13 newly discovered requirements and five catalogue-only additions remain separately identified; documents regenerated. Gap-closure plan: `docs/planning/accelerated-gap-closure-plan.md` (status updated; no batch started).
Recommended decision: approve a single narrowly scoped provenance fix (populate a provenance object for every candidate record, including free text) **without** treating that as a license for another acceptance iteration; or accept the V8 design with the provenance shortfall recorded and proceed to the gap-closure plan (the safety-critical gates are met). Either way, ask for explicit owner approval before marking V41-14.02 VERIFIED, and decide whether class E/F production policy (key management, sensor authentication) is in scope.

## 12. Reproduce
```
cd backend
python -m pytest tests/test_measurement_trust_v8.py tests/test_numeric_boundary_v7.py tests/test_numeric_evidence.py tests/test_numeric_safety.py
SAFETY_DATASET=safety-v8 SAFETY_ACCEPT_LABEL=rerun-v8 python -m pytest tests/test_safety_acceptance_v8.py -s
RUN_REAL_AI=1 SAFETY_OBS_LABEL=rerun-obs-v8 python -m pytest tests/test_safety_observational_real_model_v8.py -s
```
