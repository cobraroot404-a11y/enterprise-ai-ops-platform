"""V41-04.06 (do not sacrifice working core functionality for optional technology): the optional operational layers (shared limiter store, durable metrics, spans, Prometheus endpoint) can fail
or be absent and the core workflow (ask, extract, ticket, approval, submission) still completes. Each failure is simulated at the layer's own boundary."""
import logging

import pytest
from app.connectors.ratelimit import LIMITERS
from app.observability import metrics as metrics_module
from app.observability.metrics import METRICS
from app.workflows import worker
from sqlalchemy.exc import OperationalError
from support import REPORT, login


class Dead:
    def session(self, *a, **k):
        raise OperationalError("SELECT 1", {}, Exception("refused"))


def core_workflow(client, tenant, worker_db):
    eng, sup = login(client, tenant, "support_engineer"), login(client, tenant, "maintenance_supervisor")
    ask = client.post("/api/v1/ai/ask", headers=eng, json={"question": "What should I check for pump P-101 vibration?"})
    inc = client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": REPORT})
    ticket = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc.json()["id"]}).json()
    client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=eng)
    decided = client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers=sup, json={"decision": "approved", "comment": "ok"})
    outcomes = worker.drain(worker_db)
    final = client.get(f"/api/v1/tickets/{ticket['id']}", headers=eng).json()
    return ask.status_code, inc.status_code, decided.status_code, outcomes, final["state"]


def test_the_core_workflow_completes_with_the_shared_limiter_store_and_durable_metrics_down(client, apex_loaded, worker_db, app_db):
    previous = LIMITERS.database
    LIMITERS.use_database(Dead())  # every limiter falls back to process-local buckets
    try:
        assert METRICS.flush(Dead()) in (-1, 0)  # a metrics flush against a dead database returns instead of raising
        result = core_workflow(client, apex_loaded, worker_db)
    finally:
        LIMITERS.use_database(previous)
    assert result == (200, 201, 200, ["submitted"], "SUBMITTED")


def test_the_core_workflow_completes_when_the_metrics_flusher_thread_is_pointed_at_a_dead_database(client, apex_loaded, worker_db, app_db):
    metrics_module.stop_flusher()
    try:
        metrics_module.start_flusher(Dead(), 0.1)
        result = core_workflow(client, apex_loaded, worker_db)
    finally:
        metrics_module.stop_flusher()
        metrics_module.start_flusher(app_db, 10.0)
    assert result == (200, 201, 200, ["submitted"], "SUBMITTED")


def test_the_core_workflow_completes_when_logging_and_spans_cannot_write(client, apex_loaded, worker_db):
    class Broken(logging.Handler):
        def emit(self, record):  # what every standard handler does when its sink fails: report through handleError, never raise into the caller
            try:
                raise OSError("log sink unavailable")
            except OSError:
                self.handleError(record)

    logger, handler = logging.getLogger("eaop"), Broken()
    logger.addHandler(handler)
    previous = logging.raiseExceptions
    logging.raiseExceptions = False  # the standard library's own contract: a failing handler never propagates into the caller
    try:
        result = core_workflow(client, apex_loaded, worker_db)
    finally:
        logger.removeHandler(handler)
        logging.raiseExceptions = previous
    assert result == (200, 201, 200, ["submitted"], "SUBMITTED")


def test_a_failing_prometheus_endpoint_does_not_affect_the_core(client, apex_loaded, worker_db, monkeypatch):
    def boom(self, db):
        raise RuntimeError("metrics store exploded")

    monkeypatch.setattr(type(METRICS), "flush", boom)
    with pytest.raises(RuntimeError):
        METRICS.flush(None)  # the optional endpoint's own call would fail...
    lenient = type(client)(client.app, raise_server_exceptions=False)
    assert lenient.get("/metrics", headers=login(client, apex_loaded, "tenant_admin")).status_code == 500
    assert core_workflow(client, apex_loaded, worker_db) == (200, 201, 200, ["submitted"], "SUBMITTED")  # ...and the workflow does not depend on it
