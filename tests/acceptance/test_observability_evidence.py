"""Generates reproducible observability evidence from a real local workflow run (no fabricated telemetry).

    python -m pytest tests/acceptance/test_observability_evidence.py -q

Runs the Apex end-to-end flow (503 and lost-response injections), then records the tenant-scoped telemetry summary the API
serves and the redacted structured log lines the run produced under evaluation/observability/. The numbers are whatever this
local test run produced; they are not production telemetry.
"""
import json
import logging
import platform
from datetime import datetime, timezone
from pathlib import Path

from app.observability.logging import JsonFormatter
from app.observability.metrics import METRICS
from support import REPORT, TICKETING_KEY, login

from tests.acceptance.test_end_to_end_reliability import _run

OUT = Path(__file__).resolve().parents[2] / "evaluation" / "observability"
FORBIDDEN = ("password", "bearer ", "eyJ", "X-API-Key", "test-ticketing-key")


class _Lines(logging.Handler):
    def __init__(self):
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(self.format(record))


def test_generate_observability_evidence(uat_client, apex_uat, ticketing, worker_db, owner_engine, uat_mode):
    METRICS.reset()
    handler = _Lines()
    root = logging.getLogger("eaop")
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        mocks = {"url": ticketing.url, "key": TICKETING_KEY, "state": ticketing.state}
        done = _run(uat_client, apex_uat, REPORT, "What should I check when pump P-101 shows abnormal vibration?", mocks, worker_db,
                    owner_engine, failures=[None, "503", "lost_response"])
        summary = uat_client.get("/api/v1/observability/summary", headers=login(uat_client, apex_uat, "read_only_auditor"))
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
    assert summary.status_code == 200 and len(done) == 3
    body = summary.json()
    parsed = []
    for line in handler.lines:
        try:
            parsed.append(json.loads(line))
        except ValueError:
            continue
    events = sorted({p.get("event") or p.get("message") for p in parsed})
    text = "\n".join(handler.lines)
    leaked = [f for f in FORBIDDEN if f.lower() in text.lower()]
    assert not leaked, f"sensitive values appeared in logs: {leaked}"  # reported by pattern name only
    for needed in ("connector.call", "submission.outcome", "ticket.transition"):
        assert needed in events, (needed, events)
    OUT.mkdir(parents=True, exist_ok=True)
    keep = [line for line in handler.lines if '"event"' in line][:60]
    (OUT / "sample-logs.jsonl").write_text("\n".join(keep) + "\n", encoding="utf-8", newline="\n")
    (OUT / "telemetry-summary.json").write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    meta = {"generated_utc": datetime.now(timezone.utc).isoformat(),
            "command": "python -m pytest tests/acceptance/test_observability_evidence.py -q",
            "mode": uat_mode, "python": platform.python_version(), "log_lines_captured": len(handler.lines),
            "event_types": events, "workflow": "Apex end-to-end with injected 503 and lost-response failures (3 tickets)",
            "labelling": "Local test-run telemetry; not production measurements."}
    (OUT / "run-metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n")
    (OUT / "README.md").write_text(
        "# Observability evidence\n\n"
        "Produced by `python -m pytest tests/acceptance/test_observability_evidence.py -q` from a real local run of the Apex "
        "end-to-end workflow (three tickets; a 503 and a lost response injected on the way). Nothing here is hand-written or "
        "fabricated, and none of it is production telemetry.\n\n"
        "- `telemetry-summary.json` - what `GET /api/v1/observability/summary` returned to a read-only auditor of that tenant "
        "(process metrics scoped to the tenant plus durable database counts).\n"
        "- `sample-logs.jsonl` - up to 60 structured log events from the run, after redaction (correlation ids, tenant ids, "
        "no credentials, tokens or document text; the test fails if any such pattern appears).\n"
        "- `run-metadata.json` - command, time, event types seen.\n\n"
        "Limits: process metrics reset on restart and cover the API process only; worker activity is durable through the database "
        "and logs. No OpenTelemetry/Prometheus export exists (optional in the specification).\n", encoding="utf-8", newline="\n")
