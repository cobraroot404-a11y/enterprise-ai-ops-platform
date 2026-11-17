"""UAT-B01 .. UAT-B07: Meridian Fleet Logistics (fictional) acceptance scenarios, through the real HTTP API.

Meridian is onboarded through the public API and configuration only. Deterministic mode proves workflow, isolation and integration
behaviour; AI behaviour is accepted only from the UAT_BACKEND=real run.
"""
import copy
import json
import uuid
from pathlib import Path

import httpx
from app.workflows import worker
from sqlalchemy import text
from support import PASSWORD, REPORT, ROOT, login, onboard_meridian

MERIDIAN = "Meridian Fleet Logistics (fictional)"
BRAKE = "Vehicle VH-2101 shows low brake pressure of 52 psi with a hissing noise at the rear axle."
FAST = worker.WorkerConfig(backoff_base=0, backoff_cap=0, http_timeout=1.0)
DESK_KEY = "test-servicedesk-key"


def inject_desk(servicedesk, mode, count=1):
    r = httpx.post(f"{servicedesk.url}/admin/failure", json={"mode": mode, "count": count}, headers={"X-API-Key": DESK_KEY})
    assert r.status_code == 200


def audit_actions(client, tenant):
    aud = login(client, tenant, "read_only_auditor")
    return [a["action"] for a in client.get("/api/v1/audit", headers=aud, params={"limit": 100}).json()["items"]]


def approved_ticket(client, m, report=BRAKE):
    eng, sup = login(client, m, "support_engineer"), login(client, m, "maintenance_supervisor")
    adm = login(client, m, "tenant_admin")
    inc = client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": report}).json()
    author = eng
    if inc["review_status"] == "needs_review":
        assert client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup, json={
            "decision": "accept", "comment": "UAT supervisor review of an incident without verified evidence."}).status_code == 200
    ticket = client.post("/api/v1/tickets", headers=author, json={"incident_id": inc["id"]}).json()
    client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=author)
    res = client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers=sup, json={"decision": "approved", "comment": "UAT"})
    assert res.status_code == 200
    return inc, ticket["id"], eng, sup, adm


def test_uat_b01_second_tenant_onboarding(uat, uat_client, owner_engine, servicedesk_server, fleet_server, crm_server):
    with uat("UAT-B01", MERIDIAN, "Second-tenant onboarding", ["R10.1", "R10.3", "R8.1"],
             "Platform running with Apex; Meridian origins authorized by the operator (server allow-list); no Meridian code exists in the services",
             "onboarding/meridian.json (tenant, members, connectors, domain profile, documents)",
             ["Run the onboarding tool against the public API only", "Read the onboarding health checks", "Check that no customer-specific tables exist"],
             "Meridian exists as a separate tenant with members, connectors, profile and documents created through supported APIs only, and all health "
             "checks pass; the database schema contains no Meridian-specific objects") as u:
        m = onboard_meridian(uat_client, owner_engine, servicedesk_server, fleet_server, crm_server, "uatb01")
        health = uat_client.get("/api/v1/onboarding/health", headers=login(uat_client, m, "tenant_admin")).json()
        profile = uat_client.get("/api/v1/tenant-profile", headers=login(uat_client, m, "support_engineer")).json()
        with owner_engine.connect() as c:
            tables = {r[0] for r in c.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))}
        assert health["passed"] == health["total"] > 5 and profile["profile"]["asset_label"] == "vehicle"
        assert not any(w in t for t in tables for w in ("meridian", "apex", "fleet"))
        u.actual = f"{health['passed']} of {health['total']} onboarding checks pass; profile v{profile['version']}; no customer-specific tables"
        u.evidence = {"health": {c["id"]: c["status"] for c in health["checks"]}, "profile_version": profile["version"]}


def test_uat_b02_customer_specific_schema_mapping(uat, uat_client, meridian_uat):
    eng = login(uat_client, meridian_uat, "support_engineer")
    with uat("UAT-B02", MERIDIAN, "Customer-specific schema mapping", ["R10.2", "R12.3"], "Meridian onboarded with field mappings in its profile",
             "fleet_register.csv, service_history.csv, telematics_alerts.csv with Meridian's own column names",
             ["Search for a service record", "Inspect the stored passage and record id"],
             "Records are keyed by Meridian's ids (VH-xxxx, SR-xxxx) and carry the mapped column names (vehicle_id, root_cause, resolution)") as u:
        hits = uat_client.post("/api/v1/search", headers=eng, json={"query": "VH-2101 brake chamber diaphragm hissing", "k": 8}).json()["items"]
        history = [h for h in hits if h["filename"] == "service_history.csv"]
        assert history and history[0]["record_id"].startswith("SR-") and "root_cause" in history[0]["text"] and "vehicle_id" in history[0]["text"]
        register = uat_client.post("/api/v1/search", headers=eng, json={"query": "VH-2101 refrigerated delivery truck", "k": 8}).json()["items"]
        assert any(h["filename"] == "fleet_register.csv" and h["record_id"] == "VH-2101" for h in register)
        u.actual = f"service record {history[0]['record_id']} and register record VH-2101 carry mapped columns"
        u.evidence = {"service_record": history[0]["record_id"], "mapped_columns_present": ["vehicle_id", "root_cause"]}


def test_uat_b03_fleet_issue_extraction(uat, uat_client, meridian_uat, uat_mode, fleet_server, crm_server):
    eng = login(uat_client, meridian_uat, "support_engineer")
    with uat("UAT-B03", MERIDIAN, "Fleet issue extraction", ["R14.1", "R14.3", "R8.1"], "Meridian onboarded; fleet and CRM mocks running",
             f"Report: {BRAKE}", ["Extract the incident", "Check asset verification, deterministic priority and enrichment notes", "Extract a report with no vehicle id"],
             "VH-2101 identified and verified against the fleet register; priority P3 from Meridian's category rules (the free-text 52 psi is an UNVERIFIED candidate, not a priority input); fleet telematics and CRM "
             "notes present; a report without a vehicle id is rejected, never guessed",
             limitations="In real-AI mode the model may choose a near-miss category (observed: 'leak'); priority follows the extracted category and the regex-read signals.") as u:
        inc = uat_client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": BRAKE}).json()
        notes = " ".join(inc["notes"])
        assert inc["asset_id"] == "VH-2101" and inc["asset_verified"] is True and inc["priority"] in ("P2", "P3")  # category-driven; real-model category may differ
        assert "odometer" in notes and "Harbor Fresh Foods" in notes
        assert inc["review_status"] == ("pending_review" if inc["citations"] else "needs_review")
        bad = uat_client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": "A strange noise somewhere in the depot, no idea which truck."})
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "asset_not_identified"
        u.actual = f"VH-2101 verified; category {inc['category']}; priority {inc['priority']}; {len(inc['citations'])} citation(s); enrichments present"
        u.evidence = {"category": inc["category"], "priority": inc["priority"], "review_status": inc["review_status"], "backend": uat_mode,
                      "extraction_backend": inc["extraction_backend"]}


def test_uat_b04_ticket_approval(uat, uat_client, meridian_uat):
    eng, sup = login(uat_client, meridian_uat, "support_engineer"), login(uat_client, meridian_uat, "maintenance_supervisor")
    with uat("UAT-B04", MERIDIAN, "Ticket approval", ["R15.1", "R15.2", "R8.1"], "Meridian incident extracted",
             "VH-2101 brake incident", ["Draft and request approval as an engineer", "Engineer tries to approve", "Supervisor approves"],
             "The author cannot approve; the supervisor's decision is recorded with a comment; the ticket becomes APPROVED") as u:
        inc = uat_client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": BRAKE}).json()
        if inc["review_status"] == "needs_review":
            uat_client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup, json={"decision": "accept", "comment": "UAT supervisor review."})
        t = uat_client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()["id"]
        uat_client.post(f"/api/v1/tickets/{t}/request-approval", headers=eng)
        assert uat_client.post(f"/api/v1/approvals/{t}/decision", headers=eng, json={"decision": "approved"}).status_code == 403
        done = uat_client.post(f"/api/v1/approvals/{t}/decision", headers=sup, json={"decision": "approved", "comment": "Brake fault verified"}).json()
        history = uat_client.get(f"/api/v1/tickets/{t}/history", headers=eng).json()
        assert done["state"] == "APPROVED" and history["approvals"][0]["comment"] == "Brake fault verified"
        u.actual = "author approval 403; supervisor approval recorded with comment; ticket APPROVED"
        u.evidence = {"state": done["state"], "approvals": history["approvals"]}


def test_uat_b05_correct_customer_api_submission(uat, uat_client, meridian_uat, apex_uat, worker_db, servicedesk_server, ticketing):
    with uat("UAT-B05", MERIDIAN, "Correct customer API submission", ["R11.1", "R10.2", "R8.1"], "Meridian connector maps to the service-desk work-order contract; Apex also active",
             "Approved Meridian ticket and an approved Apex ticket in the same worker queue",
             ["Approve both tickets", "Run the worker", "Inspect each external system"],
             "Meridian's ticket arrives only at its service desk as a work order with the mapped fields and urgency (WO- id); Apex's reaches only its own system (MNT- id)") as u:
        approved_ticket(uat_client, apex_uat, REPORT)
        _, tid, eng, _, _ = approved_ticket(uat_client, meridian_uat)
        assert sorted(worker.drain(worker_db, FAST)) == ["submitted", "submitted"]
        final = uat_client.get(f"/api/v1/tickets/{tid}", headers=eng).json()
        (order,) = servicedesk_server.state.tickets.values()
        assert final["external_ticket_id"].startswith("WO-") and len(ticketing.state.tickets) == 1
        assert set(order["payload"]) == {"summary", "details", "urgency", "vehicle_ref", "source_ref"}
        assert order["payload"]["urgency"] == {"P2": "high", "P3": "normal"}[final["priority"]] and order["payload"]["vehicle_ref"] == "VH-2101" and order["payload"]["source_ref"] == tid
        u.actual = f"work order {final['external_ticket_id']} with mapped fields; Apex system received only its own ticket"
        u.evidence = {"work_order": final["external_ticket_id"], "payload_keys": sorted(order["payload"]), "urgency": order["payload"]["urgency"],
                      "apex_system_tickets": len(ticketing.state.tickets)}


def test_uat_b06_cross_tenant_access_denied(uat, uat_client, meridian_uat, apex_uat):
    with uat("UAT-B06", MERIDIAN, "Cross-tenant access denied", ["R16.1", "R8.1"], "Apex and Meridian both hold incidents, tickets and documents",
             "Apex and Meridian users of every role", ["Create a ticket in each tenant", "Each tenant's users try to read and act on the other's objects",
              "Search and ask from each tenant for the other's content"],
             "Every cross-tenant read or action is denied or hidden; retrieval never returns the other tenant's passages; audit trails are separate") as u:
        m_eng, a_eng = login(uat_client, meridian_uat, "support_engineer"), login(uat_client, apex_uat, "support_engineer")
        m_inc = uat_client.post("/api/v1/incidents/extract", headers=m_eng, json={"report_text": BRAKE}).json()
        a_inc = uat_client.post("/api/v1/incidents/extract", headers=a_eng, json={"report_text": REPORT}).json()
        for headers, foreign in ((a_eng, m_inc), (m_eng, a_inc)):
            assert uat_client.get(f"/api/v1/incidents/{foreign['id']}", headers=headers).status_code == 404
        denied = 0
        for role in ("tenant_admin", "maintenance_supervisor", "support_engineer", "read_only_auditor"):
            h = login(uat_client, apex_uat, role)
            for method, path in (("GET", f"/api/v1/incidents/{m_inc['id']}"), ("POST", f"/api/v1/incidents/{m_inc['id']}/review"),
                                 ("POST", f"/api/v1/incidents/{m_inc['id']}/verify-asset")):
                r = uat_client.request(method, path, headers=h, json={"decision": "accept", "comment": "cross tenant attempt"})
                denied += r.status_code in (403, 404, 409, 422)
        hits = uat_client.post("/api/v1/search", headers=a_eng, json={"query": "brake line pressure air dryer VH-2101", "k": 10}).json()["items"]
        m_hits = uat_client.post("/api/v1/search", headers=m_eng, json={"query": "pump bearing vibration drive end", "k": 10}).json()["items"]
        assert denied == 12 and not any(h["filename"].startswith(("meridian", "fleet", "service", "telematics")) for h in hits)
        assert not any(h["filename"].startswith(("apex", "equipment_", "incident_h", "maintenance_l")) for h in m_hits)
        assert not any(a["entity_id"] == m_inc["id"] for a in uat_client.get("/api/v1/audit", headers=login(uat_client, apex_uat, "tenant_admin")).json()["items"])
        u.actual = "12 of 12 cross-tenant attempts denied; searches stayed inside each tenant; audit trails separate"
        u.evidence = {"attempts_denied": denied, "apex_search_hits": len(hits), "meridian_search_hits": len(m_hits)}


def test_uat_b07_failure_recovery(uat, uat_client, meridian_uat, worker_db, servicedesk_server):
    with uat("UAT-B07", MERIDIAN, "Failure recovery", ["R15.4", "R15.3", "R11.2"], "Meridian approved tickets; service-desk mock configurable",
             "HTTP 503 once, then a lost response", ["Approve a ticket while the service desk returns 503", "Run the worker", "Approve another and lose the response", "Run the worker"],
             "Both tickets end SUBMITTED; each produced exactly one work order (the lost response is replayed with the same idempotency key)") as u:
        inject_desk(servicedesk_server, "503", 1)
        _, t1, eng, _, _ = approved_ticket(uat_client, meridian_uat)
        o1 = worker.drain(worker_db, FAST)
        inject_desk(servicedesk_server, "lost_response", 1)
        _, t2, eng, _, _ = approved_ticket(uat_client, meridian_uat)
        o2 = worker.drain(worker_db, FAST)
        s1 = uat_client.get(f"/api/v1/tickets/{t1}", headers=eng).json()
        s2 = uat_client.get(f"/api/v1/tickets/{t2}", headers=eng).json()
        assert o1 == ["retry_scheduled", "submitted"] and o2[-1] == "submitted"
        assert s1["state"] == s2["state"] == "SUBMITTED" and len(servicedesk_server.state.tickets) == 2
        u.actual = f"503: {o1}; lost response: {o2}; work orders {len(servicedesk_server.state.tickets)} for 2 tickets"
        u.evidence = {"transient_outcomes": o1, "lost_response_outcomes": o2, "work_orders": 2}


def test_uat_b_meridian_uses_the_same_application_and_no_customer_code(uat, uat_client):
    """Supporting check for R8.1: no shared service names Meridian or fleet concepts (configuration only)."""
    import re
    root = Path(ROOT)
    offenders = []
    for path in (root / "backend" / "app").rglob("*.py"):
        if re.search(r"meridian|VH-d{4}", path.read_text(encoding="utf-8"), re.IGNORECASE):
            offenders.append(path.relative_to(root).as_posix())
    allowed: set[str] = set()  # "fleet" is only a generic connector kind name; customer names and ids appear nowhere
    assert set(offenders) <= allowed, offenders
    assert PASSWORD and copy and json and uuid  # keep imports used
