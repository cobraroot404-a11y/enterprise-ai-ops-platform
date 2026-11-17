"""Observability: structured logs, correlation ids, tenant-aware metrics, error classification, and log hygiene."""
import json
import logging

import httpx
import pytest
from app.observability.logging import JsonFormatter, redact_value
from app.workflows import worker
from sqlalchemy import text
from support import PASSWORD, REPORT, TICKETING_KEY, login


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.lines: list[dict] = []
        self.raw: list[str] = []

    def emit(self, record):
        line = self.format(record)
        self.raw.append(line)
        self.lines.append(json.loads(line))


@pytest.fixture()
def logs():
    handler, logger = Capture(), logging.getLogger("eaop")
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.INFO)
    yield handler
    logger.removeHandler(handler)
    logger.setLevel(previous)


def summary(client, tenant, role="tenant_admin"):
    return client.get("/api/v1/observability/summary", headers=login(client, tenant, role))


def series(snapshot, which, name, **labels):
    pool = snapshot["process"]["counters" if which == "counter" else "timers"]
    return [s for s in pool if s["name"] == name and all(s["labels"].get(k) == v for k, v in labels.items())]


# ---- redaction ----------------------------------------------------------------------------------------------------------------
def test_formatter_redacts_credentials_in_fields_messages_and_nested_values():
    record = logging.LogRecord("eaop.test", logging.INFO, "f", 1, "login with password=hunter2-secret and Bearer abcdefghijklmnop", (), None)
    record.__dict__.update({"password": "hunter2", "api_key": "k-123456789", "Authorization": "Bearer zzzzzzzzzzzz",
                            "details": {"token": "t-123456789", "ok": "fine", "text": "x-api-key: abcdefgh12345"},
                            "jwt_in_value": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk"})
    line = JsonFormatter().format(record)
    for secret in ("hunter2", "k-123456789", "zzzzzzzzzzzz", "t-123456789", "abcdefgh12345", "eyJhbGciOiJIUzI1NiJ9", "abcdefghijklmnop"):
        assert secret not in line
    assert json.loads(line)["details"]["ok"] == "fine" and "[REDACTED" in line


def test_long_values_are_truncated_so_documents_cannot_be_dumped_into_logs():
    assert len(redact_value("x" * 5000)) < 600


# ---- logs of a complete workflow contain no secrets, tokens, documents or user text -----------------------------------------------
def test_workflow_logs_are_structured_correlated_and_free_of_sensitive_content(client, apex_loaded, worker_db, ticketing, logs):
    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    inc = client.post("/api/v1/incidents/extract", headers={**eng, "X-Correlation-ID": "corr-test-123"}, json={"report_text": REPORT}).json()
    ask = client.post("/api/v1/ai/ask", headers=eng, json={"question": "What should I check when pump P-101 shows abnormal vibration?"}).json()
    ticket = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()
    client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=eng)
    client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers=sup, json={"decision": "approved", "comment": "private reviewer comment"})
    assert worker.drain(worker_db) == ["submitted"]
    assert ask["grounded"]

    blob = "\n".join(logs.raw)
    token = eng["Authorization"].split(" ", 1)[1]
    forbidden = [PASSWORD, token, TICKETING_KEY, "drive-end bearing", "grinding noise", "private reviewer comment",
                 "Replace the drive-end bearing set", "P-101 shows abnormal vibration"]
    leaked = [f for f in forbidden if f in blob]
    assert leaked == [], leaked
    requests = [ln for ln in logs.lines if ln.get("message") == "request"]
    assert requests and all(r.get("correlation_id") and r.get("route") for r in requests)
    assert any(r["correlation_id"] == "corr-test-123" and r["route"] == "/incidents/extract" for r in requests)
    assert all("?" not in r["path"] for r in requests)
    events = {ln.get("event") for ln in logs.lines if ln.get("event")}
    assert {"ticket.transition", "submission.claimed", "submission.outcome", "connector.call"} <= events
    transition = [ln for ln in logs.lines if ln.get("event") == "ticket.transition"]
    assert {(t["from_state"], t["to_state"]) for t in transition} >= {("DRAFT", "PENDING_APPROVAL"), ("PENDING_APPROVAL", "APPROVED"),
                                                                        ("APPROVED", "SUBMITTING"), ("SUBMITTING", "SUBMITTED")}
    outcome = next(ln for ln in logs.lines if ln.get("event") == "submission.outcome")
    assert outcome["outcome"] == "submitted" and outcome["tenant_id"] == apex_loaded.id and outcome["duration_ms"] >= 0
    call = next(ln for ln in logs.lines if ln.get("event") == "connector.call")
    assert call["outcome"] == "ok" and "/" not in call["origin"] and "tickets" not in json.dumps(call)  # origin only, never paths


def test_correlation_id_is_returned_and_generated(client, apex):
    echoed = client.get("/api/v1/health", headers={"X-Correlation-ID": "abc-123"})
    assert echoed.headers["X-Correlation-ID"] == "abc-123"
    assert client.get("/api/v1/health").headers["X-Correlation-ID"]


# ---- tenant-aware metrics ----------------------------------------------------------------------------------------------------------
def test_metrics_cover_latency_outcomes_reviews_and_transitions_per_tenant(client, apex_loaded, worker_db, ticketing, owner_engine):
    from support import make_tenant

    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    client.post("/api/v1/ai/ask", headers=eng, json={"question": "What should I check when pump P-101 shows abnormal vibration?"})
    client.post("/api/v1/ai/ask", headers=eng, json={"question": "What is the chief executive's favourite colour?"})
    inc = client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": REPORT}).json()
    unreg = client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": "Pump Z-777 shows vibration at 8.0 mm/s with noise."}).json()
    client.post(f"/api/v1/incidents/{unreg['id']}/review", headers=sup, json={"decision": "reject", "comment": "not a real asset"})
    ticket = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()
    client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=eng)
    client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers=sup, json={"decision": "approved"})
    assert worker.drain(worker_db) == ["submitted"]

    snap = summary(client, apex_loaded).json()
    t = apex_loaded.id
    assert series(snap, "timer", "retrieval_seconds", tenant=t)[0]["count"] >= 3
    assert series(snap, "timer", "embedding_seconds", tenant=t) and series(snap, "timer", "llm_seconds", tenant=t, kind="answer")
    assert series(snap, "timer", "llm_seconds", tenant=t, kind="extract")[0]["p95_s"] >= 0
    assert series(snap, "counter", "ai_answers_total", tenant=t, outcome="grounded")[0]["value"] >= 1  # extraction also asks for guidance
    assert series(snap, "counter", "ai_answers_total", tenant=t, outcome="insufficient_evidence")[0]["value"] >= 1
    assert series(snap, "counter", "incidents_extracted_total", tenant=t, review_status="pending_review")[0]["value"] == 1
    assert series(snap, "counter", "incidents_extracted_total", tenant=t, review_status="needs_review")[0]["value"] == 1
    assert series(snap, "counter", "incident_reviews_total", tenant=t, decision="reject")[0]["value"] == 1
    assert series(snap, "counter", "connector_calls_total", tenant=t, outcome="ok")[0]["value"] >= 1
    assert series(snap, "counter", "submission_outcomes_total", tenant=t, outcome="submitted")[0]["value"] == 1
    assert series(snap, "counter", "ticket_transitions_total", tenant=t, from_state="SUBMITTING", to_state="SUBMITTED")
    db = snap["database"]
    assert db["submission"]["submitted"] == 1 and db["incident_review"]["extracted"] == 2
    assert db["incident_review"]["review_required_rate"] == 0.5 and db["incident_review"]["rejected"] == 1
    assert {(x["from"], x["to"]) for x in db["ticket_transitions"]} >= {("APPROVED", "SUBMITTING"), ("SUBMITTING", "SUBMITTED")}

    other = make_tenant(owner_engine, "obsother")  # another tenant sees none of this tenant's series or counts
    other_snap = summary(client, other).json()
    assert other_snap["process"]["counters"] == [] and other_snap["process"]["timers"] == []
    assert other_snap["database"]["submission"]["submitted"] == 0
    assert apex_loaded.id not in json.dumps(other_snap)


def test_metrics_never_contain_user_text_documents_or_credentials(client, apex_loaded):
    eng = login(client, apex_loaded, "support_engineer")
    client.post("/api/v1/ai/ask", headers=eng, json={"question": "secret question about drive-end bearing"})
    blob = json.dumps(summary(client, apex_loaded).json())
    assert "secret question" not in blob and "drive-end" not in blob and PASSWORD not in blob


def test_connector_failures_retries_and_denials_are_classified(client, apex_loaded, worker_db, ticketing, owner_engine):
    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    httpx.post(f"{ticketing.url}/admin/failure", json={"mode": "503", "count": 1}, headers={"X-API-Key": TICKETING_KEY})
    inc = client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": REPORT}).json()
    ticket = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()
    client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=eng)
    client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers=sup, json={"decision": "approved"})
    cfg = worker.WorkerConfig(backoff_base=0, backoff_cap=0)
    assert worker.process_one(worker_db, cfg) == "retry_scheduled"
    snap = summary(client, apex_loaded).json()
    t = apex_loaded.id
    assert series(snap, "counter", "connector_calls_total", tenant=t, outcome="transient")[0]["value"] == 1
    assert series(snap, "counter", "submission_retries_total", tenant=t)[0]["value"] == 1
    assert snap["database"]["submission"]["retries_scheduled"] == 1
    assert snap["database"]["ticket_error_classes"] == {"transient": 1}
    with owner_engine.begin() as conn:  # destination becomes unauthorized between attempts: classified as denied, nothing sent
        conn.execute(text("UPDATE connectors SET base_url = 'http://169.254.169.254' WHERE tenant_id = :t AND kind = 'ticketing'"), {"t": t})
    assert worker.drain(worker_db, cfg) == ["failed_permanent"]
    snap = summary(client, apex_loaded).json()
    assert series(snap, "counter", "connector_calls_total", tenant=t, outcome="denied")[0]["value"] == 1
    assert snap["database"]["submission"]["dead_lettered"] == 1 and snap["database"]["ticket_error_classes"] == {"permanent": 1}


def test_api_errors_are_classified_without_leaking_detail(client, apex):
    from app.observability.metrics import METRICS

    METRICS.reset()
    assert client.get("/api/v1/tickets").status_code == 401
    assert client.post("/api/v1/ai/ask", headers=login(client, apex, "support_engineer"), json={"question": "x"}).status_code == 422
    names = {(c["name"], c["labels"].get("error")) for c in METRICS.snapshot()["counters"]}
    assert ("errors_total", "validation_error") in names and any(n == "errors_total" for n, _ in names)
    timers = {tuple(sorted(t["labels"].items())) for t in METRICS.snapshot()["timers"] if t["name"] == "http_request_seconds"}
    assert all("tickets/" not in dict(t).get("route", "") or "{" in dict(t)["route"] for t in timers)  # route templates, never raw ids


# ---- trace ids (V41-22.01): one id across the API request, the outbox event, the worker run and the connector call ---------------------
TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"


def test_trace_id_follows_a_ticket_from_the_api_through_the_outbox_to_the_connector_call(client, apex_loaded, worker_db, ticketing, logs):
    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    inc = client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": REPORT}).json()
    ticket = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()
    client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=eng)
    decided = client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers={**sup, "traceparent": f"00-{TRACE}-00f067aa0ba902b7-01"},
                          json={"decision": "approved", "comment": "ok"})
    assert decided.status_code == 200 and decided.headers["X-Trace-ID"] == TRACE
    assert worker.drain(worker_db) == ["submitted"]
    by_event = {ln.get("event"): ln for ln in logs.lines if ln.get("event") in ("submission.claimed", "submission.outcome", "connector.call")}
    assert by_event["submission.outcome"]["trace_id"] == TRACE and by_event["connector.call"]["trace_id"] == TRACE
    request_line = next(ln for ln in logs.lines if ln.get("message") == "request" and ln["route"] == "/approvals/{ticket_id}/decision")
    assert request_line["trace_id"] == TRACE


def test_trace_id_is_derived_from_the_correlation_id_and_invalid_traceparents_are_ignored(client, apex):
    from app.observability.tracing import parse_traceparent, trace_id_for

    echoed = client.get("/api/v1/health", headers={"X-Correlation-ID": "abc-123"})
    assert echoed.headers["X-Trace-ID"] == trace_id_for("abc-123") and len(echoed.headers["X-Trace-ID"]) == 32
    bad = client.get("/api/v1/health", headers={"traceparent": "00-" + "0" * 32 + "-00f067aa0ba902b7-01"})
    assert bad.headers["X-Trace-ID"] != "0" * 32
    assert parse_traceparent("garbage") is None and parse_traceparent(f"00-{TRACE}-00f067aa0ba902b7-01") == TRACE
    assert parse_traceparent(f"01-{TRACE}-00f067aa0ba902b7-01") is None  # only version 00 is understood
    assert trace_id_for(TRACE) == TRACE and trace_id_for(None) is None


def test_outbound_traceparent_is_well_formed_and_absent_outside_a_trace():
    from app.observability import tracing

    assert tracing.outbound_headers() == {}
    with tracing.use_trace(TRACE):
        header = tracing.outbound_headers()["traceparent"]
        assert tracing.parse_traceparent(header) == TRACE
    assert header.endswith("-01") and len(header.split("-")[2]) == 16
    assert tracing.current() is None  # restored after the block
