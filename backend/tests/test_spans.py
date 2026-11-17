"""Spans (V41-22.01, V41-22.02 partly): named, timed units of work inside a trace, written as structured log events with parent links. The OpenTelemetry data model, not the SDK."""
import json
import logging

import pytest
from app.observability import tracing
from app.workflows import worker
from support import REPORT, login
from test_observability import Capture

TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"


@pytest.fixture()
def spans():
    handler, logger = Capture(), logging.getLogger("eaop")
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.INFO)
    yield lambda: [ln for ln in handler.lines if ln.get("event") == "span"]
    logger.removeHandler(handler)
    logger.setLevel(previous)


def test_nested_spans_link_to_their_parent_record_status_and_duration_and_restore_context(spans):
    with tracing.use_trace(TRACE):
        with tracing.span("outer", kind="a") as attrs:
            with tracing.span("inner"):
                pass
            attrs["rows"] = 3
        with pytest.raises(ValueError), tracing.span("failing"):
            raise ValueError("boom")
        assert tracing.current_span() is None
    got = {s["span_name"]: s for s in spans()}
    assert got["inner"]["parent_span_id"] == got["outer"]["span_id"] and got["outer"]["parent_span_id"] is None
    assert got["outer"]["attr_rows"] == 3 and got["outer"]["attr_kind"] == "a" and got["outer"]["status"] == "ok" and got["outer"]["duration_ms"] >= 0
    assert got["failing"]["status"] == "error" and got["failing"]["attr_error_class"] == "ValueError"
    assert all(s["trace_id"] == TRACE and len(s["span_id"]) == 16 for s in got.values())


def test_no_span_is_emitted_without_a_trace_and_outbound_calls_name_the_current_span(spans):
    with tracing.span("untraced"):
        pass
    assert spans() == []
    with tracing.use_trace(TRACE), tracing.span("calling") as _:
        sid = tracing.current_span()
        assert tracing.parse_traceparent(tracing.outbound_headers()["traceparent"]) == TRACE
        assert tracing.outbound_headers()["traceparent"].split("-")[2] == sid  # the receiver's parent is this span


def test_a_ticket_produces_linked_request_connector_and_outbox_spans_in_one_trace(client, apex_loaded, worker_db, ticketing, spans):
    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    inc = client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": REPORT}).json()
    ticket = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()
    client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=eng)
    decided = client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers={**sup, "traceparent": f"00-{TRACE}-00f067aa0ba902b7-01"}, json={"decision": "approved", "comment": "ok"})
    assert decided.status_code == 200
    assert worker.drain(worker_db) == ["submitted"]
    in_trace = [s for s in spans() if s["trace_id"] == TRACE]
    names = [s["span_name"] for s in in_trace]
    assert {"http.request", "outbox.submission", "connector.call"} <= set(names), names
    outbox = next(s for s in in_trace if s["span_name"] == "outbox.submission")
    call = next(s for s in in_trace if s["span_name"] == "connector.call")
    assert call["parent_span_id"] == outbox["span_id"] and outbox["attr_outcome"] == "submitted"
    request = next(s for s in in_trace if s["span_name"] == "http.request")
    assert request["attr_route"] == "/approvals/{ticket_id}/decision" and request["attr_status"] == 200 and request["parent_span_id"] is None
    assert "report_text" not in json.dumps(in_trace) and REPORT[:30] not in json.dumps(in_trace)  # attributes are identifiers and numbers only
