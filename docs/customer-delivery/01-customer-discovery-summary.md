# 1. Customer discovery summary (FICTIONAL customers)

> Apex Industrial and Meridian Fleet are fictional. No real interviews or customer data exist. Every need below is an assumption stated in [../customer-discovery](../customer-discovery/README.md).

| | Apex Industrial Manufacturing | Meridian Fleet Services |
|---|---|---|
| Problem | Maintenance engineers lose time finding evidence across manuals, inspections, maintenance CSVs and incident history, then re-key tickets | Technicians juggle telematics, CRM, bulletins and a service desk, and re-key work items |
| Existing systems (mocked locally) | Maintenance ticketing (8101), spare-parts inventory (8102) | Telematics/fleet (8103), CRM (8104), service desk (8105) |
| What the platform adds | Cited answers or an explicit "insufficient evidence", structured incidents, human verification of numeric readings, approval-gated ticket submission, audit | The same, mapped to the service-desk contract through configuration only |
| Hard constraints | Tenant separation; no self-approval; verified numeric evidence only; local inference; every consequential action audited | Same, plus a distinct service-desk credential held outside the database |
| Deployment | Local workstation or small server, CPU-only inference | Same |

**Shared success criteria (assumed):** grounded, cited answers; structured incidents a human can accept or reject; one ticket per approved incident with an external id and no duplicates; complete audit trail; safe recovery when an external system fails; zero cross-tenant visibility.

**What was actually demonstrated** (against local mocks, same-author evidence): the full workflow for both customers through the API and UI; both customers side by side with zero cross-tenant visibility; recovery from injected failures; document, REST, CSV and signed-webhook ingestion. See the [acceptance plan](06-customer-acceptance-plan.md) and the [walkthrough](technical-walkthrough.md).

**What was not done:** no real customer system is connected, no real customer data was processed, no production deployment exists, and AI-quality targets are partly unmet (see the [retrospective](10-implementation-retrospective.md)).
