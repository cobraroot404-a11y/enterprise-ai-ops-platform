# Phase 4: security hardening and reliability

All results below come from the commands in `evaluation/reports/phase4-gate/manifest.json`. Functional tests use the deterministic test-only AI backends; the real-AI suite uses Ollama + MiniLM. Nothing here changes the Phase 3 AI-quality findings.

## Controls and the tests that prove them
| Control | Where | Proof |
|---|---|---|
| JWT expiry, tampering, `alg: none`, wrong algorithm, missing/malformed claims, unknown user | `app/api/deps.py` | `test_security.py`, `test_jwt_and_throttle.py` |
| Login brute-force throttle (10 failures/min/account, 429 + Retry-After; success clears) | `core_routes.py` | `test_jwt_and_throttle.py` |
| RBAC from the DB role (not the token) on every route; authorization runs before body validation | `api/deps.py`, `core/rbac.py` | `test_api_namespace_security.py`: route table is checked against the live OpenAPI schema, so a new route without security expectations fails the suite; role x route matrix; platform-admin isolation |
| Cross-tenant access across all namespaces and vector retrieval | RLS + explicit tenant filters | `test_api_namespace_security.py`, `test_security.py`, FI-05 |
| PostgreSQL RLS (all tenant tables incl. memberships and embedding profiles), pooled-connection context isolation | migrations 0001-0003, `database/session.py` | `test_security.py`, `test_membership_rls.py` |
| Concurrent approvals, approval bypass, rejected tickets, retries, idempotent submission, outbox lease/recovery, poison events | `ticket_service.py`, `worker.py` | `test_workflow.py`, FI-01..FI-07 |
| Append-only audit, one active outbox event per ticket, one approval per ticket | DB trigger/indexes/constraints | `test_control_mutations.py` |

## Mutation-style proofs (`test_control_mutations.py`)
Each test (1) shows the control blocking an attack, (2) removes the control and shows the attack succeeds, (3) restores it. Controls proven load-bearing: RLS on `document_chunks` and `memberships`, the audit trigger, the outbox unique index, the approval unique constraint, `rbac.can`, JWT signature verification, the idempotency key (lost response then retry creates a duplicate without it), and citation/answer verification (a fabricated quote, part number and number are shown without it).

## AI reliability safeguards (deterministic, `app/ai/safeguards.py`)
- Citations must be verbatim quotes of retrieved passages (existing) **and** point at current chunks owned by the tenant (`verify_citation_sources`).
- Identifiers (equipment, part, incident IDs) in an answer must appear in the evidence or the question; numbers must appear in the **cited evidence** (not the question).
- Incidents carry `review_status`: `pending_review` only if the equipment is in the tenant's authorized register AND guidance has verified evidence; otherwise `needs_review`. A ticket can only be drafted from `pending_review` or a human-`accepted` incident (supervisor/admin, comment required, audited); rejected incidents can never become tickets. Human approval before external submission is unchanged.
- Structured output that fails validation or hallucinates an asset ID falls back to deterministic rules or is rejected (existing).

## Defects found and fixed during Phase 4
- A real-model probe showed the model writing "exceeds **8.4** mm/s" (the user's reading) where the manual says 7.1; the first numeric safeguard allowed numbers from the question. Fixed (evidence-only) with a regression test; the real model's corrupted answer is now withheld.
- Identifier regex matched `INC-2025` before the full `INC-2025-1001` (caught by a unit test).
- An outbox event for a missing ticket crashed the worker (poison message). It is now dead-lettered and the queue continues.
- Malformed (but validly signed) token claims returned 500; now 401.
- Member-admin endpoints returned 422 instead of 403 for unauthorized callers with bad bodies; authorization now precedes validation.
- Database outage returned a raw 500; now `503 database_unavailable` with `Retry-After`.
- Concurrent uploads of identical content could race on the unique constraint; now resolved as `duplicate` (forced-race test FI-09b).
- Test isolation: the worker drains a global queue, so leftover events from earlier tests polluted exact-count assertions; fixtures now retire them.

## Phase 4 closure additions (before Meridian)
**Human-review gate (strengthened).** `needs_review` still blocks drafting for missing evidence, an unregistered
asset, or unresolved model-output validation (a rules fallback after an invalid LLM response now forces review
too). Accepting an incident needs a supervisor/admin and a written justification, is audited, and appends a labelled
human-review note; it **never** changes `asset_verified` or the citations. An unregistered asset becomes verified only by
re-checking the tenant's authoritative register (`POST /incidents/{id}/verify-asset`, audited) after the register is
updated through the audited document ingestion; until then the ticket cannot be approved, submitted or retried, and the
worker refuses to release it even if an approval already exists (`submission.blocked`). Review (incident level) and
approval (ticket level) are separate permissions, rows and audit actions. Proven in `test_review_gate.py` (7 tests,
including concurrent reviews and concurrent drafts: exactly one winner).

**Identity tables.** `users`/`tenants` now have RLS, SELECT-only grants and narrow `SECURITY DEFINER` write functions;
platform-admin sign-ins and cross-tenant administration are audited. Details and accepted limitations:
[identity-tables.md](identity-tables.md). Proven in `test_identity_security.py` (17 tests).

**Resource protection** (`app/core/limits.py`). Request bodies are capped (JSON 1 MB, uploads `MAX_UPLOAD_BYTES` plus
multipart overhead; enforced on the declared length and while streaming, standardized 413). Document ingestion
(`MAX_CONCURRENT_INGEST`, default 2) and AI inference (`MAX_CONCURRENT_LLM`, default 2) have bounded concurrency; extra
callers wait briefly and then receive 429 + `Retry-After`, and slots are always released. The login throttle is
unchanged. **These limits, like the login throttle, are in-process: they protect one local instance and are not a
distributed rate-limiting solution.** A multi-instance deployment needs a shared store or an API gateway. No paid or
external service is used. Proven in `test_resource_limits.py` (6 tests).

**Re-measurement.** AI quality was re-measured on the frozen Phase 3 held-out split with the real models:
[evaluation/reports/phase4-remeasure](../../evaluation/reports/phase4-remeasure/README.md). No quality change; the 95%
citation target remains NOT MET; about three in four extracted incidents now stop for human review with this model.

## Fault injection (`tests/fault_injection`, reports in `evaluation/failure-reports/phase4/`)
FI-01 503, FI-02 429, FI-03 timeout, FI-04 malformed response, FI-05 cross-tenant attempts (40, 0 succeeded), FI-06 concurrent approvals (one winner), FI-07 worker crash and lease recovery, FI-08 prompt injection (quarantined, nothing created), FI-09/09b duplicate ingestion including a forced race, FI-10 PostgreSQL stopped and restarted (opt-in: `RUN_DISRUPTIVE=1`). All 11 recorded scenarios passed; see the report for initial state, fault, expected, actual, recovery and final state of each.

## Known limitations
- The in-memory login throttle is per API process and resets on restart; a shared store is needed for multi-instance deployments.
- `tenants` and `users` are not under RLS. Rate limiting beyond login is not implemented.
- Real-model output varies between runs even at temperature 0; real-AI tests therefore assert invariants, and AI quality remains as measured in Phase 3 (citation correctness target NOT MET). The safeguards in this phase were changed after those measurements, so the Phase 3 numbers do not describe current behavior; re-measurement is planned with the Phase 8 dataset.
- FI-10 interrupts the shared local PostgreSQL container for about a minute and is therefore opt-in.
