"""Batch 10, Checkpoints B and C: recoverable ingestion from retained original content, genuine source reprocessing, and the deletion interaction.

All failures are CONTROLLED INJECTIONS on the isolated test database (a patched embedder, a process "crash" raised as a BaseException, owner-level SQL that removes or damages stored bytes);
none of them is a real infrastructure outage."""
import hashlib
import threading

import pytest
from app.ingestion import jobs, lifecycle, sources
from app.workflows import worker
from starlette.testclient import TestClient
from support import SAMPLE_KINDS, SAMPLES, login, make_tenant
from test_ingestion_jobs import (  # noqa: F401
    FAST,
    NOTE,
    Crash,
    db_clean,
    expire_lease,
    fail_embedding,
    hits,
    job_list,
    make_due,
    run,
    sql,
    upload,
    world,
)


def source_rows(owner_engine, tenant, where=""):
    return sql(owner_engine, f"SELECT id, document_id, version FROM document_sources WHERE tenant_id = :t {where}", t=tenant)


def csv_upload(client, world):
    r = client.post("/api/v1/documents", headers=world["eng"], data={"kind": SAMPLE_KINDS["maintenance_log.csv"]}, files={"file": ("maintenance_log.csv", (SAMPLES / "maintenance_log.csv").read_bytes())})
    assert r.status_code == 201
    return r.json()["document_id"]


# ------------------------------------------------------------------------------------------------------------------------- B: recoverable initial ingestion
def test_a_successful_upload_retains_the_original_linked_to_its_version_and_the_response_is_unchanged(client, world, owner_engine):
    r = upload(client, world["eng"])
    assert r.status_code == 201 and set(r.json()) == {"document_id", "version", "chunk_count", "status"}
    rows = sql(owner_engine, "SELECT s.document_id::text, s.version, s.content_hash, s.size_bytes, v.source_id = s.id, s.content FROM document_sources s JOIN document_versions v ON v.document_id = s.document_id "
                             "WHERE s.document_id = :d", d=r.json()["document_id"])
    assert len(rows) == 1 and rows[0][1] == 1 and rows[0][2] == hashlib.sha256(NOTE).hexdigest() and rows[0][3] == len(NOTE) and rows[0][4] is True and bytes(rows[0][5]) == NOTE
    assert "content" not in str(client.get(f"/api/v1/documents/{r.json()['document_id']}", headers=world["eng"]).json()).lower().replace("content_", "")  # the API never returns the bytes


def test_an_interrupted_upload_after_the_source_was_saved_is_completed_by_the_worker_from_the_source(client, world, owner_engine, worker_db, monkeypatch):
    def die(*args, **kwargs):
        raise Crash()  # the API process dies after the job and the source were committed, before indexing
    monkeypatch.setattr(jobs, "embed_segments", die)
    with pytest.raises(BaseException):  # noqa: B017 - the simulated process death surfaces from the ASGI stack (possibly wrapped in an exception group)
        upload(client, world["eng"])
    monkeypatch.undo()
    assert sql(owner_engine, "SELECT status, payload IS NULL FROM ingestion_jobs WHERE status = 'PROCESSING'") == [("PROCESSING", True)]
    assert len(source_rows(owner_engine, world["t"].id)) == 1 and not [d for d in client.get("/api/v1/documents", headers=world["eng"]).json()["items"] if d["filename"] == "gasket.txt"]
    assert worker.drain(worker_db, FAST) == []  # the lease is still valid: nobody else touches it
    expire_lease(owner_engine)
    assert worker.drain(worker_db, FAST) == ["ingestion_completed"]  # worker restart: reclaimed, original re-read and re-parsed
    assert any(h["filename"] == "gasket.txt" for h in hits(client, world["eng"]))
    assert source_rows(owner_engine, world["t"].id, "AND document_id IS NOT NULL")[0][2] == 1 and not source_rows(owner_engine, world["t"].id, "AND document_id IS NULL")


def test_a_source_persistence_failure_accepts_nothing(client, world, owner_engine, monkeypatch):
    before = sql(owner_engine, "SELECT (SELECT count(*) FROM ingestion_jobs), (SELECT count(*) FROM document_sources), (SELECT count(*) FROM documents)")
    def boom(*a, **k):
        raise RuntimeError("injected storage failure")
    monkeypatch.setattr(sources, "store", boom)
    r = upload(TestClient(client.app, raise_server_exceptions=False), world["eng"])
    assert r.status_code >= 500 and "injected" not in r.text  # an error, never a success
    assert sql(owner_engine, "SELECT (SELECT count(*) FROM ingestion_jobs), (SELECT count(*) FROM document_sources), (SELECT count(*) FROM documents)") == before  # no job, no source, no document
    monkeypatch.undo()
    assert upload(client, world["eng"]).json()["status"] == "created"  # and the same upload works once storage is back


def test_a_parse_failure_is_permanent_and_stores_no_content(client, world, owner_engine):
    before = len(source_rows(owner_engine, world["t"].id))
    r = upload(client, world["eng"], name="empty.txt", data=b"   ")
    assert r.status_code == 422 or r.status_code == 400
    assert len(source_rows(owner_engine, world["t"].id)) == before
    assert job_list(client, world["eng"])[0]["status"] == "FAILED"


def test_an_unresolved_first_upload_is_never_reported_as_a_duplicate(client, world, owner_engine, monkeypatch):
    fail_embedding(monkeypatch)
    assert upload(client, world["eng"]).status_code == 503
    assert upload(client, world["eng"]).status_code == 503  # the same content again while the first is unresolved: still not indexed, still 503, never "duplicate"
    assert len(job_list(client, world["eng"], job_type="ingest")) == 1 and len(source_rows(owner_engine, world["t"].id)) == 1  # one job, one retained original


def test_fi09_concurrent_identical_uploads_resolve_to_one_document_and_one_source(client, world, owner_engine):
    data = b"Concurrent Batch 10 note. Torque the cover bolts to 35 Nm. Marker 77310."
    results = []

    def go(i):
        c = TestClient(client.app)
        r = c.post("/api/v1/documents", headers=world["eng"], data={"kind": "other"}, files={"file": (f"b10-{i}.txt", data)})
        results.append((r.status_code, r.json().get("status")))
    threads = [threading.Thread(target=go, args=(i,)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert all(code == 201 for code, _ in results) and [s for _, s in results].count("created") == 1 and [s for _, s in results].count("duplicate") == 5
    h = hashlib.sha256(data).hexdigest()
    assert sql(owner_engine, "SELECT count(*) FROM document_versions WHERE tenant_id = :t AND content_hash = :h", t=world["t"].id, h=h)[0][0] == 1
    assert sql(owner_engine, "SELECT count(*) FROM document_sources WHERE tenant_id = :t AND content_hash = :h", t=world["t"].id, h=h)[0][0] == 1  # the losers kept no copy


def test_a_new_version_retains_its_own_original_and_older_versions_keep_theirs(client, world, owner_engine):
    upload(client, world["eng"])
    r = upload(client, world["eng"], data=NOTE + b" Second edition.")
    assert r.json()["status"] == "new_version"
    assert [row[2] for row in source_rows(owner_engine, world["t"].id, "ORDER BY version")] == [1, 2]


def test_a_failed_upload_can_be_retried_without_uploading_again_and_never_duplicates(client, world, owner_engine, worker_db, monkeypatch):
    real = fail_embedding(monkeypatch)
    upload(client, world["eng"])
    run(owner_engine, "UPDATE ingestion_jobs SET attempts = max_attempts - 1 WHERE status = 'RETRY_PENDING'")
    make_due(owner_engine)
    assert worker.drain(worker_db, FAST) == ["ingestion_failed"]
    job = job_list(client, world["eng"])[0]
    assert job["status"] == "FAILED" and job["error_code"] == "retries_exhausted"
    from app.ai import embeddings
    monkeypatch.setattr(embeddings.DeterministicEmbedder, "embed", real)
    assert client.post(f"/api/v1/ingestion/jobs/{job['id']}/retry", headers=world["sup"]).status_code == 202
    assert client.post(f"/api/v1/ingestion/jobs/{job['id']}/retry", headers=world["sup"]).status_code == 409  # not failed any more: no double re-queue
    assert worker.drain(worker_db, FAST) == ["ingestion_completed"]
    assert sql(owner_engine, "SELECT count(*) FROM documents WHERE tenant_id = :t AND filename = 'gasket.txt'", t=world["t"].id)[0][0] == 1
    assert upload(client, world["eng"]).json()["status"] == "duplicate"


# ------------------------------------------------------------------------------------------------------------------------- C: genuine source reprocessing
def test_reprocessing_re_parses_the_retained_original_and_does_not_reuse_the_old_chunks(client, world, owner_engine, worker_db):
    doc = csv_upload(client, world)
    first = sql(owner_engine, "SELECT chunk_index, text, page_number, record_id FROM document_chunks WHERE document_id = :d AND generation = 1 ORDER BY chunk_index", d=doc)
    run(owner_engine, "UPDATE document_chunks SET text = 'TAMPERED stored chunk text' WHERE document_id = :d", d=doc)  # the stored chunks no longer equal the original
    assert client.post(f"/api/v1/documents/{doc}/reprocess", headers=world["sup"]).status_code == 202
    assert worker.drain(worker_db, FAST) == ["ingestion_completed"]
    second = sql(owner_engine, "SELECT chunk_index, text, page_number, record_id FROM document_chunks WHERE document_id = :d AND generation = 2 AND is_current ORDER BY chunk_index", d=doc)
    assert second == first and not [r for r in second if "TAMPERED" in r[1]]  # the new generation came from the ORIGINAL file, record identifiers included
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d AND is_current AND generation = 1", d=doc)[0][0] == 0
    assert sql(owner_engine, "SELECT active_generation, chunk_count FROM document_versions WHERE document_id = :d", d=doc)[0] == (2, len(first))


def test_a_historical_document_without_a_retained_original_gets_an_explicit_refusal(client, world, owner_engine):
    doc = upload(client, world["eng"]).json()["document_id"]
    run(owner_engine, "UPDATE document_versions SET source_id = NULL WHERE document_id = :d", d=doc)  # as if uploaded before source storage existed
    run(owner_engine, "DELETE FROM document_sources WHERE document_id = :d", d=doc)
    r = client.post(f"/api/v1/documents/{doc}/reprocess", headers=world["sup"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "source_not_retained" and "original file" in r.json()["error"]["message"]
    assert any(h["filename"] == "gasket.txt" for h in hits(client, world["eng"])) and sql(owner_engine, "SELECT count(*) FROM ingestion_jobs WHERE job_type = 'reprocess' AND document_id = :d", d=doc)[0][0] == 0


def test_missing_or_corrupted_originals_fail_reprocessing_permanently_and_keep_the_active_generation(client, world, owner_engine, worker_db):
    doc = csv_upload(client, world)
    before = sql(owner_engine, "SELECT id FROM document_chunks WHERE document_id = :d AND is_current ORDER BY id", d=doc)
    run(owner_engine, "UPDATE document_sources SET content = overlay(content placing 'X'::bytea from 3 for 1) WHERE document_id = :d", d=doc)  # simulated bit rot
    assert client.post(f"/api/v1/documents/{doc}/reprocess", headers=world["sup"]).status_code == 202
    assert worker.drain(worker_db, FAST) == ["ingestion_failed"]
    job = job_list(client, world["eng"], job_type="reprocess")[0]
    assert job["status"] == "FAILED" and job["error_code"] == "source_corrupted" and job["attempts"] == 1  # permanent: not retried
    run(owner_engine, "DELETE FROM document_sources WHERE document_id = :d", d=doc)  # now missing altogether
    assert client.post(f"/api/v1/ingestion/jobs/{job['id']}/retry", headers=world["sup"]).status_code == 202
    assert worker.drain(worker_db, FAST) == ["ingestion_failed"]
    assert client.get(f"/api/v1/ingestion/jobs/{job['id']}", headers=world["eng"]).json()["error_code"] == "source_missing"
    assert sql(owner_engine, "SELECT id FROM document_chunks WHERE document_id = :d AND is_current ORDER BY id", d=doc) == before  # previously usable content untouched
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d AND generation = 2", d=doc)[0][0] == 0
    assert hits(client, world["eng"], "maintenance")


def test_reprocessing_with_the_embedder_down_keeps_serving_the_old_generation_then_recovers(client, world, owner_engine, worker_db, monkeypatch):
    doc = csv_upload(client, world)
    real = fail_embedding(monkeypatch)
    assert client.post(f"/api/v1/documents/{doc}/reprocess", headers=world["sup"]).status_code == 202
    assert worker.drain(worker_db, FAST, max_iterations=1) == ["ingestion_retry_scheduled"]
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d AND generation = 2", d=doc)[0][0] == 0
    from app.ai import embeddings
    monkeypatch.setattr(embeddings.DeterministicEmbedder, "embed", real)
    make_due(owner_engine)
    assert worker.drain(worker_db, FAST) == ["ingestion_completed"]
    assert sql(owner_engine, "SELECT active_generation FROM document_versions WHERE document_id = :d", d=doc)[0][0] == 2


# ------------------------------------------------------------------------------------------------------------------------- deletion integration
def test_deletion_during_ingestion_cancels_the_job_removes_its_source_and_retry_cannot_recreate_content(client, world, owner_engine, worker_db, monkeypatch):
    doc = upload(client, world["eng"]).json()["document_id"]
    real = fail_embedding(monkeypatch)
    assert upload(client, world["eng"], data=NOTE + b" Second edition.").status_code == 503  # a new version waits for a retry (job tied to the document)
    pending = job_list(client, world["eng"], status="RETRY_PENDING")[0]
    assert len(source_rows(owner_engine, world["t"].id, "AND document_id IS NULL")) == 1
    assert client.delete(f"/api/v1/documents/{doc}", headers=world["sup"]).status_code == 200
    assert client.get(f"/api/v1/ingestion/jobs/{pending['id']}", headers=world["eng"]).json()["status"] == "CANCELLED"
    assert not source_rows(owner_engine, world["t"].id, "AND document_id IS NULL")  # the unlinked original of the cancelled job is gone at once
    from app.ai import embeddings
    monkeypatch.setattr(embeddings.DeterministicEmbedder, "embed", real)
    make_due(owner_engine)
    assert worker.drain(worker_db, FAST) == ["cleanup_completed"]  # only the cleanup runs: the cancelled job is never retried
    assert client.post(f"/api/v1/ingestion/jobs/{pending['id']}/retry", headers=world["sup"]).status_code == 409
    assert not source_rows(owner_engine, world["t"].id) and client.get(f"/api/v1/documents/{doc}", headers=world["eng"]).status_code == 404


def test_cleanup_removes_every_retained_original_of_the_document_and_reports_it(client, world, owner_engine, worker_db):
    doc = upload(client, world["eng"]).json()["document_id"]
    upload(client, world["eng"], data=NOTE + b" Second edition.")
    assert len(source_rows(owner_engine, world["t"].id, f"AND document_id = '{doc}'")) == 2
    client.delete(f"/api/v1/documents/{doc}", headers=world["sup"])
    assert len(source_rows(owner_engine, world["t"].id)) == 2  # stage A is logical: physical removal is the worker's cleanup
    assert worker.drain(worker_db, FAST) == ["cleanup_completed"]
    assert not source_rows(owner_engine, world["t"].id) and sql(owner_engine, "SELECT count(*) FROM document_sources WHERE content = :c AND tenant_id = :t", c=NOTE, t=world["t"].id)[0][0] == 0
    details = sql(owner_engine, "SELECT details FROM audit_events WHERE action = 'document.cleanup_completed' AND entity_id = :d", d=doc)[0][0]
    assert details["sources_removed"] == 2 and "gasket" not in str(details).lower() and "zebra" not in str(details)  # audited without content


def test_a_failed_cleanup_rolls_back_keeps_the_originals_and_a_retry_completes(client, world, owner_engine, worker_db, monkeypatch):
    doc = upload(client, world["eng"]).json()["document_id"]
    client.delete(f"/api/v1/documents/{doc}", headers=world["sup"])
    real = lifecycle.audit.record
    monkeypatch.setattr(lifecycle.audit, "record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("injected failure after the deletes")))
    assert worker.drain(worker_db, FAST, max_iterations=1) == ["cleanup_retry_scheduled"]
    assert len(source_rows(owner_engine, world["t"].id)) == 1  # rolled back with the failure: nothing half removed
    monkeypatch.setattr(lifecycle.audit, "record", real)
    assert worker.drain(worker_db, FAST) == ["cleanup_completed"] and not source_rows(owner_engine, world["t"].id)


def test_cleanup_of_an_old_document_never_touches_a_replacement_upload_or_another_tenant(client, world, owner_engine, worker_db):
    other = make_tenant(owner_engine, "b10other")
    other_client_hdr = login(client, other, "support_engineer")
    theirs = upload(client, other_client_hdr).json()["document_id"]  # identical bytes and file name in ANOTHER tenant
    doc = upload(client, world["eng"]).json()["document_id"]
    client.delete(f"/api/v1/documents/{doc}", headers=world["sup"])
    new = upload(client, world["eng"]).json()  # same bytes again before the old cleanup ran: a NEW document, not a duplicate
    assert new["status"] == "created" and new["document_id"] != doc
    assert worker.drain(worker_db, FAST) == ["cleanup_completed"]
    assert [r[1] for r in source_rows(owner_engine, world["t"].id)] == [__import__("uuid").UUID(new["document_id"])]  # the replacement keeps its original
    assert [str(r[1]) for r in source_rows(owner_engine, other.id)] == [theirs]  # the other tenant's original is untouched
    assert any(h["filename"] == "gasket.txt" for h in hits(client, world["eng"]))


def test_a_reprocess_job_queued_before_deletion_is_cancelled_and_cannot_activate_a_generation(client, world, owner_engine, worker_db):
    doc = csv_upload(client, world)
    job = client.post(f"/api/v1/documents/{doc}/reprocess", headers=world["sup"]).json()
    client.delete(f"/api/v1/documents/{doc}", headers=world["sup"])
    assert client.get(f"/api/v1/ingestion/jobs/{job['id']}", headers=world["eng"]).json()["status"] == "CANCELLED"
    assert worker.drain(worker_db, FAST) == ["cleanup_completed"]
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d", d=doc)[0][0] == 0 and not source_rows(owner_engine, world["t"].id)


def test_forged_source_identifiers_in_a_job_find_nothing(client, world, owner_engine, worker_db, monkeypatch):
    other = make_tenant(owner_engine, "b10forge")
    theirs = upload(client, login(client, other, "support_engineer"), data=b"Other tenant confidential original. Marker forge-4411.").json()["document_id"]
    foreign_source = sql(owner_engine, "SELECT id::text FROM document_sources WHERE document_id = :d", d=theirs)[0][0]
    fail_embedding(monkeypatch)
    upload(client, world["eng"])
    run(owner_engine, "UPDATE ingestion_jobs SET source_id = :s WHERE tenant_id = :t AND status = 'RETRY_PENDING'", s=foreign_source, t=world["t"].id)  # a forged identifier belonging to another tenant
    monkeypatch.undo()
    make_due(owner_engine)
    assert worker.drain(worker_db, FAST) == ["ingestion_failed"]
    assert job_list(client, world["eng"])[0]["error_code"] == "source_missing"  # RLS and the tenant predicate: the other tenant's bytes were never read
    assert sql(owner_engine, "SELECT count(*) FROM document_sources WHERE id = :s", s=foreign_source)[0][0] == 1  # and not deleted either
    assert not any("forge-4411" in h["text"] for h in hits(client, world["eng"], "forge-4411 confidential"))
