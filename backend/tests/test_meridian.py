"""Phase 5: the second fictional customer (Meridian Fleet Logistics) is onboarded through public APIs and
configuration only, runs the same platform code, and is isolated from Apex (deterministic backends; the real
Ollama + MiniLM run for both tenants lives in test_real_ai.py)."""
import pytest
from app.workflows import worker
from sqlalchemy import text
from support import REPORT, SAMPLES, login, onboard_meridian

BRAKE_REPORT = "Vehicle VH-2101 shows low brake pressure of 52 psi with a hissing noise at the rear axle."
ROOT_SAMPLES = SAMPLES.parent / "customer-b"


@pytest.fixture()
def meridian(client, owner_engine, servicedesk_server, fleet_server, crm_server):
    with owner_engine.begin() as conn:  # the worker drains a global queue: retire leftovers from other tests
        conn.execute(text("UPDATE outbox_events SET status = 'done' WHERE status IN ('pending', 'processing')"))
    state = servicedesk_server.state
    with state.lock:
        state.tickets.clear(), state.by_key.clear(), state.failures.clear()
        state.requests = 0
    fleet_server.app.state.requests.clear()
    crm_server.app.state.requests.clear()
    return onboard_meridian(client, owner_engine, servicedesk_server, fleet_server, crm_server)


def _extract(client, headers, text_):
    resp = client.post("/api/v1/incidents/extract", headers=headers, json={"report_text": text_})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _audit(client, tenant):
    aud = login(client, tenant, "read_only_auditor")
    return client.get("/api/v1/audit", headers=aud, params={"limit": 100}).json()["items"]


def _clear_review(client, tenant, incident):
    """Accept through the human-review path when the deterministic test model produced no grounded evidence."""
    if incident["review_status"] == "needs_review":
        sup = login(client, tenant, "maintenance_supervisor")
        assert client.post(f"/api/v1/incidents/{incident['id']}/review", headers=sup,
                           json={"decision": "accept", "comment": "Reviewed against the manual."}).status_code == 200


# ---- onboarding through supported APIs only ----------------------------------------------------------------------
def test_meridian_is_onboarded_through_the_api_with_a_versioned_profile(client, meridian, owner_engine):
    admin, eng = login(client, meridian, "tenant_admin"), login(client, meridian, "support_engineer")
    got = client.get("/api/v1/tenant-profile", headers=eng).json()
    assert got["version"] == 1 and got["using_defaults"] is False and got["profile"]["asset_label"] == "vehicle"
    assert client.put("/api/v1/tenant-profile", headers=eng, json=got["profile"]).status_code == 403  # admins only
    again = client.put("/api/v1/tenant-profile", headers=admin, json=got["profile"])
    assert again.status_code == 200 and again.json()["version"] == 2
    bad = client.put("/api/v1/tenant-profile", headers=admin, json={**got["profile"], "asset_id_pattern": "(a+)+$"})
    assert bad.status_code == 422
    assert client.get("/api/v1/tenant-profile", headers=admin).json()["version"] == 2  # rejected update changed nothing
    kinds = {c["kind"] for c in client.get("/api/v1/connectors", headers=admin).json()["items"]}
    assert kinds == {"ticketing", "fleet", "crm"}
    assert "profile.updated" in [e["action"] for e in _audit(client, meridian)]
    with owner_engine.connect() as c:  # the shared schema has no customer-specific tables or columns
        tables = {r[0] for r in c.execute(text("SELECT table_name FROM information_schema.tables "
                                              "WHERE table_schema = 'public'"))}
    assert not any("meridian" in t or "apex" in t or "fleet" in t for t in tables)


def test_fleet_documents_ingest_with_tenant_specific_mappings(client, meridian):
    eng = login(client, meridian, "support_engineer")
    docs = {d["filename"]: d for d in client.get("/api/v1/documents", headers=eng).json()["items"]}
    assert {"fleet_register.csv", "service_history.csv", "telematics_alerts.csv",
            "meridian_mx300_maintenance_manual.pdf", "meridian_depot_inspection_2026q3.pdf"} == set(docs)
    hits = client.post("/api/v1/search", headers=eng, json={"query": "VH-2101 brake chamber diaphragm hissing", "k": 8}
                       ).json()["items"]
    history = [h for h in hits if h["filename"] == "service_history.csv"]
    assert history and history[0]["record_id"] in {"SR-3001", "SR-3002"}
    assert "root_cause" in history[0]["text"] and "vehicle_id" in history[0]["text"]  # mapped column names
    unknown = client.post("/api/v1/documents", headers=eng, data={"kind": "made_up_kind"},
                          files={"file": ("x.txt", b"some text")})
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "invalid_kind"


def test_non_admin_cannot_change_connectors_or_profile_and_ticketing_config_is_validated(client, meridian):
    admin, eng = login(client, meridian, "tenant_admin"), login(client, meridian, "support_engineer")
    body = {"kind": "ticketing", "name": "evil", "base_url": "http://127.0.0.1:9", "config": {"create_path": "/ok"}}
    assert client.post("/api/v1/connectors", headers=eng, json=body).status_code == 403
    for bad_path in ("//evil.example/x", "/../admin", "http://evil.example/x", "no-leading-slash"):
        resp = client.post("/api/v1/connectors", headers=admin, json={**body, "config": {"create_path": bad_path}})
        assert resp.status_code == 422, bad_path
    resp = client.post("/api/v1/connectors", headers=admin, json={**body, "config": {"surprise": 1}})
    assert resp.status_code == 422


# ---- tenant-specific retrieval and AI incident extraction ----------------------------------------------------------
def test_meridian_extraction_uses_its_profile_register_and_integrations(client, meridian, fleet_server, crm_server):
    eng = login(client, meridian, "support_engineer")
    inc = _extract(client, eng, BRAKE_REPORT)
    assert inc["asset_id"] == "VH-2101" and inc["asset_verified"] is True  # verified in Meridian's fleet register
    assert inc["category"] == "brake_system" and inc["priority"] == "P3"   # category-driven only (V8): the free-text 52 psi is an unverified candidate
    notes = " ".join(inc["notes"])
    assert "Vehicle VH-2101: odometer 182450 km" in notes and "Harbor Fresh Foods" in notes and "gold" in notes
    assert fleet_server.app.state.requests == ["VH-2101"] and crm_server.app.state.requests == ["VH-2101"]
    assert all(c["filename"].startswith(("meridian", "fleet", "service", "telematics")) for c in inc["citations"])
    expected = "pending_review" if inc["citations"] else "needs_review"
    assert inc["review_status"] == expected
    related = {r["filename"] for r in inc["related_incidents"]}
    assert related <= {"service_history.csv"}


def test_enrichment_failures_never_block_or_decide_the_incident(client, meridian, fleet_server, crm_server):
    import httpx
    eng = login(client, meridian, "support_engineer")
    httpx.post(f"{fleet_server.url}/admin/failure", json={"mode": "503", "count": 1})
    httpx.post(f"{crm_server.url}/admin/failure", json={"mode": "malformed", "count": 1})
    inc = _extract(client, eng, BRAKE_REPORT)
    notes = " ".join(inc["notes"])
    assert "Fleet telematics lookup failed" in notes and "CRM account lookup failed" in notes
    assert inc["priority"] == "P3" and inc["asset_verified"] is True  # facts that matter are unchanged


def test_meridian_retrieval_never_returns_apex_documents_and_vice_versa(client, meridian, apex_loaded):
    m_eng, a_eng = login(client, meridian, "support_engineer"), login(client, apex_loaded, "support_engineer")
    for query in ("bearing vibration limit pump", "brake line pressure psi air dryer", "coolant temperature thermostat"):
        m_files = {h["filename"] for h in client.post("/api/v1/search", headers=m_eng, json={"query": query, "k": 10}
                                                      ).json()["items"]}
        a_files = {h["filename"] for h in client.post("/api/v1/search", headers=a_eng, json={"query": query, "k": 10}
                                                      ).json()["items"]}
        assert not any(f.startswith("apex") or f in ("equipment_register.csv", "incident_history.csv") for f in m_files)
        assert not any(f.startswith(("meridian", "fleet", "service", "telematics")) for f in a_files)
    ans = client.post("/api/v1/ai/ask", headers=a_eng, json={"question": "What is the brake line pressure limit for VH-2101?"}
                      ).json()
    assert ans["citations"] == [] or all(not c["filename"].startswith("meridian") for c in ans["citations"])


def test_profile_is_per_tenant_and_apex_keeps_its_defaults(client, meridian, apex_loaded):
    a_eng = login(client, apex_loaded, "support_engineer")
    assert client.get("/api/v1/tenant-profile", headers=a_eng).json() == {"version": 0, "using_defaults": True,
                                                                          "profile": None, "updated_at": None}
    # A Meridian vehicle ID reported to Apex is not in Apex's register: it must go to human review.
    inc = _extract(client, a_eng, "Vehicle VH-2101 shows abnormal vibration at 8.0 mm/s with grinding noise.")
    assert inc["asset_verified"] is False and inc["review_status"] == "needs_review" and inc["priority"] == "P3"
    # An Apex pump ID is not a Meridian vehicle ID: Meridian's profile does not recognise it.
    m_eng = login(client, meridian, "support_engineer")
    resp = client.post("/api/v1/incidents/extract", headers=m_eng, json={"report_text": REPORT})
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "asset_not_identified"


# ---- workflow: review, approval, idempotent submission to the correct API ----------------------------------------------
def test_meridian_end_to_end_submits_to_its_own_service_desk_only(
        client, meridian, apex_loaded, worker_db, ticketing, servicedesk_server):
    eng, sup = login(client, meridian, "support_engineer"), login(client, meridian, "maintenance_supervisor")
    a_eng, a_sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    inc = _extract(client, eng, BRAKE_REPORT)
    _clear_review(client, meridian, inc)
    ticket = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()
    assert client.post(f"/api/v1/tickets/{ticket['id']}/submit", headers=eng).status_code == 409  # not approved
    client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=eng)
    assert servicedesk_server.state.requests == 0
    assert client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers=sup,
                       json={"decision": "approved", "comment": "ok"}).json()["state"] == "APPROVED"
    # Apex runs its own workflow in the same database and the same worker queue.
    a_inc = _extract(client, a_eng, REPORT)
    a_ticket = client.post("/api/v1/tickets", headers=a_eng, json={"incident_id": a_inc["id"]}).json()
    client.post(f"/api/v1/tickets/{a_ticket['id']}/request-approval", headers=a_eng)
    client.post(f"/api/v1/approvals/{a_ticket['id']}/decision", headers=a_sup, json={"decision": "approved"})

    assert sorted(worker.drain(worker_db)) == ["submitted", "submitted"]
    final = client.get(f"/api/v1/tickets/{ticket['id']}", headers=eng).json()
    assert final["state"] == "SUBMITTED" and final["external_ticket_id"].startswith("WO-")
    a_final = client.get(f"/api/v1/tickets/{a_ticket['id']}", headers=a_eng).json()
    assert a_final["state"] == "SUBMITTED" and a_final["external_ticket_id"].startswith("MNT-")
    (order,) = servicedesk_server.state.tickets.values()
    assert set(order["payload"]) == {"summary", "details", "urgency", "vehicle_ref", "source_ref"}
    assert order["payload"]["urgency"] == "normal" and order["payload"]["vehicle_ref"] == "VH-2101"
    assert order["payload"]["source_ref"] == ticket["id"] and "Harbor Fresh Foods" in order["payload"]["details"]
    assert len(ticketing.state.tickets) == 1  # the maintenance system got only Apex's ticket
    (apex_ticket,) = ticketing.state.tickets.values()
    assert apex_ticket["payload"]["source_ticket_id"] == a_ticket["id"]
    actions = [e["action"] for e in _audit(client, meridian)]
    assert {"incident.extracted", "ticket.drafted", "approval.approved", "ticket.submitted"} <= set(actions)
    assert not any(e["entity_id"] == a_ticket["id"] for e in _audit(client, meridian))  # complete, and only its own


def test_lost_response_to_the_service_desk_does_not_create_a_duplicate_work_order(
        client, meridian, worker_db, servicedesk_server):
    import httpx
    eng, sup = login(client, meridian, "support_engineer"), login(client, meridian, "maintenance_supervisor")
    inc = _extract(client, eng, BRAKE_REPORT)
    _clear_review(client, meridian, inc)
    ticket = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()
    client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=eng)
    client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers=sup, json={"decision": "approved"})
    httpx.post(f"{servicedesk_server.url}/admin/failure", json={"mode": "lost_response", "count": 1},
               headers={"X-API-Key": "test-servicedesk-key"})
    cfg = worker.WorkerConfig(backoff_base=0, backoff_cap=0)
    assert worker.drain(worker_db, cfg)[-1] == "submitted"
    assert len(servicedesk_server.state.tickets) == 1 and servicedesk_server.state.requests == 2
    assert client.get(f"/api/v1/tickets/{ticket['id']}", headers=eng).json()["state"] == "SUBMITTED"


def test_mutation_the_connector_mapping_is_what_makes_the_submission_valid(
        client, meridian, owner_engine, worker_db, servicedesk_server):
    eng, sup = login(client, meridian, "support_engineer"), login(client, meridian, "maintenance_supervisor")
    inc = _extract(client, eng, BRAKE_REPORT)
    _clear_review(client, meridian, inc)
    ticket = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()
    client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=eng)
    client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers=sup, json={"decision": "approved"})
    with owner_engine.begin() as conn:  # control removed: the connector no longer maps to the work-order contract
        conn.execute(text("UPDATE connectors SET config = '{}'::jsonb WHERE tenant_id = :t AND kind = 'ticketing'"),
                     {"t": meridian.id})
    outcome = worker.drain(worker_db, worker.WorkerConfig(backoff_base=0, backoff_cap=0))
    assert outcome == ["failed_permanent"] and not servicedesk_server.state.tickets


def test_unregistered_vehicle_is_blocked_until_registered_then_proceeds(client, meridian, worker_db, servicedesk_server):
    eng, sup = login(client, meridian, "support_engineer"), login(client, meridian, "maintenance_supervisor")
    admin = login(client, meridian, "tenant_admin")
    inc = _extract(client, eng, "Vehicle VH-9999 shows low brake pressure of 50 psi.")
    assert inc["asset_verified"] is False and inc["review_status"] == "needs_review"
    assert client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).status_code == 409
    client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup,
                json={"decision": "accept", "comment": "VH-9999 is a rental unit being added to the fleet."})
    ticket = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()
    client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=eng)
    blocked = client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers=sup, json={"decision": "approved"})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "asset_not_registered"
    register = (ROOT_SAMPLES / "fleet_register.csv").read_text(encoding="utf-8").rstrip("\n")
    resp = client.post("/api/v1/documents", headers=admin, data={"kind": "fleet_register"}, files={
        "file": ("fleet_register.csv", (register + "\nVH-9999,Rental unit,MX-300,Harbor Depot,2026-10-01,ACC-501\n").encode())})
    assert resp.status_code == 201
    assert client.post(f"/api/v1/incidents/{inc['id']}/verify-asset", headers=sup).json()["asset_verified"] is True
    assert client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers=sup,
                       json={"decision": "approved"}).status_code == 200
    assert worker.drain(worker_db) == ["submitted"] and len(servicedesk_server.state.tickets) == 1


# ---- cross-tenant isolation between Apex and Meridian ---------------------------------------------------------------------
def test_apex_and_meridian_cannot_see_or_act_on_each_other(client, meridian, apex_loaded, worker_db):
    m_eng, m_sup = login(client, meridian, "support_engineer"), login(client, meridian, "maintenance_supervisor")
    a_eng, a_sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    m_inc = _extract(client, m_eng, BRAKE_REPORT)
    _clear_review(client, meridian, m_inc)
    m_ticket = client.post("/api/v1/tickets", headers=m_eng, json={"incident_id": m_inc["id"]}).json()
    client.post(f"/api/v1/tickets/{m_ticket['id']}/request-approval", headers=m_eng)
    a_inc = _extract(client, a_eng, REPORT)
    a_ticket = client.post("/api/v1/tickets", headers=a_eng, json={"incident_id": a_inc["id"]}).json()
    client.post(f"/api/v1/tickets/{a_ticket['id']}/request-approval", headers=a_eng)

    for headers, foreign_inc, foreign_ticket in ((a_sup, m_inc, m_ticket), (m_sup, a_inc, a_ticket)):
        for method, path in (("GET", f"/api/v1/incidents/{foreign_inc['id']}"), ("GET", f"/api/v1/tickets/{foreign_ticket['id']}"),
                             ("POST", f"/api/v1/approvals/{foreign_ticket['id']}/decision"),
                             ("POST", f"/api/v1/tickets/{foreign_ticket['id']}/cancel"),
                             ("POST", f"/api/v1/incidents/{foreign_inc['id']}/verify-asset")):
            resp = client.request(method, path, headers=headers, json={"decision": "approved"})
            assert resp.status_code in (404, 409, 422), (method, path, resp.status_code)
    for headers, own, other in ((m_eng, m_ticket, a_ticket), (a_eng, a_ticket, m_ticket)):
        ids = {t["id"] for t in client.get("/api/v1/tickets", headers=headers).json()["items"]}
        assert ids == {own["id"]}
        assert other["id"] not in {w["ticket_id"] for w in client.get("/api/v1/workflows", headers=headers).json()["items"]}
        assert {c["kind"] for c in client.get("/api/v1/connectors", headers=login(client, meridian if headers is m_eng
                else apex_loaded, "tenant_admin")).json()["items"]} >= {"ticketing"}
    # Both tickets are still pending: neither tenant could approve the other's.
    assert client.get(f"/api/v1/tickets/{m_ticket['id']}", headers=m_eng).json()["state"] == "PENDING_APPROVAL"
    assert client.get(f"/api/v1/tickets/{a_ticket['id']}", headers=a_eng).json()["state"] == "PENDING_APPROVAL"
    # Vector retrieval: every chunk behind a Meridian search belongs to Meridian (checked by citation ownership).
    for inc, headers in ((m_inc, m_eng), (a_inc, a_eng)):
        for c in inc["citations"]:
            doc = client.get(f"/api/v1/documents/{c['document_id']}", headers=headers)
            assert doc.status_code == 200
    for c in m_inc["citations"]:
        assert client.get(f"/api/v1/documents/{c['document_id']}", headers=a_eng).status_code == 404
    # Meridian cannot read Apex's audit trail.
    assert not any(e["entity_id"] in (a_ticket["id"], a_inc["id"]) for e in _audit(client, meridian))
    assert not any(e["entity_id"] in (m_ticket["id"], m_inc["id"]) for e in _audit(client, apex_loaded))


def test_evaluation_registry_is_platform_evidence_identical_for_both_customers_and_carries_no_tenant_ids(client, meridian, apex):
    """Intended visibility: every tenant role with metrics:read sees the same platform-wide evaluation index; the body never contains a tenant or user id."""
    a = client.get("/api/v1/evaluation/registry?limit=200", headers=login(client, apex, "read_only_auditor"))
    m = client.get("/api/v1/evaluation/registry?limit=200", headers=login(client, meridian, "read_only_auditor"))
    assert a.status_code == m.status_code == 200 and a.json() == m.json()
    body = m.text
    for env in (apex, meridian):
        assert str(env.id) not in body
