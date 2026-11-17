# Customer onboarding guide

How a new customer organisation (a tenant) is brought onto the platform. Both existing customers are fictional; Meridian Fleet was onboarded exactly this way, through public API calls and one configuration file, with no customer-specific code (`backend/tests/test_meridian.py` repeats it on every test run). The operator's command reference is [tenant onboarding](../operations/tenant-onboarding.md).

## Before onboarding: what to collect from the customer
| Topic | What is needed | Where it goes |
|---|---|---|
| People and roles | who administers, who supervises and approves, who reports, who audits | tenant members (five roles) |
| Assets | how assets are identified (for example `P-101`, `VH-2101`) and which document is the authoritative register | tenant profile: `asset_id_pattern`, `register_kind` |
| Documents | manuals, inspection records, incident history; file types and CSV or JSON column names | document kinds and field mappings in the profile |
| Vocabulary | fault categories, symptoms, safety words | profile categories and keywords |
| Priority policy | the rules the customer uses to prioritise work | deterministic priority rules (never a model decision) |
| Systems | ticketing contract, enrichment sources, record feeds, webhook senders | connectors and webhook endpoints ([catalogue](../integrations/README.md)) |
| Numbers | which measurements matter and who may verify them | profile signals; verification by a supervisor other than the reporter |

The fictional discovery write-ups show the level of detail: [Apex Industrial](../customer-discovery/apex-industrial.md), [Meridian Fleet](../customer-discovery/meridian-fleet.md).

## Steps
1. **Describe the tenant in one file** modelled on [`onboarding/meridian.json`](../../onboarding/meridian.json): tenant, members, connectors, profile, documents. No secret goes in the file: connector secrets are environment-variable names.
2. **Allow the customer's systems**: add their origins to the server's egress allow-list (`EGRESS_ALLOWLIST`); development mocks use `EGRESS_DEV_MOCKS`.
3. **Apply it**: `python scripts/onboard_tenant.py <file>` (platform administrator credentials from the environment). It uses only public endpoints: create tenant, add members, create connectors, set the profile, upload documents.
4. **Check readiness** on the Customer Onboarding page or `GET /api/v1/onboarding/health`: members per role, connectors configured, profile valid, documents indexed, register recognised.
5. **Feeds** (optional): create REST or CSV connectors and webhook endpoints on the Data Sources page, run a first synchronisation, and confirm the records on the Document Library page.
6. **Acceptance**: walk the customer's scenarios with them, using the [acceptance plan](../customer-delivery/06-customer-acceptance-plan.md); record results per scenario.

## What onboarding must prove before the tenant is used
- A report naming a registered asset produces an incident with the asset verified against the register.
- A question answered from the tenant's documents shows citations with verbatim quotes, and a question with no evidence is refused.
- A ticket cannot be approved by its author and reaches the customer's (mock) ticketing system exactly once after approval.
- A user of another tenant gets 404 for this tenant's documents, incidents and tickets.
These are the checks `python scripts/demo.py smoke` runs for both customers.

## After onboarding
Profile changes are versioned and audited (`PUT /api/v1/tenant-profile`). Removing a document is an audited two-stage deletion. Rotating a webhook secret keeps the previous one valid for an overlap window. Offboarding a tenant (bulk deletion or export of its data) is **not implemented**.

Limits: onboarding was exercised only with the two fictional customers and local mocks; no customer training material, service-level terms or data-migration tooling exist.
