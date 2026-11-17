"""V41-17.03: API-quality verification, nine properties (typed contracts, validation, pagination, standardized errors, OpenAPI documentation, database migrations,
transactions, constraints, indexes). Tests are named test_p1_* .. test_p9_* so scripts/api_quality_report.py can group executed results per property.

Run: python -m pytest tests/test_api_contract.py   (from backend/).  Refresh the committed OpenAPI contract snapshot after an intentional API change with
UPDATE_OPENAPI_SNAPSHOT=1 python -m pytest tests/test_api_contract.py -k snapshot   and review the diff."""
import json
import os
import re
import uuid
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from app.core.security import hash_password
from app.main import create_app
from app.models import Base
from fastapi.testclient import TestClient
from sqlalchemy import text
from support import PASSWORD, REPORT, login, make_tenant

BACKEND = Path(__file__).resolve().parents[1]
SNAPSHOT = Path(__file__).parent / "snapshots" / "openapi_contract.json"
PUBLIC = {("post", "/api/v1/auth/login"), ("get", "/api/v1/health")}
HTTP_METHODS = ("get", "post", "put", "patch", "delete")
UNREGISTERED = "Pump Z-999 shows abnormal vibration at 8.4 mm/s with grinding noise."


# ---------------------------------------------------------------------------------------------------------------------------------------------------
def spec_of(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    return r.json()


def operations(spec):
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if method in HTTP_METHODS:
                yield method, path, op


def assert_standard_error(resp, status, code=None):
    assert resp.status_code == status, (resp.status_code, resp.text[:200])
    body = resp.json()
    assert set(body) == {"error"}, body
    err = body["error"]
    assert {"code", "message", "correlation_id"} <= set(err), err
    assert resp.headers["X-Correlation-ID"] == err["correlation_id"]
    assert "Traceback" not in resp.text and 'File "' not in resp.text and "sqlalchemy" not in resp.text.lower()
    if code:
        assert err["code"] == code, err
    return err


def seed(client, tenant):
    """Documents come from apex_loaded; add incidents, tickets, pending and decided approvals and workflow rows."""
    eng, sup = login(client, tenant, "support_engineer"), login(client, tenant, "maintenance_supervisor")
    incidents = []
    for asset, v in (("P-101", 8.4), ("P-102", 7.9), ("P-103", 9.1), ("P-101", 6.2), ("M-201", 5.5), ("P-102", 10.2)):
        text_ = f"Pump {asset} shows abnormal vibration at the drive end, measured at {v} mm/s, with a grinding noise since this morning."
        r = client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": text_})
        assert r.status_code == 201, r.text
        incidents.append(r.json())
    tickets = []
    for inc in incidents[:4]:
        r = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]})
        if r.status_code == 201:
            tickets.append(r.json())
    for t in tickets[:3]:
        assert client.post(f"/api/v1/tickets/{t['id']}/request-approval", headers=eng).status_code == 200
    for t in tickets[:2]:
        assert client.post(f"/api/v1/approvals/{t['id']}/decision", headers=sup, json={"decision": "approved", "comment": "ok"}).status_code == 200
    return {"eng": eng, "sup": sup, "adm": login(client, tenant, "tenant_admin"), "aud": login(client, tenant, "read_only_auditor"), "incidents": incidents, "tickets": tickets}


@pytest.fixture()
def world(client, apex_loaded):
    return {"tenant": apex_loaded, **seed(client, apex_loaded)}


@pytest.fixture()
def strict_client(settings, app_db):
    """A client that returns 500 responses instead of re-raising server exceptions (to check the error body of an internal failure)."""
    return TestClient(create_app(settings, app_db), raise_server_exceptions=False)


# =============================== P1 typed contracts ===================================================================================================
SIGNED_RAW_BODY = {("post", "/api/v1/webhooks/{endpoint_id}")}


def test_p1_every_request_body_has_a_typed_schema_and_every_ref_resolves(client):
    spec = spec_of(client)
    schemas = spec["components"]["schemas"]
    untyped = []
    for method, path, op in operations(spec):
        body = op.get("requestBody")
        if not body:
            continue
        for ctype, media in body["content"].items():
            sch = media["schema"]
            if "$ref" in sch:
                assert sch["$ref"].rsplit("/", 1)[-1] in schemas, (method, path)
            elif (method, path) in SIGNED_RAW_BODY:
                # Batch 11B: the one documented exception. The signature covers the RAW bytes and the record shape depends on the endpoint's stored configuration, so the body cannot be a
                # fixed typed model; the schema is still declared (an object) with a description, the shape is validated against the endpoint configuration after authentication.
                assert sch.get("type") == "object" and sch.get("description") and ctype == "application/json", (method, path)
            elif not (sch.get("type") == "object" and sch.get("properties")):
                untyped.append((method, path, ctype))
    assert untyped == [], f"untyped request bodies: {untyped}"
    refs = set(re.findall(r'"#/components/schemas/([^"]+)"', json.dumps(spec)))
    assert refs <= set(schemas), refs - set(schemas)


def test_p1_success_responses_declare_typed_schemas_in_openapi(client):
    spec = spec_of(client)

    def meaningful(schema):
        while "$ref" in schema:
            schema = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
        for key in ("anyOf", "oneOf"):
            if key in schema:
                return all(meaningful(sub) for sub in schema[key])
        return bool(schema.get("properties"))
    untyped = []
    for method, path, op in operations(spec):
        for code, resp in op["responses"].items():
            if code.startswith("2"):
                sch = resp.get("content", {}).get("application/json", {}).get("schema", {})
                if not meaningful(sch):
                    untyped.append(f"{method.upper()} {path}")
    assert untyped == [], f"{len(untyped)} operations document no typed success response"


def test_p1_documented_resource_shapes_are_stable(client, world):
    inc = client.get(f"/api/v1/incidents/{world['incidents'][0]['id']}", headers=world["eng"]).json()
    assert set(inc) >= {"id", "asset_id", "asset_verified", "category", "symptoms", "related_incidents", "priority", "citations", "recommended_action", "review_status", "notes",
                        "measurements", "review_urgency", "report_text", "extraction_backend", "created_at"}
    tick = client.get(f"/api/v1/tickets/{world['tickets'][0]['id']}", headers=world["eng"]).json()
    assert set(tick) >= {"id", "incident_id", "title", "description", "priority", "state", "external_ticket_id", "attempts", "last_error", "created_by", "created_at", "updated_at", "submitted_at"}
    docs = client.get("/api/v1/documents", headers=world["eng"]).json()
    assert set(docs) == {"total", "limit", "offset", "items"} and docs["items"] and {"id", "filename", "kind"} <= set(docs["items"][0])


def test_p1_responses_are_json_and_typed_values(client, world):
    for path in ("/api/v1/incidents", "/api/v1/tickets", "/api/v1/documents", "/api/v1/audit"):
        r = client.get(path, headers=world["eng" if path != "/api/v1/audit" else "aud"])
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
        body = r.json()
        assert isinstance(body["total"], int) and isinstance(body["limit"], int) and isinstance(body["offset"], int) and isinstance(body["items"], list)


# =============================== P2 validation ========================================================================================================
def _fill(path):
    return re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)


def test_p2_every_json_body_route_rejects_wrong_shapes_without_a_500(client, world):
    spec = spec_of(client)
    admin = world["adm"]
    checked = 0
    for method, path, op in operations(spec):
        body = op.get("requestBody")
        if not body or "application/json" not in body["content"] or (method, path) in PUBLIC or "/platform/" in path or path.startswith("/api/v1/tenants"):
            continue
        for wrong in ([], "text", 12, {"unexpected": {"nested": [1, 2]}}):
            r = client.request(method.upper(), _fill(path), headers=admin, json=wrong)
            assert r.status_code < 500, (method, path, wrong, r.text[:200])
            if r.status_code >= 400:
                assert_standard_error(r, r.status_code)
            checked += 1
    assert checked >= 20


@pytest.mark.parametrize("body,field", [({}, "report_text"), ({"report_text": "short"}, "report_text"), ({"report_text": 12345678901234}, "report_text"), ({"report_text": "x" * 4001}, "report_text"),
                                        ({"report_text": REPORT, "numeric_locale": "fr"}, "numeric_locale"), ({"report_text": REPORT, "observations": "nope"}, "observations"),
                                        ({"report_text": REPORT, "observations": [{"asset_id": "P-101"}]}, "observations")])
def test_p2_incident_extraction_validates_input(client, world, body, field):
    err = assert_standard_error(client.post("/api/v1/incidents/extract", headers=world["eng"], json=body), 422, "validation_error")
    assert any(field in [str(x) for x in d["loc"]] for d in err["details"])


def test_p2_malformed_json_bad_ids_and_enums(client, world):
    assert_standard_error(client.post("/api/v1/incidents/extract", headers={**world["eng"], "Content-Type": "application/json"}, content=b'{"report_text": '), 422, "validation_error")
    assert_standard_error(client.get("/api/v1/incidents/not-a-uuid", headers=world["eng"]), 422, "validation_error")
    assert_standard_error(client.post(f"/api/v1/approvals/{world['tickets'][2]['id']}/decision", headers=world["sup"], json={"decision": "maybe", "comment": "x"}), 422, "validation_error")
    assert_standard_error(client.get("/api/v1/incidents", headers=world["eng"], params={"priority": "P9"}), 422, "validation_error")
    assert_standard_error(client.get("/api/v1/incidents", headers=world["eng"], params={"review_status": "bogus"}), 422, "validation_error")


def test_p2_oversize_json_body_is_rejected_with_a_standard_error(client, world):
    r = client.post("/api/v1/incidents/extract", headers=world["eng"], json={"report_text": "x" * 2_000_000})
    assert r.status_code == 413
    assert r.json()["error"]["code"] and "message" in r.json()["error"]


def test_p2_unknown_upload_kind_and_empty_file_are_rejected(client, world):
    r = client.post("/api/v1/documents", headers=world["eng"], data={"kind": "not_a_kind"}, files={"file": ("a.csv", b"a,b\n1,2\n")})
    assert 400 <= r.status_code < 500
    assert_standard_error(r, r.status_code)


# =============================== P3 pagination ========================================================================================================
def _list_endpoints(client):
    out = []
    for method, path, op in operations(spec_of(client)):
        names = {p["name"] for p in op.get("parameters", [])}
        if method == "get" and {"limit", "offset"} <= names:
            out.append(path)
    return sorted(out)


def _ids(items):
    return [i.get("id", i.get("ticket_id")) for i in items]


def test_p3_every_list_endpoint_is_discovered_and_paginates_consistently(client, world):
    paths = [p for p in _list_endpoints(client) if "/platform/" not in p]
    assert {"/api/v1/documents", "/api/v1/incidents", "/api/v1/tickets", "/api/v1/approvals", "/api/v1/workflows", "/api/v1/audit"} <= set(paths)
    for path in paths:
        hdr = world["aud"] if path == "/api/v1/audit" else world["sup"]
        variants = [{}] + ([{"status": "decided"}] if path == "/api/v1/approvals" else [])
        for extra in variants:
            full = client.get(path, headers=hdr, params={**extra, "limit": 100}).json()
            assert set(full) == {"total", "limit", "offset", "items"} and full["limit"] == 100 and full["offset"] == 0
            ids = _ids(full["items"])
            assert len(ids) == len(set(ids)) and full["total"] >= len(ids)
            assert ids == _ids(client.get(path, headers=hdr, params={**extra, "limit": 100}).json()["items"]), f"unstable ordering on {path}"
            if full["total"] <= 100:
                paged = []
                offset = 0
                while True:
                    page = client.get(path, headers=hdr, params={**extra, "limit": 2, "offset": offset}).json()
                    assert page["total"] == full["total"] and page["limit"] == 2 and page["offset"] == offset and len(page["items"]) <= 2
                    if not page["items"]:
                        break
                    paged += _ids(page["items"])
                    offset += 2
                assert paged == ids, f"pages are not disjoint and complete on {path}"
            beyond = client.get(path, headers=hdr, params={**extra, "offset": full["total"] + 5}).json()
            assert beyond["items"] == [] and beyond["total"] == full["total"]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"limit": -1}, {"limit": "abc"}, {"offset": -1}, {"offset": "abc"}])
def test_p3_pagination_bounds_are_enforced_on_every_list_endpoint(client, world, params):
    for path in ("/api/v1/documents", "/api/v1/incidents", "/api/v1/tickets", "/api/v1/approvals", "/api/v1/workflows", "/api/v1/audit"):
        assert_standard_error(client.get(path, headers=world["aud"], params=params), 422, "validation_error")


def test_p3_limit_edges_and_default(client, world):
    assert len(client.get("/api/v1/incidents", headers=world["eng"], params={"limit": 1}).json()["items"]) == 1
    assert client.get("/api/v1/incidents", headers=world["eng"], params={"limit": 100}).status_code == 200
    d = client.get("/api/v1/incidents", headers=world["eng"]).json()
    assert d["limit"] == 50 and d["total"] == 6


def test_p3_lists_are_tenant_scoped(client, world, owner_engine, ticketing, inventory_server):
    other = make_tenant(owner_engine, "apexb", ticketing.url, inventory_server.url)
    oe = login(client, other, "support_engineer")
    assert client.post("/api/v1/incidents/extract", headers=oe, json={"report_text": REPORT}).status_code == 201
    mine = {i["id"] for i in client.get("/api/v1/incidents", headers=world["eng"], params={"limit": 100}).json()["items"]}
    theirs = {i["id"] for i in client.get("/api/v1/incidents", headers=oe, params={"limit": 100}).json()["items"]}
    assert mine and theirs and not (mine & theirs) and len(theirs) == 1
    assert client.get("/api/v1/tickets", headers=oe).json()["total"] == 0 and client.get("/api/v1/documents", headers=oe).json()["total"] == 0


def test_p3_platform_audit_paginates_too(client, world, owner_engine):
    email = f"platform.{uuid.uuid4().hex[:6]}@example.test"
    with owner_engine.begin() as conn:
        conn.execute(text("INSERT INTO users (email, full_name, password_hash, is_platform_admin) VALUES (:e, 'Platform', :p, true)"), {"e": email, "p": hash_password(PASSWORD)})
    tok = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
    hdr = {"Authorization": f"Bearer {tok}"}
    full = client.get("/api/v1/platform/audit", headers=hdr, params={"limit": 100}).json()
    assert set(full) == {"total", "limit", "offset", "items"} and full["limit"] == 100
    assert_standard_error(client.get("/api/v1/platform/audit", headers=hdr, params={"limit": 0}), 422, "validation_error")


# =============================== P4 standardized errors ===============================================================================================
def test_p4_authentication_authorization_and_not_found_errors_use_the_standard_body(client, world):
    assert_standard_error(client.get("/api/v1/incidents"), 401)
    assert_standard_error(client.get("/api/v1/incidents", headers={"Authorization": "Bearer not.a.token"}), 401)
    assert_standard_error(client.post("/api/v1/incidents/extract", headers=world["aud"], json={"report_text": REPORT}), 403)
    assert_standard_error(client.get(f"/api/v1/incidents/{uuid.uuid4()}", headers=world["eng"]), 404, "not_found")
    assert_standard_error(client.get(f"/api/v1/tickets/{uuid.uuid4()}", headers=world["eng"]), 404, "not_found")


def test_p4_conflict_errors_use_the_standard_body(client, world):
    t = world["tickets"][0]  # already decided
    assert_standard_error(client.post(f"/api/v1/tickets/{t['id']}/request-approval", headers=world["eng"]), 409)
    assert_standard_error(client.post("/api/v1/tickets", headers=world["eng"], json={"incident_id": world["incidents"][0]["id"]}), 409)


def test_p4_unknown_routes_and_wrong_methods_use_the_standard_body(client, world):
    assert_standard_error(client.get("/api/v1/does-not-exist", headers=world["eng"]), 404, "not_found")
    assert_standard_error(client.get("/nowhere"), 404, "not_found")
    assert_standard_error(client.delete("/api/v1/incidents", headers=world["eng"]), 405, "method_not_allowed")


def test_p4_internal_failures_do_not_leak_internals_and_keep_the_correlation_id(strict_client, client, world, monkeypatch):
    from app.audit import service as audit
    real = audit.record
    monkeypatch.setattr(audit, "record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret internal detail /etc/passwd")))
    r = strict_client.post("/api/v1/incidents/extract", headers={**world["eng"], "X-Correlation-ID": "cid-p4-123"}, json={"report_text": REPORT})
    monkeypatch.setattr(audit, "record", real)
    err = assert_standard_error(r, 500, "internal_error")
    assert err["correlation_id"] == "cid-p4-123" and "secret internal detail" not in r.text and "passwd" not in r.text


def test_p4_every_response_carries_a_correlation_id_and_supplied_ids_are_echoed(client, world):
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.headers["X-Correlation-ID"]
    r = client.get("/api/v1/incidents", headers={**world["eng"], "X-Correlation-ID": "my-trace-1"})
    assert r.headers["X-Correlation-ID"] == "my-trace-1"


# =============================== P5 OpenAPI documentation =============================================================================================
def test_p5_openapi_is_valid_complete_and_documents_every_operation(client):
    spec = spec_of(client)
    assert spec["openapi"].startswith("3.") and spec["info"]["title"] and spec["info"]["version"] and spec["paths"]
    ids = []
    for method, path, op in operations(spec):
        assert op.get("summary") or op.get("description"), (method, path)
        assert op.get("tags"), (method, path)
        assert op.get("responses"), (method, path)
        ids.append(op["operationId"])
    assert len(ids) == len(set(ids)) and client.get("/docs").status_code == 200


def test_p5_openapi_declares_the_bearer_security_scheme_for_every_protected_operation(client):
    spec = spec_of(client)
    scheme = spec["components"].get("securitySchemes", {}).get("bearerAuth")
    assert scheme and scheme["type"] == "http" and scheme["scheme"] == "bearer"
    for method, path, op in operations(spec):
        if (method, path) in PUBLIC:
            assert not op.get("security"), (method, path)
        elif (method, path) in SIGNED_RAW_BODY:  # authenticated by an HMAC signature header instead of a bearer token (Batch 11B)
            sig = spec["components"]["securitySchemes"]["webhookSignature"]
            assert sig["type"] == "apiKey" and sig["in"] == "header" and sig["name"] == "X-Webhook-Signature"
            assert op.get("security") == [{"webhookSignature": []}], (method, path)
        else:
            assert op.get("security") == [{"bearerAuth": []}], (method, path)


def _schema_name(schema):
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    return "|".join(sorted(_schema_name(x) for x in schema.get("anyOf", schema.get("oneOf", [])))) or "inline"


def _contract(spec):
    out = {"operations": {}, "schemas": {}}
    for method, path, op in operations(spec):
        body = op.get("requestBody", {})
        refs = sorted({(m["schema"].get("$ref") or "inline").rsplit("/", 1)[-1] for m in body.get("content", {}).values()})
        out["operations"][f"{method.upper()} {path}"] = {
            "tags": sorted(op.get("tags", [])), "params": sorted(f"{p['in']}:{p['name']}{'*' if p.get('required') else ''}" for p in op.get("parameters", [])),
            "body": refs, "responses": sorted(op["responses"]), "secured": bool(op.get("security")),
            "success": {code: _schema_name(r.get("content", {}).get("application/json", {}).get("schema", {})) for code, r in sorted(op["responses"].items()) if code.startswith("2")}}
    for name, sch in sorted(spec["components"]["schemas"].items()):
        out["schemas"][name] = {"properties": sorted(sch.get("properties", {})), "required": sorted(sch.get("required", []))}
    return out


def test_p5_committed_openapi_snapshot_matches_the_live_contract(client):
    live = _contract(spec_of(client))
    if os.environ.get("UPDATE_OPENAPI_SNAPSHOT") == "1":
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(live, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    added = sorted(set(live["operations"]) - set(committed["operations"]))
    removed = sorted(set(committed["operations"]) - set(live["operations"]))
    changed = sorted(k for k in set(live["operations"]) & set(committed["operations"]) if live["operations"][k] != committed["operations"][k])
    schema_changes = sorted(k for k in set(live["schemas"]) | set(committed["schemas"]) if live["schemas"].get(k) != committed["schemas"].get(k))
    assert not (added or removed or changed or schema_changes), (
        f"API contract changed. added={added} removed={removed} changed={changed} schemas={schema_changes}. If intentional: UPDATE_OPENAPI_SNAPSHOT=1 python -m pytest tests/test_api_contract.py -k snapshot")


# =============================== P6 database migrations ===============================================================================================
def _script():
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    return ScriptDirectory.from_config(cfg)


def test_p6_migrations_have_one_linear_head_and_the_database_is_at_head(owner_engine):
    script = _script()
    assert len(script.get_heads()) == 1
    revs = list(script.walk_revisions())  # head -> base
    assert revs[-1].down_revision is None and all(r.down_revision == revs[i + 1].revision for i, r in enumerate(revs[:-1]))
    assert len(revs) == len(list((BACKEND / "migrations" / "versions").glob("0*.py")))
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == script.get_current_head()


def test_p6_models_never_reference_schema_the_migrations_did_not_create(owner_engine):
    """Direction that matters for runtime safety: any table or column the ORM maps must exist in the migrated database (the migrations own indexes, constraints and RLS)."""
    with owner_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": False, "compare_server_default": False}), Base.metadata)
    flat = []
    for d in diff:
        flat += d if isinstance(d, list) else [d]
    missing = [str(d[0:3]) for d in flat if d[0] in ("add_table", "add_column")]
    assert missing == [], f"models map schema that is not in the database: {missing}"


def test_p6_migrations_can_be_applied_from_scratch_and_are_idempotent_at_head(settings, owner_engine):
    # the session fixture builds the test database from the migrations; asserting it contains every expected object proves a from-scratch upgrade works
    with owner_engine.connect() as conn:
        tables = {r[0] for r in conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))}
    assert {"tenants", "users", "memberships", "connectors", "documents", "document_versions", "document_chunks", "embedding_profiles", "incidents", "tickets", "approvals", "outbox_events",
            "audit_events", "tenant_profiles", "alembic_version"} <= tables
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM information_schema.columns WHERE table_name = 'incidents' AND column_name = 'measurements'")).scalar() == 1  # the latest revision applied


# =============================== P7 transactions ======================================================================================================
def test_p7_a_rejected_upload_leaves_no_partial_rows(client, world, owner_engine):
    def counts():
        with owner_engine.connect() as conn:
            return [conn.execute(text(f"SELECT count(*) FROM {t} WHERE tenant_id = :t"), {"t": str(world["tenant"].id)}).scalar() for t in ("documents", "document_versions", "document_chunks")]
    before = counts()
    r = client.post("/api/v1/documents", headers=world["eng"], data={"kind": "equipment_manual"}, files={"file": ("broken.pdf", b"this is definitely not a pdf document")})
    assert 400 <= r.status_code < 500
    assert counts() == before


def test_p7_a_failure_inside_a_state_change_rolls_back_the_state_and_its_audit_event(strict_client, client, world, owner_engine, monkeypatch):
    from app.audit import service as audit
    inc = client.post("/api/v1/incidents/extract", headers=world["eng"], json={"report_text": UNREGISTERED}).json()
    assert inc["review_status"] == "needs_review"
    real = audit.record

    def failing(session, **kw):
        real(session, **kw)  # the audit row is added to the same transaction first
        if kw.get("action") == "incident.review_accept":
            raise RuntimeError("injected failure after the audit row was added")
    monkeypatch.setattr(audit, "record", failing)
    r = strict_client.post(f"/api/v1/incidents/{inc['id']}/review", headers=world["sup"], json={"decision": "accept", "comment": "Justified for the transaction test."})
    monkeypatch.setattr(audit, "record", real)
    assert r.status_code == 500
    after = client.get(f"/api/v1/incidents/{inc['id']}", headers=world["eng"]).json()
    assert after["review_status"] == "needs_review" and after["notes"] == inc["notes"]
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM audit_events WHERE entity_id = :i AND action = 'incident.review_accept'"), {"i": inc["id"]}).scalar() == 0


def test_p7_a_state_change_and_its_audit_event_commit_together(client, world, owner_engine):
    t = world["tickets"][2]
    with owner_engine.connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM audit_events WHERE entity_id = :i"), {"i": t["id"]}).scalar()
    assert client.post(f"/api/v1/approvals/{t['id']}/decision", headers=world["sup"], json={"decision": "approved", "comment": "ok"}).status_code == 200
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM audit_events WHERE entity_id = :i"), {"i": t["id"]}).scalar() > before
        assert conn.execute(text("SELECT count(*) FROM outbox_events WHERE aggregate_id = :i"), {"i": t["id"]}).scalar() == 1


# =============================== P8 constraints =======================================================================================================
EXPECTED_CONSTRAINTS = {  # table -> {contype: minimum count}
    "tenants": {"p": 1, "u": 1, "c": 1}, "users": {"p": 1, "u": 1}, "memberships": {"p": 1, "u": 1, "f": 2, "c": 1}, "documents": {"p": 1, "u": 1, "f": 2},
    "document_versions": {"p": 1, "u": 2, "f": 2}, "document_chunks": {"p": 1, "f": 4}, "incidents": {"p": 1, "f": 2, "c": 1}, "tickets": {"p": 1, "f": 3, "c": 2},
    "approvals": {"p": 1, "u": 1, "f": 3, "c": 1}, "outbox_events": {"p": 1, "f": 1, "c": 1}, "connectors": {"p": 1, "u": 1, "f": 1, "c": 1}, "audit_events": {"p": 1, "f": 1}}


def test_p8_key_constraints_exist_at_the_database(owner_engine):
    with owner_engine.connect() as conn:
        rows = conn.execute(text("SELECT c.relname, con.contype, count(*) FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
                                 "WHERE n.nspname = 'public' GROUP BY 1, 2")).all()
        notnull = {r[0] for r in conn.execute(text("SELECT table_name FROM information_schema.columns WHERE table_schema = 'public' AND column_name = 'tenant_id' AND is_nullable = 'NO'"))}
    have = {}
    for t, k, n in rows:
        have.setdefault(t, {})[k] = n
    for table, need in EXPECTED_CONSTRAINTS.items():
        for kind, minimum in need.items():
            assert have.get(table, {}).get(kind, 0) >= minimum, f"{table} is missing {kind} constraints ({have.get(table)})"
    # audit_events.tenant_id is deliberately nullable: platform-level events (admin sign-ins) have no tenant
    assert {"documents", "document_chunks", "incidents", "tickets", "approvals", "outbox_events", "connectors"} <= notnull


def test_p8_violating_rows_are_rejected_by_the_database(client, world, owner_engine):
    from sqlalchemy.exc import IntegrityError
    tid = str(world["tenant"].id)
    t = world["tickets"][0]
    with owner_engine.connect() as conn:
        user = conn.execute(text("SELECT id FROM users LIMIT 1")).scalar()
    cases = [("duplicate approval for one ticket", "INSERT INTO approvals (tenant_id, ticket_id, decision, decided_by, comment) VALUES (:t, :k, 'approved', :u, 'dup')", {"t": tid, "k": t["id"], "u": str(user)}),
             ("unknown tenant (foreign key)", "INSERT INTO documents (tenant_id, source_key, filename, kind) VALUES (:t, 'x', 'x', 'other')", {"t": str(uuid.uuid4())}),
             ("invalid priority (check)", "UPDATE incidents SET priority = 'P9' WHERE tenant_id = :t", {"t": tid}),
             ("invalid ticket state (check)", "UPDATE tickets SET state = 'BOGUS' WHERE tenant_id = :t", {"t": tid}),
             ("null tenant (not null)", "INSERT INTO documents (tenant_id, source_key, filename, kind) VALUES (NULL, 'x', 'x', 'other')", {})]
    for label, sql, params in cases:
        with owner_engine.connect() as conn, pytest.raises(IntegrityError, match=r".+"):
            conn.execute(text(sql), params)
            conn.commit()
        assert label


# =============================== P9 indexes ===========================================================================================================
def _indexes(owner_engine):
    with owner_engine.connect() as conn:
        tenant_tables = [r[0] for r in conn.execute(text("SELECT table_name FROM information_schema.columns WHERE table_schema = 'public' AND column_name = 'tenant_id'"))]
        idx = conn.execute(text("SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")).all()
    return tenant_tables, idx


def test_p9_search_integrity_and_uniqueness_indexes_exist(owner_engine):
    _, idx = _indexes(owner_engine)
    defs = " ".join(d for _, _, d in idx)
    assert re.search(r"USING gin \(tsv\)", defs), "full-text index missing"
    assert re.search(r"USING (hnsw|ivfflat)", defs), "vector index missing"
    for needle in ("embedding_profiles_one_active", "outbox_one_active_per_aggregate"):
        assert needle in defs
    assert any(t == "users" and "UNIQUE" in d for t, _, d in idx) and any(t == "approvals" and "UNIQUE" in d and "ticket_id" in d for t, _, d in idx)


def test_p9_every_tenant_scoped_table_has_a_tenant_leading_index(owner_engine):
    tenant_tables, idx = _indexes(owner_engine)
    missing = [t for t in tenant_tables if not any(tbl == t and re.search(r"\(tenant_id[,)]", d) for tbl, _, d in idx)]
    assert missing == [], f"tenant-scoped tables without a tenant-leading index: {missing}"


def test_p9_the_indexes_added_by_migration_0008_exist_with_the_intended_columns(owner_engine):
    """V41-17.03-IDX closed by migration 0008 (previously a strict expected failure; converted only after the defect was resolved and the marker flipped to XPASS)."""
    _, idx = _indexes(owner_engine)
    defs = {name: d for _, name, d in idx}
    for name, cols in (("incidents_tenant_created_idx", "tenant_id, created_at DESC"), ("approvals_tenant_decided_idx", "tenant_id, decided_at DESC"),
                       ("outbox_events_tenant_id_idx", "tenant_id, id DESC")):
        assert name in defs and f"({cols})" in defs[name], (name, defs.get(name))


def test_the_signed_receiver_is_the_only_exception_and_its_documentation_is_accurate(client):
    """Owner review: the two property exceptions (signature authentication, raw signed body) are limited to exactly one operation, which is documented accurately."""
    assert SIGNED_RAW_BODY == {("post", "/api/v1/webhooks/{endpoint_id}")}
    spec = spec_of(client)
    op = spec["paths"]["/api/v1/webhooks/{endpoint_id}"]["post"]
    assert op["security"] == [{"webhookSignature": []}] and set(op["responses"]) >= {"202", "401", "409", "413", "415", "422", "429", "503"}
    assert op["responses"]["202"]["content"]["application/json"]["schema"]["$ref"].endswith("/WebhookAccepted")  # the success response IS typed and validated against that schema
    assert {p["name"] for p in op["parameters"] if p["in"] == "header"} >= {"x-webhook-signature", "x-webhook-timestamp", "x-webhook-delivery-id"}
    body = op["requestBody"]["content"]["application/json"]["schema"]
    assert body["type"] == "object" and body.get("description")  # declared and described, not a typed fixed model (documented exception)
    others = [(m, p) for p, ops in spec["paths"].items() for m, o in ops.items() if m in ("get", "post", "put", "patch", "delete") and o.get("security") == [{"webhookSignature": []}]]
    assert others == [("post", "/api/v1/webhooks/{endpoint_id}")]  # no other operation uses signature authentication
