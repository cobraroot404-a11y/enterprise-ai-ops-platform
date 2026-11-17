# Fault-injection report (Phase 7: FI-01 to FI-10 per the V4.1 specification)

Generated 2026-11-12T00:34:47.986323+00:00 by `RUN_DISRUPTIVE=1 python -m pytest tests/fault_injection -q`.
Deterministic test-only AI backends; local mock services; isolated test database.

**15 of 15 scenarios passed.**

## FI-01: HTTP 503 outage - PASS

*Recorded 2026-11-12T00:33:14.063674+00:00*

- **Initial state:** Ticket APPROVED with a pending outbox event; mock ticketing healthy
- **Injected fault:** Mock ticketing fails the next 2 request(s) with '503'
- **Expected behavior:** Worker classifies the error as transient, retries with backoff, never duplicates, ends SUBMITTED
- **Actual behavior:** worker outcomes ['retry_scheduled', 'retry_scheduled', 'submitted']; attempts=3; external requests=3
- **Recovery action:** automatic exponential-backoff retries via the transactional outbox
- **Final state:** ticket SUBMITTED with external id MNT-1015; 1 external ticket(s) exist
- **Data-integrity result:** CONSISTENT: tickets=1, submitted=1 (all with external ids: True), approval rows=1 (a ticket with more than one: 0), unapproved tickets sent=0, active outbox events=0, external tickets in mock=1
- **Duplicate external actions:** 0
- **Evidence (application log lines, redacted):**
  - `{"ts": "2026-11-11T19:33:14-0500", "level": "INFO", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "76aa0221-82cb-48e2-ba8c-38f4f41926d2", "origin": "127.0.0.1:53635", "method": "GET", "outcome": "ok", "duration_ms": 14.4}`
  - `{"ts": "2026-11-11T19:33:14-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "76aa0221-82cb-48e2-ba8c-38f4f41926d2", "ticket_id": "1b384838-e44f-49bb-a929-8092958f22f7", "from_state": "DRAFT", "to_state": "PENDING_APPROVAL"`
  - `{"ts": "2026-11-11T19:33:14-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "76aa0221-82cb-48e2-ba8c-38f4f41926d2", "ticket_id": "1b384838-e44f-49bb-a929-8092958f22f7", "from_state": "PENDING_APPROVAL", "to_state": "APPROV`
  - `{"ts": "2026-11-11T19:33:14-0500", "level": "INFO", "logger": "eaop.worker", "message": "submission.claimed", "event": "submission.claimed", "event_id": 23, "ticket_id": "1b384838-e44f-49bb-a929-8092958f22f7", "tenant_id": "76aa0221-82cb-48e2-ba8c-38f4f41926d2"}`
  - `{"ts": "2026-11-11T19:33:14-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "76aa0221-82cb-48e2-ba8c-38f4f41926d2", "ticket_id": "1b384838-e44f-49bb-a929-8092958f22f7", "from_state": "APPROVED", "to_state": "SUBMITTING", "`
  - `{"ts": "2026-11-11T19:33:14-0500", "level": "WARNING", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "76aa0221-82cb-48e2-ba8c-38f4f41926d2", "origin": "127.0.0.1:53638", "method": "POST", "outcome": "transient", "duration_ms": 14.9}`
  - `{"ts": "2026-11-11T19:33:14-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "76aa0221-82cb-48e2-ba8c-38f4f41926d2", "ticket_id": "1b384838-e44f-49bb-a929-8092958f22f7", "from_state": "SUBMITTING", "to_state": "RETRY_PENDIN`
  - `{"ts": "2026-11-11T19:33:14-0500", "level": "WARNING", "logger": "eaop.worker", "message": "submission.outcome", "event": "submission.outcome", "event_id": 23, "ticket_id": "1b384838-e44f-49bb-a929-8092958f22f7", "tenant_id": "76aa0221-82cb-48e2-ba8c-38f4f41926d2", "outcome": "retry_scheduled", "dur`
  - `{"ts": "2026-11-11T19:33:14-0500", "level": "INFO", "logger": "eaop.worker", "message": "submission.claimed", "event": "submission.claimed", "event_id": 23, "ticket_id": "1b384838-e44f-49bb-a929-8092958f22f7", "tenant_id": "76aa0221-82cb-48e2-ba8c-38f4f41926d2"}`
  - `{"ts": "2026-11-11T19:33:14-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "76aa0221-82cb-48e2-ba8c-38f4f41926d2", "ticket_id": "1b384838-e44f-49bb-a929-8092958f22f7", "from_state": "RETRY_PENDING", "to_state": "SUBMITTIN`
  - `{"ts": "2026-11-11T19:33:14-0500", "level": "WARNING", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "76aa0221-82cb-48e2-ba8c-38f4f41926d2", "origin": "127.0.0.1:53638", "method": "POST", "outcome": "transient", "duration_ms": 14.6}`
  - `{"ts": "2026-11-11T19:33:14-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "76aa0221-82cb-48e2-ba8c-38f4f41926d2", "ticket_id": "1b384838-e44f-49bb-a929-8092958f22f7", "from_state": "SUBMITTING", "to_state": "RETRY_PENDIN`
  - `23 structured log line(s) captured during this scenario`

## FI-02: HTTP 429 rate limiting - PASS

*Recorded 2026-11-12T00:33:14.845558+00:00*

- **Initial state:** Ticket APPROVED with a pending outbox event; mock ticketing healthy
- **Injected fault:** Mock ticketing fails the next 2 request(s) with '429'
- **Expected behavior:** Worker classifies the error as transient, retries with backoff, never duplicates, ends SUBMITTED
- **Actual behavior:** worker outcomes ['retry_scheduled', 'retry_scheduled', 'submitted']; attempts=3; external requests=3
- **Recovery action:** automatic exponential-backoff retries via the transactional outbox
- **Final state:** ticket SUBMITTED with external id MNT-1016; 1 external ticket(s) exist
- **Data-integrity result:** CONSISTENT: tickets=1, submitted=1 (all with external ids: True), approval rows=1 (a ticket with more than one: 0), unapproved tickets sent=0, active outbox events=0, external tickets in mock=1
- **Duplicate external actions:** 0
- **Evidence (application log lines, redacted):**
  - `{"ts": "2026-11-11T19:33:14-0500", "level": "INFO", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "c582f1c2-dbcb-4d9c-b5a7-64b1320e53ee", "origin": "127.0.0.1:53635", "method": "GET", "outcome": "ok", "duration_ms": 14.0}`
  - `{"ts": "2026-11-11T19:33:14-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "c582f1c2-dbcb-4d9c-b5a7-64b1320e53ee", "ticket_id": "b0175ad9-a214-433d-bb5f-a6cf89be7e01", "from_state": "DRAFT", "to_state": "PENDING_APPROVAL"`
  - `{"ts": "2026-11-11T19:33:14-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "c582f1c2-dbcb-4d9c-b5a7-64b1320e53ee", "ticket_id": "b0175ad9-a214-433d-bb5f-a6cf89be7e01", "from_state": "PENDING_APPROVAL", "to_state": "APPROV`
  - `{"ts": "2026-11-11T19:33:15-0500", "level": "INFO", "logger": "eaop.worker", "message": "submission.claimed", "event": "submission.claimed", "event_id": 24, "ticket_id": "b0175ad9-a214-433d-bb5f-a6cf89be7e01", "tenant_id": "c582f1c2-dbcb-4d9c-b5a7-64b1320e53ee"}`
  - `{"ts": "2026-11-11T19:33:15-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "c582f1c2-dbcb-4d9c-b5a7-64b1320e53ee", "ticket_id": "b0175ad9-a214-433d-bb5f-a6cf89be7e01", "from_state": "APPROVED", "to_state": "SUBMITTING", "`
  - `{"ts": "2026-11-11T19:33:15-0500", "level": "WARNING", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "c582f1c2-dbcb-4d9c-b5a7-64b1320e53ee", "origin": "127.0.0.1:53638", "method": "POST", "outcome": "transient", "duration_ms": 18.2}`
  - `{"ts": "2026-11-11T19:33:15-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "c582f1c2-dbcb-4d9c-b5a7-64b1320e53ee", "ticket_id": "b0175ad9-a214-433d-bb5f-a6cf89be7e01", "from_state": "SUBMITTING", "to_state": "RETRY_PENDIN`
  - `{"ts": "2026-11-11T19:33:15-0500", "level": "WARNING", "logger": "eaop.worker", "message": "submission.outcome", "event": "submission.outcome", "event_id": 24, "ticket_id": "b0175ad9-a214-433d-bb5f-a6cf89be7e01", "tenant_id": "c582f1c2-dbcb-4d9c-b5a7-64b1320e53ee", "outcome": "retry_scheduled", "dur`
  - `{"ts": "2026-11-11T19:33:15-0500", "level": "INFO", "logger": "eaop.worker", "message": "submission.claimed", "event": "submission.claimed", "event_id": 24, "ticket_id": "b0175ad9-a214-433d-bb5f-a6cf89be7e01", "tenant_id": "c582f1c2-dbcb-4d9c-b5a7-64b1320e53ee"}`
  - `{"ts": "2026-11-11T19:33:15-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "c582f1c2-dbcb-4d9c-b5a7-64b1320e53ee", "ticket_id": "b0175ad9-a214-433d-bb5f-a6cf89be7e01", "from_state": "RETRY_PENDING", "to_state": "SUBMITTIN`
  - `{"ts": "2026-11-11T19:33:15-0500", "level": "WARNING", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "c582f1c2-dbcb-4d9c-b5a7-64b1320e53ee", "origin": "127.0.0.1:53638", "method": "POST", "outcome": "transient", "duration_ms": 16.6}`
  - `{"ts": "2026-11-11T19:33:15-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "c582f1c2-dbcb-4d9c-b5a7-64b1320e53ee", "ticket_id": "b0175ad9-a214-433d-bb5f-a6cf89be7e01", "from_state": "SUBMITTING", "to_state": "RETRY_PENDIN`
  - `23 structured log line(s) captured during this scenario`

## FI-03: Network timeout - PASS

*Recorded 2026-11-12T00:33:15.626786+00:00*

- **Initial state:** Ticket APPROVED with a pending outbox event; mock ticketing healthy
- **Injected fault:** Mock ticketing fails the next 1 request(s) with 'timeout'
- **Expected behavior:** Worker classifies the error as transient, retries with backoff, never duplicates, ends SUBMITTED
- **Actual behavior:** worker outcomes ['retry_scheduled', 'submitted']; attempts=2; external requests=2
- **Recovery action:** automatic exponential-backoff retries via the transactional outbox
- **Final state:** ticket SUBMITTED with external id MNT-1017; 1 external ticket(s) exist
- **Data-integrity result:** CONSISTENT: tickets=1, submitted=1 (all with external ids: True), approval rows=1 (a ticket with more than one: 0), unapproved tickets sent=0, active outbox events=0, external tickets in mock=1
- **Duplicate external actions:** 0
- **Evidence (application log lines, redacted):**
  - `{"ts": "2026-11-11T19:33:15-0500", "level": "INFO", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "abb46eda-9ded-434d-bf46-3941782d69ba", "origin": "127.0.0.1:53635", "method": "GET", "outcome": "ok", "duration_ms": 14.1}`
  - `{"ts": "2026-11-11T19:33:15-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "abb46eda-9ded-434d-bf46-3941782d69ba", "ticket_id": "b11a6a74-ace4-4da2-b7ca-fa2c0de77de5", "from_state": "DRAFT", "to_state": "PENDING_APPROVAL"`
  - `{"ts": "2026-11-11T19:33:15-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "abb46eda-9ded-434d-bf46-3941782d69ba", "ticket_id": "b11a6a74-ace4-4da2-b7ca-fa2c0de77de5", "from_state": "PENDING_APPROVAL", "to_state": "APPROV`
  - `{"ts": "2026-11-11T19:33:15-0500", "level": "INFO", "logger": "eaop.worker", "message": "submission.claimed", "event": "submission.claimed", "event_id": 25, "ticket_id": "b11a6a74-ace4-4da2-b7ca-fa2c0de77de5", "tenant_id": "abb46eda-9ded-434d-bf46-3941782d69ba"}`
  - `{"ts": "2026-11-11T19:33:15-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "abb46eda-9ded-434d-bf46-3941782d69ba", "ticket_id": "b11a6a74-ace4-4da2-b7ca-fa2c0de77de5", "from_state": "APPROVED", "to_state": "SUBMITTING", "`
  - `{"ts": "2026-11-11T19:33:16-0500", "level": "WARNING", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "abb46eda-9ded-434d-bf46-3941782d69ba", "origin": "127.0.0.1:53638", "method": "POST", "outcome": "transient", "duration_ms": 413.2}`
  - `{"ts": "2026-11-11T19:33:16-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "abb46eda-9ded-434d-bf46-3941782d69ba", "ticket_id": "b11a6a74-ace4-4da2-b7ca-fa2c0de77de5", "from_state": "SUBMITTING", "to_state": "RETRY_PENDIN`
  - `{"ts": "2026-11-11T19:33:16-0500", "level": "WARNING", "logger": "eaop.worker", "message": "submission.outcome", "event": "submission.outcome", "event_id": 25, "ticket_id": "b11a6a74-ace4-4da2-b7ca-fa2c0de77de5", "tenant_id": "abb46eda-9ded-434d-bf46-3941782d69ba", "outcome": "retry_scheduled", "dur`
  - `{"ts": "2026-11-11T19:33:16-0500", "level": "INFO", "logger": "eaop.worker", "message": "submission.claimed", "event": "submission.claimed", "event_id": 25, "ticket_id": "b11a6a74-ace4-4da2-b7ca-fa2c0de77de5", "tenant_id": "abb46eda-9ded-434d-bf46-3941782d69ba"}`
  - `{"ts": "2026-11-11T19:33:16-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "abb46eda-9ded-434d-bf46-3941782d69ba", "ticket_id": "b11a6a74-ace4-4da2-b7ca-fa2c0de77de5", "from_state": "RETRY_PENDING", "to_state": "SUBMITTIN`
  - `{"ts": "2026-11-11T19:33:16-0500", "level": "INFO", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "abb46eda-9ded-434d-bf46-3941782d69ba", "origin": "127.0.0.1:53638", "method": "POST", "outcome": "ok", "duration_ms": 15.1}`
  - `{"ts": "2026-11-11T19:33:16-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "abb46eda-9ded-434d-bf46-3941782d69ba", "ticket_id": "b11a6a74-ace4-4da2-b7ca-fa2c0de77de5", "from_state": "SUBMITTING", "to_state": "SUBMITTED", `
  - `18 structured log line(s) captured during this scenario`

## FI-04: Malformed API response - PASS

*Recorded 2026-11-12T00:33:16.754665+00:00*

- **Initial state:** Ticket APPROVED with a pending outbox event; mock ticketing healthy
- **Injected fault:** Mock ticketing fails the next 1 request(s) with 'malformed'
- **Expected behavior:** Worker classifies the error as transient, retries with backoff, never duplicates, ends SUBMITTED
- **Actual behavior:** worker outcomes ['retry_scheduled', 'submitted']; attempts=2; external requests=2
- **Recovery action:** automatic exponential-backoff retries via the transactional outbox
- **Final state:** ticket SUBMITTED with external id MNT-1018; 1 external ticket(s) exist
- **Data-integrity result:** CONSISTENT: tickets=1, submitted=1 (all with external ids: True), approval rows=1 (a ticket with more than one: 0), unapproved tickets sent=0, active outbox events=0, external tickets in mock=1
- **Duplicate external actions:** 0
- **Evidence (application log lines, redacted):**
  - `{"ts": "2026-11-11T19:33:16-0500", "level": "INFO", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "4b299129-a229-490e-8e92-26ab5ffdedec", "origin": "127.0.0.1:53635", "method": "GET", "outcome": "ok", "duration_ms": 14.3}`
  - `{"ts": "2026-11-11T19:33:16-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "4b299129-a229-490e-8e92-26ab5ffdedec", "ticket_id": "5aef0b2c-a155-4d47-9fbd-b3f55041e4e5", "from_state": "DRAFT", "to_state": "PENDING_APPROVAL"`
  - `{"ts": "2026-11-11T19:33:16-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "4b299129-a229-490e-8e92-26ab5ffdedec", "ticket_id": "5aef0b2c-a155-4d47-9fbd-b3f55041e4e5", "from_state": "PENDING_APPROVAL", "to_state": "APPROV`
  - `{"ts": "2026-11-11T19:33:16-0500", "level": "INFO", "logger": "eaop.worker", "message": "submission.claimed", "event": "submission.claimed", "event_id": 26, "ticket_id": "5aef0b2c-a155-4d47-9fbd-b3f55041e4e5", "tenant_id": "4b299129-a229-490e-8e92-26ab5ffdedec"}`
  - `{"ts": "2026-11-11T19:33:16-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "4b299129-a229-490e-8e92-26ab5ffdedec", "ticket_id": "5aef0b2c-a155-4d47-9fbd-b3f55041e4e5", "from_state": "APPROVED", "to_state": "SUBMITTING", "`
  - `{"ts": "2026-11-11T19:33:16-0500", "level": "WARNING", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "4b299129-a229-490e-8e92-26ab5ffdedec", "origin": "127.0.0.1:53638", "method": "POST", "outcome": "malformed", "duration_ms": 19.3}`
  - `{"ts": "2026-11-11T19:33:16-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "4b299129-a229-490e-8e92-26ab5ffdedec", "ticket_id": "5aef0b2c-a155-4d47-9fbd-b3f55041e4e5", "from_state": "SUBMITTING", "to_state": "RETRY_PENDIN`
  - `{"ts": "2026-11-11T19:33:16-0500", "level": "WARNING", "logger": "eaop.worker", "message": "submission.outcome", "event": "submission.outcome", "event_id": 26, "ticket_id": "5aef0b2c-a155-4d47-9fbd-b3f55041e4e5", "tenant_id": "4b299129-a229-490e-8e92-26ab5ffdedec", "outcome": "retry_scheduled", "dur`
  - `{"ts": "2026-11-11T19:33:16-0500", "level": "INFO", "logger": "eaop.worker", "message": "submission.claimed", "event": "submission.claimed", "event_id": 26, "ticket_id": "5aef0b2c-a155-4d47-9fbd-b3f55041e4e5", "tenant_id": "4b299129-a229-490e-8e92-26ab5ffdedec"}`
  - `{"ts": "2026-11-11T19:33:16-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "4b299129-a229-490e-8e92-26ab5ffdedec", "ticket_id": "5aef0b2c-a155-4d47-9fbd-b3f55041e4e5", "from_state": "RETRY_PENDING", "to_state": "SUBMITTIN`
  - `{"ts": "2026-11-11T19:33:17-0500", "level": "INFO", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "4b299129-a229-490e-8e92-26ab5ffdedec", "origin": "127.0.0.1:53638", "method": "POST", "outcome": "ok", "duration_ms": 22.9}`
  - `{"ts": "2026-11-11T19:33:17-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "4b299129-a229-490e-8e92-26ab5ffdedec", "ticket_id": "5aef0b2c-a155-4d47-9fbd-b3f55041e4e5", "from_state": "SUBMITTING", "to_state": "SUBMITTED", `
  - `18 structured log line(s) captured during this scenario`

## FI-05: Unauthorized cross-tenant access - PASS

*Recorded 2026-11-12T00:33:17.489512+00:00*

- **Initial state:** Tenant A has a pending ticket, incident, documents
- **Injected fault:** Tenant B's most privileged users attempt 40+ reads/writes/actions on A's resources (all namespaces)
- **Expected behavior:** Every attempt denied or hidden; zero successful cross-tenant accesses; A's data unchanged
- **Actual behavior:** 40 cross-tenant attempts, 0 succeeded; vector search leaked 0 chunks
- **Recovery action:** none needed (requests rejected)
- **Final state:** ticket still PENDING_APPROVAL
- **Data-integrity result:** CONSISTENT: tickets=1, submitted=0 (all with external ids: True), approval rows=0 (a ticket with more than one: 0), unapproved tickets sent=0, active outbox events=0, external tickets in mock=0
- **Duplicate external actions:** 0
- **Evidence (application log lines, redacted):**
  - `{"ts": "2026-11-11T19:33:17-0500", "level": "INFO", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "747e5925-8d92-407d-b581-0aee237171cc", "origin": "127.0.0.1:53635", "method": "GET", "outcome": "ok", "duration_ms": 13.6}`
  - `{"ts": "2026-11-11T19:33:17-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "747e5925-8d92-407d-b581-0aee237171cc", "ticket_id": "27dcc6d3-1b61-426f-a6df-c95354f358f3", "from_state": "DRAFT", "to_state": "PENDING_APPROVAL"`
  - `54 structured log line(s) captured during this scenario`

## FI-06: Concurrent approvals - PASS

*Recorded 2026-11-12T00:33:19.036723+00:00*

- **Initial state:** Ticket PENDING_APPROVAL
- **Injected fault:** 8 supervisors approve the same ticket at the same instant
- **Expected behavior:** Exactly one decision wins (200); the rest conflict (409); one approval row; one external ticket
- **Actual behavior:** status codes [200, 409, 409, 409, 409, 409, 409, 409]; approval rows=1; worker ['submitted']
- **Recovery action:** row lock + unique approval constraint serialise decisions
- **Final state:** ticket SUBMITTED; 1 external ticket
- **Data-integrity result:** CONSISTENT: tickets=1, submitted=1 (all with external ids: True), approval rows=1 (a ticket with more than one: 0), unapproved tickets sent=0, active outbox events=0, external tickets in mock=1
- **Duplicate external actions:** 0
- **Evidence (application log lines, redacted):**
  - `{"ts": "2026-11-11T19:33:19-0500", "level": "INFO", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "161b2e51-3f4a-491a-ad3b-28368ef42a6d", "origin": "127.0.0.1:53635", "method": "GET", "outcome": "ok", "duration_ms": 19.3}`
  - `{"ts": "2026-11-11T19:33:19-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "161b2e51-3f4a-491a-ad3b-28368ef42a6d", "ticket_id": "beaa9c62-a5ff-41a8-90ad-cdd4821f7cec", "from_state": "DRAFT", "to_state": "PENDING_APPROVAL"`
  - `{"ts": "2026-11-11T19:33:19-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "161b2e51-3f4a-491a-ad3b-28368ef42a6d", "ticket_id": "beaa9c62-a5ff-41a8-90ad-cdd4821f7cec", "from_state": "PENDING_APPROVAL", "to_state": "APPROV`
  - `{"ts": "2026-11-11T19:33:19-0500", "level": "INFO", "logger": "eaop.worker", "message": "submission.claimed", "event": "submission.claimed", "event_id": 27, "ticket_id": "beaa9c62-a5ff-41a8-90ad-cdd4821f7cec", "tenant_id": "161b2e51-3f4a-491a-ad3b-28368ef42a6d"}`
  - `{"ts": "2026-11-11T19:33:19-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "161b2e51-3f4a-491a-ad3b-28368ef42a6d", "ticket_id": "beaa9c62-a5ff-41a8-90ad-cdd4821f7cec", "from_state": "APPROVED", "to_state": "SUBMITTING", "`
  - `{"ts": "2026-11-11T19:33:19-0500", "level": "INFO", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "161b2e51-3f4a-491a-ad3b-28368ef42a6d", "origin": "127.0.0.1:53638", "method": "POST", "outcome": "ok", "duration_ms": 14.6}`
  - `{"ts": "2026-11-11T19:33:19-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "161b2e51-3f4a-491a-ad3b-28368ef42a6d", "ticket_id": "beaa9c62-a5ff-41a8-90ad-cdd4821f7cec", "from_state": "SUBMITTING", "to_state": "SUBMITTED", `
  - `{"ts": "2026-11-11T19:33:19-0500", "level": "INFO", "logger": "eaop.worker", "message": "submission.outcome", "event": "submission.outcome", "event_id": 27, "ticket_id": "beaa9c62-a5ff-41a8-90ad-cdd4821f7cec", "tenant_id": "161b2e51-3f4a-491a-ad3b-28368ef42a6d", "outcome": "submitted", "duration_ms"`
  - `21 structured log line(s) captured during this scenario`

## FI-07: Worker interruption - PASS

*Recorded 2026-11-12T00:33:19.777413+00:00*

- **Initial state:** Ticket APPROVED, pending outbox event
- **Injected fault:** Worker 'crashes' (a) right after claiming the event and (b) after marking the ticket SUBMITTING
- **Expected behavior:** Lease expiry lets another worker resume; idempotency key prevents duplicates; ends SUBMITTED once
- **Actual behavior:** after crash (a): ['submitted']; after crash (b): ['submitted']; external tickets=2
- **Recovery action:** event lease expired; second worker re-claimed and completed safely
- **Final state:** tickets SUBMITTED / SUBMITTED
- **Data-integrity result:** CONSISTENT: tickets=2, submitted=2 (all with external ids: True), approval rows=2 (a ticket with more than one: 0), unapproved tickets sent=0, active outbox events=0, external tickets in mock=2
- **Duplicate external actions:** 0
- **Evidence (application log lines, redacted):**
  - `{"ts": "2026-11-11T19:33:19-0500", "level": "INFO", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "a45374e2-b1da-4a64-9f95-764b00544867", "origin": "127.0.0.1:53635", "method": "GET", "outcome": "ok", "duration_ms": 14.2}`
  - `{"ts": "2026-11-11T19:33:19-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "a45374e2-b1da-4a64-9f95-764b00544867", "ticket_id": "f4ee18a4-1c70-4001-8565-2e9bbc9e3f1a", "from_state": "DRAFT", "to_state": "PENDING_APPROVAL"`
  - `{"ts": "2026-11-11T19:33:19-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "a45374e2-b1da-4a64-9f95-764b00544867", "ticket_id": "f4ee18a4-1c70-4001-8565-2e9bbc9e3f1a", "from_state": "PENDING_APPROVAL", "to_state": "APPROV`
  - `{"ts": "2026-11-11T19:33:19-0500", "level": "INFO", "logger": "eaop.worker", "message": "submission.claimed", "event": "submission.claimed", "event_id": 28, "ticket_id": "f4ee18a4-1c70-4001-8565-2e9bbc9e3f1a", "tenant_id": "a45374e2-b1da-4a64-9f95-764b00544867"}`
  - `{"ts": "2026-11-11T19:33:19-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "a45374e2-b1da-4a64-9f95-764b00544867", "ticket_id": "f4ee18a4-1c70-4001-8565-2e9bbc9e3f1a", "from_state": "APPROVED", "to_state": "SUBMITTING", "`
  - `{"ts": "2026-11-11T19:33:19-0500", "level": "INFO", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "a45374e2-b1da-4a64-9f95-764b00544867", "origin": "127.0.0.1:53638", "method": "POST", "outcome": "ok", "duration_ms": 15.8}`
  - `{"ts": "2026-11-11T19:33:19-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "a45374e2-b1da-4a64-9f95-764b00544867", "ticket_id": "f4ee18a4-1c70-4001-8565-2e9bbc9e3f1a", "from_state": "SUBMITTING", "to_state": "SUBMITTED", `
  - `{"ts": "2026-11-11T19:33:19-0500", "level": "INFO", "logger": "eaop.worker", "message": "submission.outcome", "event": "submission.outcome", "event_id": 28, "ticket_id": "f4ee18a4-1c70-4001-8565-2e9bbc9e3f1a", "tenant_id": "a45374e2-b1da-4a64-9f95-764b00544867", "outcome": "submitted", "duration_ms"`
  - `{"ts": "2026-11-11T19:33:20-0500", "level": "INFO", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "a45374e2-b1da-4a64-9f95-764b00544867", "origin": "127.0.0.1:53635", "method": "GET", "outcome": "ok", "duration_ms": 18.2}`
  - `{"ts": "2026-11-11T19:33:20-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "a45374e2-b1da-4a64-9f95-764b00544867", "ticket_id": "d947acb3-7b22-4d60-a371-42821a88dc95", "from_state": "DRAFT", "to_state": "PENDING_APPROVAL"`
  - `{"ts": "2026-11-11T19:33:20-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "a45374e2-b1da-4a64-9f95-764b00544867", "ticket_id": "d947acb3-7b22-4d60-a371-42821a88dc95", "from_state": "PENDING_APPROVAL", "to_state": "APPROV`
  - `{"ts": "2026-11-11T19:33:20-0500", "level": "INFO", "logger": "eaop.worker", "message": "submission.claimed", "event": "submission.claimed", "event_id": 29, "ticket_id": "d947acb3-7b22-4d60-a371-42821a88dc95", "tenant_id": "a45374e2-b1da-4a64-9f95-764b00544867"}`
  - `25 structured log line(s) captured during this scenario`

## FI-08: Prompt injection via documents - PASS

*Recorded 2026-11-12T00:33:20.658856+00:00*

- **Initial state:** Tenant has documents; no tickets
- **Injected fault:** A poisoned manual page and a poisoned incident-history row instruct the assistant to approve and submit tickets and ignore its rules
- **Expected behavior:** Poisoned passages are quarantined (excluded from context); no ticket or approval is created; the queue stays empty
- **Actual behavior:** quarantined passages=2; poisoned incident in related=False; tickets=0; outbox events=0
- **Recovery action:** none needed: untrusted text is data and never authorizes actions
- **Final state:** no ticket, no approval, nothing submitted
- **Data-integrity result:** CONSISTENT: tickets=0, submitted=0 (all with external ids: True), approval rows=0 (a ticket with more than one: 0), unapproved tickets sent=0, active outbox events=0, external tickets in mock=0
- **Duplicate external actions:** 0
- **Evidence (application log lines, redacted):**
  - `{"ts": "2026-11-11T19:33:20-0500", "level": "INFO", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "8e9b3958-fd38-4631-8c4d-bcc766729694", "origin": "127.0.0.1:53635", "method": "GET", "outcome": "ok", "duration_ms": 14.2}`
  - `7 structured log line(s) captured during this scenario`

## FI-09: Duplicate ingestion - PASS

*Recorded 2026-11-12T00:33:21.291628+00:00*

- **Initial state:** Tenant has never seen this file
- **Injected fault:** The same file is uploaded 3 times sequentially, then by 6 threads at once under different names
- **Expected behavior:** Exactly one document version and one set of chunks; every other upload reports 'duplicate'; no 5xx
- **Actual behavior:** sequential ['created', 'duplicate', 'duplicate']; concurrent [(201, 'created'), (201, 'duplicate'), (201, 'duplicate'), (201, 'duplicate'), (201, 'duplicate'), (201, 'duplicate')]; indexed copies of the concurrent file=1
- **Recovery action:** content-hash uniqueness; losing concurrent writers resolve to the existing document
- **Final state:** one version of each file
- **Data-integrity result:** CONSISTENT: content hashes stored more than once = 0
- **Duplicate external actions:** 0
- **Evidence (application log lines, redacted):**
  - `{"ts": "2026-11-11T19:33:21-0500", "level": "INFO", "logger": "eaop.api", "message": "request", "correlation_id": "10058805-7ede-4092-aabf-72a4e39d1c7a", "method": "POST", "path": "/api/v1/documents", "route": "/documents", "status": 201, "duration_ms": 28.3}`
  - `{"ts": "2026-11-11T19:33:21-0500", "level": "INFO", "logger": "eaop.api", "message": "request", "correlation_id": "3f4b87e1-38bb-41e7-b85c-c5ce81d6417e", "method": "POST", "path": "/api/v1/documents", "route": "/documents", "status": 201, "duration_ms": 16.4}`
  - `{"ts": "2026-11-11T19:33:21-0500", "level": "INFO", "logger": "eaop.api", "message": "request", "correlation_id": "02fe24b4-31fc-4efc-b4bd-d732b4ce2882", "method": "POST", "path": "/api/v1/documents", "route": "/documents", "status": 201, "duration_ms": 16.3}`
  - `{"ts": "2026-11-11T19:33:21-0500", "level": "INFO", "logger": "eaop.api", "message": "request", "correlation_id": "330a980e-06f2-463e-b297-33680d00064f", "method": "POST", "path": "/api/v1/documents", "route": "/documents", "status": 201, "duration_ms": 41.4}`
  - `{"ts": "2026-11-11T19:33:21-0500", "level": "INFO", "logger": "eaop.api", "message": "request", "correlation_id": "168c1c6d-0f66-432c-b0ca-9167f9cfc7e0", "method": "POST", "path": "/api/v1/documents", "route": "/documents", "status": 201, "duration_ms": 43.2}`
  - `{"ts": "2026-11-11T19:33:21-0500", "level": "INFO", "logger": "eaop.api", "message": "request", "correlation_id": "71091c89-c01f-4152-a46a-28c466f678a3", "method": "POST", "path": "/api/v1/documents", "route": "/documents", "status": 201, "duration_ms": 55.7}`
  - `{"ts": "2026-11-11T19:33:21-0500", "level": "INFO", "logger": "eaop.api", "message": "request", "correlation_id": "3bebfe60-175c-484b-bad3-5dbd6a0077be", "method": "POST", "path": "/api/v1/documents", "route": "/documents", "status": 201, "duration_ms": 57.4}`
  - `{"ts": "2026-11-11T19:33:21-0500", "level": "INFO", "logger": "eaop.api", "message": "request", "correlation_id": "070140e8-de51-483a-a5eb-37b9a4315863", "method": "POST", "path": "/api/v1/documents", "route": "/documents", "status": 201, "duration_ms": 49.8}`
  - `{"ts": "2026-11-11T19:33:21-0500", "level": "INFO", "logger": "eaop.api", "message": "request", "correlation_id": "2cbd8b19-c97f-40c7-ae0d-932cef00ce5b", "method": "POST", "path": "/api/v1/documents", "route": "/documents", "status": 201, "duration_ms": 57.4}`
  - `{"ts": "2026-11-11T19:33:21-0500", "level": "INFO", "logger": "eaop.api", "message": "request", "correlation_id": "dfbdc06e-b1ae-498a-942b-b424f5a08b2e", "method": "POST", "path": "/api/v1/search", "route": "/search", "status": 200, "duration_ms": 16.1}`
  - `10 structured log line(s) captured during this scenario`

## FI-09b: Duplicate ingestion: forced check-then-insert race - PASS

*Recorded 2026-11-12T00:33:21.911537+00:00*

- **Initial state:** Writer 1 has passed its duplicate check for new content
- **Injected fault:** Writer 2 commits the same content before writer 1 inserts (unique constraint collision)
- **Expected behavior:** Writer 1 resolves to 'duplicate' of writer 2's document: no error, no second copy
- **Actual behavior:** loser result: duplicate; winner: created; stored versions=1
- **Recovery action:** IntegrityError caught, transaction rolled back, duplicate lookup returned the winner
- **Final state:** exactly one stored copy
- **Data-integrity result:** CONSISTENT: stored versions of the raced content = 1
- **Duplicate external actions:** 0
- **Evidence (application log lines, redacted):**
  - `0 structured log line(s) captured during this scenario`

## FI-10: Database interruption - PASS

*Recorded 2026-11-12T00:20:00.901910+00:00*

- **Initial state:** Ticket APPROVED with a durable pending outbox event
- **Injected fault:** PostgreSQL is stopped while the API and worker are active, then restarted
- **Expected behavior:** API returns 503 (not 500); worker makes no external call and loses no state; after restart the pool recovers and the ticket is submitted exactly once
- **Actual behavior:** during outage: API 503 database_unavailable; worker raised OperationalError; external requests=0. After restart: API 200; worker ['submitted']
- **Recovery action:** PostgreSQL restarted; pooled connections re-validated (pre-ping); outbox event replayed
- **Final state:** ticket SUBMITTED; 1 external ticket
- **Data-integrity result:** CONSISTENT: tickets=1, submitted=1 (all with external ids: True), approval rows=1 (a ticket with more than one: 0), unapproved tickets sent=0, active outbox events=0, external tickets in mock=1
- **Duplicate external actions:** 0
- **Evidence (application log lines, redacted):**
  - `{"ts": "2026-11-11T19:20:00-0500", "level": "INFO", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "fe709540-af0c-4793-b9cb-adc508abb532", "origin": "127.0.0.1:65520", "method": "GET", "outcome": "ok", "duration_ms": 14.4}`
  - `{"ts": "2026-11-11T19:20:01-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "fe709540-af0c-4793-b9cb-adc508abb532", "ticket_id": "37d2f1bf-dc96-4816-b5d6-a3ef8cb38f83", "from_state": "DRAFT", "to_state": "PENDING_APPROVAL"`
  - `{"ts": "2026-11-11T19:20:01-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "fe709540-af0c-4793-b9cb-adc508abb532", "ticket_id": "37d2f1bf-dc96-4816-b5d6-a3ef8cb38f83", "from_state": "PENDING_APPROVAL", "to_state": "APPROV`
  - `{"ts": "2026-11-11T19:22:11-0500", "level": "ERROR", "logger": "eaop.api", "message": "database unavailable", "correlation_id": "eb2f12ee-577d-4ffc-b8b6-b87b78d05523"}`
  - `{"ts": "2026-11-11T19:22:11-0500", "level": "INFO", "logger": "eaop.api", "message": "request", "correlation_id": "eb2f12ee-577d-4ffc-b8b6-b87b78d05523", "method": "GET", "path": "/api/v1/tickets", "route": "/tickets", "status": 503, "duration_ms": 129999.9}`
  - `{"ts": "2026-11-11T19:24:28-0500", "level": "INFO", "logger": "eaop.worker", "message": "submission.claimed", "event": "submission.claimed", "event_id": 9, "ticket_id": "37d2f1bf-dc96-4816-b5d6-a3ef8cb38f83", "tenant_id": "fe709540-af0c-4793-b9cb-adc508abb532"}`
  - `{"ts": "2026-11-11T19:24:28-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "fe709540-af0c-4793-b9cb-adc508abb532", "ticket_id": "37d2f1bf-dc96-4816-b5d6-a3ef8cb38f83", "from_state": "APPROVED", "to_state": "SUBMITTING", "`
  - `{"ts": "2026-11-11T19:24:28-0500", "level": "INFO", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "fe709540-af0c-4793-b9cb-adc508abb532", "origin": "127.0.0.1:65517", "method": "POST", "outcome": "ok", "duration_ms": 15.3}`
  - `{"ts": "2026-11-11T19:24:28-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "fe709540-af0c-4793-b9cb-adc508abb532", "ticket_id": "37d2f1bf-dc96-4816-b5d6-a3ef8cb38f83", "from_state": "SUBMITTING", "to_state": "SUBMITTED", `
  - `{"ts": "2026-11-11T19:24:28-0500", "level": "INFO", "logger": "eaop.worker", "message": "submission.outcome", "event": "submission.outcome", "event_id": 9, "ticket_id": "37d2f1bf-dc96-4816-b5d6-a3ef8cb38f83", "tenant_id": "fe709540-af0c-4793-b9cb-adc508abb532", "outcome": "submitted", "duration_ms":`
  - `16 structured log line(s) captured during this scenario`

## REL-01: Additional: LLM timeout or failure - PASS

*Recorded 2026-11-12T00:33:11.416328+00:00*

- **Initial state:** Apex documents ingested; the language model is healthy
- **Injected fault:** The model call times out (reported as invalid output), then an unexpected exception occurs inside the model client
- **Expected behavior:** Questions are withheld honestly (no citation, no answer text); incident extraction falls back to deterministic rules and is blocked for human review; an unexpected failure is a standardized 500 with no detail and the service keeps working
- **Actual behavior:** timeout: ask 200 grounded=False problems=['llm output invalid: Ollama request failed: ReadTimeout']; extraction review_status=needs_review fallback=True; draft 409; unexpected exception: 500 internal_error; after recovery: 200
- **Recovery action:** automatic: the next request uses the healthy model; no manual action
- **Final state:** no ticket created from the unreviewed incident
- **Data-integrity result:** CONSISTENT: tickets=0, submitted=0 (all with external ids: True), approval rows=0 (a ticket with more than one: 0), unapproved tickets sent=0, active outbox events=0, external tickets in mock=0
- **Duplicate external actions:** 0
- **Evidence (application log lines, redacted):**
  - `{"ts": "2026-11-11T19:33:11-0500", "level": "ERROR", "logger": "eaop.api", "message": "unhandled error", "correlation_id": "1d26c253-0f4d-43b2-ac39-2ed7f0934eff", "exc": "Traceback (most recent call last):\n  File \"<local-path>\\`
  - `5 structured log line(s) captured during this scenario`

## REL-02: Additional: embedding or retrieval failure - PASS

*Recorded 2026-11-12T00:33:12.013847+00:00*

- **Initial state:** Apex documents indexed; embedding model healthy
- **Injected fault:** The embedding model raises while embedding a query and while embedding an uploaded document
- **Expected behavior:** Search, ask and upload return 503 embedding_unavailable with Retry-After (never a raw 500); the failed upload stores nothing; everything works again once the model recovers
- **Actual behavior:** during outage: search 503 embedding_unavailable, ask 503, upload 503; chunks before/during 16/16; after recovery: search 200, upload 201 created
- **Recovery action:** automatic once the embedding model is available; the client retries after Retry-After
- **Final state:** index consistent; no partial documents
- **Data-integrity result:** CONSISTENT: chunk count unchanged during the outage (16 == 16)
- **Duplicate external actions:** 0
- **Evidence (application log lines, redacted):**
  - `{"ts": "2026-11-11T19:33:12-0500", "level": "INFO", "logger": "eaop.api", "message": "request", "correlation_id": "36e50c24-100e-48f2-8233-5d9f44868b86", "method": "POST", "path": "/api/v1/search", "route": "/search", "status": 503, "duration_ms": 13.8}`
  - `{"ts": "2026-11-11T19:33:12-0500", "level": "INFO", "logger": "eaop.api", "message": "request", "correlation_id": "b4706949-c9e8-4049-8fd6-d1f8413ddc28", "method": "POST", "path": "/api/v1/ai/ask", "route": "/ai/ask", "status": 503, "duration_ms": 14.7}`
  - `{"ts": "2026-11-11T19:33:12-0500", "level": "INFO", "logger": "eaop.api", "message": "request", "correlation_id": "770f5b6d-c78c-4a3a-b664-52451b9673cf", "method": "POST", "path": "/api/v1/documents", "route": "/documents", "status": 503, "duration_ms": 17.4}`
  - `7 structured log line(s) captured during this scenario`

## REL-03: Additional: invalid structured AI output - PASS

*Recorded 2026-11-12T00:33:12.589762+00:00*

- **Initial state:** Apex documents ingested
- **Injected fault:** The model returns (a) non-conforming output, (b) a hallucinated equipment id that is not in the report, (c) nothing identifying equipment
- **Expected behavior:** Invalid output never reaches a ticket: (a) falls back to deterministic rules and blocks for human review; (b) is rejected as invalid and falls back; (c) is refused with asset_not_identified; no incident is created for (c)
- **Actual behavior:** (a) ('needs_review', True); (b) ('P-101', 'mechanical_vibration', 'needs_review'); (c) 422 asset_not_identified; incidents stored=2
- **Recovery action:** deterministic rules take over; the human-review gate holds
- **Final state:** no ticket possible without human review; nothing sent externally
- **Data-integrity result:** CONSISTENT: tickets=0, submitted=0 (all with external ids: True), approval rows=0 (a ticket with more than one: 0), unapproved tickets sent=0, active outbox events=0, external tickets in mock=0
- **Duplicate external actions:** 0
- **Evidence (application log lines, redacted):**
  - `{"ts": "2026-11-11T19:33:12-0500", "level": "INFO", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "bee4672d-e6a5-468a-be5a-65e3af49d06b", "origin": "127.0.0.1:53635", "method": "GET", "outcome": "ok", "duration_ms": 14.1}`
  - `{"ts": "2026-11-11T19:33:12-0500", "level": "INFO", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "bee4672d-e6a5-468a-be5a-65e3af49d06b", "origin": "127.0.0.1:53635", "method": "GET", "outcome": "ok", "duration_ms": 13.5}`
  - `6 structured log line(s) captured during this scenario`

## REL-04: Additional: API process restart between approval and submission - PASS

*Recorded 2026-11-12T00:33:13.232092+00:00*

- **Initial state:** Ticket APPROVED with a durable outbox event
- **Injected fault:** The API process is restarted (a brand new application instance) before the worker submits; the worker is then started
- **Expected behavior:** No state is lost: the new instance sees the approved ticket; the worker submits exactly once; the audit trail is continuous
- **Actual behavior:** after restart ticket was APPROVED; worker ['submitted']; final SUBMITTED; audit events for the ticket=7
- **Recovery action:** none required: PostgreSQL is the authoritative state store and the outbox is durable
- **Final state:** ticket SUBMITTED as MNT-1014
- **Data-integrity result:** CONSISTENT: tickets=1, submitted=1 (all with external ids: True), approval rows=1 (a ticket with more than one: 0), unapproved tickets sent=0, active outbox events=0, external tickets in mock=1
- **Duplicate external actions:** 0
- **Evidence (application log lines, redacted):**
  - `{"ts": "2026-11-11T19:33:13-0500", "level": "INFO", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "4a0b30db-75d9-4934-8c7c-5d07015bd777", "origin": "127.0.0.1:53635", "method": "GET", "outcome": "ok", "duration_ms": 13.8}`
  - `{"ts": "2026-11-11T19:33:13-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "4a0b30db-75d9-4934-8c7c-5d07015bd777", "ticket_id": "30ff6d51-220e-4ac6-90b9-5980e001401a", "from_state": "DRAFT", "to_state": "PENDING_APPROVAL"`
  - `{"ts": "2026-11-11T19:33:13-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "4a0b30db-75d9-4934-8c7c-5d07015bd777", "ticket_id": "30ff6d51-220e-4ac6-90b9-5980e001401a", "from_state": "PENDING_APPROVAL", "to_state": "APPROV`
  - `{"ts": "2026-11-11T19:33:13-0500", "level": "INFO", "logger": "eaop.worker", "message": "submission.claimed", "event": "submission.claimed", "event_id": 22, "ticket_id": "30ff6d51-220e-4ac6-90b9-5980e001401a", "tenant_id": "4a0b30db-75d9-4934-8c7c-5d07015bd777"}`
  - `{"ts": "2026-11-11T19:33:13-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "4a0b30db-75d9-4934-8c7c-5d07015bd777", "ticket_id": "30ff6d51-220e-4ac6-90b9-5980e001401a", "from_state": "APPROVED", "to_state": "SUBMITTING", "`
  - `{"ts": "2026-11-11T19:33:13-0500", "level": "INFO", "logger": "eaop.connector", "message": "connector.call", "event": "connector.call", "tenant_id": "4a0b30db-75d9-4934-8c7c-5d07015bd777", "origin": "127.0.0.1:53638", "method": "POST", "outcome": "ok", "duration_ms": 15.3}`
  - `{"ts": "2026-11-11T19:33:13-0500", "level": "INFO", "logger": "eaop.workflow", "message": "ticket.transition", "event": "ticket.transition", "tenant_id": "4a0b30db-75d9-4934-8c7c-5d07015bd777", "ticket_id": "30ff6d51-220e-4ac6-90b9-5980e001401a", "from_state": "SUBMITTING", "to_state": "SUBMITTED", `
  - `{"ts": "2026-11-11T19:33:13-0500", "level": "INFO", "logger": "eaop.worker", "message": "submission.outcome", "event": "submission.outcome", "event_id": 22, "ticket_id": "30ff6d51-220e-4ac6-90b9-5980e001401a", "tenant_id": "4a0b30db-75d9-4934-8c7c-5d07015bd777", "outcome": "submitted", "duration_ms"`
  - `17 structured log line(s) captured during this scenario`
