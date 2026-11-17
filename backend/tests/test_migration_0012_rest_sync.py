"""Migration 0012 (REST pull synchronization; V41-12.01 REST part, V41-11.01, V41-11.02): upgrade, constraints, privileges, isolation, downgrade and compatibility.

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
    name = f"eaop_mig12_{uuid.uuid4().hex[:8]}"
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


def _seed_at_0011(engine):
    ids = {}
    with engine.begin() as c:
        for n in ("a", "b"):
            tid, did = str(uuid.uuid4()), str(uuid.uuid4())
            c.execute(text("INSERT INTO tenants (id, slug, name) VALUES (:t, :s, :n)"), {"t": tid, "s": f"mig12-{n}-{uuid.uuid4().hex[:6]}", "n": f"Migration 12 {n}"})
            conn = c.execute(text("INSERT INTO connectors (tenant_id, kind, name, base_url) VALUES (:t, 'rest', 'records', 'http://127.0.0.1:9') RETURNING id"), {"t": tid}).scalar()
            c.execute(text("INSERT INTO documents (id, tenant_id, source_key, filename, kind) VALUES (:d, :t, 'f.json', 'f.json', 'other')"), {"d": did, "t": tid})
            c.execute(text("INSERT INTO ingestion_jobs (tenant_id, job_type, status, document_id, completed_at) VALUES (:t, 'ingest', 'COMPLETED', :d, now())"), {"t": tid, "d": did})
            ids[n] = {"tenant": tid, "document": did, "connector": str(conn)}
    return ids


def _record(c, ids, rid="R-1", h=None, status="active"):
    return c.execute(text("INSERT INTO connector_sync_records (tenant_id, connector_id, source_record_id, content_hash, document_id, status) "
                          "VALUES (:t, :c, :r, :h, :d, :s) RETURNING id"),
                     {"t": ids["tenant"], "c": ids["connector"], "r": rid, "h": h or hashlib.sha256(rid.encode()).hexdigest(), "d": ids["document"], "s": status}).scalar()


def test_upgrade_keeps_existing_jobs_and_adds_the_sync_type_without_touching_them(scratch):
    command.upgrade(scratch["cfg"], "0011")
    scratch["ids"] = _seed_at_0011(scratch["engine"])
    with scratch["engine"].connect() as c:
        before = c.execute(text("SELECT id, job_type, status FROM ingestion_jobs ORDER BY id")).all()
    command.upgrade(scratch["cfg"], "0012")
    with scratch["engine"].connect() as c:
        assert c.execute(text("SELECT id, job_type, status FROM ingestion_jobs ORDER BY id")).all() == before
        assert c.execute(text("SELECT count(*) FROM ingestion_jobs WHERE connector_id IS NULL AND progress IS NULL")).scalar() == 2
        assert c.execute(text("SELECT count(*) FROM connector_sync_records")).scalar() == 0
        assert c.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'connector_sync_records'")).one() == (True, True)


def test_the_constraints_reject_inconsistent_jobs_and_records(scratch):
    ids = scratch["ids"]["a"]
    bad_jobs = ["INSERT INTO ingestion_jobs (tenant_id, job_type, status) VALUES (:t, 'sync', 'QUEUED')",  # a sync job needs its connector
                "INSERT INTO ingestion_jobs (tenant_id, job_type, status, connector_id) VALUES (:t, 'ingest', 'QUEUED', :c)",  # only sync jobs have one
                "INSERT INTO ingestion_jobs (tenant_id, job_type, status, connector_id) VALUES (:t, 'delete', 'QUEUED', :c)"]
    for statement in bad_jobs:
        with scratch["engine"].connect() as c, pytest.raises(DBAPIError):
            c.execute(text(statement), {"t": ids["tenant"], "c": ids["connector"]})
            c.commit()
    with scratch["engine"].begin() as c:
        c.execute(text("INSERT INTO ingestion_jobs (tenant_id, job_type, status, connector_id, idempotency_key) VALUES (:t, 'sync', 'QUEUED', :c, 'sync:x')"), {"t": ids["tenant"], "c": ids["connector"]})
        _record(c, ids)
    with scratch["engine"].connect() as c, pytest.raises(DBAPIError):  # one row per source record
        _record(c, ids)
        c.commit()
    for kwargs in (dict(rid="R-2", h="nothash"), dict(rid="R-3", status="archived")):
        with scratch["engine"].connect() as c, pytest.raises(DBAPIError):
            _record(c, ids, **kwargs)
            c.commit()
    with scratch["engine"].connect() as c, pytest.raises(DBAPIError):  # one ACTIVE sync per connector (idempotency)
        c.execute(text("INSERT INTO ingestion_jobs (tenant_id, job_type, status, connector_id, idempotency_key) VALUES (:t, 'sync', 'QUEUED', :c, 'sync:x')"), {"t": ids["tenant"], "c": ids["connector"]})
        c.commit()


def test_the_application_role_is_tenant_isolated_and_can_only_mark_records_deleted(scratch):
    ids = scratch["ids"]
    with scratch["engine"].begin() as c:
        _record(c, ids["b"], rid="B-1")
    engine = create_engine(scratch["settings"].url("app").rsplit("/", 1)[0] + "/" + scratch["name"])
    try:
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM connector_sync_records")).scalar() == 0  # no tenant context
            c.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": ids["b"]["tenant"]})
            assert c.execute(text("SELECT count(DISTINCT tenant_id) FROM connector_sync_records")).scalar() == 1
            assert c.execute(text("SELECT count(*) FROM connector_sync_records WHERE tenant_id = :a"), {"a": ids["a"]["tenant"]}).scalar() == 0

            def priv(col):
                return c.execute(text("SELECT has_column_privilege(current_user, 'connector_sync_records', :c, 'UPDATE')"), {"c": col}).scalar()
            assert priv("status") and not priv("content_hash") and not priv("document_id")
            assert not c.execute(text("SELECT has_table_privilege(current_user, 'connector_sync_records', 'INSERT')")).scalar()
            c.rollback()
    finally:
        engine.dispose()


def test_the_worker_writes_sync_records_only_inside_its_tenant_context(scratch):
    ids = scratch["ids"]
    with scratch["engine"].connect() as c:
        assert c.execute(text("SELECT has_table_privilege('eaop_worker', 'document_sources', 'INSERT')")).scalar()  # granted by 0012 for pulled records
    engine = create_engine(scratch["settings"].url("worker").rsplit("/", 1)[0] + "/" + scratch["name"])
    try:
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM connector_sync_records")).scalar() == 0
            c.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": ids["a"]["tenant"]})
            assert c.execute(text("SELECT count(*) FROM connector_sync_records")).scalar() == 1  # tenant A's record only
            assert c.execute(text("SELECT count(*) FROM connector_sync_records WHERE tenant_id = :b"), {"b": ids["b"]["tenant"]}).scalar() == 0
            assert c.execute(text("UPDATE connector_sync_records SET status = 'deleted' WHERE tenant_id = :b"), {"b": ids["b"]["tenant"]}).rowcount == 0  # tenant B's row is invisible
            c.rollback()
        with engine.connect() as c, pytest.raises(DBAPIError):  # a record for ANOTHER tenant than the context is refused by policy
            c.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": ids["a"]["tenant"]})
            _record(c, ids["b"], rid="FORGED")
            c.commit()
    finally:
        engine.dispose()


def test_downgrade_refuses_to_discard_provenance_then_restores_and_reapply_works(scratch):
    engine = scratch["engine"]
    with pytest.raises(RuntimeError, match="refusing to downgrade 0012"):
        command.downgrade(scratch["cfg"], "0011")
    with engine.begin() as c:
        c.execute(text("DELETE FROM connector_sync_records"))
    with pytest.raises(RuntimeError, match="refusing to downgrade 0012"):  # a sync job still exists
        command.downgrade(scratch["cfg"], "0011")
    with engine.begin() as c:
        c.execute(text("DELETE FROM ingestion_jobs WHERE job_type = 'sync'"))
    command.downgrade(scratch["cfg"], "0011")
    with engine.connect() as c:
        assert c.execute(text("SELECT to_regclass('connector_sync_records')")).scalar() is None
        assert not c.execute(text("SELECT count(*) FROM information_schema.columns WHERE table_name = 'ingestion_jobs' AND column_name IN ('connector_id', 'progress')")).scalar()
        assert c.execute(text("SELECT count(*) FROM ingestion_jobs")).scalar() == 2  # data preserved
    command.upgrade(scratch["cfg"], "0012")
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM pg_policies WHERE tablename = 'connector_sync_records'")).scalar() == 2
