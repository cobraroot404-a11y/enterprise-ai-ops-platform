"""Shared concurrency limits (V41-16.04): the in-flight cap for inference and ingestion holds across API processes through PostgreSQL leases (migration 0016)."""
import subprocess
import sys
import threading
import time
import uuid

import pytest
from app.connectors.ratelimit import LIMITERS
from app.core.errors import AppError
from app.core.limits import ConcurrencyLimiter
from sqlalchemy import text


@pytest.fixture()
def shared(app_db):
    previous = LIMITERS.database
    LIMITERS.use_database(app_db)
    yield app_db
    LIMITERS.use_database(previous)


def limiter(limit=2, wait=0.1):
    return ConcurrencyLimiter("test", limit, wait, shared_key=f"test-{uuid.uuid4().hex[:10]}")


def test_two_independent_limiters_share_one_pool(shared):
    a = limiter(2)
    b = ConcurrencyLimiter("test", 2, 0.1, shared_key=a.shared_key)  # another process's limiter for the same pool
    first, second = a.slot(), b.slot()
    first.__enter__()
    second.__enter__()
    try:
        for who in (a, b):
            with pytest.raises(AppError) as busy, who.slot():
                pass
            assert busy.value.status_code == 429 and busy.value.code == "server_busy" and busy.value.retry_after
    finally:
        first.__exit__(None, None, None)
    with b.slot():  # a release by one process frees a slot for the other
        pass
    second.__exit__(None, None, None)


def test_threads_never_exceed_the_limit(shared):
    lim, live, peak, lock = limiter(3, wait=5.0), [0], [0], threading.Lock()

    def work():
        with lim.slot():
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            time.sleep(0.05)
            with lock:
                live[0] -= 1

    threads = [threading.Thread(target=work) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert peak[0] <= 3 and live[0] == 0


def test_separate_operating_system_processes_cannot_both_take_the_last_slot(settings, owner_engine):
    key = f"os-{uuid.uuid4().hex[:10]}"
    script = ("import sys\nfrom sqlalchemy import create_engine, text\ne = create_engine(sys.argv[1]); n = 0\n"
              "for _ in range(10):\n    with e.begin() as c:\n        if c.execute(text('SELECT concurrency_acquire(:k, 4, 60)'), {'k': sys.argv[2]}).scalar() is not None:\n            n += 1\nprint(n)\n")
    procs = [subprocess.Popen([sys.executable, "-I", "-c", script, settings.url("worker"), key], stdout=subprocess.PIPE, text=True) for _ in range(4)]
    granted = [int(p.communicate(timeout=60)[0].strip()) for p in procs]  # leases are never released here, so the total is capped
    assert sum(granted) == 4, granted
    with owner_engine.begin() as c:
        c.execute(text("DELETE FROM concurrency_leases WHERE slot_key = :k"), {"k": key})


def test_an_expired_lease_of_a_crashed_holder_frees_its_slot(shared, owner_engine):
    lim = limiter(1)
    with owner_engine.begin() as c:  # a holder that vanished without releasing, with a lease that has already expired
        c.execute(text("INSERT INTO concurrency_leases (slot_key, expires_at) VALUES (:k, clock_timestamp() - interval '1 second')"), {"k": lim.shared_key})
    with lim.slot():
        pass
    with owner_engine.begin() as c:  # and a live one blocks
        c.execute(text("INSERT INTO concurrency_leases (slot_key, expires_at) VALUES (:k, clock_timestamp() + interval '60 seconds')"), {"k": lim.shared_key})
    with pytest.raises(AppError), lim.slot():
        pass
    with owner_engine.begin() as c:
        c.execute(text("DELETE FROM concurrency_leases WHERE slot_key = :k"), {"k": lim.shared_key})


def test_a_failing_request_still_releases_its_lease(shared, owner_engine):
    lim = limiter(1)
    with pytest.raises(RuntimeError), lim.slot():
        raise RuntimeError("boom")
    with owner_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM concurrency_leases WHERE slot_key = :k"), {"k": lim.shared_key}).scalar() == 0
    with lim.slot():
        pass


def test_with_the_database_down_the_per_process_cap_still_applies(app_db):
    from sqlalchemy.exc import OperationalError

    class Dead:
        def session(self, *a, **k):
            raise OperationalError("SELECT 1", {}, Exception("refused"))

    previous = LIMITERS.database
    LIMITERS.use_database(Dead())
    try:
        lim = limiter(2)
        with lim.slot(), lim.slot():
            with pytest.raises(AppError) as busy, lim.slot():
                pass
            assert busy.value.code == "server_busy"
    finally:
        LIMITERS.use_database(previous)


def test_the_api_reports_busy_when_other_processes_hold_every_inference_slot(client, apex, shared, owner_engine):
    from support import login

    eng = login(client, apex, "support_engineer")
    n = client.app.state.limiters["inference"].limit
    with owner_engine.begin() as c:
        ids = [c.execute(text("SELECT concurrency_acquire('inference', :n, 60)"), {"n": n}).scalar() for _ in range(n)]
    try:
        assert all(ids)
        busy = client.post("/api/v1/ai/ask", headers=eng, json={"question": "What should I check for pump P-101 vibration?"})
        assert busy.status_code == 429 and busy.json()["error"]["code"] == "server_busy" and busy.headers["Retry-After"]
    finally:
        with owner_engine.begin() as c:
            c.execute(text("DELETE FROM concurrency_leases WHERE lease_id = ANY(CAST(:i AS uuid[]))"), {"i": [str(i) for i in ids if i]})
    assert client.post("/api/v1/ai/ask", headers=eng, json={"question": "What should I check for pump P-101 vibration?"}).status_code == 200
