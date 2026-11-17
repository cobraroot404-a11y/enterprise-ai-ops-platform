# Security documentation

The security model of the platform, where each control is implemented, how it is tested, and what is **not** covered. Everything here describes a local, single-machine system with fictional data; none of it has been reviewed by an independent security assessor, and nothing is claimed to be production-ready. The repository policy is in [SECURITY.md](../../SECURITY.md).

| Control | Design and limits | Implementation | Tests |
|---|---|---|---|
| Tenant isolation | forced PostgreSQL row-level security, restricted application roles, tenant context per transaction | `backend/app/database/session.py`, migrations | `backend/tests/test_api_namespace_security.py`, [phase 4](phase4-security-and-reliability.md), [phase 5 closure](phase5-closure-gate.md) |
| Authentication and sessions | JWT with expiry and tamper checks; credential lookup through a narrow database function | `backend/app/core/security.py`, [identity tables](identity-tables.md) | `backend/tests/test_jwt_and_throttle.py` |
| Authorization | five roles, permission per route, the database role decides (not the token claim) | `backend/app/core/rbac.py`, `backend/app/api/deps.py` | `backend/tests/test_api_namespace_security.py` |
| Separation of duties | an author cannot approve their own ticket; a creator cannot verify their own measurement | `backend/app/workflows/ticket_service.py` | `backend/tests/test_workflow.py`, `backend/tests/test_measurement_trust_v8.py` |
| Numeric trust boundary | numbers from text or a model never drive priority; only human-verified observations or signed simulation fixtures do. Requirement V41-14.02 is **Partial** | `backend/app/ai/measurement_trust.py` | `backend/tests/test_numeric_boundary_v7.py`; [architecture](../evaluation/numeric-safety-architecture-v8.md), [provenance closure](../evaluation/numeric-safety-provenance-closure-v8.md) |
| Prompt-injection handling | retrieved text is quarantined; answers need verified citations | `backend/app/ai/safety.py` | `backend/tests/test_ai_safeguards.py` |
| Connector egress (SSRF) | server-side allow-list, pinned addresses, no redirects, metadata addresses refused | `backend/app/connectors/egress.py` | `backend/tests/test_connector_egress.py`; [connector egress](connector-egress.md) |
| Webhook authentication | HMAC over timestamp, delivery id and raw body; constant-time comparison; durable replay ledger | `backend/app/ingestion/webhooks.py` | `backend/tests/test_webhooks.py`; [design](../architecture/webhooks-and-csv.md) |
| Secrets | referenced by environment-variable name; never stored, returned or logged; a scan gates commits | `scripts/secret_scan.py` | `backend/tests/test_observability.py`; [test credentials](test-credentials.md) |
| Rate and concurrency limits | shared across processes through PostgreSQL, with a per-process fallback | `backend/app/connectors/ratelimit.py`, `backend/app/core/limits.py` | `backend/tests/test_shared_rate_limits.py`, `backend/tests/test_shared_concurrency.py`, `backend/tests/test_concurrency_fairness.py`; [limits](rate-limiting-limitations.md) |
| Audit | append-only audit log (database trigger); consequential actions recorded without content | `backend/app/audit/service.py` | `backend/tests/test_control_mutations.py` |
| Document deletion | audited two-stage deletion with tombstones | `backend/app/ingestion/lifecycle.py` | `backend/tests/test_document_lifecycle.py`, `backend/tests/test_deletion_exposure_audit.py`; [lifecycle](../architecture/document-lifecycle.md) |
| Input and upload restrictions | size limits before buffering, type checks, bounded parsing | `backend/app/core/limits.py` | `backend/tests/test_resource_limits.py` |
| Error hygiene | a standard error body without stack traces or SQL | `backend/app/api/v1/error_contracts.py` | `backend/tests/test_api_error_contract.py` |
| Dependencies and licences | declared licences inventoried; no paid service required | [inventory](third-party-license-inventory.json) | `tests/test_third_party_notices.py`, `tests/test_no_paid_services.py` |
| Git provenance | **defect PROV-01 is open**: 52 commits carry an AI co-author trailer and 3 were authored under a tool's name | `scripts/provenance_check.py` | `tests/test_repository_provenance.py`; [recorded exceptions](../planning/provenance-exceptions.json) |

## Not covered
No independent penetration test or code review; no threat model document beyond the control descriptions above; no TLS termination, key management service, single sign-on or multi-factor authentication; no IP-keyed or edge rate limiting; backups keep deleted content; no data-retention or erasure policy has been decided; the webhook receiver has not been exposed to a public network. Dependency vulnerabilities are not scanned against an advisory database (no such tool was approved for download).
