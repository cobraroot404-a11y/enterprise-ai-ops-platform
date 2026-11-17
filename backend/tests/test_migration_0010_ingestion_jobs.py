"""Migration 0010 (durable ingestion jobs, chunk generations; V41-12.03, V41-12.04): upgrade, constraints, privileges, isolation, downgrade and data preservation.

Every destructive step runs in a DISPOSABLE database created for this module and dropped afterwards; the shared test database is only read."""
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
    name = f"eaop_mig10_{uuid.uuid4().hex[:8]}"
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


def _seed(engine):
    """Two tenants, each with a document, a version and a chunk, inserted at revision 0009 (before generations and jobs exist)."""
    ids = {}
    with engine.begin() as c:
        for n in ("a", "b"):
            tid, did = str(uuid.uuid4()), str(uuid.uuid4())
            c.execute(text("INSERT INTO tenants (id, slug, name) VALUES (:t, :s, :n)"), {"t": tid, "s": f"mig10-{n}-{uuid.uuid4().hex[:6]}", "n": f"Migration 10 {n}"})
            profile = c.execute(text("INSERT INTO embedding_profiles (tenant_id, provider, model, revision, dim, active) VALUES (:t, 'deterministic', 'm', 'r', 384, true) RETURNING id"), {"t": tid}).scalar()
            c.execute(text("INSERT INTO documents (id, tenant_id, source_key, filename, kind) VALUES (:d, :t, 'f.txt', 'f.txt', 'other')"), {"d": did, "t": tid})
            version = c.execute(text("INSERT INTO document_versions (tenant_id, document_id, version, content_hash, size_bytes, media_type, chunk_count, embedding_backend) "
                                     "VALUES (:t, :d, 1, :h, 10, 'text/plain', 1, 'deterministic') RETURNING id"), {"t": tid, "d": did, "h": uuid.uuid4().hex}).scalar()
            c.execute(text("INSERT INTO document_chunks (tenant_id, document_id, version_id, version, chunk_index, text, suspicious, is_current, embedding, embedding_profile_id) "
                           "VALUES (:t, :d, :v, 1, 0, 'hello', false, true, array_fill(0.1::real, ARRAY[384])::vector, :p)"), {"t": tid, "d": did, "v": version, "p": profile})
            ids[n] = {"tenant": tid, "document": did, "version": str(version)}
    return ids


def test_upgrade_preserves_data_and_adds_generations_defaulting_to_one(scratch):
    command.upgrade(scratch["cfg"], "0009")
    scratch["ids"] = _seed(scratch["engine"])
    with scratch["engine"].connect() as c:
        before = c.execute(text("SELECT id, text, is_current, chunk_index FROM document_chunks ORDER BY id")).all()
        docs = c.execute(text("SELECT id, filename, lifecycle_status FROM documents ORDER BY id")).all()
    command.upgrade(scratch["cfg"], "0010")
    with scratch["engine"].connect() as c:
        assert c.execute(text("SELECT id, text, is_current, chunk_index FROM document_chunks ORDER BY id")).all() == before
        assert c.execute(text("SELECT id, filename, lifecycle_status FROM documents ORDER BY id")).all() == docs
        assert c.execute(text("SELECT count(*) FROM document_chunks WHERE generation = 1")).scalar() == 2
        assert c.execute(text("SELECT count(*) FROM document_versions WHERE active_generation = 1 AND processing_job_id IS NULL")).scalar() == 2
        assert c.execute(text("SELECT count(*) FROM ingestion_jobs")).scalar() == 0
        assert c.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'ingestion_jobs'")).one() == (True, True)


def test_the_job_constraints_reject_forged_or_inconsistent_rows(scratch):
    ids = scratch["ids"]["a"]
    cases = {
        "unknown status": "INSERT INTO ingestion_jobs (tenant_id, job_type, status) VALUES (:t, 'ingest', 'DONE')",
        "unknown type": "INSERT INTO ingestion_jobs (tenant_id, job_type, status) VALUES (:t, 'delete', 'QUEUED')",
        "completed without a time": "INSERT INTO ingestion_jobs (tenant_id, job_type, status) VALUES (:t, 'ingest', 'COMPLETED')",
        "processing without a lease": "INSERT INTO ingestion_jobs (tenant_id, job_type, status) VALUES (:t, 'ingest', 'PROCESSING')",
        "content kept on a finished job": "INSERT INTO ingestion_jobs (tenant_id, job_type, status, completed_at, payload) VALUES (:t, 'ingest', 'FAILED', now(), '{}'::jsonb)",
        "more attempts than allowed": "INSERT INTO ingestion_jobs (tenant_id, job_type, status, attempts, max_attempts) VALUES (:t, 'ingest', 'QUEUED', 6, 5)",
        "unbounded retry limit": "INSERT INTO ingestion_jobs (tenant_id, job_type, status, max_attempts) VALUES (:t, 'ingest', 'QUEUED', 1000)",
    }
    for statement in cases.values():
        with scratch["engine"].connect() as c, pytest.raises(DBAPIError):
            c.execute(text(statement), {"t": ids["tenant"]})
            c.commit()
    with scratch["engine"].begin() as c:  # a valid row, and the partial unique index: one ACTIVE job per idempotency key, history unlimited
        c.execute(text("INSERT INTO ingestion_jobs (tenant_id, job_type, status, idempotency_key) VALUES (:t, 'ingest', 'QUEUED', 'k1')"), {"t": ids["tenant"]})
    with scratch["engine"].connect() as c, pytest.raises(DBAPIError):
        c.execute(text("INSERT INTO ingestion_jobs (tenant_id, job_type, status, idempotency_key) VALUES (:t, 'ingest', 'RETRY_PENDING', 'k1')"), {"t": ids["tenant"]})
        c.commit()
    with scratch["engine"].begin() as c:
        c.execute(text("UPDATE ingestion_jobs SET status = 'FAILED', completed_at = now() WHERE idempotency_key = 'k1'"))
        c.execute(text("INSERT INTO ingestion_jobs (tenant_id, job_type, status, idempotency_key) VALUES (:t, 'ingest', 'QUEUED', 'k1')"), {"t": ids["tenant"]})  # allowed again once the first ended


def test_the_application_role_is_tenant_isolated_on_jobs(scratch):
    ids = scratch["ids"]
    with scratch["engine"].begin() as c:
        c.execute(text("INSERT INTO ingestion_jobs (tenant_id, job_type, status) VALUES (:t, 'reprocess', 'QUEUED')"), {"t": ids["b"]["tenant"]})
    engine = create_engine(scratch["settings"].url("app").rsplit("/", 1)[0] + "/" + scratch["name"])
    try:
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM ingestion_jobs")).scalar() == 0  # no tenant context: nothing
            c.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": ids["b"]["tenant"]})
            assert c.execute(text("SELECT count(DISTINCT tenant_id) FROM ingestion_jobs")).scalar() == 1
            assert c.execute(text("SELECT count(*) FROM ingestion_jobs WHERE tenant_id = :a"), {"a": ids["a"]["tenant"]}).scalar() == 0
    finally:
        engine.dispose()


def test_the_worker_can_store_content_only_inside_its_tenant_context_and_only_the_columns_it_needs(scratch):
    ids = scratch["ids"]
    engine = create_engine(scratch["settings"].url("worker").rsplit("/", 1)[0] + "/" + scratch["name"])
    try:
        with engine.connect() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": ids["a"]["tenant"]})
            assert c.execute(text("SELECT count(*) FROM document_chunks")).scalar() == 1  # only tenant A's chunk
            priv = lambda sql, **p: c.execute(text(sql), p).scalar()  # noqa: E731
            assert priv("SELECT has_table_privilege(current_user, 'ingestion_jobs', 'UPDATE')") and not priv("SELECT has_table_privilege(current_user, 'ingestion_jobs', 'DELETE')")
            assert priv("SELECT has_table_privilege(current_user, 'document_chunks', 'INSERT')") and priv("SELECT has_column_privilege(current_user, 'document_chunks', 'is_current', 'UPDATE')")
            assert not priv("SELECT has_column_privilege(current_user, 'document_chunks', 'text', 'UPDATE')")  # content is written once, never edited
            assert not priv("SELECT has_column_privilege(current_user, 'documents', 'lifecycle_status', 'UPDATE')")  # still cannot delete or revive a document
            assert priv("SELECT has_column_privilege(current_user, 'document_versions', 'active_generation', 'UPDATE')") and not priv("SELECT has_column_privilege(current_user, 'document_versions', 'content_hash', 'UPDATE')")
            c.rollback()
        with engine.connect() as c, pytest.raises(DBAPIError):  # a chunk for ANOTHER tenant than the one in context is refused by policy
            c.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": ids["a"]["tenant"]})
            c.execute(text("INSERT INTO document_chunks (tenant_id, document_id, version_id, version, chunk_index, text, suspicious, is_current, embedding) "
                           "VALUES (:t, :d, :v, 1, 5, 'x', false, false, array_fill(0.1::real, ARRAY[384])::vector)"), {"t": ids["b"]["tenant"], "d": ids["b"]["document"], "v": ids["b"]["version"]})
            c.commit()
    finally:
        engine.dispose()


def test_downgrade_refuses_to_discard_lineage_then_restores_the_previous_schema_and_reapply_works(scratch):
    engine = scratch["engine"]
    with pytest.raises(RuntimeError, match="refusing to downgrade 0010"):
        command.downgrade(scratch["cfg"], "0009")  # jobs exist
    with engine.begin() as c:
        c.execute(text("DELETE FROM ingestion_jobs"))
        c.execute(text("UPDATE document_chunks SET generation = 2 WHERE chunk_index = 0 AND tenant_id = :t"), {"t": scratch["ids"]["a"]["tenant"]})
    with pytest.raises(RuntimeError, match="refusing to downgrade 0010"):
        command.downgrade(scratch["cfg"], "0009")  # a reprocessed generation exists
    with engine.begin() as c:
        c.execute(text("UPDATE document_chunks SET generation = 1"))
    command.downgrade(scratch["cfg"], "0009")
    with engine.connect() as c:
        assert c.execute(text("SELECT to_regclass('ingestion_jobs')")).scalar() is None
        assert not c.execute(text("SELECT count(*) FROM information_schema.columns WHERE table_name = 'document_chunks' AND column_name = 'generation'")).scalar()
        assert c.execute(text("SELECT count(*) FROM document_chunks")).scalar() == 2  # data preserved
        assert c.execute(text("SELECT count(*) FROM pg_policies WHERE tablename = 'embedding_profiles' AND policyname = 'worker_tenant_scoped'")).scalar() == 0
    command.upgrade(scratch["cfg"], "0010")
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM document_chunks WHERE generation = 1")).scalar() == 2
        assert c.execute(text("SELECT count(*) FROM pg_policies WHERE tablename = 'ingestion_jobs'")).scalar() == 2
