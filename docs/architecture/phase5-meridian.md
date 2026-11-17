# Phase 5: Meridian Fleet Logistics (second customer, configuration only)

Meridian is a fictional fleet operator: vehicles (`VH-2101`), brake and cooling problems, a CRM with SLA tiers, fleet
telematics, and a service desk whose work-order API differs from Apex's maintenance ticketing. It runs on the **same
code** as Apex. Onboarding procedure and the profile reference: [../operations/tenant-onboarding.md](../operations/tenant-onboarding.md).

## What changed in shared code (once, generically)
Phase 4 hardcoded equipment-maintenance assumptions in the shared services (asset ID regex, category list, vibration
policy, document kinds, ticketing contract). Phase 5 replaced them with **tenant configuration**; nothing names Meridian.
| Area | Before | Now |
|---|---|---|
| Domain vocabulary, categories, signals, priority rules, enrichments, CSV mappings | constants in `ai/rules.py` | `tenant_profiles` table + `app/profile/*` (validated, versioned, audited, RLS) |
| Extraction (deterministic and Ollama) | fixed prompt/schema | built-in path unchanged when no profile; `ai/profile_extraction.py` builds prompt/schema from the profile otherwise |
| Asset register / guidance / history kinds | fixed document kinds | profile fields; same verification and review gate |
| Ticketing contract | `POST /tickets` | connector config: `create_path`, `id_field`, `payload_map`, `priority_map` (validated) |
| External lookups | inventory only | read-only profile *enrichments* on any tenant connector (fleet, CRM) |
| Upload kinds and CSV/JSON mapping | fixed | profile-driven; global kinds still allowed |
Tenants without a profile (Apex) keep exactly the previous behavior; a test proves the generic engine reproduces the
built-in rules on 30 reports. Apex was **not** migrated onto a profile, so the Phase 3/4 measurements still describe it.

New shared pieces are customer-neutral: `tenant_profiles` (migration 0005), `/api/v1/tenant-profile`, `ai/profile_extraction.py`,
`connectors/enrichment.py`, `scripts/onboard_tenant.py`. Customer-specific content is only data: `onboarding/meridian.json`,
`sample-data/customer-b/`, and the three mock services (`mock-services/{fleet,crm,servicedesk}`).

## Meridian workflow
Upload fleet register / manual / inspection PDF / service history / telematics CSV (mapped columns) -> report -> profile
extraction (asset `VH-xxxx` verified against `fleet_register`; priority from Meridian's rules, e.g. brake pressure <= 55 psi
-> P2, <= 40 psi or coolant >= 115 C or a safety keyword -> P1) -> retrieval with citations from the Meridian manual ->
fleet-telematics and CRM enrichment notes -> human incident review when needed -> ticket draft -> separate approval ->
outbox worker -> `POST /api/v2/work-orders` with the mapped payload and an idempotency key -> `WO-xxxx` stored.

## Isolation evidence (deterministic backends, `test_meridian.py`)
Retrieval never returns the other customer's documents (three shared-vocabulary queries, both directions); every API route
on the other tenant's incident/ticket/approval returns 404/409/422; ticket lists, workflow queues, audit trails and
connectors are per tenant; with both tenants approved in one worker queue, the Meridian ticket reaches only the service
desk (`WO-`) and the Apex ticket only the maintenance system (`MNT-`); a mutation test shows the connector mapping is what
makes the submission valid (without it the service desk rejects the payload and the ticket fails permanently); lost-response
retry produces exactly one work order; an unregistered vehicle is blocked until registered and re-verified.

## Real-AI observations (Ollama `qwen2.5:1.5b` + MiniLM, small and not a benchmark)
- Automated tests (opt-in): Meridian ingestion on MiniLM, grounded and ungrounded questions, profile extraction,
  an Apex + Meridian end-to-end run through one worker, and real-embedding retrieval isolation: all pass; assertions are
  invariants because real output varies.
- Manual UI run with live inference (fixtures `meridian-uitest`, `apex-uitest`): the Meridian grounded answer cited the
  maintenance manual verbatim; extraction identified `VH-2101`, verified it, produced P2 and related service records
  SR-3001/SR-3002, and added the fleet and CRM notes. **The model chose category `leak` (because of "hissing") instead of
  `brake_system`, and the troubleshooting step produced no verifiable citation, so the incident went to human review.**
  Priority was unaffected because it comes from the numeric signal. After a supervisor's justified acceptance and a
  separate approval by the tenant admin, the worker created `WO-7001` in Meridian's service desk and nothing in Apex's
  system. The same flow for Apex (`P-101`) produced a grounded, cited recommendation and `MNT-1001` in the maintenance system.
- No retrieval or answer-quality benchmark was run for Meridian: its corpus is 15 chunks of synthetic text, so any rate
  would be meaningless. Meridian is validated for correctness, isolation and workflow, not for AI quality.

## Limitations
Connector destinations are now restricted by a server-side per-tenant egress policy (Phase 5 closure: [connector-egress.md](../security/connector-egress.md)); profile regexes run on
Python's backtracking engine without a timeout; the UI wording is only partly profile-driven (placeholders, labels, document
kinds); incident categories on a 1.5B model are unreliable at the margins; the review gate sends most incidents to a human
with this model (see the Phase 4 re-measurement); mock services are in-memory; CI has not run.
