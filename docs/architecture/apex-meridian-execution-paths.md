# Apex built-in behavior vs Meridian profile-driven behavior (and the planned unification)

## Current state (Phase 5 closure)
| | Apex (tenants with no profile) | Meridian (tenants with a profile) |
|---|---|---|
| Parsing and priority | `app/ai/rules.py` (module unchanged since commit `44b1083`) | `app/profile/engine.py` driven by `tenant_profiles` |
| Ollama extraction | static prompt v3 and `FIELDS_SCHEMA` in `ollama_llm.py`, byte-identical to Phase 3 | `app/ai/profile_extraction.py` builds prompt and schema from the profile |
| Register / guidance / history kinds | `equipment_register`, `equipment_manual` + `inspection_report`, `incident_history` | profile fields |
| Categories | fixed list | profile list (plus implicit `other`) |
| Ticketing | `POST /tickets` (connector config empty) | connector config (`create_path`, `payload_map`, ...) |
| Extra lookups | spare-part inventory notes | profile enrichments (fleet, CRM) |

Identical for both: the review gate and external-release blocker, approvals and separation of duties, the outbox worker
and idempotency, citation and answer verification, RLS, RBAC, audit, and the connector egress policy.

## Duplicated execution paths (technical debt)
Branches on `profile is None` exist in `incident_service.extract_incident`, `DeterministicLLM.extract_fields`,
`OllamaLLM.extract_fields` and the document-upload route. Two implementations of "parse a report and decide priority"
(`rules.py` and `engine.py`) are therefore kept consistent by tests rather than by construction. This was a deliberate
choice: Apex's behavior, and the Phase 3/4 measurements that describe it, stay untouched while Meridian is added.

## Compatibility evidence
- `backend/tests/test_apex_compat.py`: golden outputs for 32 reports recorded **from the Phase 4 commit** (`44b1083`) must be
  reproduced exactly; `rules.py` hashes identically to that commit; the Apex Ollama prompts and schemas hash to the
  `prompts_sha256` recorded in all three Phase 3 evidence manifests; an Apex tenant with no profile is still served by the
  built-in path.
- `backend/tests/test_profile_engine.py`: the generic engine, configured with Apex's rules, reproduces the built-in rules on
  30 reports (parse, category, signals, priority). This is the key evidence that a unified engine is feasible.
- `git diff 44b1083 HEAD -- backend/app/ai/rules.py backend/app/ai/safeguards.py backend/app/ai/rag.py` is empty.
- Phase 3 and Phase 4 evaluation artifacts are unchanged (`git status` on `evaluation/reports/phase3` is clean).

## Planned unification (a separate improvement before final release)
1. Express Apex's rules as an explicit `apex-default` profile (already shown equivalent by the test above).
2. Make the profile the only path: remove the `profile is None` branches; keep a platform default profile for tenants
   without one.
3. Prompt compatibility: generate Apex's Ollama prompt and schema from the profile and assert byte-for-byte equality with
   prompt v3 (the Phase 3 hash is the acceptance test), or bump the prompt version and re-measure.
4. Gate: the golden file, the equivalence test, the full functional and real-AI suites and a repeat of the Phase 3/4
   evaluation must match before merging; Apex's historical evidence files must remain untouched.
5. Not part of Phase 5 or 6; schedule as its own regression-tested change.
