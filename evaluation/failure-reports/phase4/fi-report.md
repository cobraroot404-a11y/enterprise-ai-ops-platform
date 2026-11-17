# Fault-injection report (Phase 4)

Generated 2026-11-11T23:43:35.105662+00:00 by `python -m pytest tests/fault_injection -q (set RUN_DISRUPTIVE=1 for FI-10)`.
Deterministic test-only AI backends; local mock services; isolated test database.

**11 of 11 scenarios passed.**

## FI-01: HTTP 503 outage - PASS

*Recorded 2026-11-11T23:42:03.141518+00:00*

- **Initial state:** Ticket APPROVED with a pending outbox event; mock ticketing healthy
- **Injected fault:** Mock ticketing fails the next 2 request(s) with '503'
- **Expected behavior:** Worker classifies the error as transient, retries with backoff, never duplicates, ends SUBMITTED
- **Actual behavior:** worker outcomes ['retry_scheduled', 'retry_scheduled', 'submitted']; attempts=3; external requests=3
- **Recovery action:** automatic exponential-backoff retries via the transactional outbox
- **Final state:** ticket SUBMITTED with external id MNT-1001; 1 external ticket(s) exist

## FI-02: HTTP 429 rate limiting - PASS

*Recorded 2026-11-11T23:42:04.025583+00:00*

- **Initial state:** Ticket APPROVED with a pending outbox event; mock ticketing healthy
- **Injected fault:** Mock ticketing fails the next 2 request(s) with '429'
- **Expected behavior:** Worker classifies the error as transient, retries with backoff, never duplicates, ends SUBMITTED
- **Actual behavior:** worker outcomes ['retry_scheduled', 'retry_scheduled', 'submitted']; attempts=3; external requests=3
- **Recovery action:** automatic exponential-backoff retries via the transactional outbox
- **Final state:** ticket SUBMITTED with external id MNT-1002; 1 external ticket(s) exist

## FI-03: Network timeout - PASS

*Recorded 2026-11-11T23:42:04.860129+00:00*

- **Initial state:** Ticket APPROVED with a pending outbox event; mock ticketing healthy
- **Injected fault:** Mock ticketing fails the next 1 request(s) with 'timeout'
- **Expected behavior:** Worker classifies the error as transient, retries with backoff, never duplicates, ends SUBMITTED
- **Actual behavior:** worker outcomes ['retry_scheduled', 'submitted']; attempts=2; external requests=2
- **Recovery action:** automatic exponential-backoff retries via the transactional outbox
- **Final state:** ticket SUBMITTED with external id MNT-1003; 1 external ticket(s) exist

## FI-04: Malformed API response - PASS

*Recorded 2026-11-11T23:42:06.023998+00:00*

- **Initial state:** Ticket APPROVED with a pending outbox event; mock ticketing healthy
- **Injected fault:** Mock ticketing fails the next 1 request(s) with 'malformed'
- **Expected behavior:** Worker classifies the error as transient, retries with backoff, never duplicates, ends SUBMITTED
- **Actual behavior:** worker outcomes ['retry_scheduled', 'submitted']; attempts=2; external requests=2
- **Recovery action:** automatic exponential-backoff retries via the transactional outbox
- **Final state:** ticket SUBMITTED with external id MNT-1004; 1 external ticket(s) exist

## FI-05: Unauthorized cross-tenant access - PASS

*Recorded 2026-11-11T23:42:06.751445+00:00*

- **Initial state:** Tenant A has a pending ticket, incident, documents
- **Injected fault:** Tenant B's most privileged users attempt 40+ reads/writes/actions on A's resources (all namespaces)
- **Expected behavior:** Every attempt denied or hidden; zero successful cross-tenant accesses; A's data unchanged
- **Actual behavior:** 40 cross-tenant attempts, 0 succeeded; vector search leaked 0 chunks
- **Recovery action:** none needed (requests rejected)
- **Final state:** ticket still PENDING_APPROVAL

## FI-06: Concurrent approvals - PASS

*Recorded 2026-11-11T23:42:08.228002+00:00*

- **Initial state:** Ticket PENDING_APPROVAL
- **Injected fault:** 8 supervisors approve the same ticket at the same instant
- **Expected behavior:** Exactly one decision wins (200); the rest conflict (409); one approval row; one external ticket
- **Actual behavior:** status codes [200, 409, 409, 409, 409, 409, 409, 409]; approval rows=1; worker ['submitted']
- **Recovery action:** row lock + unique approval constraint serialise decisions
- **Final state:** ticket SUBMITTED; 1 external ticket

## FI-07: Worker interruption - PASS

*Recorded 2026-11-11T23:42:09.033593+00:00*

- **Initial state:** Ticket APPROVED, pending outbox event
- **Injected fault:** Worker 'crashes' (a) right after claiming the event and (b) after marking the ticket SUBMITTING
- **Expected behavior:** Lease expiry lets another worker resume; idempotency key prevents duplicates; ends SUBMITTED once
- **Actual behavior:** after crash (a): ['submitted']; after crash (b): ['submitted']; external tickets=2
- **Recovery action:** event lease expired; second worker re-claimed and completed safely
- **Final state:** tickets SUBMITTED / SUBMITTED

## FI-08: Prompt injection via documents - PASS

*Recorded 2026-11-11T23:42:09.878649+00:00*

- **Initial state:** Tenant has documents; no tickets
- **Injected fault:** A poisoned manual page and a poisoned incident-history row instruct the assistant to approve and submit tickets and ignore its rules
- **Expected behavior:** Poisoned passages are quarantined (excluded from context); no ticket or approval is created; the queue stays empty
- **Actual behavior:** quarantined passages=2; poisoned incident in related=False; tickets=0; outbox events=0
- **Recovery action:** none needed: untrusted text is data and never authorizes actions
- **Final state:** no ticket, no approval, nothing submitted

## FI-09: Duplicate ingestion - PASS

*Recorded 2026-11-11T23:42:10.528619+00:00*

- **Initial state:** Tenant has never seen this file
- **Injected fault:** The same file is uploaded 3 times sequentially, then by 6 threads at once under different names
- **Expected behavior:** Exactly one document version and one set of chunks; every other upload reports 'duplicate'; no 5xx
- **Actual behavior:** sequential ['created', 'duplicate', 'duplicate']; concurrent [(201, 'created'), (201, 'duplicate'), (201, 'duplicate'), (201, 'duplicate'), (201, 'duplicate'), (201, 'duplicate')]; indexed copies of the concurrent file=1
- **Recovery action:** content-hash uniqueness; losing concurrent writers resolve to the existing document
- **Final state:** one version of each file

## FI-09b: Duplicate ingestion: forced check-then-insert race - PASS

*Recorded 2026-11-11T23:42:11.136205+00:00*

- **Initial state:** Writer 1 has passed its duplicate check for new content
- **Injected fault:** Writer 2 commits the same content before writer 1 inserts (unique constraint collision)
- **Expected behavior:** Writer 1 resolves to 'duplicate' of writer 2's document: no error, no second copy
- **Actual behavior:** loser result: duplicate; winner: created; stored versions=1
- **Recovery action:** IntegrityError caught, transaction rolled back, duplicate lookup returned the winner
- **Final state:** exactly one stored copy

## FI-10: Database interruption - PASS

*Recorded 2026-11-11T22:14:37.913767+00:00*

- **Initial state:** Ticket APPROVED with a durable pending outbox event
- **Injected fault:** PostgreSQL is stopped while the API and worker are active, then restarted
- **Expected behavior:** API returns 503 (not 500); worker makes no external call and loses no state; after restart the pool recovers and the ticket is submitted exactly once
- **Actual behavior:** during outage: API 503 database_unavailable; worker raised OperationalError; external requests=0. After restart: API 200; worker ['submitted']
- **Recovery action:** PostgreSQL restarted; pooled connections re-validated (pre-ping); outbox event replayed
- **Final state:** ticket SUBMITTED; 1 external ticket
