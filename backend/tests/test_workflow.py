import threading

import pytest
from app.workflows import state_machine as sm
from app.workflows import worker
from app.workflows.worker import WorkerConfig
from fastapi.testclient import TestClient
from sqlalchemy import text
from support import REPORT, login

FAST = WorkerConfig(backoff_base=0, http_timeout=1.0)


@pytest.fixture()
def actors(client, apex_loaded):
    return {
        "tenant": apex_loaded,
        "eng": login(client, apex_loaded, "support_engineer"),
        "sup": login(client, apex_loaded, "maintenance_supervisor"),
        "adm": login(client, apex_loaded, "tenant_admin"),
        "aud": login(client, apex_loaded, "read_only_auditor"),
    }


def draft(client, actors, report=REPORT):
    incident = client.post("/api/v1/incidents/extract", headers=actors["eng"], json={"report_text": report}).json()
    resp = client.post("/api/v1/tickets", headers=actors["eng"], json={"incident_id": incident["id"]})
    assert resp.status_code == 201, resp.text
    return resp.json()


def pending(client, actors):
    ticket = draft(client, actors)
    resp = client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=actors["eng"])
    assert resp.status_code == 200 and resp.json()["state"] == "PENDING_APPROVAL"
    return ticket


def approve(client, actors, ticket_id, who="sup"):
    return client.post(f"/api/v1/approvals/{ticket_id}/decision", headers=actors[who],
                       json={"decision": "approved", "comment": "ok"})


def state_of(client, actors, ticket_id):
    return client.get(f"/api/v1/tickets/{ticket_id}", headers=actors["eng"]).json()


def audit_actions(client, actors, ticket_id):
    items = client.get("/api/v1/audit", headers=actors["aud"], params={"entity_id": ticket_id, "limit": 100}).json()
    return [i["action"] for i in reversed(items["items"])]


# ---- the complete Apex workflow ---------------------------------------------------------------------
def test_apex_end_to_end(client, actors, worker_db, ticketing):
    ticket = draft(client, actors)
    assert ticket["state"] == "DRAFT" and ticket["priority"] == "P3" and "Evidence" in ticket["description"]
    edited = client.patch(f"/api/v1/tickets/{ticket['id']}", headers=actors["eng"],
                          json={"title": "[P2] Vibration on P-101 (engineer reviewed)"})
    assert edited.json()["title"].endswith("(engineer reviewed)")
    assert client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=actors["eng"]).status_code == 200

    queue = client.get("/api/v1/approvals", headers=actors["sup"]).json()
    assert [t["id"] for t in queue["items"]] == [ticket["id"]]
    assert approve(client, actors, ticket["id"]).json()["state"] == "APPROVED"
    assert ticketing.state.requests == 0  # nothing leaves the platform until the worker runs

    assert worker.drain(worker_db, FAST) == ["submitted"]
    final = state_of(client, actors, ticket["id"])
    assert final["state"] == "SUBMITTED" and final["external_ticket_id"].startswith("MNT-")
    assert ticketing.state.tickets[final["external_ticket_id"]]["payload"]["source_ticket_id"] == ticket["id"]

    actions = audit_actions(client, actors, ticket["id"])
    for expected in ("ticket.drafted", "ticket.edited", "approval.approved", "ticket.submitted"):
        assert expected in actions
    assert actions.index("ticket.drafted") < actions.index("approval.approved") < actions.index("ticket.submitted")

    metrics = client.get("/api/v1/metrics", headers=actors["sup"]).json()
    assert metrics["tickets_by_state"] == {"SUBMITTED": 1} and metrics["approvals_decided"] == 1
    history = client.get("/api/v1/workflows", headers=actors["sup"]).json()["items"]
    assert history[0]["status"] == "done"


# ---- approval cannot be bypassed --------------------------------------------------------------------
def test_unapproved_tickets_cannot_be_submitted(client, actors, worker_db, ticketing, owner_engine):
    ticket = draft(client, actors)
    assert client.post(f"/api/v1/tickets/{ticket['id']}/submit", headers=actors["eng"]).json()["error"]["code"] \
        == "approval_required"
    client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=actors["eng"])
    assert client.post(f"/api/v1/tickets/{ticket['id']}/submit", headers=actors["eng"]).status_code == 409
    assert client.post(f"/api/v1/tickets/{ticket['id']}/retry", headers=actors["sup"]).status_code == 409
    # Even a forged outbox event for an unapproved ticket is refused by the worker.
    with owner_engine.begin() as conn:
        conn.execute(text("INSERT INTO outbox_events (tenant_id, topic, aggregate_id) "
                          "VALUES (:t, 'ticket.submit', :a)"), {"t": actors["tenant"].id, "a": ticket["id"]})
    assert worker.drain(worker_db, FAST) == ["blocked"]
    assert ticketing.state.requests == 0
    assert state_of(client, actors, ticket["id"])["state"] == "PENDING_APPROVAL"
    assert "submission.blocked" in audit_actions(client, actors, ticket["id"])


def test_rejected_ticket_is_never_submitted(client, actors, worker_db, ticketing, owner_engine):
    ticket = pending(client, actors)
    resp = client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers=actors["sup"],
                       json={"decision": "rejected", "comment": "not needed"})
    assert resp.json()["state"] == "REJECTED"
    assert client.post(f"/api/v1/tickets/{ticket['id']}/submit", headers=actors["sup"]).status_code == 409
    assert client.post(f"/api/v1/tickets/{ticket['id']}/retry", headers=actors["sup"]).status_code == 409
    assert approve(client, actors, ticket["id"]).status_code == 409  # cannot flip a decision
    with owner_engine.begin() as conn:  # forged event + tampered state still cannot submit
        conn.execute(text("UPDATE tickets SET state = 'APPROVED' WHERE id = :i"), {"i": ticket["id"]})
        conn.execute(text("INSERT INTO outbox_events (tenant_id, topic, aggregate_id) "
                          "VALUES (:t, 'ticket.submit', :a)"), {"t": actors["tenant"].id, "a": ticket["id"]})
    assert worker.drain(worker_db, FAST) == ["blocked"]
    assert ticketing.state.requests == 0


def test_only_authorized_roles_decide_and_not_on_own_tickets(client, actors):
    ticket = pending(client, actors)
    assert approve(client, actors, ticket["id"], who="eng").status_code == 403  # engineer role escalation
    assert approve(client, actors, ticket["id"], who="aud").status_code == 403
    # separation of duties: a supervisor cannot approve their own draft
    own = client.post("/api/v1/incidents/extract", headers=actors["sup"], json={"report_text": REPORT}).json()
    own_ticket = client.post("/api/v1/tickets", headers=actors["sup"], json={"incident_id": own["id"]}).json()
    client.post(f"/api/v1/tickets/{own_ticket['id']}/request-approval", headers=actors["sup"])
    resp = approve(client, actors, own_ticket["id"])
    assert resp.status_code == 403 and resp.json()["error"]["code"] == "self_approval"


def test_edits_locked_after_submission_for_approval(client, actors):
    ticket = pending(client, actors)
    resp = client.patch(f"/api/v1/tickets/{ticket['id']}", headers=actors["eng"], json={"title": "sneaky edit"})
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "not_editable"


def test_duplicate_draft_prevented_until_cancelled(client, actors):
    ticket = draft(client, actors)
    again = client.post("/api/v1/tickets", headers=actors["eng"], json={"incident_id": ticket["incident_id"]})
    assert again.status_code == 409 and again.json()["error"]["code"] == "duplicate_ticket"
    assert client.post(f"/api/v1/tickets/{ticket['id']}/cancel", headers=actors["eng"]).json()["state"] == "CANCELLED"
    assert client.post("/api/v1/tickets", headers=actors["eng"],
                       json={"incident_id": ticket["incident_id"]}).status_code == 201


def test_state_machine_rejects_every_undeclared_transition():
    class T:
        tenant_id = None
        id = "x"

    for src, allowed in sm.TRANSITIONS.items():
        for dst in sm.TRANSITIONS:
            t = T()
            t.state = src
            if dst in allowed:
                continue
            with pytest.raises(sm.InvalidTransition):
                sm.transition(None, t, dst)
            assert t.state == src


# ---- concurrency ------------------------------------------------------------------------------------
def test_concurrent_approvals_have_exactly_one_winner(client, actors, worker_db, ticketing):
    ticket = pending(client, actors)
    results, barrier = [], threading.Barrier(8)

    def attempt():
        local = TestClient(client.app)
        barrier.wait()
        results.append(approve(local, actors, ticket["id"]).status_code)

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [200] + [409] * 7
    approvals = client.get("/api/v1/approvals", headers=actors["sup"], params={"status": "decided"}).json()
    assert approvals["total"] == 1
    assert worker.drain(worker_db, FAST) == ["submitted"]
    assert ticketing.state.requests == 1 and len(ticketing.state.tickets) == 1


def test_concurrent_workers_submit_each_ticket_once(client, actors, worker_db, ticketing):
    ids = []
    for _ in range(5):
        t = pending(client, actors)
        assert approve(client, actors, t["id"]).status_code == 200
        ids.append(t["id"])
    outcomes = []

    def run():
        outcomes.extend(worker.drain(worker_db, FAST))

    threads = [threading.Thread(target=run) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert outcomes.count("submitted") == 5
    assert len(ticketing.state.tickets) == 5 and ticketing.state.requests == 5
    assert {state_of(client, actors, i)["state"] for i in ids} == {"SUBMITTED"}


def test_orphaned_outbox_event_is_dead_lettered_without_blocking_the_queue(client, actors, worker_db, ticketing,
                                                                           owner_engine):
    import uuid
    with owner_engine.begin() as conn:  # a poison event pointing at a ticket that does not exist
        conn.execute(text("INSERT INTO outbox_events (tenant_id, topic, aggregate_id) "
                          "VALUES (:t, 'ticket.submit', :a)"),
                     {"t": actors["tenant"].id, "a": str(uuid.uuid4())})
    ticket = pending(client, actors)
    approve(client, actors, ticket["id"])
    outcomes = worker.drain(worker_db, FAST)
    assert "orphaned" in outcomes and outcomes.count("submitted") == 1  # the real ticket is still submitted
    assert state_of(client, actors, ticket["id"])["state"] == "SUBMITTED"
    assert worker.drain(worker_db, FAST) == []  # the poison event is not retried


# ---- failure recovery and idempotency ---------------------------------------------------------------
def _inject(ticketing, mode, count=1, **extra):
    import httpx
    resp = httpx.post(f"{ticketing.url}/admin/failure", json={"mode": mode, "count": count, **extra},
                      headers={"X-API-Key": "test-ticketing-key"})
    assert resp.status_code == 200


def test_transient_outage_recovers_without_duplicates(client, actors, worker_db, ticketing):
    ticket = pending(client, actors)
    approve(client, actors, ticket["id"])
    _inject(ticketing, "503", count=2)
    assert worker.drain(worker_db, FAST) == ["retry_scheduled", "retry_scheduled", "submitted"]
    final = state_of(client, actors, ticket["id"])
    assert final["state"] == "SUBMITTED" and final["attempts"] == 3
    assert len(ticketing.state.tickets) == 1
    actions = audit_actions(client, actors, ticket["id"])
    assert actions.count("submission.retry_scheduled") == 2


def test_rate_limit_is_retried(client, actors, worker_db, ticketing):
    ticket = pending(client, actors)
    approve(client, actors, ticket["id"])
    _inject(ticketing, "429")
    assert worker.drain(worker_db, FAST) == ["retry_scheduled", "submitted"]


def test_timeout_is_retried(client, actors, worker_db, ticketing):
    ticket = pending(client, actors)
    approve(client, actors, ticket["id"])
    _inject(ticketing, "timeout", timeout_seconds=2.0)
    assert worker.drain(worker_db, WorkerConfig(backoff_base=0, http_timeout=0.4)) == ["retry_scheduled", "submitted"]
    assert len(ticketing.state.tickets) == 1


def test_lost_response_does_not_create_duplicate_external_ticket(client, actors, worker_db, ticketing):
    """The external system created the ticket but the response was lost; the retry must reuse it."""
    ticket = pending(client, actors)
    approve(client, actors, ticket["id"])
    _inject(ticketing, "lost_response")
    assert worker.drain(worker_db, FAST) == ["retry_scheduled", "submitted"]
    assert ticketing.state.requests == 2 and len(ticketing.state.tickets) == 1


def test_malformed_response_is_handled(client, actors, worker_db, ticketing):
    ticket = pending(client, actors)
    approve(client, actors, ticket["id"])
    _inject(ticketing, "malformed")
    assert worker.drain(worker_db, FAST) == ["retry_scheduled", "submitted"]
    assert len(ticketing.state.tickets) == 1
    assert "malformed" in "".join(
        i["details"].get("error", "") for i in client.get(
            "/api/v1/audit", headers=actors["aud"], params={"entity_id": ticket["id"]}).json()["items"])


def test_permanent_error_dead_letters_then_manual_retry_recovers(client, actors, worker_db, ticketing):
    ticket = pending(client, actors)
    approve(client, actors, ticket["id"])
    _inject(ticketing, "400")
    assert worker.drain(worker_db, FAST) == ["failed_permanent"]
    failed = state_of(client, actors, ticket["id"])
    assert failed["state"] == "FAILED" and "permanent" in failed["last_error"]
    assert client.get("/api/v1/metrics", headers=actors["sup"]).json()["dead_letters"] == 1
    assert client.post(f"/api/v1/tickets/{ticket['id']}/retry", headers=actors["eng"]).status_code == 403
    retried = client.post(f"/api/v1/tickets/{ticket['id']}/retry", headers=actors["sup"])
    assert retried.json()["state"] == "RETRY_PENDING"
    assert worker.drain(worker_db, FAST) == ["submitted"]
    assert len(ticketing.state.tickets) == 1


def test_exhausted_retries_end_in_failed_state(client, actors, worker_db, ticketing):
    ticket = pending(client, actors)
    approve(client, actors, ticket["id"])
    _inject(ticketing, "503", count=10)
    outcomes = worker.drain(worker_db, WorkerConfig(backoff_base=0, max_attempts=3, http_timeout=1))
    assert outcomes == ["retry_scheduled", "retry_scheduled", "failed_permanent"]
    assert state_of(client, actors, ticket["id"])["state"] == "FAILED"
    assert len(ticketing.state.tickets) == 0


def test_retry_cannot_manufacture_approval(client, actors, owner_engine):
    ticket = pending(client, actors)
    with owner_engine.begin() as conn:  # a FAILED ticket that never had an approval record
        conn.execute(text("UPDATE tickets SET state = 'FAILED' WHERE id = :i"), {"i": ticket["id"]})
    resp = client.post(f"/api/v1/tickets/{ticket['id']}/retry", headers=actors["sup"])
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "not_retryable"


def test_worker_interruption_is_recovered_after_lease_expiry(client, actors, worker_db, ticketing):
    ticket = pending(client, actors)
    approve(client, actors, ticket["id"])
    claimed = worker._claim(worker_db, WorkerConfig(lease_seconds=0))  # worker "crashes" right after claiming
    assert claimed is not None
    assert ticketing.state.requests == 0
    assert worker.drain(worker_db, WorkerConfig(lease_seconds=0, backoff_base=0)) == ["submitted"]
    assert len(ticketing.state.tickets) == 1


def test_crash_after_marking_submitting_resumes_safely(client, actors, worker_db, ticketing, owner_engine):
    ticket = pending(client, actors)
    approve(client, actors, ticket["id"])
    worker._claim(worker_db, WorkerConfig(lease_seconds=0))
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE tickets SET state = 'SUBMITTING', attempts = 1 WHERE id = :i"),
                     {"i": ticket["id"]})
    assert worker.drain(worker_db, WorkerConfig(lease_seconds=0, backoff_base=0)) == ["submitted"]
    assert state_of(client, actors, ticket["id"])["state"] == "SUBMITTED" and len(ticketing.state.tickets) == 1
    # Re-delivering the event for an already submitted ticket is a harmless no-op.
    with owner_engine.begin() as conn:
        conn.execute(text("INSERT INTO outbox_events (tenant_id, topic, aggregate_id) "
                          "VALUES (:t, 'ticket.submit', :a)"), {"t": actors["tenant"].id, "a": ticket["id"]})
    assert worker.drain(worker_db, FAST) == ["already_submitted"]
    assert ticketing.state.requests == 2 or len(ticketing.state.tickets) == 1
    assert len(ticketing.state.tickets) == 1
