"""Durable operational metrics (V41-22.01): flushed additively to PostgreSQL, summed across processes, surviving restarts, exposed in Prometheus text format, tenant-isolated.

Two independent registries stand in for separate API and worker processes. Database failures are simulated with a store that raises OperationalError."""
import re
import time
import uuid

import pytest
from app.observability import metrics as metrics_module
from app.observability.metrics import METRICS, Registry, read_durable, render_prometheus
from app.workflows import worker
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from support import REPORT, TICKETING_KEY, login


def durable(owner_engine, name: str, **labels) -> float:
    """Sum of the durable series called `name` whose labels contain all of `labels`."""
    with owner_engine.connect() as c:
        rows = c.execute(text("SELECT labels, value FROM metric_series WHERE name = :n"), {"n": name}).all()
    return sum(v for lb, v in rows if all(str(lb.get(k)) == str(x) for k, x in labels.items()))


class DeadDatabase:
    def session(self, *args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


def tenant_label() -> str:
    return str(uuid.uuid4())


# ------------------------------------------------------------------------------------------------------------------- flushing semantics
def test_flush_writes_deltas_once_and_is_a_no_op_when_nothing_changed(app_db, owner_engine):
    registry, tenant = Registry(), tenant_label()
    registry.incr("unit_events_total", 3, tenant=tenant, kind="a")
    registry.observe("unit_seconds", 0.2, tenant=tenant)
    registry.observe("unit_seconds", 3.0, tenant=tenant)
    assert registry.flush(app_db) > 0
    assert durable(owner_engine, "unit_events_total", tenant=tenant) == 3
    assert durable(owner_engine, "unit_seconds_count", tenant=tenant) == 2
    assert abs(durable(owner_engine, "unit_seconds_sum", tenant=tenant) - 3.2) < 1e-6
    assert registry.flush(app_db) == 0  # nothing new: nothing written, nothing double counted
    registry.incr("unit_events_total", 2, tenant=tenant, kind="a")
    registry.flush(app_db)
    assert durable(owner_engine, "unit_events_total", tenant=tenant) == 5


def test_two_processes_and_a_restart_add_up(app_db, worker_db, owner_engine):
    tenant = tenant_label()
    api, worker_process = Registry(), Registry()
    api.incr("unit_shared_total", 4, tenant=tenant)
    worker_process.incr("unit_shared_total", 6, tenant=tenant)
    api.flush(app_db)
    worker_process.flush(worker_db)
    assert durable(owner_engine, "unit_shared_total", tenant=tenant) == 10  # series from different processes sum
    restarted = Registry()  # a restart: a fresh in-memory registry
    restarted.incr("unit_shared_total", 1, tenant=tenant)
    restarted.flush(app_db)
    assert durable(owner_engine, "unit_shared_total", tenant=tenant) == 11  # earlier flushed values were not lost
    assert restarted.snapshot()["counters"][0]["value"] == 1  # the in-process view still starts at zero, as documented


def test_a_failed_flush_keeps_its_deltas_and_the_retry_counts_them_exactly_once(app_db, owner_engine):
    registry, tenant = Registry(), tenant_label()
    registry.incr("unit_retry_total", 7, tenant=tenant)
    registry.observe("unit_retry_seconds", 1.5, tenant=tenant)
    assert registry.flush(DeadDatabase()) == -1
    assert durable(owner_engine, "unit_retry_total", tenant=tenant) == 0
    registry.incr("unit_retry_total", 1, tenant=tenant)  # activity during the outage
    assert registry.flush(app_db) > 0
    assert durable(owner_engine, "unit_retry_total", tenant=tenant) == 8
    assert durable(owner_engine, "unit_retry_seconds_count", tenant=tenant) == 1
    assert registry.flush(app_db) == 0


def test_concurrent_flushes_in_one_process_never_double_count(app_db, owner_engine):
    import threading

    registry, tenant = Registry(), tenant_label()
    registry.incr("unit_concurrent_total", 100, tenant=tenant)
    threads = [threading.Thread(target=registry.flush, args=(app_db,)) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert durable(owner_engine, "unit_concurrent_total", tenant=tenant) == 100


def test_the_background_flusher_writes_without_being_asked(app_db, owner_engine):
    tenant = tenant_label()
    metrics_module.stop_flusher()
    try:
        metrics_module.start_flusher(app_db, 0.2)
        METRICS.incr("unit_background_total", 5, tenant=tenant)
        deadline = time.time() + 5
        while time.time() < deadline and durable(owner_engine, "unit_background_total", tenant=tenant) < 5:
            time.sleep(0.1)
        assert durable(owner_engine, "unit_background_total", tenant=tenant) == 5
    finally:
        metrics_module.stop_flusher()
        metrics_module.start_flusher(app_db, 10.0)


# ------------------------------------------------------------------------------------------------------------------- database-level safety
def test_the_database_functions_are_monotonic_and_the_table_is_not_directly_reachable(app_db, worker_db):
    for db in (app_db, worker_db):
        with db.session() as s, pytest.raises(Exception, match="non-negative"):
            s.execute(text("SELECT metric_add(:k, 'unit_bad_total', '{}'::jsonb, NULL, -1)"), {"k": "0" * 64})
        with db.session() as s, pytest.raises(ProgrammingError):
            s.execute(text("UPDATE metric_series SET value = 0"))
        with db.session() as s, pytest.raises(ProgrammingError):
            s.execute(text("SELECT * FROM metric_series"))
    with app_db.session() as s, pytest.raises(Exception, match="series_key"):
        s.execute(text("SELECT metric_add('not-a-hash', 'unit_bad_total', '{}'::jsonb, NULL, 1)"))


def test_read_returns_one_tenant_plus_platform_series_and_everything_only_when_asked(app_db):
    a, b = tenant_label(), tenant_label()
    registry = Registry()
    registry.incr("unit_scope_total", 1, tenant=a)
    registry.incr("unit_scope_total", 2, tenant=b)
    registry.incr("unit_scope_platform_total", 3)
    registry.flush(app_db)
    with app_db.session() as s:
        mine = {(r["name"], r["labels"].get("tenant")) for r in read_durable(s, a)}
        everything = {(r["name"], r["labels"].get("tenant")) for r in read_durable(s, a, everything=True)}
    assert ("unit_scope_total", a) in mine and ("unit_scope_total", b) not in mine and ("unit_scope_platform_total", None) in mine
    assert ("unit_scope_total", b) in everything


# ------------------------------------------------------------------------------------------------------------------- the Prometheus endpoint
def test_prometheus_endpoint_requires_a_token_and_a_permitted_role(client, apex):
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    assert client.get("/metrics", headers=login(client, apex, "support_engineer")).status_code == 200  # every tenant role holds metrics:read
    assert client.get("/openapi.json").json()["paths"].get("/metrics") is None  # outside the typed JSON contract
    ok = client.get("/metrics", headers=login(client, apex, "tenant_admin"))
    assert ok.status_code == 200 and ok.headers["content-type"].startswith("text/plain; version=0.0.4")


def test_the_endpoint_shows_a_tenants_own_series_cumulative_histograms_and_never_another_tenants(client, apex, owner_engine):
    from support import make_tenant

    other = make_tenant(owner_engine, "apex", "http://127.0.0.1:9", "http://127.0.0.1:9")
    for env in (apex, other):
        client.post("/api/v1/ai/ask", headers=login(client, env, "support_engineer"), json={"question": "What should I check for pump P-101 vibration?"})
    mine = client.get("/metrics", headers=login(client, apex, "tenant_admin")).text
    assert apex.id in mine and other.id not in mine
    assert "# TYPE eaop_http_request_seconds histogram" in mine and "eaop_ai_answers_total" in mine
    def labels_of(line: str) -> dict:
        return dict(re.findall(r'(\w+)="([^"]*)"', line.split("{", 1)[1].rsplit("}", 1)[0]))

    groups: dict[tuple, list[tuple[str, float]]] = {}
    counts: dict[tuple, float] = {}
    for line in mine.splitlines():
        if 'route="/ai/ask"' not in line:
            continue
        labels = labels_of(line)
        value = float(line.rsplit(" ", 1)[1])
        if line.startswith("eaop_http_request_seconds_bucket"):
            groups.setdefault(tuple(sorted((k, v) for k, v in labels.items() if k != "le")), []).append((labels["le"], value))
        elif line.startswith("eaop_http_request_seconds_count"):
            counts[tuple(sorted(labels.items()))] = value
    assert groups, "no /ai/ask histogram in the output"
    for labels, buckets in groups.items():  # each label set (method, route, status class) is its own histogram
        values = [v for _, v in buckets]
        assert values == sorted(values) and buckets[-1][0] == "+Inf"  # cumulative, monotonic, ending at +Inf
        assert buckets[-1][1] == counts[labels] >= 1


def test_label_values_are_escaped_in_the_text_format():
    text_out = render_prometheus([{"name": "unit_total", "labels": {"note": 'a"b\\c\nd'}, "value": 1.0}])
    assert 'note="a\\"b\\\\c\\nd"' in text_out and text_out.endswith("\n")


# ------------------------------------------------------------------------------------------------------------------- the metrics the specification lists
def test_every_listed_metric_family_is_recorded_durably_for_a_real_workflow(client, apex_loaded, worker_db, ticketing, owner_engine, app_db):
    tenant = apex_loaded.id
    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")

    def approved():
        inc = client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": REPORT}).json()
        tid = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()["id"]
        client.post(f"/api/v1/tickets/{tid}/request-approval", headers=eng)
        assert client.post(f"/api/v1/approvals/{tid}/decision", headers=sup, json={"decision": "approved", "comment": "ok"}).status_code == 200
        return tid

    approved()
    assert worker.drain(worker_db) == ["submitted"]
    import httpx

    httpx.post(f"{ticketing.url}/admin/failure", json={"mode": "400", "count": 1}, headers={"X-API-Key": TICKETING_KEY})
    approved()
    worker.drain(worker_db)  # a permanent error: the event is a dead letter
    METRICS.flush(app_db)
    families = {
        "request latency": "http_request_seconds_count", "retrieval latency": "retrieval_seconds_count", "inference duration": "llm_seconds_count",
        "ingestion duration": "ingestion_seconds_count", "workflow completion time": "workflow_completion_seconds_count",
        "approval turnaround time": "approval_turnaround_seconds_count", "external API calls": "connector_calls_total", "dead-letter counts": "dead_letters_total",
    }
    missing = {label: name for label, name in families.items() if durable(owner_engine, name, tenant=tenant) <= 0 and name != "http_request_seconds_count"}
    assert missing == {}, missing
    assert durable(owner_engine, "http_request_seconds_count") > 0  # request latency carries route labels, not a tenant label
