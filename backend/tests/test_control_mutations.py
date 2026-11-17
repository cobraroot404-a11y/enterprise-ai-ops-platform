"""Mutation-style proofs that critical security controls are what actually stop attacks.

Pattern for every test: (1) the control blocks the attack, (2) the control is deliberately removed and the
attack SUCCEEDS (so a regression would be detected), (3) the control is restored and blocks again.
DDL mutations are always undone in `finally`.
"""
import contextlib
import time
import uuid

import httpx
import jwt
import pytest
from app.ai.embeddings import DeterministicEmbedder
from app.ai.llm import CitedQuote, LLMAnswer
from app.ai.rag import answer_question
from app.connectors.clients import TicketingClient
from app.core import rbac
from app.ingestion.service import ingest
from app.workflows import worker
from app.workflows.worker import WorkerConfig
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from support import REPORT, SAMPLE_KINDS, SAMPLES, TICKETING_KEY, ingest_samples, login, make_tenant


@contextlib.contextmanager
def mutated(owner_engine, apply_sql: str, restore_sql: str):
    with owner_engine.begin() as conn:
        conn.execute(text(apply_sql))
    try:
        yield
    finally:
        with owner_engine.begin() as conn:
            conn.execute(text(restore_sql))


def _uid(owner_engine, email):
    with owner_engine.connect() as c:
        return str(c.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email}).scalar())


def _count_other_tenant_chunks(app_db, as_tenant, other):
    with app_db.session(as_tenant.id) as s:
        return s.execute(text("SELECT count(*) FROM document_chunks WHERE tenant_id = :o"), {"o": other.id}).scalar()


# ---- row-level security ------------------------------------------------------------------------------------
def test_mutation_rls_on_document_chunks_is_the_cross_tenant_barrier(app_db, owner_engine, client, ticketing):
    a, b = make_tenant(owner_engine, "mra", ticketing.url), make_tenant(owner_engine, "mrb", ticketing.url)
    ingest_samples(client, login(client, a, "support_engineer"))
    assert _count_other_tenant_chunks(app_db, b, a) == 0  # (1) RLS blocks even a query with no tenant filter
    with mutated(owner_engine,
                 "ALTER TABLE document_chunks NO FORCE ROW LEVEL SECURITY; "
                 "ALTER TABLE document_chunks DISABLE ROW LEVEL SECURITY",
                 "ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY; "
                 "ALTER TABLE document_chunks FORCE ROW LEVEL SECURITY"):
        assert _count_other_tenant_chunks(app_db, b, a) > 0  # (2) without RLS the raw query leaks tenant A data
        # defense in depth: the explicit tenant filter inside search() still holds when RLS is gone
        hits = client.post("/api/v1/search", headers=login(client, b, "support_engineer"),
                           json={"query": "drive-end bearing vibration"}).json()["items"]
        assert hits == []
    assert _count_other_tenant_chunks(app_db, b, a) == 0  # (3) restored


def test_mutation_rls_on_memberships_stops_self_escalation(app_db, owner_engine):
    t = make_tenant(owner_engine, "mrm")
    eng = _uid(owner_engine, t.users["support_engineer"])
    sql = "UPDATE memberships SET role = 'tenant_admin' WHERE user_id = :u"

    def attempt():
        with app_db.session(t.id, eng) as s:
            n = s.execute(text(sql), {"u": eng}).rowcount
            s.commit()
            return n

    assert attempt() == 0  # (1) blocked by the policy
    with mutated(owner_engine,
                 "ALTER TABLE memberships NO FORCE ROW LEVEL SECURITY; "
                 "ALTER TABLE memberships DISABLE ROW LEVEL SECURITY",
                 "ALTER TABLE memberships ENABLE ROW LEVEL SECURITY; "
                 "ALTER TABLE memberships FORCE ROW LEVEL SECURITY"):
        assert attempt() == 1  # (2) without the policy an engineer promotes themselves
        with owner_engine.begin() as c:
            c.execute(text("UPDATE memberships SET role = 'support_engineer' WHERE user_id = :u"), {"u": eng})
    assert attempt() == 0  # (3)


# ---- audit immutability, outbox uniqueness, approval uniqueness -------------------------------------------------
def test_mutation_audit_trigger_makes_log_append_only(owner_engine):
    t = make_tenant(owner_engine, "mau")
    with owner_engine.begin() as c:
        c.execute(text("INSERT INTO audit_events (tenant_id, action, entity_type) VALUES (:t, 'x', 'y')"), {"t": t.id})
    update = "UPDATE audit_events SET action = 'tampered' WHERE tenant_id = :t"
    with pytest.raises(DBAPIError), owner_engine.begin() as c:  # (1)
        c.execute(text(update), {"t": t.id})
    with mutated(owner_engine, "DROP TRIGGER audit_events_no_update ON audit_events",
                 "CREATE TRIGGER audit_events_no_update BEFORE UPDATE OR DELETE ON audit_events "
                 "FOR EACH ROW EXECUTE FUNCTION audit_events_immutable()"):
        with owner_engine.begin() as c:  # (2) history can be rewritten
            assert c.execute(text(update), {"t": t.id}).rowcount == 1
    with pytest.raises(DBAPIError), owner_engine.begin() as c:  # (3)
        c.execute(text(update), {"t": t.id})


def test_mutation_outbox_unique_index_prevents_duplicate_submissions(owner_engine):
    t = make_tenant(owner_engine, "mob")
    agg = str(uuid.uuid4())
    ins = "INSERT INTO outbox_events (tenant_id, topic, aggregate_id) VALUES (:t, 'ticket.submit', :a)"
    with owner_engine.begin() as c:
        c.execute(text(ins), {"t": t.id, "a": agg})
    with pytest.raises(IntegrityError), owner_engine.begin() as c:  # (1) a second active event is refused
        c.execute(text(ins), {"t": t.id, "a": agg})
    restore = ("DELETE FROM outbox_events WHERE id NOT IN "
               "(SELECT min(id) FROM outbox_events GROUP BY topic, aggregate_id); "
               "CREATE UNIQUE INDEX outbox_one_active_per_aggregate ON outbox_events (topic, aggregate_id) "
               "WHERE status IN ('pending','processing')")
    with mutated(owner_engine, "DROP INDEX outbox_one_active_per_aggregate", restore):
        with owner_engine.begin() as c:  # (2) duplicates now possible
            c.execute(text(ins), {"t": t.id, "a": agg})
            count = c.execute(text("SELECT count(*) FROM outbox_events WHERE aggregate_id = :a"), {"a": agg}).scalar()
            assert count == 2
    with pytest.raises(IntegrityError), owner_engine.begin() as c:  # (3)
        c.execute(text(ins), {"t": t.id, "a": agg})


def test_mutation_approval_unique_constraint_blocks_second_decision(client, owner_engine, apex_loaded):
    apex = apex_loaded
    eng, sup = login(client, apex, "support_engineer"), login(client, apex, "maintenance_supervisor")
    inc = client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": REPORT}).json()
    tid = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()["id"]
    client.post(f"/api/v1/tickets/{tid}/request-approval", headers=eng)
    client.post(f"/api/v1/approvals/{tid}/decision", headers=sup, json={"decision": "approved"})
    sup_id = _uid(owner_engine, apex.users["maintenance_supervisor"])
    ins = ("INSERT INTO approvals (tenant_id, ticket_id, decision, decided_by) VALUES (:t, :k, 'rejected', :u)")
    p = {"t": apex.id, "k": tid, "u": sup_id}
    with pytest.raises(IntegrityError), owner_engine.begin() as c:  # (1)
        c.execute(text(ins), p)
    restore = ("DELETE FROM approvals WHERE ticket_id = :k AND decision = 'rejected'; "
               "ALTER TABLE approvals ADD CONSTRAINT approvals_ticket_id_key UNIQUE (ticket_id)")
    with owner_engine.begin() as c:
        c.execute(text("ALTER TABLE approvals DROP CONSTRAINT approvals_ticket_id_key"))
    try:
        with owner_engine.begin() as c:  # (2) a contradicting second decision can be stored
            c.execute(text(ins), p)
            assert c.execute(text("SELECT count(*) FROM approvals WHERE ticket_id = :k"), {"k": tid}).scalar() == 2
    finally:
        with owner_engine.begin() as c:
            for stmt in restore.split("; "):
                c.execute(text(stmt), {"k": tid})
    with pytest.raises(IntegrityError), owner_engine.begin() as c:  # (3)
        c.execute(text(ins), p)


# ---- application controls ------------------------------------------------------------------------------------
def test_mutation_rbac_check_is_what_stops_role_escalation(client, apex_loaded, monkeypatch):
    apex = apex_loaded
    eng, sup = login(client, apex, "support_engineer"), login(client, apex, "maintenance_supervisor")
    inc = client.post("/api/v1/incidents/extract", headers=sup, json={"report_text": REPORT}).json()
    tid = client.post("/api/v1/tickets", headers=sup, json={"incident_id": inc["id"]}).json()["id"]
    client.post(f"/api/v1/tickets/{tid}/request-approval", headers=sup)
    decide = {"decision": "approved", "comment": "x"}
    assert client.post(f"/api/v1/approvals/{tid}/decision", headers=eng, json=decide).status_code == 403  # (1)
    with monkeypatch.context() as mp:
        mp.setattr(rbac, "can", lambda role, permission: True)
        assert client.post(f"/api/v1/approvals/{tid}/decision", headers=eng, json=decide).status_code == 200  # (2)
    # (3) restored: another engineer is blocked again
    inc2 = client.post("/api/v1/incidents/extract", headers=sup, json={"report_text": REPORT}).json()
    tid2 = client.post("/api/v1/tickets", headers=sup, json={"incident_id": inc2["id"]}).json()["id"]
    client.post(f"/api/v1/tickets/{tid2}/request-approval", headers=sup)
    assert client.post(f"/api/v1/approvals/{tid2}/decision", headers=eng, json=decide).status_code == 403


def test_mutation_jwt_signature_check_is_what_rejects_forged_tokens(client, apex, owner_engine, monkeypatch):
    uid = _uid(owner_engine, apex.users["tenant_admin"])
    forged = jwt.encode({"sub": uid, "tid": apex.id, "role": "tenant_admin", "exp": int(time.time()) + 600},
                        "attacker-controlled-secret", algorithm="HS256")
    def get():
        return client.get("/api/v1/documents", headers={"Authorization": f"Bearer {forged}"}).status_code

    assert get() == 401  # (1)
    import app.api.deps as deps
    with monkeypatch.context() as mp:
        mp.setattr(deps, "decode_token", lambda secret, token: jwt.decode(
            token, options={"verify_signature": False}))
        assert get() == 200  # (2) with verification off the forged token is accepted
    assert get() == 401  # (3)


def test_mutation_idempotency_key_is_what_prevents_duplicate_external_tickets(client, apex_loaded, worker_db,
                                                                                ticketing, monkeypatch):
    apex = apex_loaded
    eng, sup = login(client, apex, "support_engineer"), login(client, apex, "maintenance_supervisor")

    def run_once():
        inc = client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": REPORT}).json()
        tid = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]}).json()["id"]
        client.post(f"/api/v1/tickets/{tid}/request-approval", headers=eng)
        client.post(f"/api/v1/approvals/{tid}/decision", headers=sup, json={"decision": "approved"})
        httpx.post(f"{ticketing.url}/admin/failure", json={"mode": "lost_response", "count": 1},
                   headers={"X-API-Key": TICKETING_KEY})
        worker.drain(worker_db, WorkerConfig(backoff_base=0, http_timeout=2))
        return len(ticketing.state.tickets)

    assert run_once() == 1  # (1) response lost, retry reuses the same external ticket
    original = TicketingClient.create_ticket

    def without_key(self, payload, idempotency_key):
        return original(self, payload, str(uuid.uuid4()))  # a fresh key each time == no idempotency

    with monkeypatch.context() as mp:
        mp.setattr(TicketingClient, "create_ticket", without_key)
        assert run_once() == 3  # (2) one more ticket for the new run PLUS a duplicate from its retry
    assert run_once() == 4  # (3) restored: exactly one new ticket again


class _Fabricator:
    name, model = "fabricator", "test"

    def answer(self, question, passages):
        return LLMAnswer(text="Replace bearing PN-9999 above 12.5 mm/s [1].",
                         cited=[CitedQuote(passages[0].index, "this sentence is not in any passage")])

    def extract_fields(self, report_text):
        raise NotImplementedError


def test_mutation_citation_verification_and_safeguards_stop_fabricated_answers(app_db, owner_engine, monkeypatch):
    t = make_tenant(owner_engine, "mci")
    uid, emb = _uid(owner_engine, t.users["support_engineer"]), DeterministicEmbedder()
    with app_db.session(t.id, uid) as s:
        for name, kind in SAMPLE_KINDS.items():
            ingest(s, tenant_id=t.id, user_id=uid, filename=name, data=(SAMPLES / name).read_bytes(), kind=kind,
                   embedder=emb)
        s.commit()
    q = "What should I check when pump P-101 shows abnormal vibration at the drive-end bearing?"

    def ask():
        with app_db.session(t.id) as s:
            return answer_question(s, t.id, q, emb, _Fabricator())

    assert not ask().grounded  # (1) fabricated quote + invented part number + invented number are withheld
    import app.ai.rag as rag
    with monkeypatch.context() as mp:
        mp.setattr(rag, "verify_citations", lambda answer, passages: ([c.index for c in answer.cited], []))
        mp.setattr(rag, "check_answer_support", lambda *a, **k: [])
        mp.setattr(rag, "verify_citation_sources", lambda *a, **k: [])
        shown = ask()
        assert shown.grounded and "PN-9999" in shown.answer  # (2) with the controls off the fabrication is shown
    assert not ask().grounded  # (3)
