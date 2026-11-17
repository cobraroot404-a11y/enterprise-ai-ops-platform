"""Additional reliability scenarios REL-01 .. REL-04: dependency failures not covered by FI-01 .. FI-10.

These use their own identifiers on purpose: the FI-01 to FI-10 definitions come from the V4.1 specification and are not
redefined or extended here. They are recorded in the same Phase 7 failure report, listed after the FI scenarios.
"""
import pytest
from app.ai.llm import LLMOutputInvalid, get_llm
from app.api.v1 import domain_routes
from app.core.config import get_settings  # noqa: F401
from app.main import create_app
from app.workflows import worker
from fastapi.testclient import TestClient
from sqlalchemy import text
from support import REPORT, login

from tests.fault_injection.test_fault_injection import FAST, approved_ticket, integrity, ticket


@pytest.fixture()
def env(client, apex_loaded):
    return {"tenant": apex_loaded, "eng": login(client, apex_loaded, "support_engineer"),
            "sup": login(client, apex_loaded, "maintenance_supervisor"), "aud": login(client, apex_loaded, "read_only_auditor")}


class DownLLM:
    """A language model that is unreachable / times out (the real client reports this as LLMOutputInvalid)."""
    name, model = "down", "test"

    def answer(self, question, passages):
        raise LLMOutputInvalid("Ollama request failed: ReadTimeout")

    def extract_fields(self, report_text, profile=None):
        raise LLMOutputInvalid("Ollama request failed: ReadTimeout")


class BuggyLLM(DownLLM):
    def answer(self, question, passages):
        raise RuntimeError("unexpected failure inside the model client")


class BadStructureLLM(DownLLM):
    def __init__(self, fields):
        self.fields = fields

    def extract_fields(self, report_text, profile=None):
        if self.fields is None:
            raise LLMOutputInvalid("extraction is not valid schema-conformant JSON")
        return self.fields

    def answer(self, question, passages):
        return get_llm("deterministic").answer(question, passages)


def test_rel01_llm_timeout_or_failure(client, env, worker_db, ticketing, owner_engine, fi, monkeypatch):
    with fi("REL-01", "Additional: LLM timeout or failure", "Apex documents ingested; the language model is healthy",
            "The model call times out (reported as invalid output), then an unexpected exception occurs inside the model client",
            "Questions are withheld honestly (no citation, no answer text); incident extraction falls back to deterministic rules and is "
            "blocked for human review; an unexpected failure is a standardized 500 with no detail and the service keeps working") as sc:
        monkeypatch.setattr(domain_routes, "get_llm", lambda _name: DownLLM())
        ask = client.post("/api/v1/ai/ask", headers=env["eng"], json={"question": "What should I check when pump P-101 vibrates?"})
        inc = client.post("/api/v1/incidents/extract", headers=env["eng"], json={"report_text": REPORT}).json()
        blocked = client.post("/api/v1/tickets", headers=env["eng"], json={"incident_id": inc["id"]})
        monkeypatch.setattr(domain_routes, "get_llm", lambda _name: BuggyLLM())
        lenient = TestClient(client.app, raise_server_exceptions=False)  # observe the 500 the client would see
        boom = lenient.post("/api/v1/ai/ask", headers=env["eng"], json={"question": "What should I check when pump P-101 vibrates?"})
        monkeypatch.undo()
        after = client.post("/api/v1/ai/ask", headers=env["eng"], json={"question": "What should I check when pump P-101 vibrates?"})
        sc.actual_behavior = (f"timeout: ask {ask.status_code} grounded={ask.json()['grounded']} problems={ask.json()['problems'][:1]}; extraction "
                              f"review_status={inc['review_status']} fallback={'rules-fallback' in inc['extraction_backend']}; draft {blocked.status_code}; "
                              f"unexpected exception: {boom.status_code} {boom.json()['error']['code']}; after recovery: {after.status_code}")
        sc.recovery_action = "automatic: the next request uses the healthy model; no manual action"
        sc.final_state = "no ticket created from the unreviewed incident"
        sc.duplicate_external_actions = ticketing.state.requests
        sc.data_integrity = integrity(owner_engine, env["tenant"].id, ticketing)
        assert ask.status_code == 200 and not ask.json()["grounded"] and ask.json()["citations"] == []
        assert inc["review_status"] == "needs_review" and "rules-fallback" in inc["extraction_backend"] and blocked.status_code == 409
        assert boom.status_code == 500 and boom.json()["error"]["code"] == "internal_error" and "RuntimeError" not in boom.text
        assert after.status_code == 200 and ticketing.state.requests == 0


def test_rel02_embedding_or_retrieval_failure(client, env, owner_engine, ticketing, fi, monkeypatch):
    from app.ai import embeddings
    with fi("REL-02", "Additional: embedding or retrieval failure", "Apex documents indexed; embedding model healthy",
            "The embedding model raises while embedding a query and while embedding an uploaded document",
            "Search, ask and upload return 503 embedding_unavailable with Retry-After (never a raw 500); the failed upload stores nothing; "
            "everything works again once the model recovers") as sc:
        real = embeddings.DeterministicEmbedder.embed

        def failing(self, texts):
            raise RuntimeError("model file could not be loaded")

        monkeypatch.setattr(embeddings.DeterministicEmbedder, "embed", failing)
        before = client.get("/api/v1/ingestion/status", headers=env["eng"]).json()
        search = client.post("/api/v1/search", headers=env["eng"], json={"query": "drive-end bearing vibration"})
        ask = client.post("/api/v1/ai/ask", headers=env["eng"], json={"question": "What should I check when pump P-101 vibrates?"})
        upload = client.post("/api/v1/documents", headers=env["eng"], data={"kind": "other"}, files={"file": ("rel02.txt", b"REL-02 note about gaskets.")})
        mid = client.get("/api/v1/ingestion/status", headers=env["eng"]).json()
        monkeypatch.setattr(embeddings.DeterministicEmbedder, "embed", real)
        recovered = client.post("/api/v1/search", headers=env["eng"], json={"query": "drive-end bearing vibration"})
        retry = client.post("/api/v1/documents", headers=env["eng"], data={"kind": "other"}, files={"file": ("rel02.txt", b"REL-02 note about gaskets.")})
        sc.actual_behavior = (f"during outage: search {search.status_code} {search.json()['error']['code']}, ask {ask.status_code}, upload {upload.status_code}; "
                              f"chunks before/during {before['chunks']}/{mid['chunks']}; after recovery: search {recovered.status_code}, upload {retry.status_code} {retry.json().get('status')}")
        sc.recovery_action = "automatic once the embedding model is available; the client retries after Retry-After"
        sc.final_state = "index consistent; no partial documents"
        sc.duplicate_external_actions = 0
        sc.data_integrity = f"CONSISTENT: chunk count unchanged during the outage ({before['chunks']} == {mid['chunks']})"
        assert search.status_code == ask.status_code == upload.status_code == 503 and search.headers["Retry-After"]
        assert search.json()["error"]["code"] == "embedding_unavailable" and "model file" not in search.text
        assert before["chunks"] == mid["chunks"] and recovered.status_code == 200 and retry.json()["status"] == "created"


def test_rel03_invalid_structured_ai_output(client, env, owner_engine, ticketing, fi, monkeypatch):
    with fi("REL-03", "Additional: invalid structured AI output", "Apex documents ingested",
            "The model returns (a) non-conforming output, (b) a hallucinated equipment id that is not in the report, (c) nothing identifying equipment",
            "Invalid output never reaches a ticket: (a) falls back to deterministic rules and blocks for human review; (b) is rejected as invalid "
            "and falls back; (c) is refused with asset_not_identified; no incident is created for (c)") as sc:
        results = {}
        monkeypatch.setattr(domain_routes, "get_llm", lambda _name: BadStructureLLM(None))
        a = client.post("/api/v1/incidents/extract", headers=env["eng"], json={"report_text": REPORT}).json()
        results["a"] = (a["review_status"], "rules-fallback" in a["extraction_backend"])
        monkeypatch.setattr(domain_routes, "get_llm", lambda _name: BadStructureLLM(
            {"asset_id": "P-999", "category": "leak", "symptoms": ["x"], "vibration_mm_s": None, "smoke_or_fire": False}))
        b = client.post("/api/v1/incidents/extract", headers=env["eng"], json={"report_text": REPORT}).json()
        results["b"] = (b["asset_id"], b["category"], b["review_status"])
        monkeypatch.setattr(domain_routes, "get_llm", lambda _name: BadStructureLLM(None))
        c = client.post("/api/v1/incidents/extract", headers=env["eng"], json={"report_text": "There is a strange noise somewhere in the plant."})
        monkeypatch.undo()
        total = client.get("/api/v1/incidents", headers=env["eng"]).json()["total"]
        sc.actual_behavior = f"(a) {results['a']}; (b) {results['b']}; (c) {c.status_code} {c.json()['error']['code']}; incidents stored={total}"
        sc.recovery_action = "deterministic rules take over; the human-review gate holds"
        sc.final_state = "no ticket possible without human review; nothing sent externally"
        sc.duplicate_external_actions = ticketing.state.requests
        sc.data_integrity = integrity(owner_engine, env["tenant"].id, ticketing)
        assert results["a"] == ("needs_review", True)
        assert results["b"][0] == "P-101" and results["b"][2] == "needs_review"  # the hallucinated asset id and category are not used
        assert c.status_code == 422 and c.json()["error"]["code"] == "asset_not_identified" and total == 2
        assert ticketing.state.requests == 0


def test_rel04_recovery_after_api_process_restart(client, env, worker_db, ticketing, owner_engine, settings, app_db, fi):
    with fi("REL-04", "Additional: API process restart between approval and submission", "Ticket APPROVED with a durable outbox event",
            "The API process is restarted (a brand new application instance) before the worker submits; the worker is then started",
            "No state is lost: the new instance sees the approved ticket; the worker submits exactly once; the audit trail is continuous") as sc:
        tid = approved_ticket(client, env)
        restarted = TestClient(create_app(settings, app_db))
        same = restarted.get(f"/api/v1/tickets/{tid}", headers=login(restarted, env["tenant"], "support_engineer")).json()
        outcomes = worker.drain(worker_db, FAST)
        final = restarted.get(f"/api/v1/tickets/{tid}", headers=login(restarted, env["tenant"], "support_engineer")).json()
        with owner_engine.connect() as c:
            events = c.execute(text("SELECT count(*) FROM audit_events WHERE tenant_id = :t AND entity_id = :e"),
                               {"t": env["tenant"].id, "e": tid}).scalar()
        sc.actual_behavior = f"after restart ticket was {same['state']}; worker {outcomes}; final {final['state']}; audit events for the ticket={events}"
        sc.recovery_action = "none required: PostgreSQL is the authoritative state store and the outbox is durable"
        sc.final_state = f"ticket {final['state']} as {final['external_ticket_id']}"
        sc.duplicate_external_actions = len(ticketing.state.tickets) - 1
        sc.data_integrity = integrity(owner_engine, env["tenant"].id, ticketing)
        assert same["state"] == "APPROVED" and outcomes == ["submitted"] and final["state"] == "SUBMITTED" and events >= 5
        assert ticket(client, env, tid)["external_ticket_id"] == final["external_ticket_id"] and len(ticketing.state.tickets) == 1
