"""Empirical error probes for V41-17.03 (Batch 3.1): which error statuses does each of the 45 operations ACTUALLY emit?

`probe_all` exercises every operation with a fixed set of failure scenarios and returns {operation: {status: [scenario names]}} plus the raw error bodies, so the OpenAPI error
declarations (app.api.v1.error_contracts.ERROR_STATUSES) are checked against observed behaviour in both directions: nothing declared that no scenario produced, nothing observed
that is not declared. Scenarios: no/invalid credentials, each tenant role, an unknown resource id, an invalid body or parameter, an oversize body, operation-specific state conflicts,
a duplicate create, login throttling, server-busy concurrency limits, an unsupported/oversize upload, and injected database and internal failures."""
import re
import uuid

from app.core.security import hash_password
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from support import PASSWORD, REPORT, SAMPLES

HTTP = ("get", "post", "put", "patch", "delete")
PUBLIC = {("post", "/api/v1/auth/login"), ("get", "/api/v1/health")}
VALID_BODIES = {
    ("patch", "/api/v1/tenants/{tenant_id}/members/{user_id}"): {"role": "support_engineer"},
    ("patch", "/api/v1/tickets/{ticket_id}"): {"title": "Edited title"},
    ("post", "/api/v1/approvals/{ticket_id}/decision"): {"decision": "approved", "comment": "Looks fine."},
    ("post", "/api/v1/incidents/{incident_id}/review"): {"decision": "accept", "comment": "Justified for the probe."},
    ("post", "/api/v1/incidents/{incident_id}/measurements/{name}/verify"): {"decision": "approve", "comment": "Checked the printout.", "expected_trust_status": "UNVERIFIED"},
}


def fill(path, tenant_id=None, ticket=None, incident=None, doc=None, user=None, name="vibration_mm_s"):
    def sub(m):
        key = m.group(1)
        return {"tenant_id": tenant_id, "ticket_id": ticket, "incident_id": incident, "document_id": doc, "user_id": user, "name": name}.get(key) or str(uuid.uuid4())
    return re.sub(r"\{([^}]+)\}", sub, path)


def template_of(templates, method, path):
    """Map a concrete request path back to its OpenAPI path template (literal routes win over parameterised ones)."""
    path = path.split("?")[0]
    for tpl in sorted((t for t in templates), key=lambda t: t.count("{")):
        if re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", tpl), path):
            return tpl
    raise AssertionError(f"no OpenAPI template for {method} {path}")


class Probe:
    def __init__(self, templates):
        self.templates = {m: [t for mm, t in templates if mm == m] for m in HTTP}
        self.obs = {}      # op -> status -> [scenarios]
        self.bodies = []   # (op, scenario, status, body_text, headers)

    def add(self, method, path, scenario, resp):
        if resp.status_code >= 400:
            op = f"{method.upper()} {template_of(self.templates[method], method, path)}"
            self.obs.setdefault(op, {}).setdefault(resp.status_code, []).append(scenario)
            self.bodies.append((op, scenario, resp.status_code, resp.text, dict(resp.headers)))
        return resp


def probe_all(client, strict_client, w, owner_engine, app_db, settings, monkeypatch, ticketing):
    """w is the `world` fixture of test_api_contract (tenant, tokens, incidents, tickets)."""
    spec = client.get("/openapi.json").json()
    ops = [(m, p, o) for p, ops_ in spec["paths"].items() for m, o in ops_.items() if m in HTTP]
    P = Probe([(m, p) for m, p, _ in ops])
    tid = str(w["tenant"].id)
    eng, sup, adm, aud = w["eng"], w["sup"], w["adm"], w["aud"]
    roles = {"engineer": eng, "supervisor": sup, "admin": adm, "auditor": aud}
    other_user = str(uuid.uuid4())
    # ---- platform admin token (for operations only a platform administrator may call)
    email = f"platform.err.{uuid.uuid4().hex[:6]}@example.test"
    with owner_engine.begin() as conn:
        conn.execute(text("INSERT INTO users (email, full_name, password_hash, is_platform_admin) VALUES (:e, 'Platform', :p, true)"), {"e": email, "p": hash_password(PASSWORD)})
    padm = {"Authorization": "Bearer " + client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]}

    def call(m, p, scenario, headers=None, **kw):
        return P.add(m, p, scenario, client.request(m.upper(), p, headers=headers, **kw))

    for m, p, o in ops:
        has_body = "requestBody" in o
        json_body = has_body and "application/json" in o["requestBody"]["content"]
        path = fill(p, tenant_id=tid)
        # -- credentials
        if (m, p) not in PUBLIC:
            call(m, path, "no_credentials", json={} if json_body else None)
            call(m, path, "invalid_token", headers={"Authorization": "Bearer not.a.token"}, json={} if json_body else None)
        # -- each tenant role, empty body (role checks run before body validation)
        for rname, hdr in roles.items():
            if (m, p) in PUBLIC:
                break
            call(m, path, f"role:{rname}", headers=hdr, json={} if json_body else None)
        if (m, p) not in PUBLIC and ("/platform/" in p or p == "/api/v1/tenants"):
            call(m, path, "platform_admin_wrong_body", headers=padm, json={} if json_body else None)
        # -- unknown resource id (as the tenant administrator)
        if "{" in p:
            call(m, fill(p), "unknown_id:admin", headers=adm, json={} if json_body else None)
            call(m, fill(p), "unknown_id:supervisor", headers=sup, json={} if json_body else None)
        # -- invalid body / params
        if json_body:
            for bad in ("not-an-object", {"unexpected": [1, 2, {"x": None}]}, []):
                call(m, path, "invalid_body:admin", headers=adm, json=bad)
        # -- a well-formed body for an id that does not exist (the 404 path behind body validation) and invalid query / path values
        if "{" in p and json_body and (m, p) in VALID_BODIES:
            for rname in ("admin", "supervisor", "engineer"):
                call(m, fill(p), f"unknown_id_valid_body:{rname}", headers={"admin": adm, "supervisor": sup, "engineer": eng}[rname], json=VALID_BODIES[(m, p)])
        for prm in o.get("parameters", []):
            if prm["in"] == "query" and prm["schema"].get("type") == "integer":
                call(m, path, "invalid_query_integer", headers=adm, params={prm["name"]: "abc"})
                call(m, path, "query_out_of_range", headers=adm, params={prm["name"]: "-5"})
            if prm["in"] == "query" and prm["name"] in ("order", "status"):
                call(m, path, "invalid_query_enum", headers=adm, params={prm["name"]: "zzz"})
        # -- oversize body
        if json_body:
            call(m, path, "oversize_body", headers=adm, json={"report_text": "x" * 2_000_000})
    # ---- targeted probes behind earlier checks: platform administrator paths, unknown member / incident with a valid body
    call("get", "/api/v1/platform/audit", "platform_invalid_limit", headers=padm, params={"limit": "abc"})
    call("get", "/api/v1/platform/audit", "platform_limit_out_of_range", headers=padm, params={"limit": "-5"})
    for m_, p_, kw_ in (("get", "/api/v1/tenants/{tenant_id}/members", {}), ("post", "/api/v1/tenants/{tenant_id}/members", {"json": {"email": f"n.{uuid.uuid4().hex[:6]}@example.test", "full_name": "New Person", "password": "A-long-password-123", "role": "support_engineer"}}),
                        ("patch", "/api/v1/tenants/{tenant_id}/members/{user_id}", {"json": {"role": "support_engineer"}}), ("delete", "/api/v1/tenants/{tenant_id}/members/{user_id}", {})):
        call(m_, fill(p_), "platform_admin_unknown_tenant", headers=padm, **kw_)
        call(m_, fill(p_, tenant_id=tid), "own_tenant_unknown_member", headers=adm, **kw_)
    call("post", "/api/v1/tickets", "unknown_incident", headers=eng, json={"incident_id": str(uuid.uuid4())})
    call("post", "/api/v1/connectors", "destination_rejected", headers=adm, json={"kind": "ticketing", "name": f"bad-{uuid.uuid4().hex[:6]}", "base_url": "http://169.254.169.254/", "config": {}})
    call("post", "/api/v1/incidents/extract", "no_numbers_or_assets", headers=eng, json={"report_text": "short"})
    # ---- login: bad credentials, invalid body, throttle
    call("post", "/api/v1/auth/login", "bad_credentials", json={"email": w["tenant"].users["tenant_admin"], "password": "wrong-password-123", "tenant": w["tenant"].slug})
    call("post", "/api/v1/auth/login", "invalid_body", json={"email": 1})
    for _ in range(12):
        r = call("post", "/api/v1/auth/login", "throttle", json={"email": f"nobody.{uuid.uuid4().hex[:6]}@example.test", "password": "wrong-password-123", "tenant": w["tenant"].slug})
        if r.status_code == 429:
            break
    # a repeatedly failing identity: the lockout is per identity + address
    for _ in range(12):
        r = call("post", "/api/v1/auth/login", "throttle_known_user", json={"email": w["tenant"].users["support_engineer"], "password": "wrong-password-123", "tenant": w["tenant"].slug})
        if r.status_code == 429:
            break
    # ---- operation-specific state conflicts and duplicates
    t = w["tickets"]
    inc = w["incidents"]
    call("post", "/api/v1/tickets", "duplicate_ticket", headers=eng, json={"incident_id": inc[0]["id"]})
    call("patch", f"/api/v1/tickets/{t[0]['id']}", "edit_non_draft", headers=eng, json={"title": "Edited title"})
    call("post", f"/api/v1/tickets/{t[0]['id']}/request-approval", "request_on_decided", headers=eng)
    call("post", f"/api/v1/approvals/{t[0]['id']}/decision", "decide_not_pending", headers=sup, json={"decision": "approved", "comment": "again"})
    call("post", f"/api/v1/tickets/{t[3]['id']}/submit", "submit_not_approved", headers=eng)
    call("post", f"/api/v1/tickets/{t[3]['id']}/retry", "retry_not_failed", headers=sup)
    client.post(f"/api/v1/tickets/{t[3]['id']}/cancel", headers=eng)
    call("post", f"/api/v1/tickets/{t[3]['id']}/cancel", "cancel_twice", headers=eng)
    call("post", f"/api/v1/tickets/{t[0]['id']}/cancel", "cancel_decided", headers=eng)
    call("post", f"/api/v1/incidents/{inc[0]['id']}/review", "review_not_needs_review", headers=sup, json={"decision": "accept", "comment": "Already fine."})
    unreg = client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": "Pump Z-999 shows abnormal vibration at 8.4 mm/s with grinding noise."}).json()
    client.post(f"/api/v1/incidents/{unreg['id']}/review", headers=sup, json={"decision": "reject", "comment": "Rejected for the probe."})
    call("post", f"/api/v1/incidents/{unreg['id']}/verify-asset", "verify_asset_rejected", headers=sup)
    # Batch 9: a reprocessing job that is not FAILED cannot be retried (409); the job reads and the reprocess operation use the generic scenarios above
    doc_id = client.get("/api/v1/documents", headers=eng, params={"limit": 1}).json()["items"][0]["id"]
    job = client.post(f"/api/v1/documents/{doc_id}/reprocess", headers=sup)
    if job.status_code == 202:
        call("post", f"/api/v1/ingestion/jobs/{job.json()['id']}/retry", "retry_job_not_failed", headers=sup)
    # Batch 11B: webhook endpoint conflicts and the signed receiver (unsupported type, invalid payload, replay, flood)
    import time as _time

    from app.ingestion import webhooks as _wh
    monkeypatch.setenv("WEBHOOK_PROBE_SECRET", "probe-secret-value-0123456789")
    monkeypatch.setenv("WEBHOOK_PROBE_NEXT", "probe-next-secret-value-9876543210")
    ep_name = f"probe-{uuid.uuid4().hex[:6]}"
    ep = client.post("/api/v1/webhook-endpoints", headers=adm, json={"name": ep_name, "secret_ref": "WEBHOOK_PROBE_SECRET", "config": {"id_field": "id"}}).json()
    call("post", "/api/v1/webhook-endpoints", "webhook_endpoint_duplicate_name", headers=adm, json={"name": ep_name, "secret_ref": "WEBHOOK_PROBE_SECRET", "config": {"id_field": "id"}})
    client.patch(f"/api/v1/webhook-endpoints/{ep['id']}", headers=adm, json={"secret_ref": "WEBHOOK_PROBE_NEXT"})
    call("patch", f"/api/v1/webhook-endpoints/{uuid.uuid4()}", "webhook_endpoint_unknown", headers=adm, json={"status": "disabled"})
    call("patch", f"/api/v1/webhook-endpoints/{ep['id']}", "webhook_secret_reference_reused", headers=adm, json={"secret_ref": "WEBHOOK_PROBE_SECRET"})

    def delivery(path_id, body: bytes, delivery_id: str, content_type="application/json", secret="probe-next-secret-value-9876543210", scenario="webhook_delivery"):
        ts = str(int(_time.time()))
        hdrs = {"Content-Type": content_type, "X-Webhook-Timestamp": ts, "X-Webhook-Delivery-Id": delivery_id, "X-Webhook-Signature": _wh.sign(secret, ts, delivery_id, body)}
        return call("post", f"/api/v1/webhooks/{path_id}", scenario, headers=hdrs, content=body)

    delivery(ep["id"], b'{"id": "P-1"}', "probe-wrong-type", content_type="text/plain", scenario="webhook_unsupported_media_type")
    delivery(ep["id"], b"{broken", "probe-bad-payload", scenario="webhook_invalid_payload")
    delivery(ep["id"], b'{"id": "P-1"}', "probe-replay-1", scenario="webhook_accepted")
    delivery(ep["id"], b'{"id": "P-1"}', "probe-replay-1", scenario="webhook_replayed")
    monkeypatch.setattr(_wh, "RATE_BURST", 1)
    monkeypatch.setattr(_wh, "RATE_PER_SECOND", 0.01)
    for n in range(3):
        delivery(ep["id"], b'{"id": "P-2"}', f"probe-flood-{n}", scenario="webhook_flood")
    # Batch 11A: a REST connector without a records configuration cannot be synchronised (409), and the live-probe parameter is validated (422)
    with owner_engine.begin() as conn:
        plain = conn.execute(text("INSERT INTO connectors (tenant_id, kind, name, base_url, config) VALUES (:t, 'rest', :n, 'http://127.0.0.1:9', '{}') RETURNING id"),
                             {"t": tid, "n": f"probe-plain-{uuid.uuid4().hex[:6]}"}).scalar()
    call("post", f"/api/v1/connectors/{plain}/sync", "sync_without_records_configuration", headers=sup)
    call("get", "/api/v1/connectors/health?probe=maybe", "probe_parameter_invalid", headers=adm)
    call("get", "/api/v1/evaluation/registry", "platform_token_is_not_tenant_scoped", headers=padm)
    call("get", "/api/v1/evaluation/registry", "limit_out_of_range", headers=adm, params={"limit": "0"})
    # Batch 10: a document stored before original files were retained cannot be reprocessed from source (409 source_not_retained)
    legacy = client.post("/api/v1/documents", headers=eng, data={"kind": "other"}, files={"file": ("probe-legacy.txt", b"Legacy probe document without a retained original. Marker 55521.")})
    if legacy.status_code == 201:
        with owner_engine.begin() as conn:
            conn.execute(text("UPDATE document_versions SET source_id = NULL WHERE document_id = :d"), {"d": legacy.json()["document_id"]})
        call("post", f"/api/v1/documents/{legacy.json()['document_id']}/reprocess", "reprocess_without_retained_original", headers=sup)
    call("post", f"/api/v1/incidents/{inc[1]['id']}/measurements/vibration_mm_s/verify", "verify_stale_state", headers=sup,
         json={"decision": "approve", "comment": "Checked the printout.", "expected_trust_status": "VALIDATED"})
    call("post", f"/api/v1/incidents/{inc[1]['id']}/measurements/coolant_temp_c/verify", "verify_nothing_pending", headers=sup,
         json={"decision": "approve", "comment": "Checked the printout.", "expected_trust_status": "UNVERIFIED"})
    call("post", f"/api/v1/incidents/{inc[1]['id']}/measurements/vibration_mm_s/verify", "verify_creator_is_reviewer", headers=eng,
         json={"decision": "approve", "comment": "Checked the printout.", "expected_trust_status": "UNVERIFIED"})
    call("post", "/api/v1/tenants", "duplicate_slug", headers=padm, json={"slug": w["tenant"].slug, "name": "Duplicate tenant"})
    member = {"email": w["tenant"].users["support_engineer"], "full_name": "Existing Member", "password": "A-long-password-123", "role": "support_engineer"}
    call("post", f"/api/v1/tenants/{tid}/members", "duplicate_member", headers=adm, json=member)
    call("post", f"/api/v1/tenants/{tid}/members", "invalid_role", headers=adm, json={**member, "email": f"x.{uuid.uuid4().hex[:6]}@example.test", "role": "platform_admin"})
    conn_body = {"kind": "ticketing", "name": f"probe-{uuid.uuid4().hex[:6]}", "base_url": ticketing.url, "config": {}}
    client.post("/api/v1/connectors", headers=adm, json=conn_body)
    call("post", "/api/v1/connectors", "duplicate_connector", headers=adm, json=conn_body)
    # ---- uploads: unsupported type, unreadable file, oversize file
    call("post", "/api/v1/documents", "unsupported_file_type", headers=eng, data={"kind": "other"}, files={"file": ("notes.exe", b"MZ binary")})
    call("post", "/api/v1/documents", "unreadable_pdf", headers=eng, data={"kind": "equipment_manual"}, files={"file": ("broken.pdf", b"not a pdf at all")})
    call("post", "/api/v1/documents", "oversize_file", headers=eng, data={"kind": "other"}, files={"file": ("big.csv", b"a,b\n" + b"1,2\n" * (settings.max_upload_bytes // 4 + 10))})
    # ---- concurrency limits (server busy) and injected infrastructure failures
    app = client.app
    for lim, m, path, kw in (("inference", "post", "/api/v1/incidents/extract", {"json": {"report_text": REPORT}}), ("inference", "post", "/api/v1/ai/ask", {"json": {"question": "What should I check on pump P-101?"}}),
                             ("ingestion", "post", "/api/v1/documents", {"data": {"kind": "incident_history"}, "files": {"file": ("h.csv", (SAMPLES / "incident_history.csv").read_bytes())}})):
        limiter = app.state.limiters[lim]
        held = []
        try:
            for _ in range(limiter.limit):
                cm = limiter.slot()
                cm.__enter__()
                held.append(cm)
            call(m, path, f"server_busy:{lim}", headers=eng, **kw)
        finally:
            for cm in held:
                cm.__exit__(None, None, None)
    return P, spec, ops, roles, padm, other_user


def inject_failures(strict_client, ops, w, monkeypatch, app_db):
    """Every operation under (a) an unavailable database and (b) an unexpected internal error. Returns {op: {status: scenario}} and the bodies."""
    out = {}
    bodies = []

    class Broken:
        def __init__(self, exc):
            self.exc = exc

        def __call__(self, *a, **k):
            raise self.exc
    for label, exc in (("database_down", OperationalError("SELECT 1", {}, Exception("connection refused"))), ("internal_error", RuntimeError("secret internal detail /etc/passwd"))):
        monkeypatch.setattr(app_db, "session", Broken(exc))
        for m, p, o in ops:
            json_body = "requestBody" in o and "application/json" in o["requestBody"]["content"]
            hdr = w["adm"] if (m, p) not in PUBLIC else {}
            body = {"email": "a@example.test", "password": "A-long-password-123"} if p == "/api/v1/auth/login" else ({} if json_body else None)
            r = strict_client.request(m.upper(), fill(p, tenant_id=str(w["tenant"].id)), headers=hdr, json=body)
            out.setdefault(f"{m.upper()} {p}", {}).setdefault(r.status_code, []).append(label)
            bodies.append((f"{m.upper()} {p}", label, r.status_code, r.text, dict(r.headers)))
        monkeypatch.undo()
    return out, bodies
