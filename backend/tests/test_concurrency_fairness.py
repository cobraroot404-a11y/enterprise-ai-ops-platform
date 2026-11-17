"""Shared concurrency limits, second part (V41-16.04): fairness between tenants, housekeeping, metrics, privileges, and migrations 0016 and 0017 in a disposable database."""
import uuid

import pytest
from app.connectors.ratelimit import LIMITERS, maintenance
from app.core.errors import AppError
from app.core.limits import ConcurrencyLimiter
from app.observability.metrics import METRICS
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError


class Dead:
    def session(self, *a, **k):
        raise OperationalError("SELECT 1", {}, Exception("refused"))


@pytest.fixture()
def shared(app_db):
    previous = LIMITERS.database
    LIMITERS.use_database(app_db)
    yield app_db
    LIMITERS.use_database(previous)


def pool(limit=3, wait=0.1) -> ConcurrencyLimiter:
    return ConcurrencyLimiter("test", limit, wait, shared_key=f"test-{uuid.uuid4().hex[:10]}")


def test_one_tenant_cannot_occupy_the_whole_pool_and_another_tenant_still_gets_a_slot(shared):
    lim = pool(3)
    assert lim.tenant_limit == 2  # default: all but one slot
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    first, second = lim.slot(tenant_a), lim.slot(tenant_a)
    first.__enter__()
    second.__enter__()
    try:
        with pytest.raises(AppError) as busy, lim.slot(tenant_a):
            pass
        assert busy.value.code == "server_busy" and busy.value.status_code == 429
        with lim.slot(tenant_b):  # the remaining slot is still available to another tenant
            with pytest.raises(AppError), lim.slot(tenant_b):  # and now the pool itself is full
                pass
    finally:
        first.__exit__(None, None, None)
        second.__exit__(None, None, None)
    with lim.slot(tenant_a), lim.slot(tenant_a):  # everything was released, including the tenant share leases
        pass


def test_a_single_slot_pool_and_an_explicit_tenant_limit_behave_as_configured(shared):
    assert pool(1).tenant_limit == 1
    lim = ConcurrencyLimiter("test", 4, 0.05, shared_key=f"test-{uuid.uuid4().hex[:10]}", tenant_limit=1)
    tenant = str(uuid.uuid4())
    with lim.slot(tenant):
        with pytest.raises(AppError), lim.slot(tenant):
            pass
        with lim.slot(str(uuid.uuid4())):
            pass
    assert ConcurrencyLimiter("test", 2, 0.05, tenant_limit=99).tenant_limit == 2  # never above the pool


def test_tenant_shares_are_separate_keys_and_every_lease_is_released(shared, owner_engine):
    lim = pool(3)
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    with lim.slot(tenant_a), lim.slot(tenant_b):
        with owner_engine.connect() as c:
            keys = sorted(r[0] for r in c.execute(text("SELECT slot_key FROM concurrency_leases WHERE slot_key LIKE :p"), {"p": lim.shared_key + "%"}))
        assert keys == sorted([lim.shared_key, lim.shared_key, f"{lim.shared_key}:tenant:{tenant_a}", f"{lim.shared_key}:tenant:{tenant_b}"])
    with owner_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM concurrency_leases WHERE slot_key LIKE :p"), {"p": lim.shared_key + "%"}).scalar() == 0


def test_a_rejected_request_does_not_leak_its_tenant_share_lease(shared, owner_engine):
    lim = pool(2)  # tenant share 1
    blocker_a, blocker_b, tenant = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    with lim.slot(blocker_a), lim.slot(blocker_b):
        with pytest.raises(AppError), lim.slot(tenant):  # takes its tenant share, then finds the pool full
            pass
        with owner_engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM concurrency_leases WHERE slot_key = :k"), {"k": f"{lim.shared_key}:tenant:{tenant}"}).scalar() == 0
    with lim.slot(tenant):
        pass


def test_the_per_process_fallback_keeps_both_caps():
    previous = LIMITERS.database
    LIMITERS.use_database(Dead())
    try:
        lim = pool(3, wait=0.05)
        tenant = str(uuid.uuid4())
        with lim.slot(tenant), lim.slot(tenant):
            with pytest.raises(AppError), lim.slot(tenant):  # the tenant share still applies without the database
                pass
            with lim.slot(str(uuid.uuid4())):
                with pytest.raises(AppError), lim.slot(str(uuid.uuid4())):  # and so does the pool cap
                    pass
        with lim.slot(tenant):
            pass
    finally:
        LIMITERS.use_database(previous)


def test_rejections_and_fallbacks_are_counted(shared):
    def count(name, **labels):
        return sum(c["value"] for c in METRICS.snapshot()["counters"] if c["name"] == name and all(c["labels"].get(k) == v for k, v in labels.items()))

    lim = pool(1)
    before = count("concurrency_rejected_total", pool=lim.shared_key, reason="pool_full")
    with lim.slot():
        with pytest.raises(AppError), lim.slot():
            pass
    assert count("concurrency_rejected_total", pool=lim.shared_key, reason="pool_full") == before + 1


def test_the_sweep_removes_expired_leases_and_idle_buckets_and_never_a_live_lease(shared, owner_engine):
    dead, live = f"sweep-dead-{uuid.uuid4().hex[:8]}", f"sweep-live-{uuid.uuid4().hex[:8]}"
    idle_bucket = f"test:idle:{uuid.uuid4().hex}"
    with owner_engine.begin() as c:
        c.execute(text("INSERT INTO concurrency_leases (slot_key, expires_at) VALUES (:d, clock_timestamp() - interval '5 seconds'), (:l, clock_timestamp() + interval '60 seconds')"),
                  {"d": dead, "l": live})
        c.execute(text("SELECT rate_limit_take(:k, 1, 1)"), {"k": idle_bucket})
        c.execute(text("UPDATE rate_limit_state SET updated_at = now() - interval '2 hours' WHERE bucket_key = :k"), {"k": idle_bucket})
    result = maintenance(shared)
    assert result["leases_removed"] >= 1 and result["buckets_removed"] >= 1 and "error" not in result
    with owner_engine.begin() as c:
        assert c.execute(text("SELECT count(*) FROM concurrency_leases WHERE slot_key = :d"), {"d": dead}).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM concurrency_leases WHERE slot_key = :l"), {"l": live}).scalar() == 1
        assert c.execute(text("SELECT count(*) FROM rate_limit_state WHERE bucket_key = :k"), {"k": idle_bucket}).scalar() == 0
        c.execute(text("DELETE FROM concurrency_leases WHERE slot_key = :l"), {"l": live})


def test_maintenance_reports_an_unreachable_database_instead_of_raising():
    assert "error" in maintenance(Dead())


def test_application_roles_cannot_touch_the_lease_table_and_invalid_arguments_are_refused(app_db, worker_db):
    for db in (app_db, worker_db):
        for sql in ("SELECT * FROM concurrency_leases", "DELETE FROM concurrency_leases", "INSERT INTO concurrency_leases (slot_key, expires_at) VALUES ('x', now())"):
            with db.session() as s, pytest.raises(ProgrammingError):
                s.execute(text(sql))
        for bad in ("concurrency_acquire('', 1, 60)", "concurrency_acquire('k', 0, 60)", "concurrency_acquire('k', 1001, 60)", "concurrency_acquire('k', 1, 0)", "concurrency_acquire('k', 1, 3601)"):
            with db.session() as s, pytest.raises(Exception, match="invalid concurrency arguments"):
                s.execute(text(f"SELECT {bad}"))


def test_the_api_applies_the_tenant_share_so_one_organisation_cannot_starve_another(client, apex, shared, owner_engine):
    from support import login, make_tenant

    limiter = client.app.state.limiters["inference"]
    if limiter.tenant_limit >= limiter.limit:
        pytest.skip("the configured pool has one slot: there is no separate tenant share")
    question = {"question": "What should I check for pump P-101 vibration?"}
    with owner_engine.begin() as c:  # another process is already serving this tenant's full share
        held = [c.execute(text("SELECT concurrency_acquire(:k, :n, 60)"), {"k": f"inference:tenant:{apex.id}", "n": limiter.tenant_limit}).scalar() for _ in range(limiter.tenant_limit)]
        assert all(held)
    try:
        busy = client.post("/api/v1/ai/ask", headers=login(client, apex, "support_engineer"), json=question)
        assert busy.status_code == 429 and busy.json()["error"]["code"] == "server_busy"
        other = make_tenant(owner_engine, "apex", "http://127.0.0.1:9", "http://127.0.0.1:9")
        assert client.post("/api/v1/ai/ask", headers=login(client, other, "support_engineer"), json=question).status_code == 200
    finally:
        with owner_engine.begin() as c:
            c.execute(text("DELETE FROM concurrency_leases WHERE slot_key = :k"), {"k": f"inference:tenant:{apex.id}"})


def test_migrations_0015_to_0017_upgrade_downgrade_and_the_whole_chain_from_empty(settings):
    from alembic import command
    from alembic.config import Config
    from support import ROOT

    name = f"eaop_mig17_{uuid.uuid4().hex[:8]}"
    base = settings.url("owner").rsplit("/", 1)[0]
    admin = create_engine(base + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE DATABASE {name}"))
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    cfg.attributes["url"] = base + "/" + name
    engine = create_engine(base + "/" + name)
    try:
        command.upgrade(cfg, "0015")  # the whole chain from an empty database up to 0015
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM pg_tables WHERE tablename = 'concurrency_leases'")).scalar() == 0
        command.upgrade(cfg, "0016")
        with engine.begin() as c:
            assert [c.execute(text("SELECT concurrency_acquire('k', 2, 60)")).scalar() is not None for _ in range(3)] == [True, True, False]
            assert c.execute(text("SELECT count(*) FROM pg_proc WHERE proname = 'concurrency_sweep'")).scalar() == 0
            for role in ("eaop_app", "eaop_worker"):
                assert c.execute(text("SELECT has_table_privilege(:r, 'concurrency_leases', 'SELECT')"), {"r": role}).scalar() is False
                assert c.execute(text("SELECT has_function_privilege(:r, 'concurrency_acquire(text, integer, integer)', 'EXECUTE')"), {"r": role}).scalar() is True
        command.upgrade(cfg, "head")
        with engine.begin() as c:
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0017"
            c.execute(text("UPDATE concurrency_leases SET expires_at = clock_timestamp() - interval '1 second'"))
            assert c.execute(text("SELECT concurrency_sweep()")).scalar() == 2
            assert c.execute(text("SELECT has_function_privilege('public', 'concurrency_sweep()', 'EXECUTE')")).scalar() is False
        command.downgrade(cfg, "0015")
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM pg_tables WHERE tablename = 'concurrency_leases'")).scalar() == 0
            assert c.execute(text("SELECT count(*) FROM pg_proc WHERE proname LIKE 'concurrency_%'")).scalar() == 0
            assert c.execute(text("SELECT count(*) FROM pg_tables WHERE tablename IN ('rate_limit_state', 'metric_series')")).scalar() == 2  # 0015 is untouched
        command.upgrade(cfg, "head")
        with engine.connect() as c:
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0017"
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        admin.dispose()
