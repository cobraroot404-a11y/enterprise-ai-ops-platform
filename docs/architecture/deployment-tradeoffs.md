# Deployment tradeoffs

Nothing here has been deployed beyond a developer workstation. This document compares options so that a future deployment decision is informed; it makes no claim that any option was tried.

## Monolith or microservices
| | Modular monolith + worker (built) | Microservices (not built) |
|---|---|---|
| Consistency | One database transaction covers approval, outbox and audit | Needs sagas or an outbox per service and cross-service idempotency |
| Isolation | One forced-RLS database model, one place to test it | Isolation must be re-proved in every service and database |
| Operation | One image plus a worker; runs on a laptop | Many deployables, service discovery, tracing, contract tests |
| Scaling | Scale API and worker replicas together; the database is the limit | Independent scaling of ingestion, retrieval and workflow |
| Fit now | Two fictional tenants, one machine | Justified by team size or load that does not exist here |

## Compute and data choices
| Question | Local choice | Cloud-shaped alternative | Tradeoff |
|---|---|---|---|
| Database | PostgreSQL 16 + pgvector | Managed PostgreSQL with pgvector (RDS/Aurora, Azure Database for PostgreSQL, Cloud SQL, AlloyDB) | Keeps RLS and the schema unchanged; adds cost and a network hop; the database owner/superuser assumptions in the tests need review |
| Queue | Database tables polled by workers | SQS/Service Bus/Pub-Sub or a stream | Lower coupling and throughput; loses single-transaction enqueue unless an outbox is kept |
| Originals | `bytea` in PostgreSQL | Object storage with checksums | Cheaper at scale; loses atomic commit with the job and needs orphan handling |
| AI | Local CPU models | Hosted or GPU inference | Better latency/quality; data leaves the machine and costs money |
| Rate limiting | Process-local | Gateway or Redis | Required before more than one API replica |
| Secrets | Environment variables named by connectors | Secrets manager | Required before shared deployment |

## Kubernetes
Optional and not built: a Deployment each for API and worker, a Job for migrations, secrets from the platform's secret store. The worker's database role and the migration owner role must stay separate.

## Recommendation
Keep the modular monolith. Before any shared deployment add: container images, distributed rate limiting, managed secrets, TLS and a gateway in front of the webhook receiver, a retention and backup policy, and independent security review. See [cloud-portability.md](cloud-portability.md).
