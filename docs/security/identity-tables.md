# Identity tables (`users`, `tenants`): audit and authorization model

Added before Meridian onboarding (Phase 4 closure). Migration: `0004_identity_hardening.py`. Tests:
`backend/tests/test_identity_security.py` (17), `test_review_gate.py`.

## Finding (before)
The API role `eaop_app` had `SELECT, INSERT, UPDATE` on `tenants` and `users` with no row-level security. Any
application bug or injection reaching those tables could have listed every account (emails and password
hashes) across tenants, set `is_platform_admin`, or overwritten another user's password hash. No existing test
reached it because the HTTP layer never exposed such a path; it was a missing defence in depth, not an exploit.

## Authorization model (after)
| Concern | Control |
|---|---|
| Read `users` | RLS: own row, plus members of the current tenant context only |
| Read `tenants` | RLS: current tenant, the caller's own tenants, or a platform admin |
| Write `users` / `tenants` | INSERT/UPDATE/DELETE revoked from the API role. Writes only through `SECURITY DEFINER` functions that re-check the caller inside the database |
| Sign-in | `auth_find_user(email)`: exact match only, so the table cannot be scanned |
| Create tenant | `app_create_tenant`: platform admin only |
| Create user | `app_provision_user`: tenant admin of the current tenant, or platform admin; never creates a platform admin; lower-cases the email |
| Platform admin flag | Cannot be set by the API role at all (only the owner/seed path) |
| Platform admin scope | No access to tenant data endpoints (403). May administer members of a tenant; each such access writes `platform.tenant_access` into that tenant's audit log. Sign-ins write `platform.login` to a tenant-less audit trail readable only by platform admins (`GET /api/v1/platform/audit`) |
| Worker role | No grants on either table |
| Existing RLS | Unchanged. Nothing was weakened |

RLS is `ENABLE`d (not `FORCE`d) on these two tables so the definer functions, which run as the table owner (the
admin/migration role, never used by the API), work. `eaop_app` is neither owner, superuser nor `BYPASSRLS`
(asserted by a test).

## Owner security disposition for Gate C

On November 16, 2026, the owner approved ENABLE without FORCE on exactly
`users`, `tenants`, and `webhook_endpoints` for the local candidate.
The two identity exceptions are limited to the owner-executed identity and
administration functions above. The webhook exception supports the documented
[single pre-authentication endpoint lookup](../architecture/webhooks-and-csv.md).
Every other relation in the tenant RLS inventory must also have FORCE enabled.

The approved forced set is `approvals`, `audit_events`,
`connector_sync_records`, `connectors`, `document_chunks`, `document_sources`,
`document_versions`, `documents`, `embedding_profiles`, `incidents`,
`ingestion_jobs`, `memberships`, `outbox_events`, `tenant_profiles`, `tickets`,
and `webhook_deliveries`. The enabled set is these sixteen plus the three
exceptions. The reviewer validates exact identities, ownership, grants,
policies, memberships and runtime role attributes against the isolated
PostgreSQL catalog. App and worker must not own the protected tables or have
SUPERUSER or BYPASSRLS. The exception also depends on least privilege,
tenant-scoped access, the bounded webhook lookup, and zero unauthorized
success in restricted-role authorization tests.

This is an owner-approved security design for the local candidate.
Independent Gate C acceptance still requires the qualifying reviewer record.

## Verified
Grants are exactly `SELECT` on both tables for the API role and none for the worker; no-context queries return 0
rows; user context shows only the own row; tenant context shows only that tenant's members; raw `UPDATE`,
`INSERT` and `DELETE` as the API role are denied (7 statements); the database functions refuse non-admins and
callers without context; the member endpoint cannot create platform admins; platform audit is platform-admin
only; and a mutation-style test shows that disabling RLS on `users` makes every account enumerable and
re-enabling it blocks that again.

## Accepted limitations
- The tenant context (`app.tenant_id`) is set by the application from a verified token plus a database
  membership check. If an attacker could run arbitrary SQL **as the API role** they could set it themselves and
  read that tenant's data and member list. RLS limits the blast radius to one tenant per transaction; it is not a
  defence against a fully compromised application process.
- Adding an existing account by email (`POST /tenants/{id}/members`) returns that account's id, so a tenant admin
  can learn that an email is registered somewhere. A deliberate multi-tenant feature; mitigated by role checks
  and auditing, not removed.
- `auth_find_user` is an exact-match oracle for "does this email exist"; sign-in responses are identical for a
  wrong password and an unknown user, and failures are throttled per account (per process, see below).
- A platform admin account is created only through the seed/owner path; there is no self-service flow and no MFA.
