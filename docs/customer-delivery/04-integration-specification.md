# 4. Integration specification

All external systems are **local mocks**; this specification describes the contracts the platform implements and tests against them. Credentials are never stored in the database: connector rows hold the **name** of a server environment variable. Destinations must be on the server's per-tenant egress allow-list (tenants cannot widen it); redirects are never followed.

## Outbound
| Integration | Contract | Behaviour |
|---|---|---|
| Ticketing (Apex, port 8101) | `POST /tickets` with `Idempotency-Key`; response `ticket_id` | Submitted by the worker after approval; retries with exponential backoff; exactly one ticket per approved ticket; failures retried then marked failed with a retry operation for supervisors |
| Service desk (Meridian, 8105) | Own path, field names and priority values (connector configuration `payload_map`, `priority_map`, `create_path`, `id_field`) | Same worker, same idempotency and audit |
| Inventory (8102), Fleet/telematics (8103), CRM (8104) | `GET` lookups | Used as enrichments; failures degrade gracefully and are recorded |

## Inbound and pull (Batches 11A and 11B)
| Source | How | Notes |
|---|---|---|
| REST records | Connector kind `rest`, `config.records`; `POST /connectors/{id}/sync` | Cursor, offset or page pagination with hard bounds; connector-scoped rate limit (process-local) and `Retry-After`; API key from `secret_ref`; one document per record keyed by the source record id |
| CSV file | Connector kind `csv`, `config.csv`; same sync operation | UTF-8 only, bounded rows, bytes and cells; malformed rows rejected and counted; row number and record id as provenance |
| Signed webhook | Tenant administrator provisions `POST /webhook-endpoints`; the sender posts to `/api/v1/webhooks/{endpoint_id}` | See below |
| Document upload | `POST /documents` (synchronous contract unchanged) | PDF, CSV, JSON, text; duplicate detection by content hash |

### Webhook delivery protocol
Headers: `Content-Type: application/json`, `X-Webhook-Delivery-Id` (8 to 64 characters of `A-Z a-z 0-9 . _ : -`, unique per delivery), `X-Webhook-Timestamp` (Unix seconds), `X-Webhook-Signature: sha256=<hex>` where `<hex>` is HMAC-SHA256, keyed with the endpoint's shared secret, over the bytes `"<timestamp>.<delivery id>."` followed by the **raw request body**. Python sender example:

```python
import hashlib, hmac, json, time, urllib.request
body = json.dumps({"id": "REC-1", "title": "Pump note", "body": "Seal weeps under load."}).encode()
ts, delivery_id = str(int(time.time())), "delivery-0001"
sig = "sha256=" + hmac.new(SECRET.encode(), f"{ts}.{delivery_id}.".encode() + body, hashlib.sha256).hexdigest()
req = urllib.request.Request(URL, data=body, method="POST", headers={"Content-Type": "application/json", "X-Webhook-Timestamp": ts, "X-Webhook-Delivery-Id": delivery_id, "X-Webhook-Signature": sig})
```
Responses: `202` queued (not yet processed; follow the returned `job_id`), `401 invalid_signature` (every authentication failure looks the same), `401 timestamp_out_of_window` (more than 300 s from the server clock, only reported to a valid signer), `409 webhook_replayed` (the delivery id was already received), `413` (over 256 KiB), `415` (not JSON), `422 invalid_payload`, `429` (rate limit, `Retry-After`), `503 webhook_not_configured`. A sender must use a new delivery id for each new delivery and for a corrected payload; retrying after a 5xx is safe because nothing is committed on a 5xx. Secret rotation: the administrator names a new variable; both secrets are accepted until the old one is dropped.

Payload shape per endpoint configuration: one record object, a list of record objects, or an object holding the list under `record_path`; each record needs the configured `id_field` (never invented) and `required_fields`.

## Processing guarantees (all inbound and pull sources)
Per-record idempotency by content hash and source record id (unchanged skipped, changed becomes a new version); a record the customer deleted stays deleted even if the source changes it; originals retained and checksum-verified; transient failures retried with bounded backoff; success recorded only after processing completes; audit without content or credentials.
Full designs: [../architecture/rest-ingestion.md](../architecture/rest-ingestion.md), [../architecture/webhooks-and-csv.md](../architecture/webhooks-and-csv.md), [../architecture/ingestion-jobs.md](../architecture/ingestion-jobs.md).
