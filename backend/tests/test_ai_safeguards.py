import pytest
from app.ai.embeddings import DeterministicEmbedder
from app.ai.llm import CitedQuote, LLMAnswer
from app.ai.rag import answer_question
from app.ai.safeguards import (
    check_answer_support,
    unsupported_identifiers,
    unsupported_numbers,
    verify_citation_sources,
)
from app.ingestion.service import ingest
from sqlalchemy import text
from support import REPORT, SAMPLE_KINDS, SAMPLES, login, make_tenant

EVIDENCE = ["If vibration velocity exceeds 7.1 mm/s RMS at the drive-end bearing, stop pump P-101. "
            "Replace the bearing set (PN-4417) if bearing temperature exceeds 85 C."]


# ---- pure safeguard logic ------------------------------------------------------------------------------
def test_unsupported_identifiers_detected():
    assert unsupported_identifiers("Replace PN-4417 on P-101.", EVIDENCE) == []
    assert unsupported_identifiers("Replace PN-9999 on P-101.", EVIDENCE) == ["PN-9999"]
    assert unsupported_identifiers("See incident INC-2025-1001.", EVIDENCE) == ["INC-2025-1001"]
    assert unsupported_identifiers("Check Z-999.", EVIDENCE, question="What about Z-999?") == []  # user-supplied


def test_unsupported_numbers_detected():
    assert unsupported_numbers("Limit is 7.1 mm/s and 85 C [1].", EVIDENCE) == []
    assert unsupported_numbers("Limit is 12 mm/s [1].", EVIDENCE) == ["12"]
    assert unsupported_numbers("About 8,000 hours.", ["Replace every 8000 hours."]) == []  # comma formatting
    # A figure typed by the user must never be presented as a manual specification (found with the real model:
    # the manual says 7.1 mm/s, the user reported 8.4 mm/s, and the model wrote "exceeds 8.4 mm/s").
    question = "Pump P-101 vibration is 8.4 mm/s, what should I check?"
    assert unsupported_numbers("Stop the pump if velocity exceeds 8.4 mm/s [1].", EVIDENCE) == ["8.4"]
    assert check_answer_support("Stop the pump if velocity exceeds 8.4 mm/s [1].", EVIDENCE, question)
    assert check_answer_support("Stop the pump if velocity exceeds 7.1 mm/s [1].", EVIDENCE, question) == []
    assert check_answer_support("Replace PN-9999 at 12 mm/s [1].", EVIDENCE, "q")  # both problems reported
    assert check_answer_support("Stop pump P-101 above 7.1 mm/s [1].", EVIDENCE, "q") == []


# ---- integrated into the answer pipeline ---------------------------------------------------------------------
class ScriptedLLM:
    name, model = "scripted", "test"

    def __init__(self, text_, quote_from_passage=0):
        self.text, self.idx = text_, quote_from_passage

    def answer(self, question, passages):
        quote = passages[self.idx].text.split(".")[0]
        return LLMAnswer(text=self.text, cited=[CitedQuote(passages[self.idx].index, quote)])

    def extract_fields(self, report_text):
        raise NotImplementedError


@pytest.fixture()
def loaded(owner_engine, app_db):
    tenant = make_tenant(owner_engine, "safe")
    with owner_engine.connect() as c:
        uid = str(c.execute(text("SELECT id FROM users WHERE email = :e"),
                            {"e": tenant.users["support_engineer"]}).scalar())
    emb = DeterministicEmbedder()
    with app_db.session(tenant.id, uid) as s:
        for name, kind in SAMPLE_KINDS.items():
            ingest(s, tenant_id=tenant.id, user_id=uid, filename=name, data=(SAMPLES / name).read_bytes(),
                   kind=kind, embedder=emb)
        s.commit()
    return tenant, emb


Q = "What should I check when pump P-101 shows abnormal vibration at the drive-end bearing?"


def test_answer_with_hallucinated_identifier_or_number_is_withheld(app_db, loaded, monkeypatch):
    # The scripted model always cites passage [1]; this test verifies the verification rules, so it runs with the validated baseline retrieval
    # order (the Phase 8 candidate's identifier boost changes which passage is first and, conservatively, withholds this answer instead).
    monkeypatch.delenv("EAOP_TUNING", raising=False)
    tenant, emb = loaded
    with app_db.session(tenant.id) as s:
        ok = answer_question(s, tenant.id, Q, emb, ScriptedLLM("Stop the pump above 7.1 mm/s [1]."))
        assert ok.grounded, ok.problems  # supported claims pass
        bad_id = answer_question(s, tenant.id, Q, emb, ScriptedLLM("Replace bearing PN-9999 above 7.1 mm/s [1]."))
        bad_num = answer_question(s, tenant.id, Q, emb, ScriptedLLM("Stop the pump above 12.5 mm/s [1]."))
    assert not bad_id.grounded and any("PN-9999" in p for p in bad_id.problems) and bad_id.citations == []
    assert not bad_num.grounded and any("12.5" in p for p in bad_num.problems) and bad_num.citations == []


def test_citation_sources_must_be_current_and_tenant_owned(app_db, owner_engine, loaded):
    tenant, emb = loaded
    other = make_tenant(owner_engine, "safe-other")
    with owner_engine.connect() as c:
        uid_o = str(c.execute(text("SELECT id FROM users WHERE email = :e"),
                              {"e": other.users["support_engineer"]}).scalar())
    with app_db.session(other.id, uid_o) as s:  # a chunk owned by a different tenant
        ingest(s, tenant_id=other.id, user_id=uid_o, filename="theirs.txt", data=b"Other tenant private fact 42.",
               kind="other", embedder=emb)
        s.commit()
    with owner_engine.connect() as c:
        foreign = str(c.execute(text("SELECT id FROM document_chunks WHERE tenant_id = :t LIMIT 1"),
                                {"t": other.id}).scalar())
        own = str(c.execute(text("SELECT id FROM document_chunks WHERE tenant_id = :t LIMIT 1"),
                            {"t": tenant.id}).scalar())
    with app_db.session(tenant.id) as s:
        assert verify_citation_sources(s, tenant.id, [{"chunk_id": own}]) == []
        assert verify_citation_sources(s, tenant.id, [{"chunk_id": foreign}])  # not this tenant's chunk
        assert verify_citation_sources(s, tenant.id, [{"chunk_id": "00000000-0000-0000-0000-000000000000"}])
    with owner_engine.begin() as c:  # superseded (non-current) chunks cannot be cited either
        c.execute(text("UPDATE document_chunks SET is_current = false WHERE id = :i"), {"i": own})
    with app_db.session(tenant.id) as s:
        assert verify_citation_sources(s, tenant.id, [{"chunk_id": own}])


# ---- incident review gate: blocks automated external actions ------------------------------------------------
def _extract(client, headers, text_):
    resp = client.post("/api/v1/incidents/extract", headers=headers, json={"report_text": text_})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_unverified_equipment_blocks_ticketing_until_human_review(client, apex_loaded):
    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    inc = _extract(client, eng, "Pump Z-999 shows abnormal vibration at 8.4 mm/s with grinding noise.")
    assert inc["review_status"] == "needs_review" and inc["asset_verified"] is False
    assert any("Human review required" in n for n in inc["notes"])
    blocked = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "incident_needs_review"

    review = {"decision": "accept", "comment": "Z-999 is a newly installed pump; verified on site."}
    assert client.post(f"/api/v1/incidents/{inc['id']}/review", headers=eng, json=review).status_code == 403
    assert client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup,
                       json={"decision": "accept", "comment": "ok"}).status_code == 422  # comment required
    accepted = client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup, json=review)
    assert accepted.status_code == 200 and accepted.json()["review_status"] == "accepted"
    assert client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup, json=review).status_code == 409
    assert client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).status_code == 201
    aud = login(client, apex_loaded, "read_only_auditor")
    actions = [a["action"] for a in client.get("/api/v1/audit", headers=aud, params={"limit": 100}).json()["items"]]
    assert "incident.review_accept" in actions


def test_rejected_incident_can_never_become_a_ticket(client, apex_loaded):
    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    inc = _extract(client, eng, "Pump Z-998 is vibrating at 6 mm/s with a grinding noise.")
    rejected = client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup,
                           json={"decision": "reject", "comment": "Not a real asset."})
    assert rejected.json()["review_status"] == "rejected"
    resp = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]})
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "incident_needs_review"


def test_incident_without_grounded_evidence_needs_review(client, owner_engine, ticketing):
    tenant = make_tenant(owner_engine, "noevid", ticketing.url)  # only an equipment register, no manuals
    eng = login(client, tenant, "support_engineer")
    client.post("/api/v1/documents", headers=eng, data={"kind": "equipment_register"},
                files={"file": ("equipment_register.csv", (SAMPLES / "equipment_register.csv").read_bytes())})
    inc = _extract(client, eng, REPORT)
    assert inc["asset_verified"] is True and inc["citations"] == []
    assert inc["review_status"] == "needs_review"
    assert client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).status_code == 409


def test_verified_and_grounded_incident_proceeds_without_review(client, apex_loaded):
    eng = login(client, apex_loaded, "support_engineer")
    inc = _extract(client, eng, REPORT)
    assert inc["review_status"] == "pending_review"
    assert client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).status_code == 201
