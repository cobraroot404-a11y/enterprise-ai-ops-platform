"""Phase 4 closure: the incident human-review gate cannot be bypassed.

Review (incident level) and approval (ticket level) are separate authorization events; a supervisor's
acceptance never turns unsupported claims into verified facts, and nothing leaves the platform for an
unregistered asset or an uncleared incident - by direct API call, retry or concurrent request.
"""
import threading

import pytest
from app.ai.embeddings import DeterministicEmbedder
from app.ai.llm import LLMOutputInvalid
from app.services.incident_service import extract_incident
from app.workflows import worker
from sqlalchemy import text
from support import REPORT, SAMPLES, login

UNREGISTERED = "Pump Z-999 shows abnormal vibration at 8.4 mm/s with grinding noise."
ACCEPT = {"decision": "accept", "comment": "Z-999 is a newly installed pump, verified on site."}


def _extract(client, headers, report=UNREGISTERED):
    resp = client.post("/api/v1/incidents/extract", headers=headers, json={"report_text": report})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _actions(client, tenant):
    aud = login(client, tenant, "read_only_auditor")
    return [a["action"] for a in client.get("/api/v1/audit", headers=aud, params={"limit": 100}).json()["items"]]


def _register_with_z999(client, headers):
    base = (SAMPLES / "equipment_register.csv").read_text(encoding="utf-8").rstrip("\n")
    data = (base + "\nZ-999,New cooling pump,CP-200,Plant 2,2026-10-01\n").encode()
    resp = client.post("/api/v1/documents", headers=headers, data={"kind": "equipment_register"},
                       files={"file": ("equipment_register.csv", data)})
    assert resp.status_code == 201, resp.text


def test_acceptance_never_turns_unsupported_claims_into_verified_facts(client, apex_loaded):
    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    inc = _extract(client, eng)
    accepted = client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup, json=ACCEPT).json()
    assert accepted["review_status"] == "accepted"
    assert accepted["asset_verified"] is False and accepted["citations"] == inc["citations"]
    assert any("Justification: Z-999 is a newly installed pump" in n for n in accepted["notes"])
    # Acceptance is not an approval: no ticket exists, no approval row exists, and the audit actions differ.
    assert client.get("/api/v1/tickets", headers=eng).json()["items"] == []
    assert client.get("/api/v1/approvals", headers=sup, params={"status": "decided"}).json()["items"] == []
    assert "incident.review_accept" in _actions(client, apex_loaded)
    assert not any(a.startswith("approval.") for a in _actions(client, apex_loaded))


def test_accepted_but_unregistered_asset_is_blocked_at_approval_and_submission(
        client, apex_loaded, worker_db, ticketing):
    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    inc = _extract(client, eng)
    client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup, json=ACCEPT)
    ticket = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()
    client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=eng)

    resp = client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers=sup, json={"decision": "approved"})
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "asset_not_registered"
    assert client.get(f"/api/v1/tickets/{ticket['id']}", headers=eng).json()["state"] == "PENDING_APPROVAL"
    assert client.post(f"/api/v1/tickets/{ticket['id']}/submit", headers=eng).status_code == 409
    assert worker.drain(worker_db) == [] and not ticketing.state.tickets
    # Reviewer assertion alone cannot verify the asset: re-verification only reads the register.
    still = client.post(f"/api/v1/incidents/{inc['id']}/verify-asset", headers=sup).json()
    assert still["asset_verified"] is False

    # Authorized registration process: an audited register upload, then a re-verification event.
    _register_with_z999(client, eng)
    verified = client.post(f"/api/v1/incidents/{inc['id']}/verify-asset", headers=sup).json()
    assert verified["asset_verified"] is True
    done = client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers=sup, json={"decision": "approved"})
    assert done.status_code == 200 and done.json()["state"] == "APPROVED"
    assert worker.drain(worker_db) == ["submitted"] and len(ticketing.state.tickets) == 1
    actions = _actions(client, apex_loaded)
    assert {"incident.review_accept", "incident.asset_reverified", "approval.approved", "ticket.submitted"} <= set(actions)


def test_rejected_and_unresolved_incidents_cannot_bypass_the_gate(client, apex_loaded):
    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    unresolved, rejected = _extract(client, eng), _extract(client, eng, "Pump Z-998 vibrates at 6 mm/s, grinding.")
    client.post(f"/api/v1/incidents/{rejected['id']}/review", headers=sup,
                json={"decision": "reject", "comment": "Not a real asset."})
    for inc in (unresolved, rejected):
        for _ in range(3):  # repeated attempts are refused every time
            resp = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]})
            assert resp.status_code == 409 and resp.json()["error"]["code"] == "incident_needs_review"
    # A rejected incident can't be re-reviewed or re-verified into acceptance either.
    assert client.post(f"/api/v1/incidents/{rejected['id']}/review", headers=sup, json=ACCEPT).status_code == 409
    assert client.post(f"/api/v1/incidents/{rejected['id']}/verify-asset", headers=sup).status_code == 409
    assert client.get("/api/v1/tickets", headers=eng).json()["items"] == []


def test_worker_refuses_to_release_if_incident_stops_being_cleared(
        client, apex_loaded, owner_engine, worker_db, ticketing):
    """Defence in depth: even an approved ticket is not sent if its incident no longer clears the gate."""
    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    inc = _extract(client, eng, REPORT)
    ticket = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()
    client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=eng)
    assert client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers=sup,
                       json={"decision": "approved"}).status_code == 200
    with owner_engine.begin() as conn:  # simulate state tampering after approval
        conn.execute(text("UPDATE incidents SET asset_verified = false WHERE id = :i"), {"i": inc["id"]})
    assert worker.drain(worker_db) == ["blocked"]
    assert not ticketing.state.tickets and ticketing.state.requests == 0
    assert "submission.blocked" in _actions(client, apex_loaded)
    assert client.get(f"/api/v1/tickets/{ticket['id']}", headers=eng).json()["state"] == "APPROVED"


def test_concurrent_reviews_have_exactly_one_winner(client, apex_loaded):
    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    inc = _extract(client, eng)
    codes = []
    bodies = [{"decision": d, "comment": "concurrent review attempt"} for d in ("accept", "reject") * 3]
    threads = [threading.Thread(target=lambda b=b: codes.append(
        client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup, json=b).status_code)) for b in bodies]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [200] + [409] * 5
    final = client.get(f"/api/v1/incidents/{inc['id']}", headers=eng).json()["review_status"]
    assert final in ("accepted", "rejected")
    reviews = [a for a in _actions(client, apex_loaded) if a.startswith("incident.review_")]
    assert len(reviews) == 1


def test_concurrent_draft_requests_create_one_ticket(client, apex_loaded):
    eng = login(client, apex_loaded, "support_engineer")
    inc = _extract(client, eng, REPORT)
    codes = []
    threads = [threading.Thread(target=lambda: codes.append(
        client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).status_code)) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert codes.count(201) == 1 and codes.count(409) == 4


class _InvalidLLM:
    name, model = "scripted", "test"

    def extract_fields(self, report_text):
        raise LLMOutputInvalid("not json")

    def answer(self, question, passages):
        from app.ai.llm import get_llm
        return get_llm("deterministic").answer(question, passages)


@pytest.mark.parametrize("report", [REPORT])
def test_validation_failure_fallback_forces_human_review(app_db, owner_engine, apex_loaded, report):
    with owner_engine.connect() as c:
        uid = str(c.execute(text("SELECT id FROM users WHERE email = :e"),
                            {"e": apex_loaded.users["support_engineer"]}).scalar())
    with app_db.session(apex_loaded.id, uid) as s:
        inc = extract_incident(s, tenant_id=apex_loaded.id, user_id=uid, report_text=report,
                               embedder=DeterministicEmbedder(), llm=_InvalidLLM())
        assert inc.asset_verified and inc.citations  # everything else is fine...
        assert inc.review_status == "needs_review"   # ...but unresolved model-output failure needs a human
        assert any("failed validation" in n or "model output" in n for n in inc.notes)


def test_retry_of_a_failed_ticket_is_blocked_if_the_incident_no_longer_clears_the_gate(
        client, apex_loaded, owner_engine, worker_db, ticketing):
    import httpx
    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    inc = _extract(client, eng, REPORT)
    ticket = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()
    client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=eng)
    client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers=sup, json={"decision": "approved"})
    httpx.post(f"{ticketing.url}/admin/failure", json={"mode": "400", "count": 1}, headers={"X-API-Key": "test-ticketing-key"})
    assert worker.drain(worker_db) == ["failed_permanent"]
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE incidents SET asset_verified = false WHERE id = :i"), {"i": inc["id"]})
    retry = client.post(f"/api/v1/tickets/{ticket['id']}/retry", headers=sup)
    assert retry.status_code == 409 and retry.json()["error"]["code"] == "asset_not_registered"
    assert worker.drain(worker_db) == [] and ticketing.state.requests == 1  # nothing was re-sent
    with owner_engine.begin() as conn:  # a rejected incident can never be released either
        conn.execute(text("UPDATE incidents SET asset_verified = true, review_status = 'rejected' WHERE id = :i"),
                     {"i": inc["id"]})
    retry = client.post(f"/api/v1/tickets/{ticket['id']}/retry", headers=sup)
    assert retry.status_code == 409 and retry.json()["error"]["code"] == "incident_not_cleared"
