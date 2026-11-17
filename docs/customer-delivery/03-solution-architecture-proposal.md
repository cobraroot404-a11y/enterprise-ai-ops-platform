# 3. Solution architecture proposal

Proposal for the two fictional customers; it describes the system as built and run locally. Detailed design: [../architecture/system-architecture.md](../architecture/system-architecture.md), diagrams in [../architecture/diagrams.md](../architecture/diagrams.md).

## Shape
A **modular monolith**: one FastAPI service (`backend/app`) with a separate worker process (outbox, ingestion jobs, document cleanup), PostgreSQL 16 with pgvector, a React/TypeScript front end, and per-customer mock external systems. AI is local: Ollama (`qwen2.5:1.5b`) for generation and Sentence Transformers MiniLM for embeddings; deterministic test-only backends exist and are labelled as such.

## How a request flows
1. A user signs in; the token names the tenant, the role is re-checked in the database on every request.
2. Every database session sets the tenant, and PostgreSQL row-level security (forced) restricts each table to that tenant.
3. Documents are ingested (upload, REST pull, CSV pull or signed webhook) through durable jobs; the original is retained, parsed, chunked and embedded; a generation is activated atomically.
4. Questions use hybrid retrieval (vector plus full text) with tenant filtering, citation verification and an explicit insufficient-evidence outcome.
5. Incident extraction produces a validated structure. Numeric readings from free text are **unverified candidates**; only signed simulation fixtures or a supervisor's explicit verification make a reading eligible to affect priority (priority is computed by server rules, never by the model).
6. A ticket is drafted, submitted for approval by a different person, approved, and written to the outbox in the same transaction; the worker submits it idempotently to the customer's ticketing system and stores the external id.

## Customer differences are configuration
Meridian differs from Apex only by tenant profile, connector configuration and field mapping (service-desk contract, priorities, enrichments), created through the public API.

## Why this shape
One deployable unit is the simplest thing that satisfies the isolation, transaction and audit requirements on a workstation; the worker and the database queue keep slow work off the request path; local inference keeps customer content on the machine. Trade-offs are recorded in [09-architecture-tradeoff-record.md](09-architecture-tradeoff-record.md).

## Not proposed here
Cloud deployment (portability analysis only: [../architecture/cloud-portability.md](../architecture/cloud-portability.md)), distributed rate limiting, and any production hosting.
