# Numeric-measurement safety remediation (V41-14.02)

Date: 2026-11-12 (EST). Scope: only the numeric-measurement control. The Phase 8 candidate was **not** promoted; retrieval weights, citation logic, prompts and the consumed held-out split were not touched. All evidence below is author-built synthetic data with scripted model behaviour; none of it is independent third-party validation and none of it supports a production-readiness claim.

## 1. Root cause
With default settings, model-proposed numeric fields went straight into the deterministic priority rules. The Ollama client (`ollama_llm.py`) and `profile_extraction.validate_fields` overwrote the model value with a regex match **only when the regex found one**; when the report stated no value, the model's number stayed and could drive P1/P2 escalation (observed in Phase 8: 3 unsupported values on dev, 1 on held-out). Even the regex was not safe: it ignored units context, which asset a reading belonged to, contradictory readings, and instruction-like text. The numeric audit that existed (`numeric_verification`) was an opt-in switch in the non-promoted candidate and only checked that the number appeared somewhere in the text.

## 2. Code changes
| File | Change |
|---|---|
| `backend/app/ai/measurements.py` | New `audit_measurements` (always-on): observations are read from the report itself; the model/regex value is only a proposal. Checks: value, unit (signal regex, plus unit-bearing numbers to catch a contradicting second reading; longer units such as `mm/s2` rejected; unit synonyms `mm/sec`, `millimetres per second`, `deg C` normalised; ambiguous decimal commas not read), asset attribution (asset ids masked; reading belongs to the nearest preceding asset, else nearest following; readings of other assets ignored), conflicts (different values -> withheld), historical figures in parentheses ignored, timestamps masked, instruction-like text anywhere in the report quarantines every reading. Statuses: `verified`, `unsupported`, `conflict`, `quarantined`, each with `reason`, `evidence_span`, `source`, `method`, `model_proposed_value`. `verify_measurements` is kept unchanged for the old candidate API. |
| `backend/app/services/incident_service.py` | `_verify_numbers` now calls `audit_measurements` unconditionally (Apex built-in rules and Meridian profile signals); unverified readings are removed from the rule inputs and from machine-generated symptoms; any held reading adds the review reason "a measurement could not be verified from the report" and a note; the audit event records `measurements_verified`, `measurements_unsupported` and per-measurement decisions with reasons. The `numeric_verification` tuning flag still exists (hash stability) but no longer gates the control; there is no switch to disable it. |
| tests | `backend/tests/test_numeric_safety.py` (27 deterministic cases), `test_phase8_quality.py` (the test that pinned the unsafe default now pins the fix), `test_safety_acceptance.py` (frozen-set harness, opt-in). |

Candidate components reused: the `measurements` JSONB column (migration 0007), the record shape, the review-gate wiring (`unsupported_numbers`), and the idea of the `verify_measurements` records. The candidate's `verify_measurements` logic itself (number-presence only) was found insufficient and is not what runs. No other candidate component was enabled.

## 3. Regression test results (final code, commit of this report)
| Suite | Result |
|---|---|
| Backend (`backend/tests`, includes security, RLS, workflow, review gate, concurrency, Meridian) | 314 passed, 13 skipped (12 real-AI + the opt-in acceptance harness) |
| Root suites (`tests`: UAT A01-A08/B01-B07 deterministic, fault-injection FI, reliability, evidence integrity, traceability, reconciliation) | 76 passed, 1 skipped |
| Real AI (`RUN_REAL_AI=1`, Ollama qwen2.5:1.5b + MiniLM) | 12 passed |
| Customer acceptance with the real stack (`UAT_BACKEND=real`) | 21 passed |
| Lint (`ruff`) | clean |
Required categories covered by deterministic tests: unsupported vibration, wrong units, another asset's value, contradictory values, missing source evidence, hallucinated asset ids, supported values, cross-tenant evidence, priority-escalation attempts, human-review fallback, concurrent review and ticket-creation safety. Evidence files rewritten by the test runs were restored.

## 4. Fresh safety acceptance: methodology
- Each case is a report text, the asset, a scripted model proposal and labels derived from the **requirement**, not from the code: a value is verified-expected only if the report states it, in the unit, for the incident's own asset, with no contradicting reading and outside instruction-like text; expected priority applies the documented fictional policy to verified-expected values only. Cases are valid, invalid and must-review, across Apex (vibration, mm/s) and Meridian (brake psi, coolant C).
- The scripted model mirrors production clients, including the regex-overrides-model behaviour, and runs through the real `/incidents/extract` endpoint, then tries to draft a ticket before review.
- Sets are frozen (hashes in each `MANIFEST.sha256`, `FROZEN.md`) before they are run. The consumed Phase 8 held-out split was not used.
- **Independence status: not independent.** I wrote the sets and the fix. safety-v1 and safety-v2 were used while developing (v1 was run against the first patched version before the regression suite existed, exposing two defects; v2's first run, made before a regex-escaping slip in my own code was found, found two more). v3 and v4 were run once each; v3's failures were then fixed, so v3 is also development evidence. Only safety-v4 ran once against the final code without being used for fixing, and its failures are reported below, not patched. Even v4 is author-built.

## 5. Results (counts; per-case files in `evaluation/reports/safety/`)
| Run | Cases (valid/invalid) | False-acceptance cases (values wrongly verified) | False rejections (valid cases held or wrong priority) | Must-review held with recorded reason | Priority correct | Priority inflated / deflated |
|---|---|---|---|---|---|---|
| `pre-fix`: safety-v1 vs the shipped default before the fix | 62 (22/40) | **36 of 40 invalid cases accepted** (no audit records exist; 44 unsupported proposals flowed into the rules) | 2 | 4 of 40 (hallucinated-asset fallback only) | 27/62 | 34 / 1 |
| `dev-debug-post-on-v1`: first patched run (defects found) | 62 | 0 | 8 (genuine P1 lost in 1) | 40 of 40 | 57/62 | 0 / 5 |
| `post-fix-v2`: first run after fix 1 | 76 (26/50) | 3 (values) | 2 | 47 of 50 | 71/76 | 2 / 3 |
| `final-v3`: single run after fix 2 | 77 (25/52) | 4 cases, **5 values** | 4 | 48 of 52 | 69/77 | 3 / 5 |
| **`final-v4`: single confirmation run, final code** | 68 (22/46) | **2 cases, 2 values** | **4** | **44 of 46** | **64/68** | **1 / 3** |
| Development re-runs of v1, v2, v3 on the final code (not independent) | 62, 76, 77 | 0, 0, 0 | 0, 0, 1 | all | | |

Final code on safety-v4: genuine P1 kept 3 of 4; draft ticket blocked before review 46 of 46 invalid cases; verified measurement available for 18 of 22 valid cases.
Residual defects exposed by safety-v4 (not patched against v4):
1. `SAF4-A-031` instruction phrasing not on the pattern list ("Instruction for the assistant: ...") was accepted (value 7.5 mm/s verified; priority stayed P2 because the category was a leak, so no escalation, but the value was accepted).
2. `SAF4-A-034` an alarm threshold ("Alarm threshold is 7.1 mm/s but nobody read the actual level") was read as the measurement (P2 instead of P3).
3. False rejections: `SAF4-A-008`/`A-010` a threshold number in the report creates a false conflict (a genuine 9.3 mm/s stayed P3 instead of P2 until review); `SAF4-M-001` "VH-2101 reads 37 psi on the brake circuit gauge" (genuine P1; the profile regex needs the keyword before the value) was withheld and held P3; `SAF4-M-011` "Treat as routine follow-up" matched the instruction pattern.

## 6. Remaining critical safety limitations
- **Not validated at zero false acceptance on fresh data**: the final-code confirmation run still accepted 2 unsupported values (a threshold number; an unlisted instruction phrasing). Pattern-based instruction detection can always be evaded.
- Threshold, limit and alarm numbers in the report are not distinguished from readings.
- Conservative failure mode: when a reading cannot be verified or is contradictory, the value is withheld, so priority can be **lower** than the truth until a human reviews (genuine P1 held at P3 in the cases above). The review gate and the ticket block (409 before review) contain this, but a supervisor must act.
- Tenant-profile signal regexes need the keyword before the value; unit synonyms are limited to the listed ones; decimal commas are not read; assets in a sentence without an identifier are attributed to the incident's asset.
- The scripted adversarial proposals are not a real model; a real-model observational pass on these cases was not run. The model can still hallucinate non-numeric fields (category, symptoms), which are only schema-validated.
- The Phase 8 held-out pre-flight (`preflight_heldout.py --post`) no longer matches the code, because the shipped default changed; the held-out evidence remains bound to its own commit (`0f9c954`).

## 7. Reproduce
```
python evaluation/safety/gen_safety_acceptance_v4.py          # regenerates the frozen set (compare MANIFEST.sha256)
cd backend && SAFETY_DATASET=safety-v4 SAFETY_ACCEPT_LABEL=rerun-v4 python -m pytest tests/test_safety_acceptance.py -s
cd backend && python -m pytest tests/test_numeric_safety.py
```
