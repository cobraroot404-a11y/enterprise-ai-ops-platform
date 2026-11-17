# Architecture diagrams

Mermaid diagrams of the system as built (renders on GitHub and in most Markdown viewers). They describe the local platform; no cloud deployment exists. States and names are taken from the code (`app/workflows/state_machine.py`, `app/ingestion/jobs.py`, `app/ingestion/webhooks.py`).

## 1. System context
```mermaid
flowchart LR
  U[Engineers, supervisors, administrators, auditors] -->|JWT, role per tenant| API[FastAPI API :8000]
  UI[React UI :5173] --> API
  API --> DB[(PostgreSQL 16 + pgvector<br/>forced row-level security)]
  W[Worker process] --> DB
  API --> LLM[Ollama / MiniLM<br/>local inference]
  W -->|idempotent submit| TK[Ticketing mock :8101]
  W -->|idempotent submit| SD[Service desk mock :8105]
  W -->|pull, rate limited, SSRF allow-list| REC[Records mock :8106<br/>REST and CSV]
  API --> INV[Inventory :8102, Fleet :8103, CRM :8104 mocks]
  SENDER[Webhook sender] -->|HMAC-signed POST| API
```

## 2. Ingestion paths, one pipeline
```mermaid
flowchart TD
  A[Upload POST /documents] --> J[(ingestion_jobs<br/>durable, fenced lease)]
  B[REST or CSV sync<br/>POST /connectors/id/sync] --> J
  C[Signed webhook delivery] --> J
  J --> S[(document_sources<br/>original, checksum)]
  J --> WK[Worker]
  WK --> P[Parse, validate records]
  P --> E[Embed]
  E --> G[Stage new generation<br/>validate, activate atomically]
  G --> R[(chunks: tenant-filtered hybrid retrieval)]
  WK --> T[(connector_sync_records<br/>idempotency, provenance, tombstones)]
```

## 3. Webhook delivery (order of checks)
```mermaid
sequenceDiagram
  participant S as Sender
  participant A as API receiver
  participant D as Database
  participant W as Worker
  S->>A: POST /webhooks/{endpoint} body, timestamp, delivery id, signature
  A->>A: content type, size limit, rate bucket
  A->>D: webhook_endpoint_lookup(endpoint id) -> tenant, secret NAME
  A->>A: HMAC over timestamp.delivery_id.raw_body (constant time)
  A->>A: timestamp window (only after a valid signature)
  A->>A: payload shape and record count
  A->>D: ONE transaction: replay ledger (unique), original, job, audit
  A-->>S: 202 queued (not processed)
  W->>D: claim job, process records, complete
```

## 4. Ticket workflow state machine
```mermaid
stateDiagram-v2
  [*] --> DRAFT
  DRAFT --> PENDING_APPROVAL
  DRAFT --> CANCELLED
  PENDING_APPROVAL --> APPROVED
  PENDING_APPROVAL --> REJECTED
  PENDING_APPROVAL --> CANCELLED
  APPROVED --> SUBMITTING
  APPROVED --> CANCELLED
  SUBMITTING --> SUBMITTED
  SUBMITTING --> RETRY_PENDING
  SUBMITTING --> FAILED
  RETRY_PENDING --> SUBMITTING
  RETRY_PENDING --> FAILED
  FAILED --> RETRY_PENDING
  SUBMITTED --> [*]
  REJECTED --> [*]
  CANCELLED --> [*]
```
Submission is allowed only from APPROVED, RETRY_PENDING or SUBMITTING and the approval is re-verified from the approvals table, so a state value alone never authorises an external call.

## 5. Ingestion job states
```mermaid
stateDiagram-v2
  [*] --> QUEUED
  QUEUED --> PROCESSING
  QUEUED --> CANCELLED
  RETRY_PENDING --> PROCESSING
  RETRY_PENDING --> CANCELLED
  PROCESSING --> COMPLETED
  PROCESSING --> RETRY_PENDING
  PROCESSING --> FAILED
  PROCESSING --> CANCELLED
  FAILED --> QUEUED: manual retry
```

## 6. Tenant isolation
```mermaid
flowchart LR
  T[Token: user and tenant] --> M[Membership and role re-checked in the database]
  M --> SES[Session sets app.tenant_id]
  SES --> RLS[(Tenant row-level security with three documented FORCE exceptions)]
  RLS --> ONLY[Only this tenant's rows, even if an application filter is missing]
  WKR[Worker: claims jobs across tenants, but does all document work in a tenant-scoped session] --> RLS
```
