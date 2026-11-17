"""Authorization matrix over EVERY API route: authentication, role permissions and cross-tenant isolation.

The route table is checked against the live OpenAPI routes, so adding an endpoint without declaring its
security expectations here fails the suite.
"""
import uuid

import pytest
from app.core import rbac
from app.core.security import hash_password
from sqlalchemy import text
from support import PASSWORD, REPORT, login, make_tenant

ROLES = ["tenant_admin", "maintenance_supervisor", "support_engineer", "read_only_auditor"]
ANY = "<any authenticated>"
PLATFORM = "<platform admin>"

# (method, path) -> permission. Path params use {name}; tests substitute random UUIDs.
PUBLIC = {("POST", "/api/v1/auth/login"), ("GET", "/api/v1/health")}
SIGNATURE_AUTH = {("POST", "/api/v1/webhooks/{endpoint_id}")}  # authenticated by an HMAC signature, not a bearer token (tests: test_webhooks.py)
TENANT_ROUTES = {
    ("GET", "/api/v1/documents"): "documents:read",
    ("POST", "/api/v1/documents"): "documents:write",
    ("GET", "/api/v1/documents/{document_id}"): "documents:read",
    ("DELETE", "/api/v1/documents/{document_id}"): "documents:delete",
    ("POST", "/api/v1/documents/{document_id}/reprocess"): "documents:reprocess",
    ("GET", "/api/v1/ingestion/jobs"): "documents:read",
    ("GET", "/api/v1/ingestion/jobs/{job_id}"): "documents:read",
    ("POST", "/api/v1/ingestion/jobs/{job_id}/retry"): "documents:reprocess",
    ("GET", "/api/v1/ingestion/status"): "documents:read",
    ("POST", "/api/v1/connectors/{connector_id}/sync"): "connectors:sync",
    ("POST", "/api/v1/webhook-endpoints"): "webhooks:write",
    ("GET", "/api/v1/webhook-endpoints"): "webhooks:read",
    ("PATCH", "/api/v1/webhook-endpoints/{endpoint_id}"): "webhooks:write",
    ("POST", "/api/v1/search"): "search:read",
    ("POST", "/api/v1/ai/ask"): "search:read",
    ("POST", "/api/v1/incidents/extract"): "incidents:write",
    ("GET", "/api/v1/incidents"): "incidents:read",
    ("GET", "/api/v1/incidents/{incident_id}"): "incidents:read",
    ("POST", "/api/v1/incidents/{incident_id}/review"): "incidents:review",
    ("POST", "/api/v1/incidents/{incident_id}/verify-asset"): "incidents:review",
    ("POST", "/api/v1/incidents/{incident_id}/measurements/{name}/verify"): "incidents:review",
    ("GET", "/api/v1/tenant-profile"): "profile:read",
    ("GET", "/api/v1/tickets/{ticket_id}/history"): "tickets:read",
    ("GET", "/api/v1/incidents/{incident_id}/history"): "incidents:read",
    ("GET", "/api/v1/connectors/health"): "connectors:read",
    ("GET", "/api/v1/onboarding/health"): "profile:read",
    ("GET", "/api/v1/evaluation/registry"): "metrics:read",
    ("GET", "/api/v1/evaluation/reports"): "metrics:read",
    ("GET", "/api/v1/observability/summary"): "metrics:read",
    ("PUT", "/api/v1/tenant-profile"): "profile:write",
    ("POST", "/api/v1/tickets"): "tickets:write",
    ("GET", "/api/v1/tickets"): "tickets:read",
    ("GET", "/api/v1/tickets/{ticket_id}"): "tickets:read",
    ("PATCH", "/api/v1/tickets/{ticket_id}"): "tickets:write",
    ("POST", "/api/v1/tickets/{ticket_id}/request-approval"): "tickets:write",
    ("POST", "/api/v1/tickets/{ticket_id}/cancel"): "tickets:write",
    ("POST", "/api/v1/tickets/{ticket_id}/submit"): "tickets:write",
    ("POST", "/api/v1/tickets/{ticket_id}/retry"): "tickets:retry",
    ("GET", "/api/v1/approvals"): "approvals:read",
    ("POST", "/api/v1/approvals/{ticket_id}/decision"): "approvals:decide",
    ("GET", "/api/v1/workflows"): "workflows:read",
    ("GET", "/api/v1/audit"): "audit:read",
    ("GET", "/api/v1/metrics"): "metrics:read",
    ("GET", "/api/v1/connectors"): "connectors:read",
    ("POST", "/api/v1/connectors"): "connectors:write",
    ("GET", "/api/v1/tenants/{tenant_id}/members"): "members:write",
    ("POST", "/api/v1/tenants/{tenant_id}/members"): "members:write",
    ("PATCH", "/api/v1/tenants/{tenant_id}/members/{user_id}"): "members:write",
    ("DELETE", "/api/v1/tenants/{tenant_id}/members/{user_id}"): "members:write",
}
ANY_AUTH = {("GET", "/api/v1/auth/me"), ("GET", "/api/v1/tenants/mine")}
PLATFORM_ONLY = {("POST", "/api/v1/tenants"), ("GET", "/api/v1/platform/audit")}


def live_routes(client):
    """(METHOD, path) pairs from the generated OpenAPI schema (the public, version-stable view)."""
    return {(method.upper(), path) for path, ops in client.app.openapi()["paths"].items()
            if path.startswith("/api/v1") for method in ops}


def fill(path: str, tenant_id: str | None = None) -> str:
    out = path
    for name in ("document_id", "incident_id", "ticket_id", "user_id", "endpoint_id"):
        out = out.replace("{" + name + "}", str(uuid.uuid4()))
    return out.replace("{tenant_id}", tenant_id or str(uuid.uuid4()))


def call(client, method, path, headers=None):
    return client.request(method, path, headers=headers or {}, json={})


@pytest.fixture()
def platform_admin(client, owner_engine):
    email = f"platform.{uuid.uuid4().hex[:8]}@example.test"
    with owner_engine.begin() as conn:
        conn.execute(text("INSERT INTO users (email, full_name, password_hash, is_platform_admin) "
                          "VALUES (:e, 'Platform', :p, true)"), {"e": email, "p": hash_password(PASSWORD)})
    token = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_route_table_covers_every_live_route(client):
    declared = PUBLIC | SIGNATURE_AUTH | set(TENANT_ROUTES) | ANY_AUTH | PLATFORM_ONLY
    live = live_routes(client)
    assert live - declared == set(), f"routes with no security expectations: {sorted(live - declared)}"
    assert declared - live == set(), f"stale entries: {sorted(declared - live)}"
    assert {p for p in TENANT_ROUTES.values()} <= set(rbac.PERMISSIONS)


def test_every_non_public_route_rejects_anonymous_and_garbage_tokens(client):
    for method, path in sorted(live_routes(client) - PUBLIC - SIGNATURE_AUTH):
        for headers in ({}, {"Authorization": "Bearer garbage.token.value"}):
            assert call(client, method, fill(path), headers).status_code == 401, (method, path)


def test_signature_authenticated_routes_reject_anonymous_garbage_and_bearer_tokens_alike(client, apex):
    for method, path in sorted(SIGNATURE_AUTH):
        for headers in ({}, {"Authorization": "Bearer garbage.token.value"}, login(client, apex, "tenant_admin")):  # a valid user token is NOT a webhook signature
            r = client.request(method, fill(path), headers={**headers, "Content-Type": "application/json"}, content=b"{}")
            assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_signature", (method, path)


def test_role_matrix_for_every_tenant_route(client, apex):
    heads = {role: login(client, apex, role) for role in ROLES}
    for (method, path), permission in sorted(TENANT_ROUTES.items()):
        for role in ROLES:
            status = call(client, method, fill(path, tenant_id=apex.id), heads[role]).status_code
            if rbac.can(role, permission):
                assert status not in (401, 403), f"{role} should reach {method} {path}, got {status}"
            else:
                assert status == 403, f"{role} must be denied {method} {path}, got {status}"


def test_platform_admin_cannot_reach_tenant_data_and_tenants_cannot_reach_platform_routes(client, apex,
                                                                                         platform_admin):
    for (method, path), permission in sorted(TENANT_ROUTES.items()):
        if permission == "members:write":
            continue  # platform admins legitimately administer members (covered in membership tests)
        assert call(client, method, fill(path), platform_admin).status_code == 403, (method, path)
    for role in ROLES:
        assert call(client, "POST", "/api/v1/tenants", login(client, apex, role)).status_code == 403


def test_cross_tenant_access_denied_on_every_resource_route(client, owner_engine, ticketing, inventory_server):
    a = make_tenant(owner_engine, "nsa", ticketing.url, inventory_server.url)
    b = make_tenant(owner_engine, "nsb", ticketing.url, inventory_server.url)
    from support import ingest_samples
    ha = {r: login(client, a, r) for r in ROLES}
    hb = {r: login(client, b, r) for r in ROLES}
    ingest_samples(client, ha["support_engineer"])
    inc = client.post("/api/v1/incidents/extract", headers=ha["support_engineer"], json={"report_text": REPORT}).json()
    ticket = client.post("/api/v1/tickets", headers=ha["support_engineer"], json={"incident_id": inc["id"]}).json()
    client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=ha["support_engineer"])
    doc = client.get("/api/v1/documents", headers=ha["support_engineer"]).json()["items"][0]["id"]
    with owner_engine.connect() as conn:
        a_member = str(conn.execute(text("SELECT id FROM users WHERE email = :e"),
                                    {"e": a.users["support_engineer"]}).scalar())

    # B's most privileged users cannot read, change or act on A's objects by guessing their ids.
    for role in ("tenant_admin", "maintenance_supervisor"):
        h = hb[role]
        attempts = [
            ("GET", f"/api/v1/documents/{doc}"), ("GET", f"/api/v1/incidents/{inc['id']}"),
            ("GET", f"/api/v1/tickets/{ticket['id']}"), ("PATCH", f"/api/v1/tickets/{ticket['id']}"),
            ("POST", f"/api/v1/tickets/{ticket['id']}/request-approval"),
            ("POST", f"/api/v1/tickets/{ticket['id']}/cancel"), ("POST", f"/api/v1/tickets/{ticket['id']}/submit"),
            ("POST", f"/api/v1/tickets/{ticket['id']}/retry"),
            ("POST", f"/api/v1/approvals/{ticket['id']}/decision"),
            ("POST", f"/api/v1/incidents/{inc['id']}/review"),
            ("POST", f"/api/v1/incidents/{inc['id']}/verify-asset"),
        ]
        for method, path in attempts:
            body = {"title": "hijack", "decision": "approved", "comment": "hijack attempt"}
            if path.endswith("/review"):
                body = {"decision": "accept", "comment": "hijack attempt"}
            assert client.request(method, path, headers=h, json=body).status_code in (404, 409, 422), (role, path)
        for method, path in (("GET", f"/api/v1/tenants/{a.id}/members"),
                             ("POST", f"/api/v1/tenants/{a.id}/members"),
                             ("PATCH", f"/api/v1/tenants/{a.id}/members/{a_member}"),
                             ("DELETE", f"/api/v1/tenants/{a.id}/members/{a_member}")):
            assert client.request(method, path, headers=h, json={"role": "tenant_admin"}).status_code == 403
    # List endpoints only ever show the caller's own tenant data.
    hadm = hb["tenant_admin"]
    for path in ("documents", "incidents", "tickets", "workflows"):
        assert client.get(f"/api/v1/{path}", headers=hadm).json()["items"] == [], path
    assert client.get("/api/v1/approvals", headers=hadm).json()["items"] == []
    assert client.get("/api/v1/metrics", headers=hadm).json()["tickets_by_state"] == {}
    audit_b = client.get("/api/v1/audit", headers=hadm).json()["items"]
    assert all(e["entity_id"] not in (ticket["id"], inc["id"], doc) for e in audit_b)
    assert {c["name"] for c in client.get("/api/v1/connectors", headers=hadm).json()["items"]} \
        == {"mock-ticketing", "mock-inventory"} and a.id != b.id
    assert client.get("/api/v1/ingestion/status", headers=hadm).json()["chunks"] == 0
    assert client.post("/api/v1/search", headers=hb["support_engineer"],
                       json={"query": "drive-end bearing vibration"}).json()["items"] == []
    # ...and A's data is untouched by those attempts.
    assert client.get(f"/api/v1/tickets/{ticket['id']}", headers=ha["support_engineer"]).json()["state"] \
        == "PENDING_APPROVAL"
