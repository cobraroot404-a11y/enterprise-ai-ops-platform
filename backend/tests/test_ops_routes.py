"""Phase 6 backend support for the full UI: filters, history, connector/onboarding health, evaluation evidence."""
import pytest
from sqlalchemy import text
from support import REPORT, login, make_tenant, onboard_meridian


def _incident(client, headers, report=REPORT):
    resp = client.post("/api/v1/incidents/extract", headers=headers, json={"report_text": report})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_list_filters_search_sorting_and_literal_wildcards(client, apex_loaded):
    eng = login(client, apex_loaded, "support_engineer")
    docs = client.get("/api/v1/documents", headers=eng, params={"q": "register"}).json()
    assert [d["filename"] for d in docs["items"]] == ["equipment_register.csv"] and docs["total"] == 1
    by_name = client.get("/api/v1/documents", headers=eng, params={"sort": "filename", "order": "asc"}).json()["items"]
    assert [d["filename"] for d in by_name] == sorted(d["filename"] for d in by_name)
    assert client.get("/api/v1/documents", headers=eng, params={"q": "%"}).json()["total"] == 0  # literal, not a wildcard
    only = client.get("/api/v1/documents", headers=eng, params={"q": "t_r"}).json()  # literal underscore, not "any char"
    assert [d["filename"] for d in only["items"]] == ["equipment_register.csv"]
    verified = _incident(client, eng)
    unregistered = _incident(client, eng, "Pump Z-999 shows abnormal vibration at 8.4 mm/s with grinding noise.")
    needs = client.get("/api/v1/incidents", headers=eng, params={"review_status": "needs_review"}).json()
    assert {i["id"] for i in needs["items"]} == {unregistered["id"]}
    assert client.get("/api/v1/incidents", headers=eng, params={"q": "Z-999"}).json()["total"] == 1
    assert client.get("/api/v1/incidents", headers=eng, params={"priority": "P3"}).json()["total"] == 2
    assert client.get("/api/v1/incidents", headers=eng, params={"review_status": "bogus"}).status_code == 422
    asc = client.get("/api/v1/incidents", headers=eng, params={"sort": "asset_id", "order": "asc"}).json()["items"]
    assert [i["asset_id"] for i in asc] == ["P-101", "Z-999"]
    ticket = client.post("/api/v1/tickets", headers=eng, json={"incident_id": verified["id"]}).json()
    assert client.get("/api/v1/tickets", headers=eng, params={"q": "P-101"}).json()["total"] == 1
    assert client.get("/api/v1/tickets", headers=eng, params={"priority": "P4"}).json()["total"] == 0
    assert client.get("/api/v1/tickets", headers=eng, params={"state": "DRAFT", "sort": "bogus"}).json()["total"] == 1
    wf = client.get("/api/v1/workflows", headers=eng, params={"status": "pending"}).json()
    assert wf["total"] == 0
    assert client.get("/api/v1/workflows", headers=eng, params={"ticket_id": ticket["id"]}).json()["total"] == 0


def test_audit_filters_metrics_and_histories(client, apex_loaded, worker_db, ticketing):
    from app.workflows import worker
    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    aud = login(client, apex_loaded, "read_only_auditor")
    inc = _incident(client, eng)
    ticket = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()
    client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=eng)
    client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers=sup,
                json={"decision": "approved", "comment": "looks right"})
    assert worker.drain(worker_db) == ["submitted"]
    audit = client.get("/api/v1/audit", headers=aud, params={"entity_type": "ticket", "q": "approval"}).json()
    assert audit["total"] >= 1 and all(i["entity_type"] == "ticket" and "approval" in i["action"] for i in audit["items"])
    hist = client.get(f"/api/v1/tickets/{ticket['id']}/history", headers=eng).json()  # tickets:read, not audit:read
    actions = [e["action"] for e in hist["events"]]
    assert "ticket.drafted" in actions and "approval.approved" in actions and "ticket.submitted" in actions
    assert hist["approvals"][0]["decision"] == "approved" and hist["approvals"][0]["comment"] == "looks right"
    ih = client.get(f"/api/v1/incidents/{inc['id']}/history", headers=eng).json()
    assert "incident.extracted" in [e["action"] for e in ih["events"]] and ih["tickets"][0]["state"] == "SUBMITTED"
    m = client.get("/api/v1/metrics", headers=eng).json()
    assert m["incidents_by_review_status"] == {"pending_review": 1} and m["tickets_by_state"] == {"SUBMITTED": 1}
    assert m["outbox_by_status"] == {"done": 1} and m["incidents_by_priority"] == {"P3": 1}
    assert m["tickets_needing_retries"] == 0 and m["documents_by_kind"]["equipment_register"] == 1


def test_connector_health_reports_configuration_and_delivery_not_a_fake_probe(client, apex, owner_engine):
    admin = login(client, apex, "tenant_admin")
    items = client.get("/api/v1/connectors/health", headers=admin).json()["items"]
    by_kind = {i["kind"]: i for i in items}
    assert by_kind["ticketing"]["status"] == "ok" and by_kind["ticketing"]["destination_authorized"] is True
    assert by_kind["ticketing"]["secret_configured"] is True and "none" in by_kind["ticketing"]["probe"]
    assert by_kind["ticketing"]["delivery"]["submitted"] == 0
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE connectors SET base_url = 'http://169.254.169.254' "
                          "WHERE tenant_id = :t AND kind = 'inventory'"), {"t": apex.id})
    after = {i["kind"]: i for i in client.get("/api/v1/connectors/health", headers=admin).json()["items"]}["inventory"]
    assert after["status"] == "blocked" and after["destination_authorized"] is False
    assert client.get("/api/v1/connectors/health", headers=login(client, apex, "support_engineer")).status_code == 403


def test_onboarding_health_is_derived_from_real_configuration(client, owner_engine, servicedesk_server, fleet_server,
                                                              crm_server, apex_loaded):
    meridian = onboard_meridian(client, owner_engine, servicedesk_server, fleet_server, crm_server, "ob")
    admin = login(client, meridian, "tenant_admin")
    health = client.get("/api/v1/onboarding/health", headers=admin).json()
    status = {c["id"]: c["status"] for c in health["checks"]}
    assert status["register"] == "pass" and status["guidance"] == "pass" and status["destinations"] == "pass"
    assert health["passed"] == health["total"]
    eng = client.get("/api/v1/onboarding/health", headers=login(client, meridian, "support_engineer")).json()
    assert any(c["status"] == "unavailable" for c in eng["checks"])  # connector detail is admin-only
    apex_health = client.get("/api/v1/onboarding/health", headers=login(client, apex_loaded, "tenant_admin")).json()
    assert {c["id"]: c["status"] for c in apex_health["checks"]}["register"] == "pass"


def test_onboarding_health_fails_honestly_for_an_empty_tenant(client, apex):
    checks = {c["id"]: c["status"] for c in
              client.get("/api/v1/onboarding/health", headers=login(client, apex, "tenant_admin")).json()["checks"]}
    assert checks["register"] == "fail" and checks["guidance"] == "fail" and checks["embedding"] == "fail"


def test_history_endpoints_are_tenant_scoped(client, apex_loaded, owner_engine):
    apex = make_tenant(owner_engine, "histother")
    eng = login(client, apex_loaded, "support_engineer")
    inc = _incident(client, eng)
    ticket = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()
    other = login(client, apex, "support_engineer")
    assert client.get(f"/api/v1/tickets/{ticket['id']}/history", headers=other).status_code == 404
    assert client.get(f"/api/v1/incidents/{inc['id']}/history", headers=other).status_code == 404


def test_evaluation_reports_are_read_from_artifacts_and_report_targets_honestly(client, apex):
    data = client.get("/api/v1/evaluation/reports", headers=login(client, apex, "read_only_auditor")).json()
    assert data["available"] and "Targets are proposals" in data["disclaimer"]
    real = [r for r in data["runs"] if r["evidence_class"] == "real_ai"]
    assert len(real) >= 6 and {r["group"] for r in real} == {"phase3", "phase4-remeasure"}
    targets = {t["id"]: t for t in data["targets"]}
    assert targets["citation_correctness"]["status"] == "NOT MET" and targets["citation_correctness"]["actual"]["max"] < 0.95
    assert targets["recall_at_5"]["status"] == "MET" and targets["structured_validity"]["status"] == "NOT MET"
    assert data["smoke"] and data["smoke"][-1]["checks_passed"] == data["smoke"][-1]["checks_total"]
    assert "functional only" in data["disclaimer"]
    assert data["fault_injection"]["scenarios"] == data["fault_injection"]["passed"] == 11
    baseline = [r for r in data["runs"] if r["evidence_class"] != "real_ai"]
    assert baseline and all("deterministic" in r["evidence_class"] for r in baseline)


@pytest.mark.parametrize("path", ["/api/v1/evaluation/reports", "/api/v1/connectors/health", "/api/v1/onboarding/health"])
def test_new_endpoints_require_authentication(client, path):
    assert client.get(path).status_code == 401


def test_evaluation_registry_is_read_only_paged_and_authenticated(client, apex, owner_engine):
    from sqlalchemy import text
    with owner_engine.begin() as c:
        c.execute(text("DELETE FROM evaluation_runs WHERE manifest_path LIKE 'tmp-reg-ops/%'"))
        for i in range(3):
            c.execute(text("INSERT INTO evaluation_runs (run_id, suite, manifest_path, manifest_sha256, started_at) VALUES (:r, 'tmp-suite', :p, :s, now())"),
                      {"r": f"ops-{i}", "p": f"tmp-reg-ops/{i}/manifest.json", "s": "a" * 64})
    try:
        assert client.get("/api/v1/evaluation/registry").status_code == 401
        h = login(client, apex, "read_only_auditor")
        data = client.get("/api/v1/evaluation/registry?suite=tmp-suite&limit=2", headers=h).json()
        assert data["total"] == 3 and len(data["items"]) == 2 and data["items"][0]["manifest_sha256"] == "a" * 64
        assert len(client.get("/api/v1/evaluation/registry?suite=tmp-suite&limit=2&offset=2", headers=h).json()["items"]) == 1
        assert client.get("/api/v1/evaluation/registry?limit=0", headers=h).status_code == 422
        for method in ("post", "put", "delete", "patch"):
            assert getattr(client, method)("/api/v1/evaluation/registry", headers=h).status_code == 405
        # any tenant role with metrics:read sees the same platform evidence (no tenant data in this table)
        other = login(client, apex, "support_engineer")
        assert client.get("/api/v1/evaluation/registry?suite=tmp-suite", headers=other).json()["total"] == 3
    finally:
        with owner_engine.begin() as c:
            c.execute(text("DELETE FROM evaluation_runs WHERE manifest_path LIKE 'tmp-reg-ops/%'"))
