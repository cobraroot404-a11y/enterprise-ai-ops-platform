# Customer acceptance report (deterministic)

Generated 2026-11-17T01:25:11.205546+00:00 by `UAT_BACKEND=deterministic python -m pytest tests/acceptance -q`.

**Deterministic TEST-ONLY backends: workflow, security and integration evidence only; NOT acceptance evidence for AI behaviour.**

**15 of 15 scenarios passed.**

| Test | Customer | Title | Requirements | Result |
|---|---|---|---|---|
| UAT-A01 | Apex Industrial Manufacturing (fictional) | Document ingestion | R12.1, R12.2, R12.3 | PASS |
| UAT-A02 | Apex Industrial Manufacturing (fictional) | Evidence-grounded retrieval | R13.1, R13.2, R13.3 | PASS |
| UAT-A03 | Apex Industrial Manufacturing (fictional) | Historical incident matching | R14.2, R7.1 | PASS |
| UAT-A04 | Apex Industrial Manufacturing (fictional) | Structured ticket generation | R14.1, R14.3, R14.4, R7.1 | PASS |
| UAT-A05 | Apex Industrial Manufacturing (fictional) | Unapproved submission blocked | R15.1, R15.2, R16.2 | PASS |
| UAT-A06 | Apex Industrial Manufacturing (fictional) | Approved ticket submission | R15.1, R11.1, R15.5, R7.1 | PASS |
| UAT-A07 | Apex Industrial Manufacturing (fictional) | Duplicate prevention | R15.3, R15.6, R11.3 | PASS |
| UAT-A08 | Apex Industrial Manufacturing (fictional) | API failure recovery | R15.4, R11.2, R15.3 | PASS |
| UAT-B01 | Meridian Fleet Logistics (fictional) | Second-tenant onboarding | R10.1, R10.3, R8.1 | PASS |
| UAT-B02 | Meridian Fleet Logistics (fictional) | Customer-specific schema mapping | R10.2, R12.3 | PASS |
| UAT-B03 | Meridian Fleet Logistics (fictional) | Fleet issue extraction | R14.1, R14.3, R8.1 | PASS |
| UAT-B04 | Meridian Fleet Logistics (fictional) | Ticket approval | R15.1, R15.2, R8.1 | PASS |
| UAT-B05 | Meridian Fleet Logistics (fictional) | Correct customer API submission | R11.1, R10.2, R8.1 | PASS |
| UAT-B06 | Meridian Fleet Logistics (fictional) | Cross-tenant access denied | R16.1, R8.1 | PASS |
| UAT-B07 | Meridian Fleet Logistics (fictional) | Failure recovery | R15.4, R15.3, R11.2 | PASS |

## UAT-A01: Document ingestion - PASS

*Customer: Apex Industrial Manufacturing (fictional). Backend mode: deterministic. Executed 2026-11-17T01:24:51.669048+00:00*

- **Requirement IDs:** R12.1, R12.2, R12.3
- **Preconditions:** Apex tenant exists with no documents; support engineer signed in
- **Test data:** Fictional Apex pump manual (PDF), inspection report (PDF), equipment register, incident history and maintenance log (CSV)
- **Steps:**
  1. Upload each of the five sample files
  2. Upload the equipment register again unchanged
  3. List the documents
  4. Search for a manual passage and read its provenance
- **Expected result:** Five documents created with chunks; the repeat upload is reported as duplicate; hashes and versions are listed; search results carry page numbers (PDF) or record ids (CSV)
- **Actual result:** 5 documents ingested {'apex_cp200_pump_manual.pdf': ('created', 3), 'apex_inspection_report_2026q3.pdf': ('created', 1), 'equipment_register.csv': ('created', 4), 'incident_history.csv': ('created', 5), 'maintenance_log.csv': ('created', 3)}; repeat upload 'duplicate'; first hit page=None
- **Evidence:** `evaluation/customer-acceptance/deterministic/uat-report.json` (scenario `UAT-A01`): ingest_results={"apex_cp200_pump_manual.pdf": ["created", 3], "apex_inspection_report_2026q3.pdf": ["created", 1], "equipment_register.csv": ["created", 4], "incident_history.; documents_listed=5; duplicate_status="duplicate"; sha256_recorded=true; provenance_page_numbers=[1, 2]

## UAT-A02: Evidence-grounded retrieval - PASS

*Customer: Apex Industrial Manufacturing (fictional). Backend mode: deterministic. Executed 2026-11-17T01:24:52.503945+00:00*

- **Requirement IDs:** R13.1, R13.2, R13.3
- **Preconditions:** Apex documents ingested
- **Test data:** 3 answerable questions and 1 unanswerable question
- **Steps:**
  1. Ask each question
  2. Check every citation: source ownership and verbatim quote
  3. Ask an out-of-scope question
- **Expected result:** Every answer shown is grounded with verified citations from Apex documents; unanswerable questions get an insufficient-evidence response with no citation. For the real model: at least 2 of the 3 prepared questions produce a verified grounded answer (measured Phase 3 coverage was about 75%)
- **Actual result:** 3 of 3 answerable questions grounded with verified citations; out-of-scope question refused
- **Evidence:** `evaluation/customer-acceptance/deterministic/uat-report.json` (scenario `UAT-A02`): answers=[{"question": "What should I check when pump P-101 shows abnormal vibration at the drive-end bearing?", "grounded": true, "citations": 3, "problems": []}, {"que; backend="deterministic"
- **Outstanding limitations:** Real-model coverage varies between runs; the 95% citation-correctness target remains NOT MET (Phase 3/4).

## UAT-A03: Historical incident matching - PASS

*Customer: Apex Industrial Manufacturing (fictional). Backend mode: deterministic. Executed 2026-11-17T01:24:53.150530+00:00*

- **Requirement IDs:** R14.2, R7.1
- **Preconditions:** Apex incident history ingested
- **Test data:** Report: P-101 abnormal vibration 8.4 mm/s with grinding noise
- **Steps:**
  1. Extract an incident from the report
  2. Inspect related incidents
- **Expected result:** Past incidents for the same equipment (INC-2024-0412, INC-2025-0107) are listed, same-asset first, from Apex's own history
- **Actual result:** related incidents ['INC-2025-0107', 'INC-2024-0412', 'INC-2025-0633']; first is same-asset
- **Evidence:** `evaluation/customer-acceptance/deterministic/uat-report.json` (scenario `UAT-A03`): related_incident_ids=["INC-2025-0107", "INC-2024-0412", "INC-2025-0633"]; incident_id="9d1f2997-955b-4021-b535-4f57126a6946"

## UAT-A04: Structured ticket generation - PASS

*Customer: Apex Industrial Manufacturing (fictional). Backend mode: deterministic. Executed 2026-11-17T01:24:53.836594+00:00*

- **Requirement IDs:** R14.1, R14.3, R14.4, R7.1
- **Preconditions:** Apex documents ingested
- **Test data:** Report: P-101 abnormal vibration 8.4 mm/s with grinding noise
- **Steps:**
  1. Extract the incident
  2. Check the validated fields
  3. Create a ticket draft (after human review if the platform requires it)
- **Expected result:** A schema-valid incident (asset P-101 verified, category, symptoms, priority P3 from category rules; the free-text vibration reading is an UNVERIFIED candidate flagged for urgent review, not a priority input, citations or an explicit no-evidence note, review status); a draft whose content carries the asset, priority, evidence and notes
- **Actual result:** incident pending_review (category mechanical_vibration, 1 citation(s)); draft DRAFT
- **Evidence:** `evaluation/customer-acceptance/deterministic/uat-report.json` (scenario `UAT-A04`): category="mechanical_vibration"; priority="P3"; review_status="pending_review"; citations=1; extraction_backend="deterministic/deterministic"; backend="deterministic"
- **Outstanding limitations:** In real-AI mode the model's category and symptoms vary; priority is rule-based.

## UAT-A05: Unapproved submission blocked - PASS

*Customer: Apex Industrial Manufacturing (fictional). Backend mode: deterministic. Executed 2026-11-17T01:24:54.848072+00:00*

- **Requirement IDs:** R15.1, R15.2, R16.2
- **Preconditions:** Apex draft tickets exist
- **Test data:** Two tickets: one PENDING_APPROVAL, one REJECTED
- **Steps:**
  1. Try to submit an unapproved ticket
  2. Let the worker run
  3. Engineer tries to approve
  4. Supervisor rejects; try to retry/submit the rejected ticket
- **Expected result:** Submission refused (409); the external system receives nothing; engineers cannot approve; a rejected ticket can never be submitted
- **Actual result:** submit before approval 409; engineer approval 403; rejected ticket submit/retry 409; worker idle; mock requests 0
- **Evidence:** `evaluation/customer-acceptance/deterministic/uat-report.json` (scenario `UAT-A05`): submit_status=409; engineer_approval_status=403; external_requests=0

## UAT-A06: Approved ticket submission - PASS

*Customer: Apex Industrial Manufacturing (fictional). Backend mode: deterministic. Executed 2026-11-17T01:24:55.776750+00:00*

- **Requirement IDs:** R15.1, R11.1, R15.5, R7.1
- **Preconditions:** Apex incident reviewed as required
- **Test data:** P-101 incident, supervisor approval
- **Steps:**
  1. Request approval
  2. Supervisor approves
  3. Worker submits
  4. Read the ticket and the audit trail
- **Expected result:** The ticket reaches the maintenance mock exactly once, its external id (MNT-) is stored, and the audit trail records draft, approval and submission
- **Actual result:** ticket SUBMITTED as MNT-1009; 1 external ticket; audit has draft, approval, submission
- **Evidence:** `evaluation/customer-acceptance/deterministic/uat-report.json` (scenario `UAT-A06`): external_ticket_id="MNT-1009"; external_tickets=1; audit_actions=["approval.approved", "document.created", "incident.extracted", "incident.priority_decided", "ingestion.attempt_started", "ingestion.job_completed", "ingestion.

## UAT-A07: Duplicate prevention - PASS

*Customer: Apex Industrial Manufacturing (fictional). Backend mode: deterministic. Executed 2026-11-17T01:24:56.811665+00:00*

- **Requirement IDs:** R15.3, R15.6, R11.3
- **Preconditions:** Apex incident ready for a ticket
- **Test data:** Concurrent drafts, concurrent approvals, direct re-submit, lost-response retry
- **Steps:**
  1. Create tickets for one incident from 5 threads
  2. Approve one ticket from 6 threads
  3. Re-submit and re-approve
  4. Inject a lost response and let the worker retry
- **Expected result:** One ticket per incident; one approval wins; one external ticket in every case, including after a lost response
- **Actual result:** draft codes [201, 409, 409, 409, 409]; approval codes [200, 409, 409, 409, 409, 409]; worker ['retry_scheduled', 'submitted']; external tickets 1
- **Evidence:** `evaluation/customer-acceptance/deterministic/uat-report.json` (scenario `UAT-A07`): draft_status_codes=[201, 409, 409, 409, 409]; approval_status_codes=[200, 409, 409, 409, 409, 409]; worker_outcomes=["retry_scheduled", "submitted"]; external_tickets=1

## UAT-A08: API failure recovery - PASS

*Customer: Apex Industrial Manufacturing (fictional). Backend mode: deterministic. Executed 2026-11-17T01:24:58.249969+00:00*

- **Requirement IDs:** R15.4, R11.2, R15.3
- **Preconditions:** Apex approved tickets; maintenance mock configurable
- **Test data:** Two consecutive HTTP 503 responses; one permanent HTTP 400
- **Steps:**
  1. Approve a ticket while the mock returns 503 twice
  2. Run the worker
  3. Approve another while the mock returns 400
  4. Fix and retry as a supervisor
- **Expected result:** Transient failures are retried with backoff and end SUBMITTED once; a permanent failure is FAILED (not retried automatically) and a supervisor retry then succeeds with exactly one external ticket per ticket
- **Actual result:** 503 x2: ['retry_scheduled', 'retry_scheduled', 'submitted'], attempts 3; 400: FAILED then supervisor retry SUBMITTED; external tickets 2 for 2 tickets
- **Evidence:** `evaluation/customer-acceptance/deterministic/uat-report.json` (scenario `UAT-A08`): transient_outcomes=["retry_scheduled", "retry_scheduled", "submitted"]; attempts=3; permanent_state="FAILED"; external_tickets=2

## UAT-B01: Second-tenant onboarding - PASS

*Customer: Meridian Fleet Logistics (fictional). Backend mode: deterministic. Executed 2026-11-17T01:24:59.370808+00:00*

- **Requirement IDs:** R10.1, R10.3, R8.1
- **Preconditions:** Platform running with Apex; Meridian origins authorized by the operator (server allow-list); no Meridian code exists in the services
- **Test data:** onboarding/meridian.json (tenant, members, connectors, domain profile, documents)
- **Steps:**
  1. Run the onboarding tool against the public API only
  2. Read the onboarding health checks
  3. Check that no customer-specific tables exist
- **Expected result:** Meridian exists as a separate tenant with members, connectors, profile and documents created through supported APIs only, and all health checks pass; the database schema contains no Meridian-specific objects
- **Actual result:** 8 of 8 onboarding checks pass; profile v1; no customer-specific tables
- **Evidence:** `evaluation/customer-acceptance/deterministic/uat-report.json` (scenario `UAT-B01`): health={"profile": "pass", "register": "pass", "guidance": "pass", "embedding": "pass", "approvers": "pass", "ticketing": "pass", "destinations": "pass", "secrets": "p; profile_version=1

## UAT-B02: Customer-specific schema mapping - PASS

*Customer: Meridian Fleet Logistics (fictional). Backend mode: deterministic. Executed 2026-11-17T01:25:00.439290+00:00*

- **Requirement IDs:** R10.2, R12.3
- **Preconditions:** Meridian onboarded with field mappings in its profile
- **Test data:** fleet_register.csv, service_history.csv, telematics_alerts.csv with Meridian's own column names
- **Steps:**
  1. Search for a service record
  2. Inspect the stored passage and record id
- **Expected result:** Records are keyed by Meridian's ids (VH-xxxx, SR-xxxx) and carry the mapped column names (vehicle_id, root_cause, resolution)
- **Actual result:** service record SR-3002 and register record VH-2101 carry mapped columns
- **Evidence:** `evaluation/customer-acceptance/deterministic/uat-report.json` (scenario `UAT-B02`): service_record="SR-3002"; mapped_columns_present=["vehicle_id", "root_cause"]

## UAT-B03: Fleet issue extraction - PASS

*Customer: Meridian Fleet Logistics (fictional). Backend mode: deterministic. Executed 2026-11-17T01:25:01.611104+00:00*

- **Requirement IDs:** R14.1, R14.3, R8.1
- **Preconditions:** Meridian onboarded; fleet and CRM mocks running
- **Test data:** Report: Vehicle VH-2101 shows low brake pressure of 52 psi with a hissing noise at the rear axle.
- **Steps:**
  1. Extract the incident
  2. Check asset verification, deterministic priority and enrichment notes
  3. Extract a report with no vehicle id
- **Expected result:** VH-2101 identified and verified against the fleet register; priority P3 from Meridian's category rules (the free-text 52 psi is an UNVERIFIED candidate, not a priority input); fleet telematics and CRM notes present; a report without a vehicle id is rejected, never guessed
- **Actual result:** VH-2101 verified; category brake_system; priority P3; 2 citation(s); enrichments present
- **Evidence:** `evaluation/customer-acceptance/deterministic/uat-report.json` (scenario `UAT-B03`): category="brake_system"; priority="P3"; review_status="pending_review"; backend="deterministic"; extraction_backend="deterministic/deterministic"
- **Outstanding limitations:** In real-AI mode the model may choose a near-miss category (observed: 'leak'); priority follows the extracted category and the regex-read signals.

## UAT-B04: Ticket approval - PASS

*Customer: Meridian Fleet Logistics (fictional). Backend mode: deterministic. Executed 2026-11-17T01:25:02.950603+00:00*

- **Requirement IDs:** R15.1, R15.2, R8.1
- **Preconditions:** Meridian incident extracted
- **Test data:** VH-2101 brake incident
- **Steps:**
  1. Draft and request approval as an engineer
  2. Engineer tries to approve
  3. Supervisor approves
- **Expected result:** The author cannot approve; the supervisor's decision is recorded with a comment; the ticket becomes APPROVED
- **Actual result:** author approval 403; supervisor approval recorded with comment; ticket APPROVED
- **Evidence:** `evaluation/customer-acceptance/deterministic/uat-report.json` (scenario `UAT-B04`): state="APPROVED"; approvals=[{"decision": "approved", "decided_by": "777796fa-89e9-4673-9d91-d40145ff944d", "comment": "Brake fault verified", "decided_at": "2026-11-17T01:25:02.910029+00:

## UAT-B05: Correct customer API submission - PASS

*Customer: Meridian Fleet Logistics (fictional). Backend mode: deterministic. Executed 2026-11-17T01:25:05.147988+00:00*

- **Requirement IDs:** R11.1, R10.2, R8.1
- **Preconditions:** Meridian connector maps to the service-desk work-order contract; Apex also active
- **Test data:** Approved Meridian ticket and an approved Apex ticket in the same worker queue
- **Steps:**
  1. Approve both tickets
  2. Run the worker
  3. Inspect each external system
- **Expected result:** Meridian's ticket arrives only at its service desk as a work order with the mapped fields and urgency (WO- id); Apex's reaches only its own system (MNT- id)
- **Actual result:** work order WO-7004 with mapped fields; Apex system received only its own ticket
- **Evidence:** `evaluation/customer-acceptance/deterministic/uat-report.json` (scenario `UAT-B05`): work_order="WO-7004"; payload_keys=["details", "source_ref", "summary", "urgency", "vehicle_ref"]; urgency="normal"; apex_system_tickets=1

## UAT-B06: Cross-tenant access denied - PASS

*Customer: Meridian Fleet Logistics (fictional). Backend mode: deterministic. Executed 2026-11-17T01:25:07.468699+00:00*

- **Requirement IDs:** R16.1, R8.1
- **Preconditions:** Apex and Meridian both hold incidents, tickets and documents
- **Test data:** Apex and Meridian users of every role
- **Steps:**
  1. Create a ticket in each tenant
  2. Each tenant's users try to read and act on the other's objects
  3. Search and ask from each tenant for the other's content
- **Expected result:** Every cross-tenant read or action is denied or hidden; retrieval never returns the other tenant's passages; audit trails are separate
- **Actual result:** 12 of 12 cross-tenant attempts denied; searches stayed inside each tenant; audit trails separate
- **Evidence:** `evaluation/customer-acceptance/deterministic/uat-report.json` (scenario `UAT-B06`): attempts_denied=12; apex_search_hits=10; meridian_search_hits=10

## UAT-B07: Failure recovery - PASS

*Customer: Meridian Fleet Logistics (fictional). Backend mode: deterministic. Executed 2026-11-17T01:25:10.180989+00:00*

- **Requirement IDs:** R15.4, R15.3, R11.2
- **Preconditions:** Meridian approved tickets; service-desk mock configurable
- **Test data:** HTTP 503 once, then a lost response
- **Steps:**
  1. Approve a ticket while the service desk returns 503
  2. Run the worker
  3. Approve another and lose the response
  4. Run the worker
- **Expected result:** Both tickets end SUBMITTED; each produced exactly one work order (the lost response is replayed with the same idempotency key)
- **Actual result:** 503: ['retry_scheduled', 'submitted']; lost response: ['retry_scheduled', 'submitted']; work orders 2 for 2 tickets
- **Evidence:** `evaluation/customer-acceptance/deterministic/uat-report.json` (scenario `UAT-B07`): transient_outcomes=["retry_scheduled", "submitted"]; lost_response_outcomes=["retry_scheduled", "submitted"]; work_orders=2
