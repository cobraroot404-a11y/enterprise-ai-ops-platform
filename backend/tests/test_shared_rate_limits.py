"""Distributed rate limiting (V41-11.02, V41-16.04): limits shared across processes through PostgreSQL.

Atomicity and sharing are tested with genuinely separate OS processes (fresh interpreters, own connections), with independent registries standing in for separate API and worker processes,
with many threads, across tenants, under bounded waits, upstream Retry-After pauses, and with the database unavailable (a fake store raising OperationalError)."""
import dataclasses
import subprocess
import sys
import threading
import time
import uuid

import pytest
from app.connectors import ratelimit
from app.connectors.ratelimit import LIMITERS, RateLimited, RateLimiters
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from support import login


def key(label: str = "t") -> str:
    return f"test:{label}:{uuid.uuid4().hex}"


@pytest.fixture()
def two_processes(settings, app_db, worker_db):
    """Two independent registries with their own database handles and roles: what an API process and a worker process each hold."""
    api, worker = RateLimiters(), RateLimiters()
    api.use_database(app_db)
    worker.use_database(worker_db)
    return api, worker


def grants(registry: RateLimiters, k: str, attempts: int, rate: float = 0.001, burst: int = 5) -> int:
    bucket = registry.get(k, "c", rate, burst)
    ok = 0
    for _ in range(attempts):
        try:
            bucket.acquire(0)
            ok += 1
        except RateLimited:
            pass
    return ok


# ------------------------------------------------------------------------------------------------------------- sharing and atomicity
def test_two_processes_draw_from_one_bucket(two_processes):
    api, worker = two_processes
    k = key()
    assert grants(api, k, 3) + grants(worker, k, 10) == 5  # burst 5 in total, not 5 per process
    assert grants(api, k, 3) == 0 and grants(worker, k, 3) == 0


def test_many_threads_across_both_processes_never_overspend(two_processes):
    api, worker = two_processes
    k = key()
    results, lock = [], threading.Lock()

    def run(registry):
        got = grants(registry, k, 25, burst=20)
        with lock:
            results.append(got)

    threads = [threading.Thread(target=run, args=(api if i % 2 else worker,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(results) == 20, results  # 200 attempts, burst 20, negligible refill: exactly 20 granted


def test_separate_operating_system_processes_share_the_limit(settings, owner_engine):
    k = key("os")
    url = settings.url("worker")
    script = (
        "import sys\n"
        "from sqlalchemy import create_engine, text\n"
        "e = create_engine(sys.argv[1]); granted = 0\n"
        "for _ in range(30):\n"
        "    with e.begin() as c:\n"
        "        if c.execute(text('SELECT rate_limit_take(:k, 0.001, 25)'), {'k': sys.argv[2]}).scalar() == 0:\n"
        "            granted += 1\n"
        "print(granted)\n")
    procs = [subprocess.Popen([sys.executable, "-I", "-c", script, url, k], stdout=subprocess.PIPE, text=True) for _ in range(4)]
    granted = [int(p.communicate(timeout=60)[0].strip()) for p in procs]
    assert all(p.returncode == 0 for p in procs) and sum(granted) == 25, granted  # 120 attempts from 4 interpreters, burst 25


def test_tokens_refill_over_time_from_the_database_clock(two_processes):
    api, _ = two_processes
    k = key()
    assert grants(api, k, 5, rate=2, burst=2) == 2  # a slow machine would need over half a second for these five calls to add a token
    time.sleep(1.4)  # 2 per second: two tokens, capped at the burst of two
    assert grants(api, k, 5, rate=2, burst=2) == 2


def test_a_bounded_wait_succeeds_when_short_and_raises_with_a_hint_when_long(two_processes):
    api, _ = two_processes
    k = key()
    bucket = api.get(k, "c", 4, 1)
    bucket.acquire(0)
    waited = bucket.acquire(2.0)  # 4 per second: about 0.25 s
    assert 0.1 < waited < 1.5
    slow = api.get(key(), "c", 0.5, 1)
    slow.acquire(0)
    started = time.monotonic()
    with pytest.raises(RateLimited) as caught:
        slow.acquire(0.3)
    assert time.monotonic() - started < 1.0 and 1.0 < caught.value.retry_after <= 2.1


def test_a_stop_event_ends_a_wait_at_once(two_processes):
    api, _ = two_processes
    bucket = api.get(key(), "c", 0.2, 1)
    bucket.acquire(0)
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()
    started = time.monotonic()
    with pytest.raises(RateLimited):
        bucket.acquire(20, stop)
    assert time.monotonic() - started < 2.0


def test_an_upstream_retry_after_pauses_every_process_but_only_that_bucket(two_processes):
    api, worker = two_processes
    k = key()
    api.get(k, "c", 100, 10).pause(2.0)
    with pytest.raises(RateLimited) as caught:
        worker.get(k, "c", 100, 10).acquire(0)  # another process sees the pause
    assert 0.5 < caught.value.retry_after <= 2.1
    assert grants(api, key(), 3, rate=100, burst=10) == 3  # other buckets are not affected
    api.get(k, "c", 100, 10).pause(1000)  # bounded: never longer than the 30 second cap
    with pytest.raises(RateLimited) as capped:
        worker.get(k, "c", 100, 10).acquire(0)
    assert capped.value.retry_after <= 30.1


# ------------------------------------------------------------------------------------------------------------- isolation and privileges
def test_tenants_do_not_share_buckets(two_processes):
    api, _ = two_processes
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    assert grants(api, tenant_a, 10, burst=3) == 3
    assert grants(api, tenant_b, 10, burst=3) == 3  # exhausting A leaves B untouched
    assert grants(api, tenant_a, 1, burst=3) == 0


def test_application_roles_cannot_touch_the_tables_directly_and_invalid_arguments_are_refused(app_db, worker_db):
    for db in (app_db, worker_db):
        for sql in ("SELECT * FROM rate_limit_state", "DELETE FROM rate_limit_state", "UPDATE rate_limit_state SET tokens = 1000",
                    "SELECT * FROM metric_series", "INSERT INTO metric_series (series_key, name) VALUES ('x', 'y')"):
            with db.session() as s, pytest.raises(ProgrammingError):
                s.execute(text(sql))
        for bad in ("rate_limit_take('', 1, 1, 1)", "rate_limit_take('k', 0, 1, 1)", "rate_limit_take('k', 1001, 1, 1)", "rate_limit_take('k', 1, 1001, 1)",
                    "rate_limit_take('k', 1, 5, 6)", "rate_limit_take('k', -1, 5, 1)"):
            with db.session() as s, pytest.raises(Exception, match="invalid rate limit arguments"):
                s.execute(text(f"SELECT {bad}"))
    with pytest.raises(ValueError):
        RateLimiters().get("t", "c", 0, 1)


def test_the_sweep_removes_only_idle_unpaused_buckets(owner_engine, app_db):
    idle, fresh, paused = key("idle"), key("fresh"), key("paused")
    store = ratelimit.SharedStore(app_db)
    for k in (idle, fresh, paused):
        store.take(k, 1, 1)
    store.pause(paused, 20)
    with owner_engine.begin() as c:
        c.execute(text("UPDATE rate_limit_state SET updated_at = now() - interval '2 hours' WHERE bucket_key IN (:a, :b)"), {"a": idle, "b": paused})
    store.sweep(3600)
    with owner_engine.connect() as c:
        left = {r[0] for r in c.execute(text("SELECT bucket_key FROM rate_limit_state WHERE bucket_key IN (:a, :b, :c)"), {"a": idle, "b": fresh, "c": paused})}
    assert left == {fresh, paused}


# ------------------------------------------------------------------------------------------------------------- database unavailable and recovery
class DeadDatabase:
    def session(self, *args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


def test_with_the_database_down_limits_still_apply_locally_and_recover_afterwards(app_db, monkeypatch):
    monkeypatch.setattr(ratelimit, "STORE_RETRY_SECONDS", 0.3)
    registry = RateLimiters()
    registry.use_database(DeadDatabase())
    k = key()
    started = time.monotonic()
    assert grants(registry, k, 20, burst=4) == 4  # never unlimited: the local bucket enforces the burst
    assert time.monotonic() - started < 2.0  # and the outage does not make every call slow
    registry.use_database(app_db)  # the database comes back (a new store is configured; buckets rebuild)
    assert grants(registry, k, 20, burst=4) == 4  # the shared bucket for this key was never touched during the outage
    registry2 = RateLimiters()
    registry2.use_database(DeadDatabase())
    registry2.store_failed()
    time.sleep(0.4)
    registry2.use_database(app_db)
    assert grants(registry2, key(), 20, burst=4) == 4  # shared again


def test_a_store_failure_is_counted(monkeypatch):
    from app.observability.metrics import METRICS

    registry = RateLimiters()
    registry.use_database(DeadDatabase())
    before = sum(c["value"] for c in METRICS.snapshot()["counters"] if c["name"] == "ratelimit_store_unavailable_total")
    registry.get("t", "c", 10, 2).acquire(0)
    after = sum(c["value"] for c in METRICS.snapshot()["counters"] if c["name"] == "ratelimit_store_unavailable_total")
    assert after == before + 1


# ------------------------------------------------------------------------------------------------------------- the application surfaces
def test_the_expensive_operations_are_limited_per_organisation_and_isolated(client, apex, owner_engine, settings):
    from support import make_tenant

    client.app.state.settings = dataclasses.replace(settings, api_rate_per_second=0.01, api_rate_burst=3)
    eng = login(client, apex, "support_engineer")
    codes = [client.post("/api/v1/ai/ask", headers=eng, json={"question": "What should I check for pump P-101 vibration?"}) for _ in range(5)]
    assert [r.status_code for r in codes[:3]] == [200, 200, 200]
    limited = codes[3]
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited" and int(limited.headers["Retry-After"]) >= 1
    assert limited.json()["error"]["correlation_id"] and "bucket" not in limited.text
    other = make_tenant(owner_engine, "apex", "http://127.0.0.1:9", "http://127.0.0.1:9")
    assert client.post("/api/v1/ai/ask", headers=login(client, other, "support_engineer"), json={"question": "What should I check for pump P-101 vibration?"}).status_code == 200
    assert client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": "Pump P-101 vibrates strongly."}).status_code in (201, 422)  # a different operation has its own bucket


def test_login_throttling_is_shared_so_it_survives_a_second_process(client, apex):
    from app.api.v1 import core_routes

    email = apex.users["support_engineer"]
    for _ in range(core_routes.MAX_FAILURES):
        assert client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password-123", "tenant": apex.slug}).status_code == 401
    blocked = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password-123", "tenant": apex.slug})
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "too_many_attempts"
    core_routes._failures.clear()  # a different API process has no local memory of these failures
    again = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password-123", "tenant": apex.slug})
    assert again.status_code == 429 and int(again.headers["Retry-After"]) >= 1
    LIMITERS.store.window_clear(f"login:{email.lower().strip()}")  # clean up so later tests can sign in
    core_routes._failures.clear()


def test_every_outbound_client_is_limited_not_only_the_new_connectors(records_server, monkeypatch):
    from app.connectors import http
    from app.connectors.http import ConnectorError, HttpConnector
    from support import RECORDS_KEY

    monkeypatch.setattr(http, "OUTBOUND_RATE", 0.5)
    monkeypatch.setattr(http, "OUTBOUND_BURST", 2)
    monkeypatch.setattr(http, "OUTBOUND_MAX_WAIT", 0.0)
    tenant = str(uuid.uuid4())
    connector = HttpConnector(records_server.url, api_key=RECORDS_KEY, timeout=3.0, tenant_slug="*", tenant_id=tenant)
    outcomes = []
    for _ in range(4):
        try:
            connector.request("GET", "/v1/apex/csv", raw=True)
            outcomes.append("ok")
        except ConnectorError as exc:
            outcomes.append(f"{exc.kind}:{'rate' if 'rate limit' in str(exc) else 'other'}")
    assert outcomes[:2] == ["ok", "ok"] and outcomes[2:] == ["transient:rate", "transient:rate"]  # a transient error: the caller retries later
