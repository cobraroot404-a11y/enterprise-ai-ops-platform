# Cloud deployment portability (analysis only)

**No cloud resource was provisioned, no cloud credential was used, and no deployment was tested.** This document explains how the local platform could be adapted; it is design analysis, not evidence of a working cloud deployment. The Terraform files in [`infrastructure/terraform/`](../../infrastructure/terraform/README.md) are illustrative. They passed local formatting and [schema validation with AWS provider 5.100.0](../../evaluation/terraform/provider-validation.md).

## What must stay the same on any cloud
PostgreSQL 16 with pgvector and forced row-level security; separate owner (migrations), application and worker database roles; the worker as a separate process; local-or-private model inference (customer content must not be sent to a third-party AI service without a deliberate decision); environment-based secret names; the egress allow-list (the SSRF defence) enforced by the application and, ideally, by network policy too.

## Detailed illustrative blueprint: AWS
| Concern | Blueprint |
|---|---|
| Compute | The API and the worker as two ECS Fargate services (or two EC2 Auto Scaling groups) from one container image with different commands; migrations as a one-off task using the owner role. Images do not exist yet |
| Database | RDS for PostgreSQL 16 with the `pgvector` extension, Multi-AZ, encrypted, private subnets; three roles created by the migration task; backups via automated snapshots plus a tested restore |
| Storage | Retained originals stay in PostgreSQL in this design; moving them to S3 (with checksums and a reconciliation job) is an option that gives up atomic commit with the job |
| Networking | VPC with private subnets for tasks and database, public subnets only for the load balancer; security groups allow only ALB to API and tasks to database; NAT with an egress proxy or VPC endpoints so connectors reach only the approved origins; the webhook receiver reachable only through the ALB with WAF rate rules |
| Identity | IAM task roles with least privilege; application users keep the platform's own JWT/RBAC (no federation is built); a federation or SSO integration would be new work |
| Secrets | AWS Secrets Manager injected as the environment variables the connectors name (`secret_ref`); webhook signing secrets rotated using the overlap mechanism |
| Observability | JSON logs to CloudWatch; the platform's counters are process-local and need exporting (OpenTelemetry is not implemented); alarms on readiness, queue depth (`ingestion_jobs`, outbox) and error rates |
| Scaling | API and worker replicas scale horizontally only after distributed rate limiting replaces the process-local limiters; the database is the scaling limit (read replicas do not help writes) |
| Availability | Multi-AZ database, at least two API tasks; the worker is safe to run in several replicas (jobs use fenced leases, claims use `SKIP LOCKED`) |
| Security | Encryption at rest and in transit, private database, WAF in front of the receiver, KMS keys, CloudTrail, independent security review and penetration testing (none performed) |
| Cost | Not estimated here; the dominant items would be the database and any GPU or hosted inference. The platform's target is zero cost locally |

## Comparison: Azure and Google Cloud
| Concern | Azure | Google Cloud |
|---|---|---|
| Compute | Azure Container Apps or AKS | Cloud Run (API) and a Cloud Run job or GKE for the worker |
| Database | Azure Database for PostgreSQL Flexible Server (pgvector supported) | Cloud SQL for PostgreSQL or AlloyDB (pgvector supported) |
| Networking | VNet, Application Gateway with WAF, private endpoints | VPC, Cloud Armor, serverless VPC access / Private Service Connect |
| Identity and secrets | Managed identities, Key Vault | Workload identity, Secret Manager |
| Observability | Azure Monitor / Log Analytics | Cloud Logging and Monitoring |
Each follows the same pattern as AWS; the same constraints apply (pgvector, role separation, egress control, distributed rate limiting, secrets).

## Kubernetes
Optional and not built; see [deployment-tradeoffs.md](deployment-tradeoffs.md).

## Prerequisites before any cloud deployment
Container images built and tested for the target environment; managed secrets; distributed rate limiting; TLS and a gateway; a retention, backup and erasure policy (application deletion does not erase older backups); monitoring export; independent security review; explicit owner approval for cost and exposure.
