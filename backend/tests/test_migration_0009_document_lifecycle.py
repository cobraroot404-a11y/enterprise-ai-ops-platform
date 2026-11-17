"""Migration 0009 (document lifecycle, V41-12.05): upgrade, downgrade and data-preservation behaviour.

Every destructive step runs in a DISPOSABLE database created for this module and dropped afterwards; the shared test database is only read. Checks: existing documents survive
upgrade as active with no deletion data, the lifecycle constraints reject inconsistent rows, the worker gets exactly the tenant-scoped access cleanup needs (no cross-tenant
visibility, no ability to revive a document), the application role's tenant isolation is unchanged, the downgrade refuses to discard deletion evidence and otherwise restores
the previous schema, and re-applying works."""
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
    name = f"eaop_mig9_{uuid.uuid4().hex[:8]}"
    admin = create_engine(settings.url("owner").rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE DATABASE {name}"))
    url = settings.url("owner").rsplit("/", 1)[0] + "/" + name
    engine = create_engine(url)
    yield {"cfg": _cfg(url), "engine": engine, "url": url, "name": name, "settings": settings}
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
    admin.dispose()


def _seed(engine):
    """Two tenants with two documents each, inserted at revision 0008 (before the lifecycle columns exist)."""
    ids = {}
    with engine.begin() as c:
        for n in ("a", "b"):
            tid = str(uuid.uuid4())
            c.execute(text("INSERT INTO tenants (id, slug, name) VALUES (:t, :s, :n)"), {"t": tid, "s": f"mig9-{n}-{uuid.uuid4().hex[:6]}", "n": f"Migration 9 {n}"})
            for i in (1, 2):
                c.execute(text("INSERT INTO documents (tenant_id, source_key, filename, kind) VALUES (:t, :k, :k, 'other')"), {"t": tid, "k": f"doc{i}-{n}.txt"})
            ids[n] = tid
    return ids


def _columns(engine):
    with engine.connect() as c:
        return {r[0] for r in c.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'documents'"))}


def test_upgrade_preserves_existing_documents_as_active_and_adds_only_the_lifecycle(scratch):
    command.upgrade(scratch["cfg"], "0008")
    before = _columns(scratch["engine"])
    ids = _seed(scratch["engine"])
    scratch["ids"] = ids
    with scratch["engine"].connect() as c:
        snapshot = c.execute(text("SELECT id, tenant_id, source_key, filename, kind, current_version FROM documents ORDER BY id")).all()
    command.upgrade(scratch["cfg"], "0009")
    after = _columns(scratch["engine"])
    assert after - before == {"lifecycle_status", "deleted_at", "deleted_by", "cleanup_state", "cleanup_completed_at"} and before <= after
    with scratch["engine"].connect() as c:
        assert c.execute(text("SELECT id, tenant_id, source_key, filename, kind, current_version FROM documents ORDER BY id")).all() == snapshot  # untouched
        rows = c.execute(text("SELECT lifecycle_status, deleted_at, deleted_by, cleanup_state, cleanup_completed_at FROM documents")).all()
    assert len(rows) == 4 and all(r == ("active", None, None, None, None) for r in rows)


def test_the_lifecycle_constraints_reject_inconsistent_rows(scratch):
    bad = [
        "UPDATE documents SET lifecycle_status = 'archived'",                                                    # unknown status
        "UPDATE documents SET cleanup_state = 'pending'",                                                         # active with a cleanup state
        "UPDATE documents SET deleted_at = now()",                                                                # active with a deletion time
        "UPDATE documents SET lifecycle_status = 'deleted'",                                                      # deleted without time and state
        "UPDATE documents SET lifecycle_status = 'deleted', deleted_at = now(), cleanup_state = 'completed'",     # completed without a completion time
        "UPDATE documents SET lifecycle_status = 'deleted', deleted_at = now(), cleanup_state = 'pending', cleanup_completed_at = now()",
        "UPDATE documents SET lifecycle_status = 'deleted', deleted_at = now(), cleanup_state = 'bogus'",
    ]
    for statement in bad:
        with scratch["engine"].connect() as c, pytest.raises(DBAPIError):
            c.execute(text(statement + " WHERE source_key LIKE 'doc1-a%'"))
            c.commit()
    with scratch["engine"].connect() as c:
        assert c.execute(text("SELECT count(*) FROM documents WHERE lifecycle_status = 'active'")).scalar() == 4


def test_the_worker_has_tenant_scoped_cleanup_access_and_cannot_revive_a_document(scratch):
    s = scratch["settings"]
    worker_url = s.url("worker").rsplit("/", 1)[0] + "/" + scratch["name"]
    engine = create_engine(worker_url)
    ids = scratch["ids"]
    try:
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM documents")).scalar() == 0  # no tenant context: nothing visible
            c.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": ids["a"]})
            assert c.execute(text("SELECT count(*) FROM documents")).scalar() == 2  # only tenant A's documents
            assert c.execute(text("SELECT count(*) FROM documents WHERE tenant_id = :b"), {"b": ids["b"]}).scalar() == 0
            for chunk_privileges in ("SELECT", "DELETE"):
                assert c.execute(text("SELECT has_table_privilege(current_user, 'document_chunks', :p)"), {"p": chunk_privileges}).scalar()
            assert not c.execute(text("SELECT has_table_privilege(current_user, 'document_chunks', 'INSERT')")).scalar()
            assert c.execute(text("SELECT has_column_privilege(current_user, 'documents', 'cleanup_state', 'UPDATE')")).scalar()
            assert not c.execute(text("SELECT has_column_privilege(current_user, 'documents', 'lifecycle_status', 'UPDATE')")).scalar()  # it cannot revive or delete a document
            assert c.execute(text("SELECT has_column_privilege(current_user, 'incidents', 'citations', 'UPDATE')")).scalar()
            assert not c.execute(text("SELECT has_column_privilege(current_user, 'incidents', 'priority', 'UPDATE')")).scalar()
    finally:
        engine.dispose()


def test_the_application_role_keeps_strict_tenant_isolation(scratch):
    ids = scratch["ids"]
    engine = create_engine(scratch["settings"].url("app").rsplit("/", 1)[0] + "/" + scratch["name"])
    try:
        with engine.connect() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": ids["b"]})
            assert c.execute(text("SELECT count(DISTINCT tenant_id) FROM documents")).scalar() == 1
            assert c.execute(text("SELECT count(*) FROM documents WHERE tenant_id = :a"), {"a": ids["a"]}).scalar() == 0
    finally:
        engine.dispose()


def test_downgrade_refuses_to_discard_deletion_evidence_then_restores_the_previous_schema_and_reapply_works(scratch):
    engine = scratch["engine"]
    with engine.begin() as c:
        c.execute(text("UPDATE documents SET lifecycle_status = 'deleted', deleted_at = now(), cleanup_state = 'pending' WHERE source_key = 'doc1-a.txt'"))
    with pytest.raises(RuntimeError, match="refusing to downgrade 0009"):
        command.downgrade(scratch["cfg"], "0008")
    assert "lifecycle_status" in _columns(engine)  # the refusal left everything in place
    with engine.begin() as c:
        c.execute(text("DELETE FROM documents WHERE lifecycle_status = 'deleted'"))
    command.downgrade(scratch["cfg"], "0008")
    assert not ({"lifecycle_status", "deleted_at", "deleted_by", "cleanup_state", "cleanup_completed_at"} & _columns(engine))
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM documents")).scalar() == 3  # data preserved
        assert c.execute(text("SELECT count(*) FROM pg_policies WHERE policyname = 'worker_tenant_scoped'")).scalar() == 0
    command.upgrade(scratch["cfg"], "0009")
    command.upgrade(scratch["cfg"], "0009")  # already at 0009: a no-op (this module is about 0009; later revisions have their own test modules)
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM documents WHERE lifecycle_status = 'active'")).scalar() == 3
        assert c.execute(text("SELECT count(*) FROM pg_policies WHERE policyname = 'worker_tenant_scoped'")).scalar() == 3
