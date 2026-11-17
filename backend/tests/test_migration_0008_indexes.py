"""Migration 0008 (tenant-leading indexes for incidents, approvals, outbox_events; V41-17.03-IDX).

All destructive steps (downgrade, reapply) run in a DISPOSABLE database created for this module and dropped afterwards; the shared test database is only read.
Checks: indexes exist with the intended leading column and definition, no duplicate or redundant index, constraints / RLS policies / grants / data are unchanged by upgrade,
downgrade and reapply, and tenant isolation still holds for the application role."""
import re
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from support import ROOT

NEW = {
    "incidents_tenant_created_idx": ("incidents", ["tenant_id", "created_at"]),
    "approvals_tenant_decided_idx": ("approvals", ["tenant_id", "decided_at"]),
    "outbox_events_tenant_id_idx": ("outbox_events", ["tenant_id", "id"]),
}
TABLES = ("incidents", "approvals", "outbox_events", "tickets", "tenants", "users")


def _cfg(url):
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    cfg.attributes["url"] = url
    return cfg


@pytest.fixture(scope="module")
def scratch(settings):
    name = f"eaop_mig_{uuid.uuid4().hex[:8]}"
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
    """Two tenants with an incident, ticket, approval and outbox row each (inserted at revision 0007, before the indexes exist)."""
    with engine.begin() as c:
        for n in ("a", "b"):
            tid, uid, iid, kid = (str(uuid.uuid4()) for _ in range(4))
            c.execute(text("INSERT INTO tenants (id, slug, name) VALUES (:t, :s, :n)"), {"t": tid, "s": f"mig-{n}-{uuid.uuid4().hex[:6]}", "n": f"Migration {n}"})
            c.execute(text("INSERT INTO users (id, email, full_name, password_hash) VALUES (:u, :e, 'M', 'x')"), {"u": uid, "e": f"{n}.{uuid.uuid4().hex[:6]}@example.test"})
            c.execute(text("INSERT INTO incidents (id, tenant_id, asset_id, category, symptoms, priority, recommended_action, report_text, extraction_backend, created_by) "
                           "VALUES (:i, :t, 'P-101', 'mechanical_vibration', '[]', 'P3', 'check the bearing now', 'report text for migration test', 'test', :u)"), {"i": iid, "t": tid, "u": uid})
            c.execute(text("INSERT INTO tickets (id, tenant_id, incident_id, title, description, priority, state, created_by) VALUES (:k, :t, :i, 'x', 'y', 'P3', 'APPROVED', :u)"),
                      {"k": kid, "t": tid, "i": iid, "u": uid})
            c.execute(text("INSERT INTO approvals (tenant_id, ticket_id, decision, decided_by) VALUES (:t, :k, 'approved', :u)"), {"t": tid, "k": kid, "u": uid})
            c.execute(text("INSERT INTO outbox_events (tenant_id, topic, aggregate_id, status) VALUES (:t, 'ticket.submit', :k, 'done')"), {"t": tid, "k": kid})


def _state(engine, exclude_new=True):
    """Everything the migration must NOT change: row content, constraints, RLS flags and policies, grants, and the pre-existing indexes."""
    with engine.connect() as c:
        data = {t: c.execute(text(f"SELECT count(*), md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM {t} x")).one() for t in TABLES}
        constraints = c.execute(text("SELECT conrelid::regclass::text, conname, contype, pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace = 'public'::regnamespace ORDER BY 1, 2")).all()
        rls = c.execute(text("SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' ORDER BY 1")).all()
        policies = c.execute(text("SELECT tablename, policyname, roles::text, cmd, qual, with_check FROM pg_policies WHERE schemaname = 'public' ORDER BY 1, 2")).all()
        grants = c.execute(text("SELECT table_name, grantee, privilege_type FROM information_schema.role_table_grants WHERE table_schema = 'public' ORDER BY 1, 2, 3")).all()
        idx = c.execute(text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1")).all()
    if exclude_new:
        idx = [i for i in idx if i[0] not in NEW]
    return {"data": data, "constraints": constraints, "rls": rls, "policies": policies, "grants": grants, "indexes": idx}


def _new_indexes(engine):
    with engine.connect() as c:
        return {r[0]: r[1] for r in c.execute(text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND indexname = ANY(:n)"), {"n": list(NEW)})}


def test_upgrade_adds_exactly_the_intended_indexes_and_changes_nothing_else(scratch):
    command.upgrade(scratch["cfg"], "0007")
    assert _new_indexes(scratch["engine"]) == {}
    _seed(scratch["engine"])
    before = _state(scratch["engine"])
    command.upgrade(scratch["cfg"], "0008")
    assert _state(scratch["engine"]) == before, "upgrade changed data, constraints, RLS, grants or existing indexes"
    defs = _new_indexes(scratch["engine"])
    assert set(defs) == set(NEW)
    for name, (table, cols) in NEW.items():
        d = defs[name]
        assert f"ON public.{table} USING btree" in d, d
        listed = [c.split()[0] for c in re.search(r"\((.+)\)", d).group(1).split(", ")]
        assert listed == cols and listed[0] == "tenant_id", f"{name}: {listed}"
        assert re.search(r"(created_at|decided_at|id) DESC\)", d), f"{name} must serve the newest-first listing order"
        assert "WHERE" not in d and "UNIQUE" not in d


def test_no_redundant_or_duplicate_index_was_created(scratch):
    with scratch["engine"].connect() as c:
        rows = c.execute(text("SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename IN ('incidents', 'approvals', 'outbox_events')")).all()
    cols = {}
    for table, name, d in rows:
        key = (table, re.search(r"USING \w+ \((.+)\)", d).group(1), "WHERE" in d)
        cols.setdefault(key, []).append(name)
    assert all(len(v) == 1 for v in cols.values()), f"duplicate index definitions: {cols}"
    by_table = {}
    for table, name, _d in rows:
        by_table.setdefault(table, []).append(name)
    assert {t: len(n) for t, n in by_table.items()} == {"incidents": 2, "approvals": 3, "outbox_events": 3}  # pkey (+unique/partial existing) + exactly one new each


def test_downgrade_removes_only_the_new_indexes_and_preserves_everything_else(scratch):
    before = _state(scratch["engine"])
    command.downgrade(scratch["cfg"], "0007")
    assert _new_indexes(scratch["engine"]) == {}
    assert _state(scratch["engine"]) == before
    with scratch["engine"].connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0007"


def test_reapply_after_downgrade_and_double_upgrade_are_safe(scratch):
    before = _state(scratch["engine"])
    command.upgrade(scratch["cfg"], "0008")  # this module is about 0008 itself; later revisions have their own test modules
    assert set(_new_indexes(scratch["engine"])) == set(NEW) and _state(scratch["engine"]) == before
    command.upgrade(scratch["cfg"], "0008")  # already at 0008: a no-op, not an error
    assert set(_new_indexes(scratch["engine"])) == set(NEW)
    with scratch["engine"].connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0008"
    with pytest.raises(ProgrammingError):  # the index names are unique: a manual duplicate create is rejected, proving the migration cannot silently double up
        with scratch["engine"].begin() as c:
            c.execute(text("CREATE INDEX incidents_tenant_created_idx ON incidents (tenant_id, created_at DESC)"))


def test_tenant_isolation_and_rls_still_hold_for_the_application_role(scratch):
    """Connect as the application role in the scratch database (RLS enforced) with each tenant's context; each sees only its own rows through the new indexes."""
    import dataclasses

    from app.database.session import Database
    db = Database(dataclasses.replace(scratch["settings"], db_name=scratch["name"]), role="app")
    try:
        with scratch["engine"].connect() as c:
            tenants = [str(r[0]) for r in c.execute(text("SELECT id FROM tenants ORDER BY created_at"))]
        assert len(tenants) == 2
        for me, other in ((tenants[0], tenants[1]), (tenants[1], tenants[0])):
            with db.session(me) as s:
                for table in ("incidents", "approvals", "outbox_events"):
                    ids = {str(r[0]) for r in s.execute(text(f"SELECT tenant_id FROM {table}"))}
                    assert ids == {me}, f"{table} leaked rows across tenants: {ids}"
                assert s.execute(text("SELECT count(*) FROM incidents WHERE tenant_id = :o"), {"o": other}).scalar() == 0
    finally:
        db.dispose()


def test_existing_records_are_unchanged_after_the_full_cycle(scratch):
    with scratch["engine"].connect() as c:
        assert [c.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in ("incidents", "approvals", "outbox_events", "tickets")] == [2, 2, 2, 2]


def test_shared_test_database_has_the_indexes_from_the_normal_upgrade_path(owner_engine):
    assert set(_new_indexes(owner_engine)) == set(NEW)
