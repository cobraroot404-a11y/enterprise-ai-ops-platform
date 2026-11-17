# Batch 11B report: CSV connector and signed inbound webhooks (with the post-11A follow-ups)

Executed under the standing autonomous-execution authorisation (no stop between batches). Local only; nothing pushed, merged, deployed, published or released; no remote, no cost, no download. Shared `eaop` database untouched (still `0006`).

## 1. Post-11A follow-ups (reviewed before extending the connector)
**A. HTTP semantics of `POST /connectors/{id}/sync`.** Reviewed and kept with reasons recorded in [rest-ingestion.md](../architecture/rest-ingestion.md): the operation has no body, so 400/422 cannot arise from it; a stored connector whose configuration is invalid or whose destination the server does not approve is a conflict between the request and the target resource's state (409, `invalid_connector_config`, `connector_destination_not_allowed`); the same conditions at save time are 422 (the bad value is in the body); runtime failures are job codes, not HTTP errors of the accepted request. The operation is new, so no contract was broken.
**B. Deleted-source resurrection (fixed).** Batch 11A recreated a document when a changed upstream record followed a deletion. That reversed an explicit customer decision. Now a deleted record is a permanent tombstone: unchanged is `skipped_deleted`, **changed is `tombstoned_changed`** (not stored, not embedded, no document); the source identity row is preserved. No restore action exists and none is required by the specification text; if automatic re-import were ever wanted it would need an explicit owner policy and a restore operation (documented, not built). Tests (REST, CSV, webhook) and the live checkpoint cover it.

## 2. What was built
* **CSV connector** (kind `csv`, `config.csv`): one CSV file fetched over HTTP by the existing connector client (raw mode), parsed deterministically and boundedly (UTF-8 only, NUL refused, header rules, malformed rows rejected and counted, row/cell/byte limits, `synced_truncated`), one document per row through the REST pipeline; row number stored beside the stable record id; cell text never evaluated.
* **Signed webhooks:** endpoint management (`POST/GET/PATCH /webhook-endpoints`, tenant administrator; secret held only as an environment-variable name; rotation with an overlap window; disable) and the receiver `POST /webhooks/{endpoint_id}` (HMAC-SHA256 over `timestamp.delivery_id.raw_body`, constant-time, bounded timestamp window checked only after the signature, durable atomic replay ledger, 256 KiB streaming limit, content-type and schema validation, per-endpoint rate limit, 202 only after one transaction stored the ledger row, the raw body and the durable job). Tenant comes only from the endpoint id through one narrow `SECURITY DEFINER` lookup function.
* **Processing:** webhook jobs reuse `ingestion_jobs`, the worker, retained originals, per-record idempotency, provenance and tombstones (`connector_sync_records` now serves endpoints too).
* **Migration 0013** (additive), mock CSV endpoint, live checkpoint extension, documentation ([webhooks-and-csv.md](../architecture/webhooks-and-csv.md)).

## 3. Security decisions worth reviewing
Pre-authentication lookup is the only RLS-adjacent exception: `webhook_endpoints` has RLS enabled (not forced) so the owner-run function can resolve one id; it returns no secret, cannot enumerate, and execute is granted only to the application role (tested, including that the worker cannot call it). Signature failures are not audited (anonymous audit flooding) but counted and logged; authenticated outcomes are audited without content. All authentication failures are one indistinguishable 401. A server missing the signing variable fails closed (503). The ledger is append-only for the application. The receiver is not exposed publicly by anything in the repository.

## 4. Tests and evidence
| Check | Result |
|---|---|
| `pytest backend/tests` | **739 passed, 18 skipped, 0 failed** (11A ended at 685; +54) |
| new | `test_webhooks.py` 20, `test_csv_connector.py` 27, `test_migration_0013_webhooks_and_csv.py` 6; updated REST, contract and namespace suites |
| contract suites (error, schemas, baseline, namespace, snapshot) | pass after the reviewed additions; two V41-17.03 property tests gained one explicit documented exception for the signed receiver (signature authentication, raw signed body) |
| live (`smoke --rest --no-browser --backup`) | `20261113-140424-3fb1` PASSED: REST 20 checks and CSV/webhook 24 checks per tenant, 88 in total |
| `pytest tests` (root) | 118 passed, 1 skipped (first run: 1 failure, the secret scan flagged a literal wrong-secret string in the checkpoint script; replaced by a random value, re-run clean) |
| secret scan | 0 findings in 968 files |
| ruff | 8 findings, all pre-existing, none in changed files |
Honest history of this batch's live runs (all kept): `20261113-140117-6fb8` failed (a connection reset while my oversize-body probe was still sending: the server legitimately closes; the check now accepts 413 or a server-closed connection); `20261113-140239-f80a` failed at the backup proof (queued rotation deliveries were still being processed by the worker during the snapshot: a harness race, fixed by waiting for them); `20261113-140424-3fb1` passed. Simulated faults are controlled injections, not real outages; adversarial deliveries are deliberate negative tests.

## 5. Requirement assessment (recorded for owner review; same-author evidence)
V41-12.01 (five source types) and V41-11.01 (six connector types): **assessed VERIFIED for the local scope**, with limits recorded (API only; REST reading is the owner-approved interpretation; webhook is an inbound endpoint; local mocks only). V41-11.02: stays **PARTIAL** (rate limiter process-local, V41-16.04 stays Partial; pagination, rate limiting and live probe are not applied to the older ticketing, inventory, CRM and fleet clients). Unchanged: V41-12.03/04/05 and V41-17.03 VERIFIED; V41-14.02 and V41-23.04 PARTIAL; REL-01 open.

## 6. Limits and open items
No UI for connectors or webhooks; no ledger purge; per-process rate limits; one signature scheme; CSV pulls one file per sync; same-author evidence. Open from before: V41-14.02 formal acceptance, REL-01, Phase 8 AI-quality targets (citation correctness 89.8% held-out vs 95%, grounded coverage 59.3%, raw structured validity 90% held-out), distributed rate limiting, deployment and infrastructure deliverables, documentation and handover set, independent reproduction.

## 7. Reproduction
```
python -m pytest backend/tests -q
python -m pytest tests -q
python scripts/demo.py smoke --rest --no-browser --backup
python scripts/api_quality_report.py
python scripts/generate_v41_reconciliation.py
python scripts/secret_scan.py
```
Evidence: `evaluation/demo-runs/20261113-140424-3fb1/` (pass) and the two failed runs above, `evaluation/api-quality/api-quality-evidence.json`, `backend/tests/snapshots/openapi_contract.json`.
