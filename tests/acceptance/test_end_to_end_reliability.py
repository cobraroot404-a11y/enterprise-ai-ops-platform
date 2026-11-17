"""End-to-end reliability for both customers (works in both UAT_BACKEND modes; AI-dependent steps assert invariants).

Document ingestion -> retrieval -> grounded AI response -> incident extraction -> human review -> ticket approval -> outbox
processing -> external mock submission -> audit record, with transient failures and a lost response injected on the way.
A reconciliation step then proves: no unauthorized external action, no duplicate ticket, correct isolation, accurate states.
"""
import httpx
import pytest
from app.workflows import worker
from sqlalchemy import text
from support import REPORT, TICKETING_KEY, login

FAST = worker.WorkerConfig(backoff_base=0, backoff_cap=0, http_timeout=1.0)
BRAKE = "Vehicle VH-2101 shows low brake pressure of 52 psi with a hissing noise at the rear axle."
EXPECTED_ORDER = ["incident.extracted", "ticket.drafted", "approval.approved", "ticket.submitted"]


def _inject(url, key, mode):
    assert httpx.post(f"{url}/admin/failure", json={"mode": mode, "count": 1}, headers={"X-API-Key": key}).status_code == 200


def _run(client, tenant, report, question, mocks, worker_db, owner_engine, failures):
    eng, sup = login(client, tenant, "support_engineer"), login(client, tenant, "maintenance_supervisor")
    aud = login(client, tenant, "read_only_auditor")
    docs = client.get("/api/v1/documents", headers=eng).json()["total"]
    hits = client.post("/api/v1/search", headers=eng, json={"query": question, "k": 5}).json()["items"]
    answer = client.post("/api/v1/ai/ask", headers=eng, json={"question": question}).json()
    assert docs >= 4 and hits and (answer["grounded"] or answer["citations"] == [])
    submitted = []
    for failure in failures:
        inc = client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": report}).json()
        if inc["review_status"] == "needs_review":
            assert client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).status_code == 409  # gate holds
            assert client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup, json={
                "decision": "accept", "comment": "End-to-end reliability: supervisor review."}).status_code == 200
        t = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()["id"]
        assert client.post(f"/api/v1/tickets/{t}/submit", headers=eng).status_code == 409  # not approved yet
        client.post(f"/api/v1/tickets/{t}/request-approval", headers=eng)
        assert client.post(f"/api/v1/approvals/{t}/decision", headers=eng, json={"decision": "approved"}).status_code == 403
        if failure:
            _inject(mocks["url"], mocks["key"], failure)
        assert client.post(f"/api/v1/approvals/{t}/decision", headers=sup, json={"decision": "approved"}).status_code == 200
        outcomes = worker.drain(worker_db, FAST)
        assert outcomes[-1] == "submitted", outcomes
        submitted.append(t)
    # ---- reconciliation: external system vs database vs audit trail ------------------------------------------------------------
    external = list(mocks["state"].tickets.values())
    assert len(external) == len(submitted)  # no duplicate tickets under retries or a lost response
    source_ids = {(e["payload"].get("source_ticket_id") or e["payload"].get("source_ref")) for e in external}
    assert source_ids == set(submitted)  # every external action corresponds to a ticket created and approved here
    with owner_engine.connect() as c:
        unapproved = c.execute(text(
            "SELECT count(*) FROM tickets t WHERE t.tenant_id = :t AND t.state IN ('SUBMITTED','SUBMITTING') AND NOT EXISTS "
            "(SELECT 1 FROM approvals a WHERE a.ticket_id = t.id AND a.decision = 'approved')"), {"t": tenant.id}).scalar()
    assert unapproved == 0
    log = client.get("/api/v1/audit", headers=aud, params={"limit": 100}).json()["items"]
    for t in submitted:
        seq = [a["action"] for a in sorted((a for a in log if a["entity_id"] == t), key=lambda a: a["id"])]
        positions = [seq.index(a) for a in ("ticket.drafted", "approval.approved", "ticket.submitted")]
        assert positions == sorted(positions), seq  # drafted before approved before submitted
        final = client.get(f"/api/v1/tickets/{t}", headers=eng).json()
        assert final["state"] == "SUBMITTED" and final["external_ticket_id"] and final["attempts"] >= 1
    assert sum(1 for a in log if a["action"] == "ticket.submitted") == len(submitted)
    return submitted


def test_apex_end_to_end_reliability(uat_client, apex_uat, ticketing, worker_db, owner_engine):
    mocks = {"url": ticketing.url, "key": TICKETING_KEY, "state": ticketing.state}
    done = _run(uat_client, apex_uat, REPORT, "What should I check when pump P-101 shows abnormal vibration?", mocks, worker_db,
                owner_engine, failures=[None, "503", "lost_response"])
    assert len(done) == 3 and ticketing.state.requests >= 5  # retries happened, duplicates did not


def test_meridian_end_to_end_reliability(uat_client, meridian_uat, apex_uat, ticketing, servicedesk_server, worker_db, owner_engine):
    mocks = {"url": servicedesk_server.url, "key": "test-servicedesk-key", "state": servicedesk_server.state}
    done = _run(uat_client, meridian_uat, BRAKE, "What should I do when the service brake line pressure falls below 55 psi?", mocks,
                worker_db, owner_engine, failures=[None, "503", "lost_response"])
    assert len(done) == 3 and servicedesk_server.state.requests >= 5
    assert len(ticketing.state.tickets) == 0 and ticketing.state.requests == 0  # Apex's system was never contacted by Meridian's workflow


@pytest.mark.parametrize("failure", ["429", "malformed"])
def test_other_transient_failure_classes_recover_without_duplicates(uat_client, apex_uat, ticketing, worker_db, owner_engine, failure):
    mocks = {"url": ticketing.url, "key": TICKETING_KEY, "state": ticketing.state}
    done = _run(uat_client, apex_uat, REPORT, "What should I check when pump P-101 shows abnormal vibration?", mocks, worker_db,
                owner_engine, failures=[failure])
    assert len(done) == 1 and len(ticketing.state.tickets) == 1
