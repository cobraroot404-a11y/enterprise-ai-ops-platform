# Customer discovery: Meridian Fleet Logistics (FICTIONAL)

> **This customer is fictional.** No real customer, interview or fleet exists. Every statement is an assumption written for this project. Numbers marked "assumed" are illustrative, not measured.

## Business background
Meridian Fleet (fictional) operates delivery vehicles from two depots (the demonstration vehicles are VH-2101 to VH-2104). Vehicle availability drives revenue, and service work is tracked in a service-desk system that differs from Apex's ticketing system.

## Current workflow (assumed)
A driver or dispatcher reports a vehicle fault ("VH-2101 low brake pressure, hissing at the rear axle"). A fleet technician looks up the vehicle in the telematics system, checks the customer-facing CRM for service commitments, searches service bulletins and the alert history, and opens a work item in the service desk.

## Pain points (assumed)
Telematics, CRM and service-desk data live in separate tools; recurring faults are not linked to bulletins; priority is subjective; work items are re-keyed by hand.

## Stakeholders (fictional roles)
Fleet technician (drafts incidents and tickets); depot supervisor (approves and verifies readings); tenant administrator; read-only auditor; operations manager (sponsor).

## Existing systems (simulated by local mocks)
A fleet-management / telematics API (mock, port 8103), a CRM API (mock, 8104) and a service-desk API with its own contract and authentication (mock, 8105). Documents: telematics alert CSVs, service bulletins, a vehicle register.

## Data sources
CSV telematics alerts and vehicle register; PDF/JSON service bulletins; REST telematics and CRM lookups used as enrichments; a records feed (REST pull, CSV pull or signed webhook) for bulletins (Batches 11A and 11B).

## Security constraints (assumed)
Same tenant-separation and approval rules as Apex; the service-desk API key is distinct and held outside the database; Meridian data must never be visible to Apex users and vice versa.

## Deployment constraints (assumed)
Same local, CPU-only deployment as Apex; Meridian is onboarded through configuration and the public API only (no change to shared code).

## Success criteria (assumed)
Meridian incidents reach the correct service-desk API with the correct field mapping and priorities; enrichments from telematics and CRM appear in the incident; both customers can run side by side with zero cross-tenant visibility.

## Assumptions
One depot network, one service desk; vehicle identifiers are stable; telematics values are indicative and do not drive numeric priority unless a supervisor verifies them.

## Open questions (fictional, unresolved)
Should CRM service commitments raise priority automatically? How are bulletins superseded? Which depots may see which bulletins?

See [../customer-delivery/meridian-demo-guide.md](../customer-delivery/meridian-demo-guide.md) and the second-customer design in [../architecture/phase5-meridian.md](../architecture/phase5-meridian.md).
