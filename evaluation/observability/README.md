# Observability evidence

Produced by `python -m pytest tests/acceptance/test_observability_evidence.py -q` from a real local run of the Apex end-to-end workflow (three tickets; a 503 and a lost response injected on the way). Nothing here is hand-written or fabricated, and none of it is production telemetry.

- `telemetry-summary.json` - what `GET /api/v1/observability/summary` returned to a read-only auditor of that tenant (process metrics scoped to the tenant plus durable database counts).
- `sample-logs.jsonl` - up to 60 structured log events from the run, after redaction (correlation ids, tenant ids, no credentials, tokens or document text; the test fails if any such pattern appears).
- `run-metadata.json` - command, time, event types seen.

Limits: process metrics reset on restart and cover the API process only; worker activity is durable through the database and logs. No OpenTelemetry/Prometheus export exists (optional in the specification).
