# Integrations catalogue

Every external system in this repository is a **local mock** standing in for a fictional customer's system. The platform's side of each integration is real code with real HTTP; nothing here was run against a real customer system. Contracts and payload examples: [integration specification](../customer-delivery/04-integration-specification.md).

## Outbound (the platform calls the system)
| Integration | Connector kind | Mock (port) | Used for | Authentication | Tenant-specific behaviour lives in |
|---|---|---|---|---|---|
| Maintenance ticketing (Apex) | `ticketing` | `mock-services/ticketing` (8101) | submitting approved tickets | `X-API-Key` from the environment variable named by `secret_ref` | connector `config` (`create_path`, `id_field`, `payload_map`, `priority_map`) |
| Spare-parts inventory (Apex) | `inventory` | `mock-services/inventory` (8102) | read-only enrichment of incidents | none in the mock | tenant profile enrichments |
| Fleet telematics (Meridian) | `fleet` | `mock-services/fleet` (8103) | read-only enrichment | none in the mock | tenant profile enrichments |
| CRM (Meridian) | `crm` | `mock-services/crm` (8104) | read-only enrichment | none in the mock | tenant profile enrichments |
| Service desk, work orders (Meridian) | `ticketing` | `mock-services/servicedesk` (8105) | submitting approved tickets under a different contract | `X-API-Key` by `secret_ref` | connector `config` |
| REST records source | `rest` | `mock-services/records` (8106) | pull ingestion with cursor, offset or page pagination | `X-API-Key` by `secret_ref` | connector `config.records` ([design](../architecture/rest-ingestion.md)) |
| CSV file source | `csv` | `mock-services/records` (8106) | pull ingestion of a bounded UTF-8 CSV file with row provenance | `X-API-Key` by `secret_ref` | connector `config.csv` ([design](../architecture/webhooks-and-csv.md)) |

## Inbound (the system calls the platform)
| Integration | Endpoint | Authentication | Guarantees |
|---|---|---|---|
| Signed webhooks | `POST /api/v1/webhooks/{endpoint_id}` | HMAC-SHA256 over `timestamp.delivery_id.raw_body`, constant-time comparison, timestamp window checked only after the signature, secret rotation with an overlap | tenant taken only from the unguessable endpoint id; durable replay ledger; 256 KiB limit; 202 means durably queued, not processed ([design](../architecture/webhooks-and-csv.md)) |

## What every outbound call gets, whichever integration
- Destination control: a server-side egress allow-list, addresses pinned after validation, no redirects, link-local and metadata addresses refused ([connector egress](../security/connector-egress.md)).
- Timeouts, bounded retries with exponential backoff, and error classification (transient, permanent, malformed) in `backend/app/connectors/http.py`.
- Rate limiting shared across processes, honouring upstream `Retry-After` ([limits](../security/rate-limiting-limitations.md)).
- Idempotency: an idempotency key on ticket submission; content hashes and per-record state for pulls; the delivery ledger for webhooks.
- A trace id (`traceparent`) and structured log events without payloads or credentials ([observability](../operations/observability.md)).
- Secrets referenced by environment-variable **name** only; never stored, returned or logged.

## Health
`GET /api/v1/connectors/health` reports configuration and recent outcomes; `?probe=true` performs a bounded live probe for REST and CSV connectors. Webhook endpoints have no upstream to probe: their health is configuration and recent deliveries. The Integration Health page shows both.

## Failure behaviour that was exercised
All mocks accept injected failures (503, 429 with `Retry-After`, timeouts, malformed bodies, responses lost after the side effect). Results: [fault-injection results](../reliability/fault-injection-results.md), the 11-case recovery suite and the 14-run integration success suite in [measured performance](../performance/measured-performance.md).

## Adding an integration for a new customer
Configuration, not code, when the system fits an existing connector kind: create the connector through `POST /api/v1/connectors` with its `config` and `secret_ref`, add its origin to the egress allow-list, and reference it from the tenant profile if it enriches incidents ([onboarding](../customer-onboarding/README.md)). A system with a different interaction pattern needs a new connector kind (code).

Limits: mocks only; no OAuth or mutual TLS; pagination applies to the REST source (the older mock APIs do not paginate); webhook receiver not exposed publicly.
