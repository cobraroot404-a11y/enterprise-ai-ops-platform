"""Real AI integration tests: local Ollama (qwen2.5:1.5b) + sentence-transformers MiniLM.

Opt in with RUN_REAL_AI=1. These are separate from the deterministic functional tests and are never run
in CI. They check behaviour and verifiability (grounding, citations, schema validity); quality numbers
come from evaluation/benchmarks/run_phase3.py, not from these tests.
"""
import dataclasses
import threading

import pytest
from app.ai.embeddings import DeterministicEmbedder, get_embedder
from app.ai.llm import get_llm
from app.core.config import MINILM_MODEL, MINILM_REVISION
from app.ingestion.service import ingest
from app.main import create_app
from app.retrieval.profiles import IncompatibleEmbeddingModel
from app.retrieval.reindex import reindex_tenant
from app.retrieval.search import search
from app.workflows import worker
from fastapi.testclient import TestClient
from sqlalchemy import text
from support import REPORT, SAMPLE_KINDS, SAMPLES, ingest_samples, login, make_tenant, onboard_meridian

pytestmark = pytest.mark.real_ai


@pytest.fixture(scope="module")
def embedder():
    return get_embedder("sentence_transformers")


@pytest.fixture(scope="module")
def llm():
    import ollama_ctl  # scripts/ollama_ctl.py: starts the local server if it is not already running

    ollama_ctl.start()
    model = get_llm("ollama")
    if model.version() is None or model.digest is None:
        pytest.fail("Ollama is not reachable or the model is not pulled (expected qwen2.5:1.5b)")
    return model


@pytest.fixture()
def real_client(settings, app_db, embedder, llm):
    real = dataclasses.replace(settings, llm_backend="ollama", embedding_backend="sentence_transformers")
    return TestClient(create_app(real, app_db))


@pytest.fixture()
def real_tenant(owner_engine, ticketing, inventory_server):
    return make_tenant(owner_engine, "real", ticketing.url, inventory_server.url)


@pytest.fixture()
def real_loaded(real_client, real_tenant):
    ingest_samples(real_client, login(real_client, real_tenant, "support_engineer"))
    return real_tenant


def test_model_identity_is_pinned_and_reported(llm, embedder):
    assert llm.model == "qwen2.5:1.5b" and llm.digest and llm.version()
    assert embedder.profile.model == MINILM_MODEL and embedder.profile.revision == MINILM_REVISION
    assert embedder.dim == 384


def test_minilm_vectors_are_normalized_and_semantic(embedder):
    a, b, c = embedder.embed(["The bearing is running hot", "bearing temperature is too high",
                              "Invoice payment terms are net thirty days"])
    assert len(a) == 384 and abs(sum(x * x for x in a) - 1) < 1e-3
    dot = lambda u, v: sum(x * y for x, y in zip(u, v, strict=True))  # noqa: E731
    assert dot(a, b) > dot(a, c) + 0.2  # paraphrase is clearly closer than an unrelated sentence


def test_real_ingest_records_profile_and_paraphrase_retrieval_works(real_client, real_loaded, app_db, embedder):
    with app_db.session(real_loaded.id) as s:
        profile = s.execute(text("SELECT provider, model, revision, dim FROM embedding_profiles WHERE active")).one()
        assert tuple(profile) == ("sentence_transformers", MINILM_MODEL, MINILM_REVISION, 384)
        hits = search(s, real_loaded.id, "stop the pump if the bearing shakes too much", embedder, k=5)
        # the query shares no keywords with the manual page, so this needs real semantic similarity
        assert any(h.page_number == 2 and h.filename == "apex_cp200_pump_manual.pdf" for h in hits)
        with pytest.raises(IncompatibleEmbeddingModel):
            search(s, real_loaded.id, "pump", DeterministicEmbedder())  # deterministic vectors can't be queried


def test_real_answer_is_grounded_with_verified_citations(real_client, real_loaded):
    headers = login(real_client, real_loaded, "support_engineer")
    res = real_client.post("/api/v1/ai/ask", headers=headers,
                           json={"question": "What should I check when pump P-101 shows abnormal vibration?"}).json()
    assert res["llm_backend"] == "ollama" and res["embedding_backend"] == "sentence_transformers"
    assert res["grounded"], res
    assert res["citations"] and all(c["page_number"] or c["record_id"] for c in res["citations"])
    hits = real_client.post("/api/v1/search", headers=headers,
                            json={"query": res["citations"][0]["quote"], "k": 8}).json()["items"]
    assert any(res["citations"][0]["quote"].lower().rstrip(".") in " ".join(h["text"].lower().split()) for h in hits)


def test_real_unanswerable_question_is_not_fabricated(real_client, real_loaded):
    headers = login(real_client, real_loaded, "support_engineer")
    res = real_client.post("/api/v1/ai/ask", headers=headers,
                           json={"question": "What is the chief executive's favourite colour?"}).json()
    assert res["citations"] == [] and not res["grounded"]


def test_real_structured_extraction_is_valid(real_client, real_loaded):
    headers = login(real_client, real_loaded, "support_engineer")
    resp = real_client.post("/api/v1/incidents/extract", headers=headers, json={"report_text": REPORT})
    assert resp.status_code == 201, resp.text
    inc = resp.json()
    assert inc["extraction_backend"].startswith("ollama") and inc["asset_id"] == "P-101"
    assert inc["category"] == "mechanical_vibration" and inc["priority"] == "P3"  # category-driven (V8): the free-text reading is an unverified candidate
    # Real-model grounding varies run to run, so assert the invariant rather than a fixed outcome: a ticket is
    # only drafted automatically when the equipment is registered AND the guidance has verified evidence.
    expected = "pending_review" if inc["asset_verified"] and inc["citations"] else "needs_review"
    assert inc["review_status"] == expected


def test_real_model_cannot_invent_equipment(real_client, real_loaded):
    """A report with no equipment ID must be rejected (a real model may try to guess one)."""
    headers = login(real_client, real_loaded, "support_engineer")
    resp = real_client.post("/api/v1/incidents/extract", headers=headers, json={
        "report_text": "There is a strange noise somewhere in the plant but I cannot tell where it comes from."})
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "asset_not_identified"


def test_real_end_to_end_workflow_with_approval_and_idempotent_submission(
        real_client, real_loaded, worker_db, ticketing):
    eng = login(real_client, real_loaded, "support_engineer")
    sup = login(real_client, real_loaded, "maintenance_supervisor")
    aud = login(real_client, real_loaded, "read_only_auditor")
    inc = real_client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": REPORT}).json()
    if inc["review_status"] == "needs_review":  # real model gave no grounded evidence: the human review path
        assert real_client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).status_code == 409
        reviewed = real_client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup,
                                    json={"decision": "accept", "comment": "Reviewed manually by supervisor."})
        assert reviewed.status_code == 200
    ticket = real_client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()
    assert real_client.post(f"/api/v1/tickets/{ticket['id']}/submit", headers=eng).status_code == 409  # not approved
    real_client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=eng)
    assert ticketing.state.requests == 0
    assert real_client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers=sup,
                            json={"decision": "approved"}).json()["state"] == "APPROVED"
    results = []
    threads = [threading.Thread(target=lambda: results.extend(worker.drain(worker_db))) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("submitted") == 1 and len(ticketing.state.tickets) == 1
    final = real_client.get(f"/api/v1/tickets/{ticket['id']}", headers=eng).json()
    assert final["state"] == "SUBMITTED" and final["external_ticket_id"].startswith("MNT-")
    log = real_client.get("/api/v1/audit", headers=aud, params={"limit": 100}).json()["items"]
    actions = [i["action"] for i in log]
    assert {"incident.extracted", "ticket.drafted", "approval.approved", "ticket.submitted"} <= set(actions)


def test_reindex_deterministic_tenant_to_minilm(app_db, owner_engine, real_tenant, embedder):
    with owner_engine.connect() as conn:
        uid = str(conn.execute(text("SELECT id FROM users WHERE email = :e"),
                               {"e": real_tenant.users["support_engineer"]}).scalar())
    det = DeterministicEmbedder()
    with app_db.session(real_tenant.id, uid) as s:
        for name, kind in SAMPLE_KINDS.items():
            ingest(s, tenant_id=real_tenant.id, user_id=uid, filename=name, data=(SAMPLES / name).read_bytes(),
                   kind=kind, embedder=det)
        s.commit()
    with app_db.session(real_tenant.id, uid) as s:
        report = reindex_tenant(s, real_tenant.id, embedder, actor_id=uid)
        s.commit()
    assert report["status"] == "reindexed" and report["before"]["chunks"] == report["after"]["chunks"] > 0
    assert report["after"]["dim384"] == report["after"]["chunks"]
    with app_db.session(real_tenant.id, uid) as s:
        assert search(s, real_tenant.id, "bearing vibration limit", embedder)
        with pytest.raises(IncompatibleEmbeddingModel):
            search(s, real_tenant.id, "bearing vibration limit", det)



# ---- Phase 5: Meridian (second tenant) on the same real models ---------------------------------------------------
BRAKE_REPORT = "Vehicle VH-2101 shows low brake pressure of 52 psi with a hissing noise at the rear axle."


@pytest.fixture()
def real_meridian(real_client, owner_engine, servicedesk_server, fleet_server, crm_server, ticketing):
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE outbox_events SET status = 'done' WHERE status IN ('pending', 'processing')"))
    state = servicedesk_server.state
    with state.lock:
        state.tickets.clear(), state.by_key.clear(), state.failures.clear()
        state.requests = 0
    return onboard_meridian(real_client, owner_engine, servicedesk_server, fleet_server, crm_server, "realmer")


def test_real_meridian_profile_embedding_and_grounded_answer(real_client, real_meridian, app_db):
    with app_db.session(real_meridian.id) as s:
        profile = s.execute(text("SELECT provider, model, revision, dim FROM embedding_profiles WHERE active")).one()
        assert tuple(profile) == ("sentence_transformers", MINILM_MODEL, MINILM_REVISION, 384)
    headers = login(real_client, real_meridian, "support_engineer")
    res = real_client.post("/api/v1/ai/ask", headers=headers, json={
        "question": "What should I do when the service brake line pressure falls below 55 psi?"}).json()
    assert res["llm_backend"] == "ollama" and res["embedding_backend"] == "sentence_transformers"
    # Real-model grounding varies; the invariants are: every citation is verbatim, tenant-owned and Meridian's.
    assert all(c["filename"].startswith(("meridian", "fleet", "service", "telematics")) for c in res["citations"])
    if res["grounded"]:
        assert res["citations"]
    unrelated = real_client.post("/api/v1/ai/ask", headers=headers, json={
        "question": "What is the chief executive's favourite colour?"}).json()
    assert unrelated["citations"] == [] and not unrelated["grounded"]


def test_real_meridian_extraction_uses_profile_and_deterministic_priority(real_client, real_meridian):
    headers = login(real_client, real_meridian, "support_engineer")
    resp = real_client.post("/api/v1/incidents/extract", headers=headers, json={"report_text": BRAKE_REPORT})
    assert resp.status_code == 201, resp.text
    inc = resp.json()
    assert inc["extraction_backend"].startswith("ollama") and inc["asset_id"] == "VH-2101" and inc["asset_verified"]
    assert inc["priority"] in ("P2", "P3")  # tenant category rules only (V8): the free-text 52 psi is an unverified candidate; the real model category may differ
    assert inc["category"] in {"brake_system", "leak", "noise_vibration"}  # a real model may pick a near category
    assert "Harbor Fresh Foods" in " ".join(inc["notes"])  # CRM enrichment
    assert inc["review_status"] == ("pending_review" if inc["citations"] else "needs_review")
    bad = real_client.post("/api/v1/incidents/extract", headers=headers, json={
        "report_text": "There is a strange noise somewhere in the depot but nobody knows which truck."})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "asset_not_identified"


def test_real_both_tenants_end_to_end_and_isolated(real_client, real_loaded, real_meridian, worker_db, ticketing,
                                                    servicedesk_server):
    a_eng, a_sup = login(real_client, real_loaded, "support_engineer"), login(real_client, real_loaded,
                                                                              "maintenance_supervisor")
    m_eng, m_sup = login(real_client, real_meridian, "support_engineer"), login(real_client, real_meridian,
                                                                                "maintenance_supervisor")
    tickets = {}
    for name, eng, sup, report in (("apex", a_eng, a_sup, REPORT), ("meridian", m_eng, m_sup, BRAKE_REPORT)):
        inc = real_client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": report}).json()
        if inc["review_status"] == "needs_review":
            assert real_client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup, json={
                "decision": "accept", "comment": "Reviewed manually by supervisor."}).status_code == 200
        ticket = real_client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()
        real_client.post(f"/api/v1/tickets/{ticket['id']}/request-approval", headers=eng)
        assert real_client.post(f"/api/v1/approvals/{ticket['id']}/decision", headers=sup,
                                json={"decision": "approved"}).json()["state"] == "APPROVED"
        tickets[name] = (ticket, eng)
    assert sorted(worker.drain(worker_db)) == ["submitted", "submitted"]
    apex_final = real_client.get(f"/api/v1/tickets/{tickets['apex'][0]['id']}", headers=a_eng).json()
    mer_final = real_client.get(f"/api/v1/tickets/{tickets['meridian'][0]['id']}", headers=m_eng).json()
    assert apex_final["external_ticket_id"].startswith("MNT-") and mer_final["external_ticket_id"].startswith("WO-")
    assert len(ticketing.state.tickets) == 1 and len(servicedesk_server.state.tickets) == 1
    # Real MiniLM retrieval stays inside each tenant.
    for headers, foreign in ((a_eng, ("meridian", "fleet_", "service_", "telematics")), (m_eng, ("apex", "equipment_",
                                                                                                "incident_h", "maintenance_l"))):
        hits = real_client.post("/api/v1/search", headers=headers, json={"query": "brake pressure bearing vibration",
                                                                         "k": 10}).json()["items"]
        assert not any(h["filename"].startswith(foreign) for h in hits)
    assert real_client.get(f"/api/v1/tickets/{tickets['apex'][0]['id']}", headers=m_eng).status_code == 404
