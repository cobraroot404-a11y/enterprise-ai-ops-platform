"""Migration 0011 (controlled original-source storage; V41-12.03, V41-12.04): upgrade, constraints, privileges, isolation, downgrade and existing-document compatibility.

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
    name = f"eaop_mig11_{uuid.uuid4().hex[:8]}"
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


def _seed_at_0010(engine):
    ids = {}
    with engine.begin() as c:
        for n in ("a", "b"):
            tid, did = str(uuid.uuid4()), str(uuid.uuid4())
            c.execute(text("INSERT INTO tenants (id, slug, name) VALUES (:t, :s, :n)"), {"t": tid, "s": f"mig11-{n}-{uuid.uuid4().hex[:6]}", "n": f"Migration 11 {n}"})
            c.execute(text("INSERT INTO documents (id, tenant_id, source_key, filename, kind) VALUES (:d, :t, 'f.txt', 'f.txt', 'other')"), {"d": did, "t": tid})
            c.execute(text("INSERT INTO document_versions (tenant_id, document_id, version, content_hash, size_bytes, media_type, chunk_count, embedding_backend) "
                           "VALUES (:t, :d, 1, :h, 10, 'text/plain', 0, 'deterministic')"), {"t": tid, "d": did, "h": uuid.uuid4().hex})
            ids[n] = {"tenant": tid, "document": did}
    return ids


def _insert(c, tenant, data=b"hello", document=None, version=None, h=None, size=None):
    return c.execute(text("INSERT INTO document_sources (tenant_id, document_id, version, filename, kind, media_type, size_bytes, content_hash, content) "
                          "VALUES (:t, :d, :v, 'f.txt', 'other', 'text/plain', :s, :h, :c) RETURNING id"),
                     {"t": tenant, "d": document, "v": version, "s": len(data) if size is None else size, "h": h or hashlib.sha256(data).hexdigest(), "c": data}).scalar()


def test_upgrade_keeps_existing_documents_supported_without_a_source(scratch):
    command.upgrade(scratch["cfg"], "0010")
    scratch["ids"] = _seed_at_0010(scratch["engine"])
    with scratch["engine"].connect() as c:
        before = c.execute(text("SELECT id, filename FROM documents ORDER BY id")).all()
    command.upgrade(scratch["cfg"], "0011")
    with scratch["engine"].connect() as c:
        assert c.execute(text("SELECT id, filename FROM documents ORDER BY id")).all() == before
        assert c.execute(text("SELECT count(*) FROM document_versions WHERE source_id IS NULL")).scalar() == 2  # historical versions: no retained original
        assert c.execute(text("SELECT count(*) FROM document_sources")).scalar() == 0
        assert c.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'document_sources'")).one() == (True, True)


def test_the_constraints_reject_inconsistent_or_unbounded_content(scratch):
    t = scratch["ids"]["a"]["tenant"]
    bad = [dict(data=b"hello", size=99), dict(data=b"hello", h="not-a-hash"), dict(data=b"", size=0),
           dict(data=b"x", document=scratch["ids"]["a"]["document"]), dict(data=b"x", version=1)]  # length lie, malformed hash, empty, half-linked
    for kwargs in bad:
        with scratch["engine"].connect() as c, pytest.raises(DBAPIError):
            _insert(c, t, **kwargs)
            c.commit()
    with scratch["engine"].begin() as c:
        _insert(c, t)  # a valid, unlinked source
        _insert(c, t, data=b"linked", document=scratch["ids"]["a"]["document"], version=1)


def test_the_application_role_is_tenant_isolated_and_cannot_edit_content(scratch):
    ids = scratch["ids"]
    with scratch["engine"].begin() as c:
        _insert(c, ids["b"]["tenant"], data=b"tenant b original")
    engine = create_engine(scratch["settings"].url("app").rsplit("/", 1)[0] + "/" + scratch["name"])
    try:
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM document_sources")).scalar() == 0  # no tenant context: nothing
            c.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": ids["b"]["tenant"]})
            assert c.execute(text("SELECT count(DISTINCT tenant_id) FROM document_sources")).scalar() == 1
            assert c.execute(text("SELECT count(*) FROM document_sources WHERE tenant_id = :a"), {"a": ids["a"]["tenant"]}).scalar() == 0
            for column in ("content", "content_hash", "size_bytes"):
                assert not c.execute(text("SELECT has_column_privilege(current_user, 'document_sources', :c, 'UPDATE')"), {"c": column}).scalar()  # immutable once stored
            c.rollback()
        with engine.connect() as c, pytest.raises(DBAPIError):  # a source for ANOTHER tenant than the one in context is refused by policy
            c.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": ids["b"]["tenant"]})
            _insert(c, ids["a"]["tenant"])
            c.commit()
    finally:
        engine.dispose()


def test_the_worker_can_read_link_and_delete_only_inside_its_tenant_and_cannot_create_or_edit(scratch):
    ids = scratch["ids"]
    engine = create_engine(scratch["settings"].url("worker").rsplit("/", 1)[0] + "/" + scratch["name"])
    try:
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM document_sources")).scalar() == 0  # no tenant context
            c.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": ids["a"]["tenant"]})
            assert c.execute(text("SELECT count(*) FROM document_sources")).scalar() == 2
            assert c.execute(text("SELECT count(*) FROM document_sources WHERE tenant_id = :b"), {"b": ids["b"]["tenant"]}).scalar() == 0
            priv = lambda sql, **p: c.execute(text(sql), p).scalar()  # noqa: E731
            assert priv("SELECT has_table_privilege(current_user, 'document_sources', 'DELETE')") and not priv("SELECT has_table_privilege(current_user, 'document_sources', 'INSERT')")
            assert priv("SELECT has_column_privilege(current_user, 'document_sources', 'document_id', 'UPDATE')")
            assert not priv("SELECT has_column_privilege(current_user, 'document_sources', 'content', 'UPDATE')")
            assert c.execute(text("DELETE FROM document_sources WHERE tenant_id = :b"), {"b": ids["b"]["tenant"]}).rowcount == 0  # tenant B's source is invisible to a tenant A context
            c.rollback()
    finally:
        engine.dispose()


def test_downgrade_refuses_to_discard_original_content_then_restores_and_reapply_works(scratch):
    engine = scratch["engine"]
    with pytest.raises(RuntimeError, match="refusing to downgrade 0011"):
        command.downgrade(scratch["cfg"], "0010")
    with engine.begin() as c:
        c.execute(text("DELETE FROM document_sources"))
    command.downgrade(scratch["cfg"], "0010")
    with engine.connect() as c:
        assert c.execute(text("SELECT to_regclass('document_sources')")).scalar() is None
        assert not c.execute(text("SELECT count(*) FROM information_schema.columns WHERE table_name = 'document_versions' AND column_name = 'source_id'")).scalar()
        assert c.execute(text("SELECT count(*) FROM documents")).scalar() == 2  # data preserved
    command.upgrade(scratch["cfg"], "0011")
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM pg_policies WHERE tablename = 'document_sources'")).scalar() == 2
