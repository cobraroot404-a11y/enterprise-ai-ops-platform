# V8 provenance defect closure (V41-14.02): targeted remediation report

Date: 2026-11-12 (EST). Starting HEAD `28bbc398098b37c1f3778fa542248f307d043307` (branch `feat/apex-vertical-slice`, clean; original specification SHA-256 `b1c573e2…760da` unchanged; start digests `evaluation/reports/safety/v8b-start-hashes.txt`).
**The frozen safety-v8 result stays recorded as FAILED** (63 of 64 on complete priority-decision provenance); its dataset, scorer, labels, configuration, hashes and results (`evaluation/datasets/safety-v8/`, `evaluation/reports/safety/final-v8.json`) and all V1 to V7 artifacts are unchanged. **V41-14.02 remains PARTIAL.** No safety-v9 dataset was created and the V8 scorer was not rerun as a gate. Evidence is same-author and synthetic; nothing here supports a production-readiness claim.

## 1. Root cause of SAF8-A-040
Only structured and simulated records ever received a `provenance` object (built inside the structured-observation branch). A free-text or model-proposed candidate kept `provenance: null`. When a supervisor approved a free-text candidate, the `incident.priority_decided` audit event listed the approved observation with `provenance: null`, so the harness's provenance-completeness check failed for that one record. Priority, eligibility, authorization and the rest of the audit event were correct.

## 2. Provenance envelope (server-built, `build_provenance_envelope` in `backend/app/ai/measurement_trust.py`)
Every numeric candidate now carries, from the moment it is stored: `envelope_version`, `tenant_id`, `incident_id`, `observation_id`, `source_type` (`free_text_report`, `llm_proposal`, `structured_observation`, `simulation_fixture`, or `unknown_legacy`), `source_document_id`, `source_field`, `evidence_span`/`evidence_location` (only when the verifier actually produced them), `source_available`, `source_missing_reason`, `extraction_origin`, `trust_class`, `original_status`, `original_trust_status`, `submitted_by`, `channel`, `client_source_label` (descriptive, untrusted), `simulation_source_id`, and `establishes_truth: false`.
- It is built only from server-held facts. Nothing is taken from the request or the model.
- Nothing is fabricated. A value the model proposed with no supporting text gets `source_available: false`, null span, offsets, document and field, and the reason "the value was proposed by the model and has no supporting span in the report". A free-text candidate gets its real span and offsets; a structured one gets its field reference (`observations[0]`).
- A provenance envelope documents where a candidate came from. It does not make the measurement true, and its existence does not by itself claim complete traceability: the field `source_available` says per record whether a source reference exists.
- Invariant: extraction asserts a complete envelope on every stored candidate before the priority-decision audit event is written.

## 3. Approval-time provenance
Approval does not touch `provenance`: the original envelope is copied, the transition is applied, and the code asserts equality afterwards. A separate `verification` block records decision, transition (for example `UNVERIFIED->HUMAN_VERIFIED`), reviewer id, review timestamp, comment, incident and observation ids, priority before and after, the applied rule, `provenance_envelope_unchanged: true`, and `audit_event_id` linking to the `measurement.verified` or `measurement.rejected` audit event (the audit helper now returns the event so its id can be stored). The `incident.priority_decided` approval event carries the original envelope inside its `observations` entry. A record created before envelopes existed gets a clearly labelled `unknown_legacy` envelope at verification time (`source_available: false`, reason "predates provenance envelopes"), never an invented source. Authorization, separation of duties, row locking, stale and duplicate protections are unchanged and re-tested.

## 4. Anti-forgery behaviour (documented choice)
The request schemas for observations and for the verify call forbid unknown fields, so any client-supplied `provenance`, `provenance_envelope`, `reviewer_id`, `verified_by`, `trust_class`, `source_available`, `verification`, `audit_event_id`, `establishes_truth`, status, class, simulator flag or tenant field is rejected with **HTTP 422** (the existing API contract); nothing is silently accepted. Simulator provenance still requires the server-keyed signature. LLM output is read only for its named extraction fields, so extra provenance, trust or reviewer keys in a model response are ignored; a test proves a forging model produces an ordinary UNVERIFIED free-text envelope.

## 5. Files changed
`backend/app/ai/measurement_trust.py` (envelope builder), `backend/app/services/incident_service.py` (envelopes at extraction, preservation and verification block at approval, legacy handling), `backend/app/audit/service.py` (returns the created event; compatible), new `backend/tests/test_provenance_closure_v8.py`, requirement and traceability data and generated documents, this report. No migration, no dependency, no model change; the trust policy, free-text quarantine, locale parsing, thresholds, asset-scoped urgency, ticket approval and tenant isolation are unchanged.

## 6. Targeted test results
`test_provenance_closure_v8.py`: 24 cases pass (SAF8-A-040 regression, free-text envelope with real span, explicit absence, structured and simulated envelopes, approval preservation and verification block with audit link, rejection, audit completeness on every numeric decision path, legacy record, client forged fields (9 variants), forging LLM, builder ignores non-server data, reviewer authorization, separation of duties, tenant isolation, stale and duplicate decisions, free-text exclusion, API compatibility, and a **prospective sample** of four new wordings). The prospective sample and the SAF8-A-040 regression are development evidence only, not a replacement for the failed frozen V8 acceptance.

## 7. Full regression
Backend 458 passed, 18 skipped; root suites 72 passed plus 4 generated-document consistency tests that pass after regeneration (they referenced this report); real-AI 12 passed; real-stack customer acceptance 21 passed; secret scan 0 findings (796 files); lint 8 findings, unchanged and none from this change (seven pre-existing in frozen Phase 8 tooling and sample data, one in the frozen v7 generator). Frontend not rerun: no frontend file changed. Test-rewritten evidence files were restored.

## 8. Audit event examples (identifiers and values replaced by placeholders)
`incident.priority_decided` after approval of a free-text candidate:
```
{"tenant_id": "<tenant>", "incident_id": "<incident>", "asset_id": "<asset>", "evidence_class": "D", "verification_status": "HUMAN_VERIFIED",
 "observation_id": "<incident>:vibration_mm_s:0", "applied_rule": "numeric_rule", "numeric_rules_executed": true, "resulting_priority": "<P-level>",
 "priority_before": "<P-level>", "priority_after": "<P-level>", "authorized_by": "<reviewer id>", "decided_at": "<timestamp>",
 "observations": [{"observation_id": "<...>", "evidence_class": "D", "verification_status": "HUMAN_VERIFIED", "measurement_type": "vibration", "value": "<redacted>", "unit": "mm/s",
   "provenance": {"envelope_version": 1, "source_type": "free_text_report", "source_document_id": "<incident>", "source_field": "report_text", "source_available": true,
                  "evidence_span": "<redacted report sentence>", "extraction_origin": "deterministic_text_analysis", "trust_class": "A", "original_status": "unverified", "establishes_truth": false, "...": "..."}}]}
```
Model-proposed candidate with no source: `"provenance": {"source_type": "llm_proposal", "source_available": false, "evidence_span": null, "source_missing_reason": "the value was proposed by the model and has no supporting span in the report", "extraction_origin": "llm_proposed_value", "establishes_truth": false, "...": "..."}`.

## 9. Remaining provenance limitations
Spans exist only where the text analysis produced them (a model-proposed value without report support has none, by design); the span documents origin, not truth; legacy records stay `unknown_legacy`; the submitter's descriptive source label is untrusted; free-text record envelopes record the extraction origin but the platform does not store the original report as a separate document object (the incident's `report_text` is the source document); no sensor authentication (class E) and no key-management for the simulation key; reviewers can approve wrong values; the verify action has no frontend yet; same-author, scripted evidence.

## 10. Requirement evidence and recommendation
V41-14.02 remains **PARTIAL**: this change addresses the single frozen-gate shortfall and is verified by targeted and full regression tests only, with no new frozen acceptance, so the failed V8 result stays on record. All 238 original requirements are retained; the 13 newly discovered requirements and five catalogue-only additions stay separately identified; documents regenerated.
Recommended readiness decision: review this report together with the V8 architecture report and decide whether the evidence, scope and limitations above are sufficient to record V41-14.02 as verified *for the scoped, simulated, same-author evidence* or to keep it Partial; either way, explicit owner approval is required, and a decision on class E, simulation-key management and the frontend verify action is still open. No V9 and no Phase 9 work was started.

## 11. Reproduce
```
cd backend
python -m pytest tests/test_provenance_closure_v8.py tests/test_measurement_trust_v8.py tests/test_numeric_boundary_v7.py tests/test_numeric_evidence.py tests/test_numeric_safety.py
python -m pytest tests -q                       # full backend
RUN_REAL_AI=1 python -m pytest tests/test_real_ai.py
```
