"""Migration 0013 (signed webhooks and CSV provenance): upgrade, constraints, privileges, the narrow pre-authentication lookup function, isolation, downgrade and compatibility.

Every destructive step runs in a DISPOSABLE database created for this module and dropped afterwards; the shared test database is only read."""
import hashlib
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from support import ROOT


def _cfg(url):
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    cfg.attributes["url"] = url
    return cfg


@pytest.fixture(scope="module")
def scratch(settings):
    name = f"eaop_mig13_{uuid.uuid4().hex[:8]}"
    admin = create_engine(settings.url("owner").rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE DATABASE {name}"))
    url = settings.url("owner").rsplit("/", 1)[0] + "/" + name
    engine = create_engine(url)
    yield {"cfg": _cfg(url), "engine": engine, "name": name, "settings": settings}
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
    admin.dispose()


def _seed_at_0012(engine):
    ids = {}
    with engine.begin() as c:
        for n in ("a", "b"):
            tid, did = str(uuid.uuid4()), str(uuid.uuid4())
            c.execute(text("INSERT INTO tenants (id, slug, name) VALUES (:t, :s, :n)"), {"t": tid, "s": f"mig13-{n}-{uuid.uuid4().hex[:6]}", "n": f"Migration 13 {n}"})
            conn = c.execute(text("INSERT INTO connectors (tenant_id, kind, name, base_url) VALUES (:t, 'rest', 'records', 'http://127.0.0.1:9') RETURNING id"), {"t": tid}).scalar()
            c.execute(text("INSERT INTO documents (id, tenant_id, source_key, filename, kind) VALUES (:d, :t, 'f.json', 'f.json', 'other')"), {"d": did, "t": tid})
            c.execute(text("INSERT INTO connector_sync_records (tenant_id, connector_id, source_record_id, content_hash, document_id) VALUES (:t, :c, 'R-1', :h, :d)"),
                      {"t": tid, "c": conn, "h": hashlib.sha256(b"r").hexdigest(), "d": did})
            ids[n] = {"tenant": tid, "document": did, "connector": str(conn)}
    return ids


def _endpoint(c, tenant, name="hook", secret="WEBHOOK_SECRET_A", status="active"):
    return c.execute(text("INSERT INTO webhook_endpoints (tenant_id, name, secret_ref, status) VALUES (:t, :n, :s, :st) RETURNING id"), {"t": tenant, "n": name, "s": secret, "st": status}).scalar()


def _delivery(c, tenant, endpoint, delivery_id="delivery-0001", h=None, outcome="accepted"):
    c.execute(text("INSERT INTO webhook_deliveries (tenant_id, endpoint_id, delivery_id, body_sha256, outcome) VALUES (:t, :e, :d, :h, :o)"),
              {"t": tenant, "e": endpoint, "d": delivery_id, "h": h or hashlib.sha256(b"x").hexdigest(), "o": outcome})


def test_upgrade_keeps_existing_sync_records_and_gives_them_a_connector_origin(scratch):
    command.upgrade(scratch["cfg"], "0012")
    scratch["ids"] = _seed_at_0012(scratch["engine"])
    command.upgrade(scratch["cfg"], "0013")
    with scratch["engine"].connect() as c:
        assert c.execute(text("SELECT count(*) FROM connector_sync_records WHERE connector_id IS NOT NULL AND endpoint_id IS NULL AND source_row IS NULL")).scalar() == 2
        assert c.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'webhook_deliveries'")).one() == (True, True)
        assert c.execute(text("SELECT relrowsecurity FROM pg_class WHERE relname = 'webhook_endpoints'")).scalar() is True


def test_the_constraints_reject_inconsistent_rows_and_make_replay_detection_atomic(scratch):
    a = scratch["ids"]["a"]
    for kwargs in (dict(name="bad1", secret="lower"), dict(name="bad2", status="paused")):
        with scratch["engine"].connect() as c, pytest.raises(DBAPIError):
            _endpoint(c, a["tenant"], **kwargs)
            c.commit()
    with scratch["engine"].begin() as c:
        ep = _endpoint(c, a["tenant"])
        _delivery(c, a["tenant"], ep)
    with scratch["engine"].connect() as c, pytest.raises(DBAPIError):  # the same delivery id again: the UNIQUE (endpoint, delivery id) insert fails, which is the replay decision
        _delivery(c, a["tenant"], ep)
        c.commit()
    for kwargs in (dict(delivery_id="short"), dict(delivery_id="bad id with spaces!!"), dict(delivery_id="delivery-0002", h="nothash"), dict(delivery_id="delivery-0003", outcome="maybe")):
        with scratch["engine"].connect() as c, pytest.raises(DBAPIError):
            _delivery(c, a["tenant"], ep, **kwargs)
            c.commit()
    with scratch["engine"].connect() as c, pytest.raises(DBAPIError):  # a previous secret equal to the current one is meaningless
        c.execute(text("UPDATE webhook_endpoints SET previous_secret_ref = secret_ref WHERE id = :e"), {"e": ep})
        c.commit()
    with scratch["engine"].connect() as c, pytest.raises(DBAPIError):  # jobs: a webhook job needs its endpoint and only webhook jobs have one
        c.execute(text("INSERT INTO ingestion_jobs (tenant_id, job_type, status) VALUES (:t, 'webhook', 'QUEUED')"), {"t": a["tenant"]})
        c.commit()
    with scratch["engine"].connect() as c, pytest.raises(DBAPIError):  # a sync record belongs to exactly one origin
        c.execute(text("INSERT INTO connector_sync_records (tenant_id, connector_id, endpoint_id, source_record_id, content_hash) VALUES (:t, :c, :e, 'X', :h)"),
                  {"t": a["tenant"], "c": a["connector"], "e": ep, "h": hashlib.sha256(b"y").hexdigest()})
        c.commit()
    scratch["endpoint_a"] = str(ep)


def test_the_lookup_function_resolves_one_endpoint_and_exposes_nothing_else(scratch):
    ids = scratch["ids"]
    with scratch["engine"].begin() as c:
        eb = _endpoint(c, ids["b"]["tenant"], name="hook-b", secret="WEBHOOK_SECRET_B")
    scratch["endpoint_b"] = str(eb)
    engine = create_engine(scratch["settings"].url("app").rsplit("/", 1)[0] + "/" + scratch["name"])
    try:
        with engine.connect() as c:  # no tenant context at all: the table itself is invisible, the function still resolves a single known id
            assert c.execute(text("SELECT count(*) FROM webhook_endpoints")).scalar() == 0
            row = c.execute(text("SELECT tenant_id::text, secret_ref, status, name FROM webhook_endpoint_lookup(CAST(:e AS uuid))"), {"e": scratch["endpoint_a"]}).one()
            assert row[0] == ids["a"]["tenant"] and row[1] == "WEBHOOK_SECRET_A" and row[2] == "active" and row[3] == "hook"  # names of variables, never secrets
            assert c.execute(text("SELECT count(*) FROM webhook_endpoint_lookup(CAST(:e AS uuid))"), {"e": str(uuid.uuid4())}).scalar() == 0
            cols = [r[0] for r in c.execute(text("SELECT a.attname FROM pg_proc p, unnest(p.proargnames) WITH ORDINALITY AS a(attname, i) WHERE p.proname = 'webhook_endpoint_lookup'"))]
            assert set(cols) <= {"p_endpoint", "tenant_id", "secret_ref", "previous_secret_ref", "status", "config", "name"}
    finally:
        engine.dispose()
    with scratch["engine"].connect() as c:  # the worker role cannot call it; PUBLIC cannot either
        assert not c.execute(text("SELECT has_function_privilege('eaop_worker', 'webhook_endpoint_lookup(uuid)', 'EXECUTE')")).scalar()
        assert c.execute(text("SELECT has_function_privilege('eaop_app', 'webhook_endpoint_lookup(uuid)', 'EXECUTE')")).scalar()


def test_the_application_role_is_tenant_isolated_and_the_ledger_is_append_only(scratch):
    ids = scratch["ids"]
    with scratch["engine"].begin() as c:
        _delivery(c, ids["b"]["tenant"], scratch["endpoint_b"], delivery_id="delivery-b-0001")
    engine = create_engine(scratch["settings"].url("app").rsplit("/", 1)[0] + "/" + scratch["name"])
    try:
        with engine.connect() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": ids["b"]["tenant"]})
            assert c.execute(text("SELECT count(DISTINCT tenant_id) FROM webhook_deliveries")).scalar() == 1
            assert c.execute(text("SELECT count(DISTINCT tenant_id) FROM webhook_endpoints")).scalar() == 1
            assert c.execute(text("SELECT count(*) FROM webhook_endpoints WHERE tenant_id = :a"), {"a": ids["a"]["tenant"]}).scalar() == 0
            for table, privilege in (("webhook_deliveries", "UPDATE"), ("webhook_deliveries", "DELETE"), ("webhook_endpoints", "DELETE")):
                assert not c.execute(text("SELECT has_table_privilege(current_user, :t, :p)"), {"t": table, "p": privilege}).scalar(), (table, privilege)
            assert not c.execute(text("SELECT has_column_privilege(current_user, 'webhook_endpoints', 'config', 'UPDATE')")).scalar()  # configuration is fixed at creation
            c.rollback()
        with engine.connect() as c, pytest.raises(DBAPIError):  # a delivery for ANOTHER tenant than the context is refused by policy
            c.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": ids["b"]["tenant"]})
            _delivery(c, ids["a"]["tenant"], scratch["endpoint_a"], delivery_id="delivery-forged-1")
            c.commit()
    finally:
        engine.dispose()


def test_the_worker_reads_endpoints_only_inside_its_tenant_context(scratch):
    ids = scratch["ids"]
    engine = create_engine(scratch["settings"].url("worker").rsplit("/", 1)[0] + "/" + scratch["name"])
    try:
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM webhook_endpoints")).scalar() == 0
            c.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": ids["a"]["tenant"]})
            assert c.execute(text("SELECT count(*) FROM webhook_endpoints")).scalar() == 1 and c.execute(text("SELECT count(*) FROM webhook_endpoints WHERE tenant_id = :b"), {"b": ids["b"]["tenant"]}).scalar() == 0
            assert not c.execute(text("SELECT has_table_privilege(current_user, 'webhook_endpoints', 'INSERT')")).scalar()
            c.rollback()
    finally:
        engine.dispose()


def test_downgrade_refuses_to_discard_webhook_data_then_restores_and_reapply_works(scratch):
    engine = scratch["engine"]
    with pytest.raises(RuntimeError, match="refusing to downgrade 0013"):
        command.downgrade(scratch["cfg"], "0012")
    with engine.begin() as c:
        c.execute(text("DELETE FROM webhook_deliveries"))
        c.execute(text("DELETE FROM webhook_endpoints"))
    command.downgrade(scratch["cfg"], "0012")
    with engine.connect() as c:
        assert c.execute(text("SELECT to_regclass('webhook_endpoints')")).scalar() is None and c.execute(text("SELECT to_regclass('webhook_deliveries')")).scalar() is None
        assert not c.execute(text("SELECT count(*) FROM pg_proc WHERE proname = 'webhook_endpoint_lookup'")).scalar()
        assert c.execute(text("SELECT count(*) FROM connector_sync_records WHERE connector_id IS NOT NULL")).scalar() == 2  # data preserved, connector id mandatory again
    command.upgrade(scratch["cfg"], "0013")
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM pg_policies WHERE tablename = 'webhook_deliveries'")).scalar() == 2
