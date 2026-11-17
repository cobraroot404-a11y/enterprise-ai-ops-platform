"""V41-12.05: audited document deletion with retrieval exclusion and tenant-safe cleanup.

Stage A (logical deletion, in the request) and Stage B (content cleanup by the outbox worker) are proved separately and together: authorization, tenant isolation, immediate exclusion
from listings / direct access / search / retrieval / citation lookups, audit contents (no text), idempotency, retry and partial-failure recovery, concurrency with ingestion, and the
worker's tenant-scoped database access. Everything runs on the isolated `eaop_test` database with the deterministic test backends and the existing mock services."""
import threading
import uuid

import pytest
from app.ai.embeddings import get_embedder
from app.ai.safeguards import verify_citation_sources
from app.ingestion import lifecycle
from app.ingestion.service import ingest
from app.retrieval.search import search
from app.services import incident_service
from app.workflows import worker
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from support import REPORT, SAMPLE_KINDS, SAMPLES, ingest_samples, login, make_tenant

FAST = worker.WorkerConfig(backoff_base=0, backoff_cap=0, http_timeout=1.0, max_attempts=3)
LOG = "maintenance_log.csv"
HISTORY = "incident_history.csv"
MANUAL = "apex_cp200_pump_manual.pdf"
LOG_QUERY = "Weekly bearing inspection lubricant topped up technician R. Okafor"


def docs(client, hdr):
    items = client.get("/api/v1/documents", headers=hdr, params={"limit": 100}).json()["items"]
    return {d["filename"]: d["id"] for d in items}


def delete(client, hdr, doc_id, extra=None):
    return client.delete(f"/api/v1/documents/{doc_id}", headers={**hdr, **(extra or {})})


def hits(client, hdr, query, k=8):
    return client.post("/api/v1/search", headers=hdr, json={"query": query, "k": k}).json()["items"]


def sql(owner_engine, query, **params):
    with owner_engine.connect() as c:
        return c.execute(text(query), params).all()


@pytest.fixture()
def world(client, apex_loaded, ticketing):
    t = apex_loaded
    return {"t": t, "eng": login(client, t, "support_engineer"), "sup": login(client, t, "maintenance_supervisor"), "adm": login(client, t, "tenant_admin"), "aud": login(client, t, "read_only_auditor")}


# ---------------------------------------------------------------------------------------------------------------------------- authorization
def test_only_administrators_and_supervisors_may_delete_and_the_server_decides(client, world):
    ids = docs(client, world["eng"])
    before = len(ids)
    for who in ("eng", "aud"):
        r = delete(client, world[who], ids[LOG])
        assert r.status_code == 403 and r.json()["error"]["code"] == "insufficient_role", who
    assert delete(client, {}, ids[LOG]).status_code == 401
    assert client.delete("/api/v1/documents/not-a-uuid", headers=world["adm"]).status_code == 422
    assert len(docs(client, world["eng"])) == before  # nothing was deleted by any refused attempt
    assert delete(client, world["sup"], ids[LOG]).status_code == 200
    assert delete(client, world["adm"], ids[HISTORY]).status_code == 200


# ---------------------------------------------------------------------------------------------------------------------------- stage A
def test_logical_deletion_is_immediate_everywhere_and_audited_without_content(client, world, owner_engine, app_db):
    ids = docs(client, world["eng"])
    assert any(h["filename"] == LOG for h in hits(client, world["eng"], LOG_QUERY))  # precondition: the content is retrievable
    metrics_before = client.get("/api/v1/metrics", headers=world["eng"]).json()
    r = delete(client, world["sup"], ids[LOG], {"X-Correlation-ID": "cid-del-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["lifecycle_status"] == "deleted" and body["cleanup_state"] == "pending" and body["already_deleted"] is False and body["cleanup_completed_at"] is None
    assert body["id"] == ids[LOG] and body["filename"] == LOG
    # listings, direct access, search and counts exclude it at once (before any cleanup ran)
    assert LOG not in docs(client, world["eng"])
    assert client.get(f"/api/v1/documents/{ids[LOG]}", headers=world["eng"]).status_code == 404
    assert not any(h["filename"] == LOG for h in hits(client, world["eng"], LOG_QUERY))
    assert client.get("/api/v1/metrics", headers=world["eng"]).json()["documents"] == metrics_before["documents"] - 1
    status = client.get("/api/v1/ingestion/status", headers=world["eng"]).json()
    assert status["documents_versions"] == len(docs(client, world["eng"]))
    # the chunks are no longer current; one cleanup event is queued; the audit event holds metadata only
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d AND is_current", d=ids[LOG])[0][0] == 0
    assert sql(owner_engine, "SELECT count(*) FROM outbox_events WHERE topic = 'document.cleanup' AND aggregate_id = :d AND status = 'pending'", d=ids[LOG])[0][0] == 1
    event = sql(owner_engine, "SELECT actor_id, details, correlation_id, tenant_id FROM audit_events WHERE action = 'document.deleted' AND entity_id = :d", d=ids[LOG])
    assert len(event) == 1
    actor, details, cid, tenant = event[0]
    assert str(tenant) == world["t"].id and cid == "cid-del-1" and actor is not None
    assert set(details) <= {"outcome", "cleanup_state", "versions", "chunks", "jobs_cancelled"} and details["cleanup_state"] == "pending"
    assert "Okafor" not in str(details) and "Weekly" not in str(details)
    # a new citation lookup cannot reach the deleted text, and the document is not discoverable through retrieval helpers
    chunk_ids = [str(r[0]) for r in sql(owner_engine, "SELECT id FROM document_chunks WHERE document_id = :d", d=ids[LOG])]
    assert chunk_ids
    with app_db.session(tenant_id=world["t"].id) as s:
        assert verify_citation_sources(s, world["t"].id, [{"chunk_id": chunk_ids[0]}])  # refused: not a current chunk of an active document
        assert incident_service._cited_passage_texts(s, world["t"].id, [{"chunk_id": chunk_ids[0]}]) == []
    # the auditor sees the event in the audit log
    audit = client.get("/api/v1/audit", headers=world["aud"], params={"entity_id": ids[LOG]}).json()["items"]
    assert [a["action"] for a in audit if a["action"] != "document.created"] == ["document.deleted"]


def test_repeating_the_request_is_idempotent_and_never_duplicates_work_or_audit(client, world, owner_engine):
    ids = docs(client, world["eng"])
    first = delete(client, world["sup"], ids[LOG]).json()
    second = delete(client, world["adm"], ids[LOG])
    assert second.status_code == 200
    again = second.json()
    assert again["already_deleted"] is True and again["deleted_at"] == first["deleted_at"] and again["cleanup_state"] == "pending"
    assert sql(owner_engine, "SELECT count(*) FROM audit_events WHERE action = 'document.deleted' AND entity_id = :d", d=ids[LOG])[0][0] == 1
    assert sql(owner_engine, "SELECT count(*) FROM outbox_events WHERE topic = 'document.cleanup' AND aggregate_id = :d", d=ids[LOG])[0][0] == 1


# ---------------------------------------------------------------------------------------------------------------------------- stage B
def test_cleanup_removes_content_verifies_it_and_is_idempotent(client, world, owner_engine, worker_db):
    ids = docs(client, world["eng"])
    delete(client, world["sup"], ids[LOG])
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d", d=ids[LOG])[0][0] > 0
    assert worker.drain(worker_db, FAST) == ["cleanup_completed"]
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d", d=ids[LOG])[0][0] == 0
    assert sql(owner_engine, "SELECT count(*) FROM document_versions WHERE document_id = :d", d=ids[LOG])[0][0] == 0
    row = sql(owner_engine, "SELECT lifecycle_status, cleanup_state, cleanup_completed_at, deleted_by, filename, source_key FROM documents WHERE id = :d", d=ids[LOG])[0]
    assert row[0] == "deleted" and row[1] == "completed" and row[2] is not None and row[3] is not None and row[4] == LOG and row[5].startswith("deleted:")  # tombstone kept
    done = sql(owner_engine, "SELECT details, actor_type FROM audit_events WHERE action = 'document.cleanup_completed' AND entity_id = :d", d=ids[LOG])
    assert len(done) == 1 and done[0][1] == "worker" and done[0][0]["chunks_removed"] > 0 and done[0][0]["versions_removed"] == 1 and "Okafor" not in str(done[0][0])
    assert worker.drain(worker_db, FAST) == []  # nothing left to do
    repeated = delete(client, world["sup"], ids[LOG]).json()
    assert repeated["cleanup_state"] == "completed" and repeated["cleanup_completed_at"] is not None
    with worker_db.session(tenant_id=world["t"].id) as s:  # running the cleanup again directly changes nothing
        assert lifecycle.cleanup_document(s, tenant_id=world["t"].id, document_id=ids[LOG])["outcome"] == "already_completed"


def test_incident_and_ticket_history_survives_but_quotes_copied_from_deleted_documents_are_redacted(client, world, owner_engine, worker_db):
    inc = client.post("/api/v1/incidents/extract", headers=world["eng"], json={"report_text": REPORT}).json()
    assert inc["citations"] and inc["related_incidents"], "the deterministic flow cites the manual and lists related incidents"
    quotes = [c["quote"] for c in inc["citations"]]
    summaries = [r["summary"] for r in inc["related_incidents"]]
    if inc["review_status"] == "needs_review":
        client.post(f"/api/v1/incidents/{inc['id']}/review", headers=world["sup"], json={"decision": "accept", "comment": "Accepted for the lifecycle test."})
    ticket = client.post("/api/v1/tickets", headers=world["eng"], json={"incident_id": inc["id"]}).json()
    ids = docs(client, world["eng"])
    for name in (MANUAL, HISTORY, "equipment_register.csv", "apex_inspection_report_2026q3.pdf", LOG):
        delete(client, world["sup"], ids[name])
    # before cleanup: the read path already redacts (stage A guard) and nothing is lost from the workflow records
    masked = client.get(f"/api/v1/incidents/{inc['id']}", headers=world["eng"]).json()
    assert all(c["quote"] == lifecycle.REDACTED for c in masked["citations"]) and all(r["summary"] == lifecycle.REDACTED for r in masked["related_incidents"])
    assert masked["recommended_action"] == inc["recommended_action"] and masked["priority"] == inc["priority"] and masked["asset_id"] == inc["asset_id"]
    assert [c["filename"] for c in masked["citations"]] == [c["filename"] for c in inc["citations"]]  # event metadata is preserved
    assert any(q in str(sql(owner_engine, "SELECT citations FROM incidents WHERE id = :i", i=inc["id"])) for q in quotes)  # still stored until the worker runs
    assert all(o == "cleanup_completed" for o in worker.drain(worker_db, FAST))
    stored = str(sql(owner_engine, "SELECT citations, related_incidents FROM incidents WHERE id = :i", i=inc["id"]))
    assert not any(q in stored for q in quotes + summaries) and lifecycle.REDACTED in stored  # now physically gone from the incident record too
    assert client.get(f"/api/v1/tickets/{ticket['id']}", headers=world["eng"]).status_code == 200  # tickets and their history are not erased
    assert client.get(f"/api/v1/incidents/{inc['id']}/history", headers=world["eng"]).json()["tickets"][0]["id"] == ticket["id"]


# ---------------------------------------------------------------------------------------------------------------------------- retrieval boundary
@pytest.mark.parametrize("mode", ["hybrid", "vector", "fts"])
def test_deleted_chunks_never_come_back_from_any_retrieval_mode(client, world, app_db, mode):
    ids = docs(client, world["eng"])
    embedder = get_embedder("deterministic")
    with app_db.session(tenant_id=world["t"].id) as s:
        assert any(str(h.document_id) == ids[LOG] for h in search(s, world["t"].id, LOG_QUERY, embedder, k=10, mode=mode))
    delete(client, world["sup"], ids[LOG])
    with app_db.session(tenant_id=world["t"].id) as s:
        assert not any(str(h.document_id) == ids[LOG] for h in search(s, world["t"].id, LOG_QUERY, embedder, k=10, mode=mode))
        assert [h for h in search(s, world["t"].id, "equipment register P-101", embedder, k=5, mode=mode)]  # other documents still answer
    answer = client.post("/api/v1/ai/ask", headers=world["eng"], json={"question": "Who performed the weekly bearing inspection of P-101?"}).json()
    assert all(c["filename"] != LOG for c in answer["citations"])


def test_upload_after_deletion_creates_a_new_document_and_never_revives_or_duplicates_the_old_one(client, world, owner_engine, worker_db):
    ids = docs(client, world["eng"])
    delete(client, world["sup"], ids[LOG])
    data = (SAMPLES / LOG).read_bytes()
    again = client.post("/api/v1/documents", headers=world["eng"], data={"kind": SAMPLE_KINDS[LOG]}, files={"file": (LOG, data)})
    assert again.status_code == 201 and again.json()["status"] == "created" and again.json()["document_id"] != ids[LOG]  # not "duplicate", not "new_version"
    new_id = again.json()["document_id"]
    assert docs(client, world["eng"])[LOG] == new_id
    assert sql(owner_engine, "SELECT lifecycle_status FROM documents WHERE id = :d", d=ids[LOG])[0][0] == "deleted"
    assert worker.drain(worker_db, FAST) == ["cleanup_completed"]
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d AND is_current", d=new_id)[0][0] > 0  # the cleanup removed only the deleted document's content
    assert any(h["filename"] == LOG for h in hits(client, world["eng"], LOG_QUERY))


def test_an_upload_racing_a_deletion_cannot_revive_the_deleted_document(client, world, owner_engine, app_db):
    """Deterministic interleaving: the deletion holds the document lock while an upload of the same name starts; when the deletion commits, the upload must find the document gone."""
    ids = docs(client, world["eng"])
    tenant = world["t"].id
    result, errors = {}, []
    deleting = app_db.session(tenant_id=tenant, user_id=str(uuid.uuid4()))
    state = lifecycle.delete_document(deleting, tenant_id=tenant, user_id=uuid.uuid4(), document_id=ids[LOG])  # row locked, not yet committed
    assert state.lifecycle_status == "deleted"

    def upload():
        try:
            with app_db.session(tenant_id=tenant) as s:
                result["r"] = ingest(s, tenant_id=tenant, user_id=None, filename=LOG, data=(SAMPLES / LOG).read_bytes() + b"\nML-9999,2026-09-01,P-101,Racing upload,T. Test\n",
                                     kind=SAMPLE_KINDS[LOG], embedder=get_embedder("deterministic"))
                s.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=upload)
    thread.start()
    thread.join(2.0)
    assert thread.is_alive(), "the upload must wait for the deletion's lock rather than touching the document"
    deleting.commit()
    deleting.close()
    thread.join(30)
    assert not errors, errors
    assert result["r"].status == "created" and result["r"].document_id != ids[LOG]  # a NEW document, not a new version of the deleted one
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d AND is_current", d=ids[LOG])[0][0] == 0
    assert sql(owner_engine, "SELECT current_version, lifecycle_status FROM documents WHERE id = :d", d=ids[LOG])[0] == (1, "deleted")


def test_two_simultaneous_deletions_of_the_same_document_produce_one_event_and_one_audit_record(world, client, app_db, owner_engine):
    ids = docs(client, world["eng"])
    tenant, outcome = world["t"].id, {}
    first = app_db.session(tenant_id=tenant)
    state = lifecycle.delete_document(first, tenant_id=tenant, user_id=uuid.uuid4(), document_id=ids[LOG])  # holds the row lock, uncommitted

    def second():
        with app_db.session(tenant_id=tenant) as s:
            outcome["state"] = lifecycle.delete_document(s, tenant_id=tenant, user_id=uuid.uuid4(), document_id=ids[LOG])
            s.commit()

    thread = threading.Thread(target=second)
    thread.start()
    thread.join(1.5)
    assert thread.is_alive()  # serialised behind the first deletion
    first.commit()
    first.close()
    thread.join(30)
    assert state.already_deleted is False and outcome["state"].already_deleted is True and outcome["state"].deleted_at == state.deleted_at
    assert sql(owner_engine, "SELECT count(*) FROM audit_events WHERE action = 'document.deleted' AND entity_id = :d", d=ids[LOG])[0][0] == 1
    assert sql(owner_engine, "SELECT count(*) FROM outbox_events WHERE topic = 'document.cleanup' AND aggregate_id = :d", d=ids[LOG])[0][0] == 1


# ---------------------------------------------------------------------------------------------------------------------------- tenant isolation
def test_another_tenant_can_neither_delete_nor_observe_nor_be_affected(client, world, owner_engine, worker_db, ticketing, inventory_server):
    other = make_tenant(owner_engine, "isolation", ticketing.url, inventory_server.url)
    other_eng, other_sup = login(client, other, "support_engineer"), login(client, other, "maintenance_supervisor")
    ingest_samples(client, other_eng)
    mine, theirs = docs(client, world["eng"]), docs(client, other_eng)
    assert delete(client, other_sup, mine[LOG]).status_code == 404  # another tenant's id: not found, not forbidden
    assert delete(client, other_sup, str(uuid.uuid4())).status_code == 404
    assert LOG in docs(client, world["eng"])
    assert delete(client, world["sup"], mine[LOG]).status_code == 200
    assert delete(client, other_sup, mine[LOG]).status_code == 404  # the other tenant cannot learn that it was deleted
    assert client.get(f"/api/v1/documents/{mine[LOG]}", headers=other_eng).status_code == 404
    assert worker.drain(worker_db, FAST) == ["cleanup_completed"]
    assert docs(client, other_eng)[LOG] == theirs[LOG] and any(h["filename"] == LOG for h in hits(client, other_eng, LOG_QUERY))  # the other tenant's copy is untouched
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d", d=theirs[LOG])[0][0] > 0
    assert sql(owner_engine, "SELECT count(*) FROM audit_events WHERE tenant_id = :t AND action LIKE 'document.%delet%'", t=other.id)[0][0] == 0


def test_forged_and_orphaned_cleanup_events_delete_nothing(client, world, owner_engine, worker_db, ticketing, inventory_server):
    other = make_tenant(owner_engine, "forge", ticketing.url, inventory_server.url)
    ingest_samples(client, login(client, other, "support_engineer"))
    mine = docs(client, world["eng"])
    theirs_id = sql(owner_engine, "SELECT id FROM documents WHERE tenant_id = :t AND filename = :f", t=other.id, f=LOG)[0][0]
    count = lambda d: sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d", d=str(d))[0][0]  # noqa: E731
    before_mine, before_theirs = count(mine[LOG]), count(theirs_id)
    with owner_engine.begin() as c:
        # 1: an event of THIS tenant naming ANOTHER tenant's document; 2: this tenant's own document that is still ACTIVE; 3: an id that exists nowhere
        for tenant, aggregate in ((world["t"].id, str(theirs_id)), (world["t"].id, mine[LOG]), (world["t"].id, str(uuid.uuid4()))):
            c.execute(text("INSERT INTO outbox_events (tenant_id, topic, aggregate_id, status) VALUES (:t, 'document.cleanup', :a, 'pending')"), {"t": tenant, "a": aggregate})
    assert worker.drain(worker_db, FAST) == ["cleanup_refused"] * 3
    assert count(mine[LOG]) == before_mine and count(theirs_id) == before_theirs and LOG in docs(client, world["eng"])
    assert sql(owner_engine, "SELECT count(*) FROM outbox_events WHERE topic = 'document.cleanup' AND status = 'dead'")[0][0] >= 3


def test_the_worker_role_sees_document_artifacts_only_inside_its_tenant_context(world, worker_db, owner_engine, client, ticketing, inventory_server):
    other = make_tenant(owner_engine, "wrole", ticketing.url, inventory_server.url)
    ingest_samples(client, login(client, other, "support_engineer"))
    with worker_db.session() as s:  # no tenant context: nothing is visible and nothing can be deleted
        assert s.execute(text("SELECT count(*) FROM document_chunks")).scalar() == 0
        assert s.execute(text("DELETE FROM document_chunks")).rowcount == 0
    with worker_db.session(tenant_id=world["t"].id) as s:
        assert s.execute(text("SELECT count(DISTINCT tenant_id) FROM document_chunks")).scalar() == 1
        assert s.execute(text("SELECT count(*) FROM document_chunks WHERE tenant_id = :o"), {"o": other.id}).scalar() == 0
    with worker_db.session(tenant_id=world["t"].id) as s, pytest.raises(ProgrammingError):  # column-level privileges: it can record a cleanup, never delete or revive a document
        s.execute(text("UPDATE documents SET lifecycle_status = 'active'"))
        s.commit()


# ---------------------------------------------------------------------------------------------------------------------------- failure and recovery
def test_a_failure_in_stage_a_rolls_everything_back(world, client, app_db, owner_engine, monkeypatch):
    ids = docs(client, world["eng"])
    monkeypatch.setattr(lifecycle.audit, "record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("injected audit failure")))
    with app_db.session(tenant_id=world["t"].id, user_id=str(uuid.uuid4())) as s:
        with pytest.raises(RuntimeError):
            lifecycle.delete_document(s, tenant_id=world["t"].id, user_id=uuid.uuid4(), document_id=ids[LOG])
        s.rollback()
    assert sql(owner_engine, "SELECT lifecycle_status, cleanup_state FROM documents WHERE id = :d", d=ids[LOG])[0] == ("active", None)
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d AND is_current", d=ids[LOG])[0][0] > 0
    assert sql(owner_engine, "SELECT count(*) FROM outbox_events WHERE topic = 'document.cleanup' AND aggregate_id = :d", d=ids[LOG])[0][0] == 0
    assert LOG in docs(client, world["eng"])


def test_a_partial_cleanup_failure_rolls_back_retries_and_then_completes(client, world, owner_engine, worker_db, monkeypatch):
    ids = docs(client, world["eng"])
    delete(client, world["sup"], ids[LOG])
    chunks = sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d", d=ids[LOG])[0][0]
    real = lifecycle.audit.record
    monkeypatch.setattr(lifecycle.audit, "record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("injected failure after the deletes")))
    assert worker.drain(worker_db, FAST, max_iterations=1) == ["cleanup_retry_scheduled"]
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d", d=ids[LOG])[0][0] == chunks  # the deletes were rolled back with the failure
    assert sql(owner_engine, "SELECT cleanup_state FROM documents WHERE id = :d", d=ids[LOG])[0][0] == "pending"
    event = sql(owner_engine, "SELECT status, attempts, last_error FROM outbox_events WHERE topic = 'document.cleanup' AND aggregate_id = :d", d=ids[LOG])[0]
    assert event == ("pending", 1, "RuntimeError")  # only the error CLASS is stored
    monkeypatch.setattr(lifecycle.audit, "record", real)
    assert worker.drain(worker_db, FAST) == ["cleanup_completed"]
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d", d=ids[LOG])[0][0] == 0


def test_exhausted_retries_record_a_failure_and_a_repeated_delete_requeues_it(client, world, owner_engine, worker_db, monkeypatch):
    ids = docs(client, world["eng"])
    delete(client, world["sup"], ids[LOG])
    real = lifecycle.audit.record

    def failing(session, **kw):
        if kw.get("action") == "document.cleanup_completed":
            raise RuntimeError("injected")
        return real(session, **kw)

    monkeypatch.setattr(lifecycle.audit, "record", failing)
    assert worker.drain(worker_db, FAST) == ["cleanup_retry_scheduled", "cleanup_retry_scheduled", "cleanup_failed"]
    assert sql(owner_engine, "SELECT cleanup_state FROM documents WHERE id = :d", d=ids[LOG])[0][0] == "failed"
    failed = sql(owner_engine, "SELECT details FROM audit_events WHERE action = 'document.cleanup_failed' AND entity_id = :d", d=ids[LOG])
    assert len(failed) == 1 and set(failed[0][0]) == {"outcome", "cleanup_state", "error_class"}
    assert LOG not in docs(client, world["eng"])  # a failed cleanup never makes the content visible again
    monkeypatch.setattr(lifecycle.audit, "record", real)
    again = delete(client, world["sup"], ids[LOG]).json()
    assert again["already_deleted"] is True and again["cleanup_state"] == "pending"  # the repeat is the retry
    assert worker.drain(worker_db, FAST) == ["cleanup_completed"]
    assert sql(owner_engine, "SELECT count(*) FROM audit_events WHERE action = 'document.cleanup_requeued' AND entity_id = :d", d=ids[LOG])[0][0] == 1


def test_an_interrupted_worker_loses_nothing_the_lease_expires_and_the_event_is_reclaimed(client, world, owner_engine, worker_db):
    ids = docs(client, world["eng"])
    delete(client, world["sup"], ids[LOG])
    claimed = worker._claim(worker_db, FAST, lifecycle.CLEANUP_TOPIC)  # a worker takes the event and "crashes": nothing else happens
    assert claimed is not None
    assert worker.process_cleanup_one(worker_db, FAST) is None  # while the lease is valid nobody else takes it
    with owner_engine.begin() as c:
        c.execute(text("UPDATE outbox_events SET locked_until = now() - interval '1 minute' WHERE id = :i"), {"i": claimed[0]})
    assert worker.process_cleanup_one(worker_db, FAST) == "cleanup_completed"
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d", d=ids[LOG])[0][0] == 0


def test_no_content_files_exist_so_cleanup_has_no_storage_references_to_get_wrong():
    """Documents are stored only as database rows (versions and chunks); there is no file store, so there are no content files or storage paths to leak or leave behind."""
    from app.models import Document, DocumentVersion
    assert not [c for c in list(Document.__table__.columns) + list(DocumentVersion.__table__.columns) if any(w in c.name for w in ("path", "uri", "url", "blob", "file_ref"))]
