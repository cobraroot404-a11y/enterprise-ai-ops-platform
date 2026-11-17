import time
import uuid

import pytest
from app.core.security import create_token, verify_password
from app.database.session import Database
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from support import PASSWORD, REPORT, SAMPLES, ingest_samples, login, make_tenant


def _user_id(owner_engine, email):
    with owner_engine.connect() as conn:
        return conn.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email}).scalar()


# ---- authentication ---------------------------------------------------------------------------------
def test_password_hash_roundtrip():
    from app.core.security import hash_password
    stored = hash_password("correct horse")
    assert verify_password("correct horse", stored) and not verify_password("wrong", stored)
    assert not verify_password("x", "garbage")


def test_login_rejects_bad_credentials_uniformly(client, apex):
    wrong_pw = client.post("/api/v1/auth/login", json={"email": apex.users["tenant_admin"], "password": "nope",
                                                       "tenant": apex.slug})
    no_user = client.post("/api/v1/auth/login", json={"email": "ghost@example.test", "password": "nope",
                                                      "tenant": apex.slug})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json()["error"]["code"] == no_user.json()["error"]["code"] == "invalid_credentials"


def test_expired_token_rejected(client, apex, owner_engine, settings):
    uid = _user_id(owner_engine, apex.users["support_engineer"])
    token = create_token(settings.jwt_secret, uid, uuid.UUID(apex.id), "support_engineer", 1,
                         now=time.time() - 3600)
    resp = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401 and resp.json()["error"]["code"] == "token_expired"


def test_tampered_and_foreign_signed_tokens_rejected(client, apex, owner_engine, settings):
    uid = _user_id(owner_engine, apex.users["support_engineer"])
    good = create_token(settings.jwt_secret, uid, uuid.UUID(apex.id), "support_engineer", 5)
    head, payload, sig = good.split(".")
    tampered = f"{head}.{payload}.{sig[:-3]}abc"
    forged = create_token("a-different-secret-entirely-0123456789", uid, uuid.UUID(apex.id), "tenant_admin", 5)
    for token in (tampered, forged, "not.a.jwt"):
        resp = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401, token
    assert client.get("/api/v1/documents").status_code == 401


# ---- role escalation --------------------------------------------------------------------------------
def test_role_claim_in_token_does_not_grant_privileges(client, apex, owner_engine, settings):
    """A validly signed token claiming a higher role must not escalate: the DB role decides."""
    uid = _user_id(owner_engine, apex.users["support_engineer"])
    token = create_token(settings.jwt_secret, uid, uuid.UUID(apex.id), "tenant_admin", 5)
    resp = client.post("/api/v1/connectors", headers={"Authorization": f"Bearer {token}"},
                       json={"kind": "crm", "name": "evil", "base_url": "http://example.test"})
    assert resp.status_code == 403 and resp.json()["error"]["code"] == "insufficient_role"


def test_role_matrix(client, apex_loaded):
    eng = login(client, apex_loaded, "support_engineer")
    aud = login(client, apex_loaded, "read_only_auditor")
    sup = login(client, apex_loaded, "maintenance_supervisor")
    adm = login(client, apex_loaded, "tenant_admin")
    # auditor: read-only
    assert client.get("/api/v1/documents", headers=aud).status_code == 200
    assert client.post("/api/v1/documents", headers=aud, data={"kind": "other"},
                       files={"file": ("a.txt", b"some text here")}).status_code == 403
    assert client.post("/api/v1/incidents/extract", headers=aud, json={"report_text": REPORT}).status_code == 403
    # engineers cannot read the audit log, auditors/admins can
    assert client.get("/api/v1/audit", headers=eng).status_code == 403
    assert client.get("/api/v1/audit", headers=aud).status_code == 200
    # supervisors cannot manage connectors; admins can
    assert client.get("/api/v1/connectors", headers=sup).status_code == 403
    assert client.get("/api/v1/connectors", headers=adm).status_code == 200
    # tenant users cannot create tenants or add members elsewhere
    rogue = client.post("/api/v1/tenants", headers=adm, json={"slug": "rogue-tenant", "name": "Rogue"})
    assert rogue.status_code == 403


def test_tenant_admin_cannot_manage_other_tenants_members(client, owner_engine, apex):
    other = make_tenant(owner_engine, "other")
    adm = login(client, apex, "tenant_admin")
    resp = client.post(f"/api/v1/tenants/{other.id}/members", headers=adm,
                       json={"email": "x@example.test", "full_name": "Intruder", "password": "Intruder-pass-1",
                             "role": "tenant_admin"})
    assert resp.status_code == 403


# ---- cross-tenant API access ------------------------------------------------------------------------
@pytest.fixture()
def two_tenants(client, owner_engine, ticketing, inventory_server):
    a = make_tenant(owner_engine, "apex", ticketing.url, inventory_server.url)
    b = make_tenant(owner_engine, "meridian", ticketing.url, inventory_server.url)
    ha = login(client, a, "support_engineer")
    ingest_samples(client, ha)
    return a, b


def test_cross_tenant_api_access_denied(client, two_tenants):
    a, b = two_tenants
    ha, hb = login(client, a, "support_engineer"), login(client, b, "support_engineer")
    incident = client.post("/api/v1/incidents/extract", headers=ha, json={"report_text": REPORT}).json()
    ticket = client.post("/api/v1/tickets", headers=ha, json={"incident_id": incident["id"]}).json()
    doc_id = client.get("/api/v1/documents", headers=ha).json()["items"][0]["id"]

    # B's valid token cannot read, modify or act on A's resources by guessing IDs.
    assert client.get(f"/api/v1/incidents/{incident['id']}", headers=hb).status_code == 404
    assert client.get(f"/api/v1/tickets/{ticket['id']}", headers=hb).status_code == 404
    assert client.get(f"/api/v1/documents/{doc_id}", headers=hb).status_code == 404
    assert client.patch(f"/api/v1/tickets/{ticket['id']}", headers=hb, json={"title": "hijacked"}).status_code == 404
    assert client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=hb).status_code == 404
    assert client.post("/api/v1/tickets", headers=hb, json={"incident_id": incident["id"]}).status_code == 404
    for path in ("documents", "incidents", "tickets", "workflows"):
        assert client.get(f"/api/v1/{path}", headers=hb).json()["items"] == []


def test_login_to_foreign_tenant_denied(client, two_tenants):
    a, b = two_tenants
    resp = client.post("/api/v1/auth/login", json={"email": b.users["tenant_admin"], "password": PASSWORD,
                                                   "tenant": a.slug})
    assert resp.status_code == 401


def test_forged_tenant_claim_denied(client, two_tenants, owner_engine, settings):
    a, b = two_tenants
    uid_b = _user_id(owner_engine, b.users["tenant_admin"])
    token = create_token(settings.jwt_secret, uid_b, uuid.UUID(a.id), "tenant_admin", 5)  # B user, A tenant
    resp = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_cross_tenant_vector_retrieval_isolated(client, two_tenants):
    a, b = two_tenants
    ha, hb = login(client, a, "support_engineer"), login(client, b, "support_engineer")
    query = {"query": "drive-end bearing vibration exceeds 7.1 mm/s", "k": 10}
    assert len(client.post("/api/v1/search", headers=ha, json=query).json()["items"]) > 0
    assert client.post("/api/v1/search", headers=hb, json=query).json()["items"] == []
    answer = client.post("/api/v1/ai/ask", headers=hb, json={"question": "What causes pump vibration?"}).json()
    assert answer["insufficient_evidence"] is True and answer["citations"] == []
    # B's own data stays separate: ingest a B-only fact and confirm A cannot see it.
    client.post("/api/v1/documents", headers=hb, data={"kind": "other"},
                files={"file": ("b-only.txt", b"Meridian truck T-77 uses special zebra coolant.")})
    seen_by_a = client.post("/api/v1/search", headers=ha, json={"query": "zebra coolant T-77"}).json()["items"]
    assert not any("zebra" in h["text"] for h in seen_by_a)


# ---- row-level security / connection pooling --------------------------------------------------------
def test_rls_blocks_cross_tenant_rows_even_without_app_filters(app_db, two_tenants):
    a, b = two_tenants
    with app_db.session(a.id) as s:
        own = s.execute(text("SELECT count(*) FROM document_chunks")).scalar()  # note: no WHERE clause
        assert own > 0
        assert s.execute(text("SELECT count(*) FROM document_chunks WHERE tenant_id = :b"),
                         {"b": b.id}).scalar() == 0
    with app_db.session(b.id) as s:
        assert s.execute(text("SELECT count(*) FROM document_chunks")).scalar() == 0
        assert s.execute(text("SELECT count(*) FROM documents")).scalar() == 0
    with app_db.session() as s:  # no tenant context at all: fail closed
        assert s.execute(text("SELECT count(*) FROM document_chunks")).scalar() == 0
        assert s.execute(text("SELECT count(*) FROM audit_events")).scalar() == 0


def test_rls_blocks_writing_into_another_tenant(app_db, two_tenants):
    a, b = two_tenants
    with app_db.session(b.id) as s, pytest.raises(DBAPIError):
        s.execute(text("INSERT INTO documents (tenant_id, source_key, filename, kind) "
                       "VALUES (:t, 'x', 'x', 'other')"), {"t": a.id})
        s.commit()


def test_tenant_context_does_not_leak_through_connection_pool(settings, two_tenants):
    a, _ = two_tenants
    pooled = Database(settings, role="app", pool_size=1, max_overflow=0)  # force connection reuse
    try:
        for _ in range(3):
            with pooled.session(a.id) as s:
                assert s.execute(text("SELECT count(*) FROM documents")).scalar() > 0
                s.commit()
            with pooled.session() as s:  # same physical connection, no tenant
                assert s.execute(text("SELECT current_setting('app.tenant_id', true)")).scalar() in (None, "")
                assert s.execute(text("SELECT count(*) FROM documents")).scalar() == 0
            with pooled.session(a.id) as s:  # rollback path also clears context
                s.execute(text("SELECT 1"))
                s.rollback()
            with pooled.session() as s:
                assert s.execute(text("SELECT count(*) FROM documents")).scalar() == 0
    finally:
        pooled.dispose()


def test_app_role_cannot_bypass_rls_or_modify_audit(settings, app_db, two_tenants):
    a, _ = two_tenants
    with app_db.session(a.id) as s:
        assert s.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one() \
            == (False, False)
        s.execute(text("SELECT 1"))
    with app_db.session(a.id) as s, pytest.raises(DBAPIError):
        s.execute(text("UPDATE audit_events SET action = 'tampered'"))
    with app_db.session(a.id) as s, pytest.raises(DBAPIError):
        s.execute(text("DELETE FROM audit_events"))


def test_audit_log_is_append_only_even_for_owner(owner_engine, two_tenants):
    with owner_engine.connect() as conn, pytest.raises(DBAPIError):
        conn.execute(text("UPDATE audit_events SET action = 'tampered'"))
        conn.commit()


def test_sample_files_exist():
    assert (SAMPLES / "apex_cp200_pump_manual.pdf").exists()
