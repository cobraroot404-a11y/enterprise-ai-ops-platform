import uuid

import pytest
from app.core.security import hash_password
from app.database.session import Database
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from support import PASSWORD, login, make_tenant


@pytest.fixture()
def tenants(owner_engine):
    return make_tenant(owner_engine, "alpha"), make_tenant(owner_engine, "beta")


def uid(owner_engine, email) -> str:
    with owner_engine.connect() as conn:
        return str(conn.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email}).scalar())


def owner_role(owner_engine, tenant_id, user_id):
    with owner_engine.connect() as conn:
        return conn.execute(text("SELECT role FROM memberships WHERE tenant_id = :t AND user_id = :u"),
                            {"t": tenant_id, "u": user_id}).scalar()


def run(app_db, sql, params=None, tenant=None, user=None) -> int:
    """Execute as the restricted API role with the given context; return affected/selected row count."""
    with app_db.session(tenant, user) as s:
        result = s.execute(text(sql), params or {})
        s.commit()
        return result.rowcount if result.returns_rows is False else len(result.all())


@pytest.fixture()
def platform_admin(owner_engine, client):
    email = f"platform.{uuid.uuid4().hex[:8]}@example.test"
    with owner_engine.begin() as conn:
        conn.execute(text("INSERT INTO users (email, full_name, password_hash, is_platform_admin) "
                          "VALUES (:e, 'Platform Admin', :p, true)"), {"e": email, "p": hash_password(PASSWORD)})
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ---- database-level policies (independent of application code) -------------------------------------------
def test_cross_tenant_membership_reads_blocked(app_db, owner_engine, tenants):
    a, b = tenants
    admin_a = uid(owner_engine, a.users["tenant_admin"])
    assert run(app_db, "SELECT 1 FROM memberships", tenant=a.id, user=admin_a) == 4  # only tenant A rows
    assert run(app_db, "SELECT 1 FROM memberships WHERE tenant_id = :b", {"b": b.id}, tenant=a.id, user=admin_a) == 0
    assert run(app_db, "SELECT 1 FROM memberships", user=admin_a) == 1  # user context alone: own rows only
    assert run(app_db, "SELECT 1 FROM memberships") == 0  # no context: fail closed
    # A user's own memberships across tenants are visible to that user, and only to them.
    with owner_engine.begin() as conn:
        conn.execute(text("INSERT INTO memberships (tenant_id, user_id, role) VALUES (:t, :u, 'support_engineer')"),
                     {"t": b.id, "u": admin_a})
    assert run(app_db, "SELECT 1 FROM memberships", user=admin_a) == 2
    other = uid(owner_engine, b.users["read_only_auditor"])
    assert run(app_db, "SELECT 1 FROM memberships", user=other) == 1


def test_cross_tenant_membership_modifications_blocked(app_db, owner_engine, tenants):
    a, b = tenants
    admin_a = uid(owner_engine, a.users["tenant_admin"])
    victim = uid(owner_engine, b.users["support_engineer"])
    ctx = {"tenant": a.id, "user": admin_a}
    assert run(app_db, "UPDATE memberships SET role = 'tenant_admin' WHERE tenant_id = :b", {"b": b.id}, **ctx) == 0
    assert run(app_db, "DELETE FROM memberships WHERE tenant_id = :b", {"b": b.id}, **ctx) == 0
    with pytest.raises(DBAPIError):
        run(app_db, "INSERT INTO memberships (tenant_id, user_id, role) VALUES (:b, :u, 'tenant_admin')",
            {"b": b.id, "u": admin_a}, **ctx)
    # moving a row between tenants is rejected too (WITH CHECK)
    mover = uid(owner_engine, a.users["support_engineer"])
    with pytest.raises(DBAPIError):
        run(app_db, "UPDATE memberships SET tenant_id = :b WHERE user_id = :u", {"b": b.id, "u": mover}, **ctx)
    assert owner_role(owner_engine, b.id, victim) == "support_engineer"
    assert owner_role(owner_engine, a.id, mover) == "support_engineer"


def test_database_blocks_self_assignment_and_escalation(app_db, owner_engine, tenants):
    a, _ = tenants
    engineer = uid(owner_engine, a.users["support_engineer"])
    admin = uid(owner_engine, a.users["tenant_admin"])
    # a member cannot raise or delete their own membership, even inside their own tenant context
    assert run(app_db, "UPDATE memberships SET role = 'tenant_admin' WHERE user_id = :u", {"u": engineer},
               tenant=a.id, user=engineer) == 0
    assert run(app_db, "DELETE FROM memberships WHERE user_id = :u", {"u": engineer}, tenant=a.id, user=engineer) == 0
    assert run(app_db, "UPDATE memberships SET role = 'support_engineer' WHERE user_id = :u", {"u": admin},
               tenant=a.id, user=admin) == 0  # not even an admin can edit their own row
    assert owner_role(owner_engine, a.id, engineer) == "support_engineer"
    assert owner_role(owner_engine, a.id, admin) == "tenant_admin"
    # an outsider cannot insert themselves into a tenant
    with owner_engine.begin() as conn:
        outsider = str(conn.execute(text("INSERT INTO users (email, full_name, password_hash) "
                                         "VALUES (:e, 'Out', 'x') RETURNING id"),
                                    {"e": f"out.{uuid.uuid4().hex[:6]}@example.test"}).scalar())
    with pytest.raises(DBAPIError):
        run(app_db, "INSERT INTO memberships (tenant_id, user_id, role) VALUES (:t, :u, 'tenant_admin')",
            {"t": a.id, "u": outsider}, tenant=a.id, user=outsider)
    # writes require a user context at all
    with pytest.raises(DBAPIError):
        run(app_db, "INSERT INTO memberships (tenant_id, user_id, role) VALUES (:t, :u, 'tenant_admin')",
            {"t": a.id, "u": outsider}, tenant=a.id)
    assert run(app_db, "UPDATE memberships SET role = 'read_only_auditor' WHERE tenant_id = :t", {"t": a.id},
               tenant=a.id) == 0


def test_user_context_does_not_leak_through_connection_reuse(settings, owner_engine, tenants):
    a, _ = tenants
    admin_a = uid(owner_engine, a.users["tenant_admin"])
    pooled = Database(settings, role="app", pool_size=1, max_overflow=0)  # one physical connection, reused
    try:
        for _ in range(3):
            with pooled.session(a.id, admin_a) as s:
                assert s.execute(text("SELECT count(*) FROM memberships")).scalar() == 4
                s.commit()
            with pooled.session() as s:  # same connection, no context
                assert s.execute(text("SELECT current_setting('app.user_id', true)")).scalar() in (None, "")
                assert s.execute(text("SELECT current_setting('app.tenant_id', true)")).scalar() in (None, "")
                assert s.execute(text("SELECT count(*) FROM memberships")).scalar() == 0
            with pooled.session(user_id=admin_a) as s:  # rolled-back transaction also clears context
                s.execute(text("SELECT 1"))
                s.rollback()
            with pooled.session() as s:
                assert s.execute(text("SELECT count(*) FROM memberships")).scalar() == 0
    finally:
        pooled.dispose()


# ---- API-level behaviour ----------------------------------------------------------------------------------
def test_unauthorized_role_escalation_via_api(client, owner_engine, tenants):
    a, _ = tenants
    engineer, supervisor, admin = (login(client, a, r) for r in ("support_engineer", "maintenance_supervisor",
                                                                 "tenant_admin"))
    victim = uid(owner_engine, a.users["read_only_auditor"])
    body = {"email": "new.user@example.test", "full_name": "New User", "password": "Long-enough-pass-1",
            "role": "tenant_admin"}
    for headers in (engineer, supervisor):  # non-admin roles cannot administer members
        assert client.post(f"/api/v1/tenants/{a.id}/members", headers=headers, json=body).status_code == 403
        assert client.patch(f"/api/v1/tenants/{a.id}/members/{victim}", headers=headers,
                            json={"role": "tenant_admin"}).status_code == 403
        assert client.delete(f"/api/v1/tenants/{a.id}/members/{victim}", headers=headers).status_code == 403
        assert client.get(f"/api/v1/tenants/{a.id}/members", headers=headers).status_code == 403
    # self-assignment / self-escalation by an admin, and non-assignable roles
    me_id = uid(owner_engine, a.users["tenant_admin"])
    assert client.patch(f"/api/v1/tenants/{a.id}/members/{me_id}", headers=admin,
                        json={"role": "read_only_auditor"}).json()["error"]["code"] == "self_modification"
    assert client.post(f"/api/v1/tenants/{a.id}/members", headers=admin, json={
        **body, "email": a.users["tenant_admin"]}).json()["error"]["code"] == "self_assignment"
    assert client.post(f"/api/v1/tenants/{a.id}/members", headers=admin,
                       json={**body, "role": "platform_admin"}).json()["error"]["code"] == "invalid_role"
    assert client.delete(f"/api/v1/tenants/{a.id}/members/{me_id}", headers=admin).status_code == 403
    assert owner_role(owner_engine, a.id, victim) == "read_only_auditor"


def test_cross_tenant_member_administration_denied_via_api(client, owner_engine, tenants):
    a, b = tenants
    admin_a = login(client, a, "tenant_admin")
    target = uid(owner_engine, b.users["support_engineer"])
    assert client.get(f"/api/v1/tenants/{b.id}/members", headers=admin_a).status_code == 403
    assert client.patch(f"/api/v1/tenants/{b.id}/members/{target}", headers=admin_a,
                        json={"role": "tenant_admin"}).status_code == 403
    assert client.delete(f"/api/v1/tenants/{b.id}/members/{target}", headers=admin_a).status_code == 403
    assert client.post(f"/api/v1/tenants/{b.id}/members", headers=admin_a, json={
        "email": "x@example.test", "full_name": "Intruder", "password": "Long-enough-pass-1",
        "role": "tenant_admin"}).status_code == 403
    assert owner_role(owner_engine, b.id, target) == "support_engineer"


def test_tenant_admin_member_lifecycle_and_immediate_revocation(client, owner_engine, tenants):
    a, _ = tenants
    admin = login(client, a, "tenant_admin")
    created = client.post(f"/api/v1/tenants/{a.id}/members", headers=admin, json={
        "email": f"temp.{uuid.uuid4().hex[:6]}@example.test", "full_name": "Temp Engineer",
        "password": "Long-enough-pass-1", "role": "support_engineer"})
    assert created.status_code == 201, created.text
    new_id = created.json()["user_id"]
    members = client.get(f"/api/v1/tenants/{a.id}/members", headers=admin).json()["items"]
    assert len(members) == 5
    email = next(m["email"] for m in members if m["user_id"] == new_id)
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "Long-enough-pass-1",
                                                    "tenant": a.slug}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/documents", headers=headers).status_code == 200
    assert client.patch(f"/api/v1/tenants/{a.id}/members/{new_id}", headers=admin,
                        json={"role": "read_only_auditor"}).status_code == 200
    assert client.get("/api/v1/audit", headers=headers).status_code == 200  # new role applies immediately
    assert client.delete(f"/api/v1/tenants/{a.id}/members/{new_id}", headers=admin).status_code == 200
    assert client.get("/api/v1/documents", headers=headers).status_code == 403  # revoked despite valid token
    actions = [i["action"] for i in client.get("/api/v1/audit", headers=admin, params={"limit": 50}).json()["items"]]
    assert {"member.added", "member.role_changed", "member.removed"} <= set(actions)


def test_platform_administration_remains_functional(client, platform_admin):
    slug = f"newco-{uuid.uuid4().hex[:6]}"
    tenant = client.post("/api/v1/tenants", headers=platform_admin, json={"slug": slug, "name": "NewCo Test"})
    assert tenant.status_code == 201, tenant.text
    tid = tenant.json()["id"]
    added = client.post(f"/api/v1/tenants/{tid}/members", headers=platform_admin, json={
        "email": f"first.admin.{slug}@example.test", "full_name": "First Admin",
        "password": "Long-enough-pass-1", "role": "tenant_admin"})
    assert added.status_code == 201, added.text
    uid_new = added.json()["user_id"]
    assert len(client.get(f"/api/v1/tenants/{tid}/members", headers=platform_admin).json()["items"]) == 1
    assert client.patch(f"/api/v1/tenants/{tid}/members/{uid_new}", headers=platform_admin,
                        json={"role": "maintenance_supervisor"}).status_code == 200
    assert client.delete(f"/api/v1/tenants/{tid}/members/{uid_new}", headers=platform_admin).status_code == 200
    # a platform admin token carries no tenant, so tenant data endpoints stay closed to it
    assert client.get("/api/v1/documents", headers=platform_admin).status_code == 403


def test_my_tenants_lists_only_own_memberships(client, tenants):
    a, _ = tenants
    items = client.get("/api/v1/tenants/mine", headers=login(client, a, "support_engineer")).json()["items"]
    assert [i["slug"] for i in items] == [a.slug]
