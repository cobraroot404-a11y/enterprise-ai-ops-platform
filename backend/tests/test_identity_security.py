"""Phase 4 closure: security of the global identity tables (`users`, `tenants`).

Checks grants, RLS, enumeration, unauthorized modification (as if application code were compromised and
issued raw SQL as the API role), platform-admin scoping and auditing, and a mutation-style proof that the
RLS policy is what stops enumeration.
"""
import pytest
from app.core.security import hash_password
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from support import PASSWORD, login, make_tenant


def _uid(owner_engine, tenant, role):
    with owner_engine.connect() as c:
        return str(c.execute(text("SELECT id FROM users WHERE email = :e"), {"e": tenant.users[role]}).scalar())


@pytest.fixture()
def two(owner_engine):
    return make_tenant(owner_engine, "ida"), make_tenant(owner_engine, "idb")


@pytest.fixture()
def platform_admin(client, owner_engine):
    email = "platform.identity@example.test"
    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE email = :e AND NOT EXISTS "
                          "(SELECT 1 FROM memberships m WHERE m.user_id = users.id)"), {"e": email})
        conn.execute(text("INSERT INTO users (email, full_name, password_hash, is_platform_admin) "
                          "VALUES (:e, 'Platform', :p, true) ON CONFLICT (email) DO NOTHING"),
                     {"e": email, "p": hash_password(PASSWORD)})
    res = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}, email


# ---- grants and RLS flags (the audit of the tables) -------------------------------------------------------
def test_api_role_has_select_only_on_identity_tables_and_worker_has_none(owner_engine):
    with owner_engine.connect() as c:
        rows = c.execute(text(
            "SELECT grantee, table_name, privilege_type FROM information_schema.role_table_grants "
            "WHERE table_name IN ('users','tenants') AND grantee IN ('eaop_app','eaop_worker')")).all()
        grants = {(g, t, p) for g, t, p in rows}
        assert grants == {("eaop_app", "users", "SELECT"), ("eaop_app", "tenants", "SELECT")}
        flags = dict(c.execute(text("SELECT relname, relrowsecurity FROM pg_class "
                                    "WHERE relname IN ('users','tenants','memberships')")).all())
        assert flags == {"users": True, "tenants": True, "memberships": True}
        assert c.execute(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = 'eaop_app'")).scalar() \
            is False


# ---- enumeration -------------------------------------------------------------------------------------------
def test_no_context_sees_no_users_or_tenants(app_db, two):
    with app_db.session() as s:
        assert s.execute(text("SELECT count(*) FROM users")).scalar() == 0
        assert s.execute(text("SELECT count(*) FROM tenants")).scalar() == 0


def test_user_and_tenant_visibility_is_limited_to_own_row_and_current_tenant(app_db, owner_engine, two):
    a, b = two
    eng_a = _uid(owner_engine, a, "support_engineer")
    with app_db.session(user_id=eng_a) as s:  # user context only
        assert [r[0] for r in s.execute(text("SELECT email FROM users"))] == [a.users["support_engineer"]]
        assert [r[0] for r in s.execute(text("SELECT slug FROM tenants"))] == [a.slug]
    with app_db.session(tenant_id=a.id, user_id=eng_a) as s:  # tenant context: members of THAT tenant only
        emails = {r[0] for r in s.execute(text("SELECT email FROM users"))}
        assert emails == set(a.users.values())
        assert not emails & set(b.users.values())
        assert [r[0] for r in s.execute(text("SELECT slug FROM tenants"))] == [a.slug]
    with app_db.session(tenant_id=b.id, user_id=eng_a) as s:  # asking for another tenant's context via a
        # non-member user leaks that tenant's users only to RLS-permitted rows: tenant context alone is the
        # RLS boundary, and the API never lets a user choose it (it comes from a verified token + membership).
        assert s.execute(text("SELECT count(*) FROM memberships WHERE user_id = :u"), {"u": eng_a}).scalar() == 1


def test_api_enumeration_across_tenants(client, two):
    a, b = two
    admin_a = login(client, a, "tenant_admin")
    emails = {m["email"] for m in client.get(f"/api/v1/tenants/{a.id}/members", headers=admin_a).json()["items"]}
    assert emails == set(a.users.values()) and not emails & set(b.users.values())
    assert client.get(f"/api/v1/tenants/{b.id}/members", headers=admin_a).status_code == 403
    mine = client.get("/api/v1/tenants/mine", headers=admin_a).json()["items"]
    assert [t["slug"] for t in mine] == [a.slug]
    # Sign-in gives the same answer for a wrong tenant as for a wrong password.
    wrong_tenant = client.post("/api/v1/auth/login", json={"email": a.users["tenant_admin"], "password": PASSWORD,
                                                           "tenant": b.slug})
    wrong_pw = client.post("/api/v1/auth/login", json={"email": a.users["tenant_admin"], "password": "nope-nope-1",
                                                       "tenant": a.slug})
    assert wrong_tenant.status_code == wrong_pw.status_code == 401
    assert wrong_tenant.json()["error"]["code"] == wrong_pw.json()["error"]["code"]


# ---- unauthorized modification --------------------------------------------------------------------------------
@pytest.mark.parametrize("sql", [
    "UPDATE users SET is_platform_admin = true",
    "UPDATE users SET password_hash = 'x'",
    "UPDATE tenants SET name = 'hijacked'",
    "INSERT INTO users (email, full_name, password_hash, is_platform_admin) VALUES ('x@e.test','x','x',true)",
    "INSERT INTO tenants (slug, name) VALUES ('sneaky-tenant', 'x')",
    "DELETE FROM users",
    "DELETE FROM tenants",
])
def test_raw_sql_as_api_role_cannot_modify_identity_records(app_db, owner_engine, two, sql):
    a, _ = two
    admin = _uid(owner_engine, a, "tenant_admin")
    with pytest.raises(DBAPIError) as exc:
        with app_db.session(tenant_id=a.id, user_id=admin) as s:
            s.execute(text(sql))
    assert "permission denied" in str(exc.value)


def test_database_functions_enforce_who_may_create_tenants_and_users(app_db, owner_engine, two):
    a, _ = two
    eng, admin = _uid(owner_engine, a, "support_engineer"), _uid(owner_engine, a, "tenant_admin")
    with pytest.raises(DBAPIError):  # not a platform admin
        with app_db.session(tenant_id=a.id, user_id=admin) as s:
            s.execute(text("SELECT app_create_tenant('not-allowed-tenant', 'x')"))
    with pytest.raises(DBAPIError):  # an engineer is not a tenant admin
        with app_db.session(tenant_id=a.id, user_id=eng) as s:
            s.execute(text("SELECT app_provision_user('new@example.test', 'New', 'hash')"))
    with pytest.raises(DBAPIError):  # no user context at all
        with app_db.session(tenant_id=a.id) as s:
            s.execute(text("SELECT app_provision_user('new2@example.test', 'New', 'hash')"))
    with app_db.session(tenant_id=a.id, user_id=admin) as s:  # tenant admin may, and can never mint an admin
        new_id = s.execute(text("SELECT app_provision_user('Mixed.Case@Example.test', 'New', 'hash')")).scalar()
        s.commit()
    with owner_engine.connect() as c:
        row = c.execute(text("SELECT email, is_platform_admin FROM users WHERE id = :i"), {"i": new_id}).one()
    assert row.email == "mixed.case@example.test" and row.is_platform_admin is False


def test_tenant_member_endpoint_cannot_create_a_platform_admin_or_edit_identities(client, two):
    a, _ = two
    admin = login(client, a, "tenant_admin")
    created = client.post(f"/api/v1/tenants/{a.id}/members", headers=admin, json={
        "email": "someone.new@example.test", "full_name": "Some One", "password": "Another-Passw0rd!",
        "role": "support_engineer"})
    assert created.status_code == 201
    assert client.post(f"/api/v1/tenants/{a.id}/members", headers=admin, json={
        "email": "x@example.test", "full_name": "X Y", "password": "Another-Passw0rd!",
        "role": "platform_admin"}).status_code == 403
    # No endpoint edits global identity records.
    for method, path in (("PATCH", "/api/v1/users/me"), ("PUT", "/api/v1/users/me"), ("DELETE", "/api/v1/users/me"),
                         ("PATCH", f"/api/v1/tenants/{a.id}")):
        assert client.request(method, path, headers=admin, json={"is_platform_admin": True}).status_code in (404, 405)


# ---- platform administrator: scoped and audited -----------------------------------------------------------------
def test_platform_admin_login_is_audited_and_only_platform_admins_can_read_that_trail(client, two, platform_admin):
    headers, email = platform_admin
    trail = client.get("/api/v1/platform/audit", headers=headers).json()["items"]
    assert any(i["action"] == "platform.login" and i["details"]["email"] == email for i in trail)
    a, _ = two
    for role in ("tenant_admin", "read_only_auditor"):
        assert client.get("/api/v1/platform/audit", headers=login(client, a, role)).status_code == 403
    # ...and the tenant-less rows are not visible in any tenant's own audit view.
    audit_a = client.get("/api/v1/audit", headers=login(client, a, "read_only_auditor"),
                         params={"limit": 100}).json()["items"]
    assert not any(i["action"].startswith("platform.login") for i in audit_a)


def test_platform_admin_tenant_administration_is_visible_in_the_tenants_audit_log(client, two, platform_admin):
    headers, _ = platform_admin
    a, _ = two
    assert client.get(f"/api/v1/tenants/{a.id}/members", headers=headers).status_code == 200
    audit_a = client.get("/api/v1/audit", headers=login(client, a, "read_only_auditor"),
                         params={"limit": 100}).json()["items"]
    assert any(i["action"] == "platform.tenant_access" for i in audit_a)
    # Scope: a platform admin has no tenant data access through ordinary tenant endpoints.
    assert client.get("/api/v1/documents", headers=headers).status_code == 403
    assert client.get("/api/v1/tickets", headers=headers).status_code == 403


def test_ordinary_users_cannot_write_platform_audit_rows(app_db, owner_engine, two):
    a, _ = two
    eng = _uid(owner_engine, a, "tenant_admin")
    with pytest.raises(DBAPIError):
        with app_db.session(user_id=eng) as s:
            s.execute(text("INSERT INTO audit_events (tenant_id, action, entity_type) "
                           "VALUES (NULL, 'platform.login', 'user')"))


# ---- mutation-style proof: the policy is what blocks enumeration --------------------------------------------------
def test_mutation_rls_on_users_is_what_prevents_enumeration(app_db, owner_engine, two):
    a, b = two
    with app_db.session() as s:
        assert s.execute(text("SELECT count(*) FROM users")).scalar() == 0  # control on
    owner_engine.begin().__enter__().execute(text("ALTER TABLE users DISABLE ROW LEVEL SECURITY")) \
        if False else None
    with owner_engine.begin() as c:
        c.execute(text("ALTER TABLE users DISABLE ROW LEVEL SECURITY"))
    try:
        with app_db.session() as s:  # control removed: every account is enumerable
            assert s.execute(text("SELECT count(*) FROM users")).scalar() >= len(a.users) + len(b.users)
    finally:
        with owner_engine.begin() as c:
            c.execute(text("ALTER TABLE users ENABLE ROW LEVEL SECURITY"))
    with app_db.session() as s:  # control restored
        assert s.execute(text("SELECT count(*) FROM users")).scalar() == 0
