# Customer discovery: Apex Industrial Manufacturing (FICTIONAL)

> **This customer is fictional.** No real customer, interview, site visit or measurement exists. Every statement below is an assumption written for this project to make the platform's requirements concrete. Numbers marked "assumed" are illustrative, not measured.

## Business background
Apex Industrial (fictional) runs a continuous-process plant with pumps, compressors, valves and storage tanks (the demonstration assets are P-101, P-102, C-210, V-330 and T-415). Unplanned downtime is expensive and maintenance engineers spend a large share of each incident searching documents.

## Current workflow (assumed)
An operator reports a fault in free text ("pump P-101 vibrates and grinds"). A maintenance engineer searches equipment manuals, inspection reports and a maintenance spreadsheet, checks spare-part stock in the inventory system, then raises a maintenance ticket by hand in the maintenance ticketing system. A supervisor approves work orders by email or in the ticketing tool.

## Pain points (assumed)
Evidence is scattered across PDFs and spreadsheets; the same failure is rediscovered repeatedly; tickets are written inconsistently; urgency is judged informally; there is no reliable record of which evidence supported a decision.

## Stakeholders (fictional roles)
Support / maintenance engineer (drafts incidents and tickets); maintenance supervisor (approves, verifies readings); tenant administrator (configures connectors and users); read-only auditor (reviews the audit trail); plant manager (sponsor, not a platform user).

## Existing systems (simulated by local mocks)
A maintenance ticketing API (mock, port 8101) and a spare-parts inventory API (mock, port 8102). Documents: equipment manuals, inspection reports, maintenance CSV exports, historical incident records. No real system of the customer is connected anywhere.

## Data sources
PDF manuals and inspection reports; CSV maintenance logs and equipment register; JSON/CSV incident history; inventory lookups (REST); a records feed (REST pull, CSV file pull or signed webhook) for maintenance bulletins (Batches 11A and 11B).

## Security constraints (assumed)
Strict separation from other tenants; engineers cannot approve their own tickets; numeric readings that drive urgency must be human-verified before they count; every consequential action is audited; no customer content leaves the machine (local inference only); secrets are not stored in the database.

## Deployment constraints (assumed)
Runs on a single engineering workstation or a small on-premises server; no cloud services; PostgreSQL available locally; CPU-only inference.

## Success criteria (assumed, to be measured in acceptance)
Cited, evidence-grounded answers with an explicit "insufficient evidence" outcome when evidence is missing; structured incidents that a human can accept or reject; approval-gated ticket submission with an external ticket id and no duplicates; a complete audit trail; recovery from a failing ticketing or inventory system without losing or duplicating work.

## Assumptions
Reports are short free text; documents are searchable text or CSV (no scanned images); one plant, one ticketing system; English language; the supervisor is available to approve.

## Open questions (fictional, unresolved)
How long must audit records be retained? Which documents may leave the plant network? Should inventory shortages block ticket approval? Who owns the correctness of the equipment register?

See the solution documents in [../customer-delivery](../customer-delivery/) and the executable demonstration in [../customer-delivery/apex-demo-guide.md](../customer-delivery/apex-demo-guide.md).
