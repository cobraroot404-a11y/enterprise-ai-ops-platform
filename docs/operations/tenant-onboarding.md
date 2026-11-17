# Onboarding a customer tenant (configuration, not code)

Meridian Fleet Logistics (fictional) is onboarded with **public API calls only**, driven by
[`onboarding/meridian.json`](../../onboarding/meridian.json) and `scripts/onboard_tenant.py`. Nothing in the shared
services names Meridian, vehicles or fleet concepts; the same code serves Apex (equipment maintenance) and Meridian
(fleet maintenance). The test-suite onboards a fresh Meridian tenant through exactly this path
(`backend/tests/test_meridian.py`).

## Steps and the API that performs each
| Step | API | Who |
|---|---|---|
| Create tenant | `POST /api/v1/tenants` | platform administrator |
| First administrator and members | `POST /api/v1/tenants/{id}/members` | platform admin (first admin), then tenant admin |
| Connectors (ticketing, fleet, CRM, ...) | `POST /api/v1/connectors` | tenant admin |
| Domain profile | `PUT /api/v1/tenant-profile` (versioned, audited) | tenant admin |
| Documents (profile-driven kinds and CSV/JSON mappings) | `POST /api/v1/documents` | any role with `documents:write` |

```bash
python scripts/onboard_tenant.py onboarding/meridian.json
```
Environment (never in the file): `PLATFORM_ADMIN_EMAIL`, `PLATFORM_ADMIN_PASSWORD`, `ONBOARD_PASSWORD`; connector
secrets are referenced by **name** (`secret_ref`) and read from the server's environment. The script refuses
non-local APIs unless told otherwise and prints no credentials.

## What a tenant profile configures (`app/profile/schema.py`)
- Asset vocabulary: ID pattern (`VH-2101` vs `P-101`), which document kind is the authoritative **register**,
  which kinds supply guidance and incident history, extra document kinds.
- Categories (keywords + a description for the language model), symptoms, numeric **signals** (e.g. brake pressure in
  psi) and safety keywords.
- Deterministic **priority rules** (first match wins). Priority is never decided by a model.
- **Enrichments**: read-only lookups on tenant connectors (fleet telematics, CRM) rendered into incident notes.
  Failures are noted and never block an incident or change its priority.
- Per-kind **field mappings** for the customer's CSV/JSON layout (`id_field`, column renames).

Ticketing differences live on the **connector**, not in code: `create_path`, `id_field`, `payload_map` and
`priority_map` (the Meridian work-order API has a different contract from Apex's maintenance ticketing; the mock
rejects any payload that does not follow it).

## Safety of tenant-supplied configuration
Keywords are plain substrings. The only tenant-supplied regexes (asset ID, signals) must compile, have exactly one
capture group, be at most 200 characters and contain no nested quantifiers, and only run on reports capped at 4000
characters. Connector `create_path` must be a simple absolute path (no scheme, no `//`, no `..`). Profile and connector
changes are tenant-admin only and audited. Row-level security applies to profiles like every tenant table.

## What stays the same for every tenant
Human review gate (`needs_review`), separate ticket approval, separation of duties, idempotent outbox submission,
citation and answer verification, RLS isolation, audit trail. Tenants without a profile keep the original built-in
equipment-maintenance defaults, so existing behavior (and the Phase 3/4 measurements) is unchanged.

## Known limitations
- A tenant admin chooses connector `base_url`s, but only within the **server-controlled, per-tenant egress allow-list**
  (`EGRESS_ALLOWLIST`), enforced on every request with address validation, DNS pinning and no redirects; see
  [../security/connector-egress.md](../security/connector-egress.md). The operator must maintain that allow-list, and a real
  deployment should add network-level egress controls as well. Connector origins for a new tenant must be allow-listed
  by the operator **before** onboarding (`EGRESS_DEV_MOCKS` for local mocks).
- Profile regexes use Python's `re`, which has no timeout; the length/nesting restrictions reduce but do not remove
  the risk of pathological patterns.
- The profile has no migration path between schema versions yet (version is a counter, not a schema version).
