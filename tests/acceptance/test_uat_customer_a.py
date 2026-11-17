"""UAT-A01 .. UAT-A08: Apex Industrial Manufacturing (fictional) acceptance scenarios, through the real HTTP API.

In UAT_BACKEND=deterministic mode these prove workflow, security and integration behaviour only. Where a scenario needs AI
behaviour, the acceptance evidence is the UAT_BACKEND=real run (Ollama + MiniLM); real-model assertions are written as invariants
plus an explicit, documented success threshold, never as fixed answers.
"""
import threading

import httpx
from app.workflows import worker
from fastapi.testclient import TestClient
from support import REPORT, SAMPLES, TICKETING_KEY, login

APEX = "Apex Industrial Manufacturing (fictional)"
FAST = worker.WorkerConfig(backoff_base=0, backoff_cap=0, http_timeout=1.0)
QUESTIONS = [
    "What should I check when pump P-101 shows abnormal vibration at the drive-end bearing?",
    "At what vibration velocity should the CP-200 pump be stopped?",
    "What causes cavitation in the pump and what should be done?",
]


def actions(client, tenant):
    aud = login(client, tenant, "read_only_auditor")
    return [a["action"] for a in client.get("/api/v1/audit", headers=aud, params={"limit": 100}).json()["items"]]


def inject(ticketing, mode, count=1):
    r = httpx.post(f"{ticketing.url}/admin/failure", json={"mode": mode, "count": count}, headers={"X-API-Key": TICKETING_KEY})
    assert r.status_code == 200


def approved_ticket(client, t, report=REPORT):
    eng, sup = login(client, t, "support_engineer"), login(client, t, "maintenance_supervisor")
    inc = client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": report}).json()
    if inc["review_status"] == "needs_review":  # the human-review path; never bypassed
        assert client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup, json={
            "decision": "accept", "comment": "UAT supervisor review of an incident without verified evidence."}).status_code == 200
    ticket = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()
    client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=eng)
    res = client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers=sup, json={"decision": "approved", "comment": "UAT"})
    assert res.status_code == 200
    return inc, ticket["id"], eng, sup


def test_uat_a01_document_ingestion(uat, uat_client, owner_engine, ticketing, inventory_server):
    from support import SAMPLE_KINDS, make_tenant
    t = make_tenant(owner_engine, "uata01", ticketing.url, inventory_server.url)
    eng = login(uat_client, t, "support_engineer")
    with uat("UAT-A01", APEX, "Document ingestion", ["R12.1", "R12.2", "R12.3"],
             "Apex tenant exists with no documents; support engineer signed in",
             "Fictional Apex pump manual (PDF), inspection report (PDF), equipment register, incident history and maintenance log (CSV)",
             ["Upload each of the five sample files", "Upload the equipment register again unchanged", "List the documents",
              "Search for a manual passage and read its provenance"],
             "Five documents created with chunks; the repeat upload is reported as duplicate; hashes and versions are listed; "
             "search results carry page numbers (PDF) or record ids (CSV)") as u:
        results = {}
        for name, kind in SAMPLE_KINDS.items():
            r = uat_client.post("/api/v1/documents", headers=eng, data={"kind": kind}, files={"file": (name, (SAMPLES / name).read_bytes())})
            assert r.status_code == 201, r.text
            results[name] = (r.json()["status"], r.json()["chunk_count"])
        again = uat_client.post("/api/v1/documents", headers=eng, data={"kind": "equipment_register"},
                                files={"file": ("equipment_register.csv", (SAMPLES / "equipment_register.csv").read_bytes())}).json()
        docs = uat_client.get("/api/v1/documents", headers=eng).json()["items"]
        hits = uat_client.post("/api/v1/search", headers=eng, json={"query": "drive-end bearing vibration limit", "k": 8}).json()["items"]
        detail = uat_client.get(f"/api/v1/documents/{docs[0]['id']}", headers=eng).json()
        assert all(status == "created" and chunks > 0 for status, chunks in results.values())
        assert again["status"] == "duplicate" and len(docs) == 5 and len(detail["versions"][0]["sha256"]) == 64
        assert any(h["page_number"] for h in hits) and any(h["record_id"] for h in hits + uat_client.post(
            "/api/v1/search", headers=eng, json={"query": "P-101 incident INC-2025-0107", "k": 8}).json()["items"])
        u.actual = f"5 documents ingested {results}; repeat upload '{again['status']}'; first hit page={hits[0]['page_number']}"
        u.evidence = {"ingest_results": results, "documents_listed": len(docs), "duplicate_status": again["status"],
                      "sha256_recorded": True, "provenance_page_numbers": sorted({h["page_number"] for h in hits if h["page_number"]})}


def test_uat_a02_evidence_grounded_retrieval(uat, uat_client, apex_uat, uat_mode):
    eng = login(uat_client, apex_uat, "support_engineer")
    with uat("UAT-A02", APEX, "Evidence-grounded retrieval", ["R13.1", "R13.2", "R13.3"],
             "Apex documents ingested", f"{len(QUESTIONS)} answerable questions and 1 unanswerable question",
             ["Ask each question", "Check every citation: source ownership and verbatim quote", "Ask an out-of-scope question"],
             "Every answer shown is grounded with verified citations from Apex documents; unanswerable questions get an insufficient-evidence "
             "response with no citation. For the real model: at least 2 of the 3 prepared questions produce a verified grounded answer "
             "(measured Phase 3 coverage was about 75%)",
             limitations="Real-model coverage varies between runs; the 95% citation-correctness target remains NOT MET (Phase 3/4).") as u:
        rows, grounded = [], 0
        for q in QUESTIONS:
            res = uat_client.post("/api/v1/ai/ask", headers=eng, json={"question": q}).json()
            if res["grounded"]:
                grounded += 1
                assert res["citations"] and all(c["page_number"] or c["record_id"] for c in res["citations"])
                hits = uat_client.post("/api/v1/search", headers=eng, json={"query": res["citations"][0]["quote"], "k": 8}).json()["items"]
                assert any(res["citations"][0]["quote"].lower().rstrip(".") in " ".join(h["text"].lower().split()) for h in hits)
            else:
                assert res["citations"] == []  # never an uncited or unverified answer
            rows.append({"question": q, "grounded": res["grounded"], "citations": len(res["citations"]), "problems": res["problems"][:2]})
        blank = uat_client.post("/api/v1/ai/ask", headers=eng, json={"question": "What is the chief executive's favourite colour?"}).json()
        assert blank["citations"] == [] and not blank["grounded"]
        assert grounded >= (2 if uat_mode == "real" else 1)
        u.actual = f"{grounded} of {len(QUESTIONS)} answerable questions grounded with verified citations; out-of-scope question refused"
        u.evidence = {"answers": rows, "backend": uat_mode}


def test_uat_a03_historical_incident_matching(uat, uat_client, apex_uat):
    eng = login(uat_client, apex_uat, "support_engineer")
    with uat("UAT-A03", APEX, "Historical incident matching", ["R14.2", "R7.1"], "Apex incident history ingested",
             "Report: P-101 abnormal vibration 8.4 mm/s with grinding noise",
             ["Extract an incident from the report", "Inspect related incidents"],
             "Past incidents for the same equipment (INC-2024-0412, INC-2025-0107) are listed, same-asset first, from Apex's own history") as u:
        inc = uat_client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": REPORT}).json()
        related = inc["related_incidents"]
        ids = [r["record_id"] for r in related]
        assert {"INC-2024-0412", "INC-2025-0107"} & set(ids) and related[0]["same_asset"] is True
        assert all(r["filename"] == "incident_history.csv" for r in related)
        u.actual = f"related incidents {ids}; first is same-asset"
        u.evidence = {"related_incident_ids": ids, "incident_id": inc["id"]}


def test_uat_a04_structured_ticket_generation(uat, uat_client, apex_uat, uat_mode):
    eng = login(uat_client, apex_uat, "support_engineer")
    with uat("UAT-A04", APEX, "Structured ticket generation", ["R14.1", "R14.3", "R14.4", "R7.1"], "Apex documents ingested",
             "Report: P-101 abnormal vibration 8.4 mm/s with grinding noise",
             ["Extract the incident", "Check the validated fields", "Create a ticket draft (after human review if the platform requires it)"],
             "A schema-valid incident (asset P-101 verified, category, symptoms, priority P3 from category rules; the free-text vibration reading is an UNVERIFIED candidate flagged for urgent review, not a priority input, citations or an explicit "
             "no-evidence note, review status); a draft whose content carries the asset, priority, evidence and notes",
             limitations="In real-AI mode the model's category and symptoms vary; priority is rule-based.") as u:
        inc = uat_client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": REPORT}).json()
        assert inc["asset_id"] == "P-101" and inc["asset_verified"] is True and inc["priority"] == "P3"
        assert inc["category"] and inc["symptoms"] and inc["recommended_action"] and inc["review_status"] in ("pending_review", "needs_review")
        assert inc["review_status"] == ("pending_review" if inc["citations"] else "needs_review")
        if inc["review_status"] == "needs_review":
            assert uat_client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).status_code == 409
            sup = login(uat_client, apex_uat, "maintenance_supervisor")
            uat_client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup, json={"decision": "accept", "comment": "UAT supervisor review."})
        draft = uat_client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()
        assert draft["state"] == "DRAFT" and draft["priority"] == "P3" and "P-101" in draft["title"] and "Asset: P-101" in draft["description"]
        u.actual = f"incident {inc['review_status']} (category {inc['category']}, {len(inc['citations'])} citation(s)); draft {draft['state']}"
        u.evidence = {"category": inc["category"], "priority": inc["priority"], "review_status": inc["review_status"],
                      "citations": len(inc["citations"]), "extraction_backend": inc["extraction_backend"], "backend": uat_mode}


def test_uat_a05_unapproved_submission_blocked(uat, uat_client, apex_uat, ticketing, worker_db):
    eng, sup = login(uat_client, apex_uat, "support_engineer"), login(uat_client, apex_uat, "maintenance_supervisor")
    with uat("UAT-A05", APEX, "Unapproved submission blocked", ["R15.1", "R15.2", "R16.2"], "Apex draft tickets exist",
             "Two tickets: one PENDING_APPROVAL, one REJECTED",
             ["Try to submit an unapproved ticket", "Let the worker run", "Engineer tries to approve", "Supervisor rejects; try to retry/submit the rejected ticket"],
             "Submission refused (409); the external system receives nothing; engineers cannot approve; a rejected ticket can never be submitted") as u:
        incs = [uat_client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": REPORT}).json() for _ in range(2)]
        tickets = []
        for inc in incs:
            if inc["review_status"] == "needs_review":
                uat_client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup, json={"decision": "accept", "comment": "UAT supervisor review."})
            t = uat_client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()["id"]
            tickets.append(t)
            uat_client.post(f"/api/v1/tickets/{t}/request-approval", headers=eng)
        submit = uat_client.post(f"/api/v1/tickets/{tickets[0]}/submit", headers=eng)
        assert submit.status_code == 409 and submit.json()["error"]["code"] == "approval_required"
        assert worker.drain(worker_db, FAST) == [] and ticketing.state.requests == 0
        by_engineer = uat_client.post(f"/api/v1/approvals/{tickets[0]}/decision", headers=eng, json={"decision": "approved"})
        assert by_engineer.status_code == 403
        assert uat_client.post(f"/api/v1/approvals/{tickets[1]}/decision", headers=sup, json={"decision": "rejected", "comment": "no"}).status_code == 200
        for path in ("submit", "retry"):
            assert uat_client.post(f"/api/v1/tickets/{tickets[1]}/{path}", headers=sup).status_code == 409
        assert worker.drain(worker_db, FAST) == [] and ticketing.state.requests == 0
        u.actual = "submit before approval 409; engineer approval 403; rejected ticket submit/retry 409; worker idle; mock requests 0"
        u.evidence = {"submit_status": submit.status_code, "engineer_approval_status": by_engineer.status_code, "external_requests": ticketing.state.requests}


def test_uat_a06_approved_ticket_submission(uat, uat_client, apex_uat, ticketing, worker_db):
    with uat("UAT-A06", APEX, "Approved ticket submission", ["R15.1", "R11.1", "R15.5", "R7.1"], "Apex incident reviewed as required",
             "P-101 incident, supervisor approval", ["Request approval", "Supervisor approves", "Worker submits", "Read the ticket and the audit trail"],
             "The ticket reaches the maintenance mock exactly once, its external id (MNT-) is stored, and the audit trail records draft, approval and submission") as u:
        inc, tid, eng, _ = approved_ticket(uat_client, apex_uat)
        assert worker.drain(worker_db, FAST) == ["submitted"]
        final = uat_client.get(f"/api/v1/tickets/{tid}", headers=eng).json()
        (sent,) = ticketing.state.tickets.values()
        log = actions(uat_client, apex_uat)
        assert final["state"] == "SUBMITTED" and final["external_ticket_id"].startswith("MNT-") and sent["payload"]["asset_id"] == "P-101"
        assert {"ticket.drafted", "approval.approved", "ticket.submitted"} <= set(log)
        u.actual = f"ticket SUBMITTED as {final['external_ticket_id']}; 1 external ticket; audit has draft, approval, submission"
        u.evidence = {"external_ticket_id": final["external_ticket_id"], "external_tickets": 1, "audit_actions": sorted(set(log))}


def test_uat_a07_duplicate_prevention(uat, uat_client, apex_uat, ticketing, worker_db):
    eng, sup = login(uat_client, apex_uat, "support_engineer"), login(uat_client, apex_uat, "maintenance_supervisor")
    with uat("UAT-A07", APEX, "Duplicate prevention", ["R15.3", "R15.6", "R11.3"], "Apex incident ready for a ticket",
             "Concurrent drafts, concurrent approvals, direct re-submit, lost-response retry",
             ["Create tickets for one incident from 5 threads", "Approve one ticket from 6 threads", "Re-submit and re-approve",
              "Inject a lost response and let the worker retry"],
             "One ticket per incident; one approval wins; one external ticket in every case, including after a lost response") as u:
        inc = uat_client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": REPORT}).json()
        if inc["review_status"] == "needs_review":
            uat_client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup, json={"decision": "accept", "comment": "UAT supervisor review."})
        codes = []
        threads = [threading.Thread(target=lambda: codes.append(TestClient(uat_client.app).post(
            "/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).status_code)) for _ in range(5)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert sorted(codes) == [201, 409, 409, 409, 409]
        tid = next(t["id"] for t in uat_client.get("/api/v1/tickets", headers=eng).json()["items"])
        uat_client.post(f"/api/v1/tickets/{tid}/request-approval", headers=eng)
        decisions = []
        threads = [threading.Thread(target=lambda: decisions.append(TestClient(uat_client.app).post(
            f"/api/v1/approvals/{tid}/decision", headers=sup, json={"decision": "approved"}).status_code)) for _ in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert sorted(decisions) == [200] + [409] * 5
        inject(ticketing, "lost_response")
        outcomes = worker.drain(worker_db, FAST)
        assert outcomes[-1] == "submitted" and len(ticketing.state.tickets) == 1 and ticketing.state.requests == 2
        assert uat_client.post(f"/api/v1/tickets/{tid}/submit", headers=eng).status_code in (200, 409)
        assert worker.drain(worker_db, FAST) in ([], ["already_submitted"]) and len(ticketing.state.tickets) == 1
        u.actual = f"draft codes {sorted(codes)}; approval codes {sorted(decisions)}; worker {outcomes}; external tickets {len(ticketing.state.tickets)}"
        u.evidence = {"draft_status_codes": sorted(codes), "approval_status_codes": sorted(decisions), "worker_outcomes": outcomes, "external_tickets": 1}


def test_uat_a08_api_failure_recovery(uat, uat_client, apex_uat, ticketing, worker_db):
    with uat("UAT-A08", APEX, "API failure recovery", ["R15.4", "R11.2", "R15.3"], "Apex approved tickets; maintenance mock configurable",
             "Two consecutive HTTP 503 responses; one permanent HTTP 400",
             ["Approve a ticket while the mock returns 503 twice", "Run the worker", "Approve another while the mock returns 400", "Fix and retry as a supervisor"],
             "Transient failures are retried with backoff and end SUBMITTED once; a permanent failure is FAILED (not retried automatically) and a supervisor "
             "retry then succeeds with exactly one external ticket per ticket") as u:
        inject(ticketing, "503", 2)
        _, tid, eng, sup = approved_ticket(uat_client, apex_uat)
        outcomes = worker.drain(worker_db, FAST)
        assert outcomes == ["retry_scheduled", "retry_scheduled", "submitted"]
        a = uat_client.get(f"/api/v1/tickets/{tid}", headers=eng).json()
        inject(ticketing, "400", 1)
        _, tid2, eng, sup = approved_ticket(uat_client, apex_uat)
        assert worker.drain(worker_db, FAST) == ["failed_permanent"]
        failed = uat_client.get(f"/api/v1/tickets/{tid2}", headers=eng).json()
        assert failed["state"] == "FAILED" and len(ticketing.state.tickets) == 1
        assert uat_client.post(f"/api/v1/tickets/{tid2}/retry", headers=eng).status_code == 403
        assert uat_client.post(f"/api/v1/tickets/{tid2}/retry", headers=sup).status_code == 200
        assert worker.drain(worker_db, FAST) == ["submitted"]
        assert a["state"] == "SUBMITTED" and a["attempts"] == 3 and len(ticketing.state.tickets) == 2
        u.actual = f"503 x2: {outcomes}, attempts {a['attempts']}; 400: FAILED then supervisor retry SUBMITTED; external tickets {len(ticketing.state.tickets)} for 2 tickets"
        u.evidence = {"transient_outcomes": outcomes, "attempts": a["attempts"], "permanent_state": failed["state"], "external_tickets": 2}
