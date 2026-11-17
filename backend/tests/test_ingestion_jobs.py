"""V41-12.03 and V41-12.04: durable ingestion jobs, bounded retry, safe recovery and controlled reprocessing.

Real failure paths, not only success: the embedding model is made to fail (transient), content is made invalid (permanent), workers are "crashed" with a BaseException at each stage of
processing (the lease then expires and the job is reclaimed), claims race in threads, stale claim tokens try to overwrite newer state, and deletion races with ingestion and reprocessing.
Everything runs on the isolated `eaop_test` database with the deterministic embedder and the existing mock services."""
import threading
import uuid

import pytest
from app.ai import embeddings
from app.ai.embeddings import get_embedder
from app.ai.safeguards import verify_citation_sources
from app.ingestion import jobs, lifecycle
from app.workflows import worker
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from support import SAMPLE_KINDS, SAMPLES, ingest_samples, login, make_tenant

EMB = get_embedder("deterministic")
FAST = worker.WorkerConfig(backoff_base=0, backoff_cap=0, http_timeout=1.0, max_attempts=3, embedder=EMB)
NOTE = b"REL note: the gasket on pump P-101 must be replaced when it weeps; torque bolts to 40 Nm. Distinctive phrase zebra-quartz-9141."
QUERY = "gasket weeps torque bolts zebra-quartz-9141"


class Crash(BaseException):
    """A worker process dying: not an Exception, so no handler in the code under test can swallow it."""


def sql(owner_engine, query, **params):
    with owner_engine.connect() as c:
        return c.execute(text(query), params).all()


def run(owner_engine, query, **params):
    with owner_engine.begin() as c:
        c.execute(text(query), params)


def upload(client, hdr, name="gasket.txt", data=NOTE, kind="other"):
    return client.post("/api/v1/documents", headers=hdr, data={"kind": kind}, files={"file": (name, data)})


def job_list(client, hdr, **params):
    return client.get("/api/v1/ingestion/jobs", headers=hdr, params={"limit": 100, **params}).json()["items"]


def make_due(owner_engine):
    run(owner_engine, "UPDATE ingestion_jobs SET next_attempt_at = now() - interval '1 second' WHERE status IN ('QUEUED', 'RETRY_PENDING')")


def expire_lease(owner_engine):
    run(owner_engine, "UPDATE ingestion_jobs SET locked_until = now() - interval '1 second' WHERE status = 'PROCESSING'")


def fail_embedding(monkeypatch):
    real = embeddings.DeterministicEmbedder.embed
    monkeypatch.setattr(embeddings.DeterministicEmbedder, "embed", lambda self, texts: (_ for _ in ()).throw(RuntimeError("model file could not be loaded /secret/path")))
    return real


def hits(client, hdr, query=QUERY):
    return client.post("/api/v1/search", headers=hdr, json={"query": query, "k": 8}).json()["items"]


@pytest.fixture()
def world(client, apex, ticketing, db_clean):  # noqa: F811
    login_ = {r: login(client, apex, r) for r in ("support_engineer", "maintenance_supervisor", "tenant_admin", "read_only_auditor")}
    return {"t": apex, "eng": login_["support_engineer"], "sup": login_["maintenance_supervisor"], "adm": login_["tenant_admin"], "aud": login_["read_only_auditor"]}


@pytest.fixture()
def db_clean(owner_engine):
    run(owner_engine, "UPDATE ingestion_jobs SET status = 'CANCELLED', claim_token = NULL, locked_until = NULL, payload = NULL, completed_at = now() WHERE status IN ('QUEUED', 'PROCESSING', 'RETRY_PENDING')")


# ---------------------------------------------------------------------------------------------------------------------------- job creation, success, compatibility
def test_an_upload_is_a_durable_job_and_the_public_contract_is_unchanged(client, world, owner_engine):
    r = upload(client, world["eng"])
    assert r.status_code == 201 and set(r.json()) == {"document_id", "version", "chunk_count", "status"} and r.json()["status"] == "created"
    jobs_ = job_list(client, world["eng"], job_type="ingest")
    assert len(jobs_) == 1
    job = jobs_[0]
    assert job["status"] == "COMPLETED" and job["outcome"] == "created" and job["attempts"] == 1 and job["max_attempts"] == 5 and job["document_id"] == r.json()["document_id"]
    assert job["chunks"] == r.json()["chunk_count"] and job["error_code"] is None and job["completed_at"] and job["filename"] == "gasket.txt"
    assert job["processing_config"]["embedding_backend"] == "deterministic" and len(job["processing_config"]["safety_heuristics"]) == 10
    assert client.get(f"/api/v1/ingestion/jobs/{job['id']}", headers=world["eng"]).json() == job
    row = sql(owner_engine, "SELECT payload, claim_token, locked_until, attempts, document_id FROM ingestion_jobs WHERE id = :i", i=job["id"])[0]
    assert row[0] is None and row[1] is None and row[2] is None  # no content and no lease remain on a finished job
    actions = [a["action"] for a in client.get("/api/v1/audit", headers=world["aud"], params={"entity_id": job["id"]}).json()["items"]]
    assert sorted(actions) == ["ingestion.attempt_started", "ingestion.job_completed", "ingestion.job_created"]
    again = upload(client, world["eng"])
    assert again.status_code == 201 and again.json()["status"] == "duplicate" and len(job_list(client, world["eng"], job_type="ingest")) == 1  # a duplicate needs no job
    changed = upload(client, world["eng"], data=NOTE + b" Second edition.")
    assert changed.json()["status"] == "new_version" and changed.json()["version"] == 2


def test_permanent_failures_are_recorded_once_and_never_retried(client, world, owner_engine, worker_db):
    before = len(job_list(client, world["eng"]))
    r = upload(client, world["eng"], name="empty.txt", data=b"   \n")
    assert r.status_code == 422 and r.json()["error"]["code"] == "empty_document"  # the same error as before
    failed = [j for j in job_list(client, world["eng"]) if j["status"] == "FAILED"]
    assert len(job_list(client, world["eng"])) == before + 1 and failed[0]["error_code"] == "empty_document" and failed[0]["attempts"] == 1 and failed[0]["filename"] == "empty.txt"
    assert worker.drain(worker_db, FAST) == []  # nothing to retry
    unsupported = upload(client, world["eng"], name="tool.exe", data=b"MZ")
    assert unsupported.status_code == 415  # rejected before parsing, exactly as before (no job: it is a request error)


# ---------------------------------------------------------------------------------------------------------------------------- transient failure, retry, exhaustion
def test_a_transient_failure_keeps_the_contract_queues_a_retry_and_the_worker_completes_it(client, world, owner_engine, worker_db, monkeypatch):
    chunks_before = client.get("/api/v1/ingestion/status", headers=world["eng"]).json()["chunks"]
    real = fail_embedding(monkeypatch)
    r = upload(client, world["eng"])
    assert r.status_code == 503 and r.json()["error"]["code"] == "embedding_unavailable" and r.headers["Retry-After"] and "secret" not in r.text  # unchanged contract
    job = job_list(client, world["eng"])[0]
    assert job["status"] == "RETRY_PENDING" and job["attempts"] == 1 and job["error_code"] == "embedding_unavailable" and job["next_attempt_at"] and job["document_id"] is None
    assert "secret" not in str(job) and job["error_detail"] == "The embedding model was unavailable"  # a fixed message, never the exception text
    assert sql(owner_engine, "SELECT payload IS NULL AND source_id IS NOT NULL FROM ingestion_jobs WHERE id = :i", i=job["id"])[0][0] is True  # the ORIGINAL is retained, not parsed text
    assert client.get("/api/v1/ingestion/status", headers=world["eng"]).json()["chunks"] == chunks_before and "gasket.txt" not in [d["filename"] for d in client.get("/api/v1/documents", headers=world["eng"]).json()["items"]]
    assert not hits(client, world["eng"]) or all(h["filename"] != "gasket.txt" for h in hits(client, world["eng"]))
    make_due(owner_engine)
    assert worker.drain(worker_db, FAST, max_iterations=1) == ["ingestion_retry_scheduled"]  # still failing: rescheduled with backoff, not retried in a loop
    monkeypatch.setattr(embeddings.DeterministicEmbedder, "embed", real)
    make_due(owner_engine)
    assert worker.drain(worker_db, FAST) == ["ingestion_completed"]
    done = client.get(f"/api/v1/ingestion/jobs/{job['id']}", headers=world["eng"]).json()
    assert done["status"] == "COMPLETED" and done["attempts"] == 3 and done["outcome"] == "created" and done["document_id"]
    assert any(h["filename"] == "gasket.txt" for h in hits(client, world["eng"]))
    linked = sql(owner_engine, "SELECT s.document_id::text, s.version, v.source_id = s.id FROM ingestion_jobs j JOIN document_sources s ON s.id = j.source_id JOIN document_versions v ON v.document_id = s.document_id WHERE j.id = :i", i=job["id"])
    assert linked == [(done["document_id"], 1, True)]  # the retained original now belongs to the version that was created from it
    assert upload(client, world["eng"]).json()["status"] == "duplicate"  # idempotent: nothing was stored twice
    actions = [a["action"] for a in client.get("/api/v1/audit", headers=world["aud"], params={"entity_id": job["id"], "limit": 50}).json()["items"]]
    assert actions.count("ingestion.retry_scheduled") == 2 and actions.count("ingestion.attempt_started") == 3 and actions.count("ingestion.job_completed") == 1


def test_a_repeated_upload_resumes_the_same_job_after_a_transient_failure(client, world, owner_engine, monkeypatch):
    real = fail_embedding(monkeypatch)
    assert upload(client, world["eng"]).status_code == 503
    assert upload(client, world["eng"]).status_code == 503  # the client retries during the outage: still one job
    assert len(job_list(client, world["eng"], job_type="ingest")) == 1
    monkeypatch.setattr(embeddings.DeterministicEmbedder, "embed", real)
    r = upload(client, world["eng"])
    assert r.status_code == 201 and r.json()["status"] == "created"
    only = job_list(client, world["eng"], job_type="ingest")
    assert len(only) == 1 and only[0]["status"] == "COMPLETED" and only[0]["attempts"] == 3 and only[0]["document_id"] == r.json()["document_id"]


def test_retries_are_bounded_the_job_fails_with_retries_exhausted_and_the_original_is_kept_for_a_manual_retry(client, world, owner_engine, worker_db, monkeypatch):
    real = fail_embedding(monkeypatch)
    assert upload(client, world["eng"]).status_code == 503  # attempt 1
    outcomes = []
    for _ in range(10):
        make_due(owner_engine)
        got = worker.drain(worker_db, FAST)
        outcomes += got
        if not got:
            break
    assert outcomes == ["ingestion_retry_scheduled"] * 3 + ["ingestion_failed"]  # attempts 2, 3, 4 retry; attempt 5 reaches the limit
    job = job_list(client, world["eng"])[0]
    assert job["status"] == "FAILED" and job["attempts"] == 5 and job["error_code"] == "retries_exhausted" and job["completed_at"]
    assert sql(owner_engine, "SELECT payload IS NULL AND source_id IS NOT NULL FROM ingestion_jobs WHERE id = :i", i=job["id"])[0][0] is True
    assert sql(owner_engine, "SELECT count(*) FROM document_sources s JOIN ingestion_jobs j ON j.source_id = s.id WHERE j.id = :i AND s.document_id IS NULL", i=job["id"])[0][0] == 1  # kept, unlinked
    assert not [d for d in client.get("/api/v1/documents", headers=world["eng"]).json()["items"] if d["filename"] == "gasket.txt"]
    audit = [a["action"] for a in client.get("/api/v1/audit", headers=world["aud"], params={"entity_id": job["id"], "limit": 50}).json()["items"]]
    assert audit.count("ingestion.retry_scheduled") == 4 and audit.count("ingestion.job_failed") == 1
    assert client.post(f"/api/v1/ingestion/jobs/{job['id']}/retry", headers=world["eng"]).status_code == 403  # an engineer may not re-queue
    monkeypatch.setattr(embeddings.DeterministicEmbedder, "embed", real)  # the (simulated) failure is over
    retry = client.post(f"/api/v1/ingestion/jobs/{job['id']}/retry", headers=world["sup"])
    assert retry.status_code == 202 and retry.json()["status"] == "QUEUED" and retry.json()["attempts"] == 0  # no re-upload needed: the retained original is used
    assert worker.drain(worker_db, FAST) == ["ingestion_completed"]
    done = client.get(f"/api/v1/ingestion/jobs/{job['id']}", headers=world["eng"]).json()
    assert done["status"] == "COMPLETED" and done["outcome"] == "created" and any(h["filename"] == "gasket.txt" for h in hits(client, world["eng"]))


def test_a_job_whose_original_is_gone_or_corrupted_fails_permanently_without_retrying(client, world, owner_engine, worker_db, monkeypatch):
    fail_embedding(monkeypatch)
    upload(client, world["eng"])
    run(owner_engine, "DELETE FROM document_sources WHERE id IN (SELECT source_id FROM ingestion_jobs WHERE status = 'RETRY_PENDING')")  # a missing source (simulated storage loss)
    make_due(owner_engine)
    assert worker.drain(worker_db, FAST) == ["ingestion_failed"]
    job = job_list(client, world["eng"])[0]
    assert job["error_code"] == "source_missing" and job["attempts"] == 2 and worker.drain(worker_db, FAST) == []
    assert client.post(f"/api/v1/ingestion/jobs/{job['id']}/retry", headers=world["sup"]).json()["error"]["code"] == "source_not_retained"  # nothing left to retry from
    upload(client, world["eng"], name="other.txt", data=NOTE + b" second")  # a corrupted original (simulated bit rot, only the database owner can alter bytes)
    run(owner_engine, "UPDATE document_sources SET content = overlay(content placing 'X'::bytea from 3 for 1) WHERE id IN (SELECT source_id FROM ingestion_jobs WHERE status = 'RETRY_PENDING')")
    make_due(owner_engine)
    assert worker.drain(worker_db, FAST) == ["ingestion_failed"]
    assert {j["error_code"] for j in job_list(client, world["eng"])} == {"source_missing", "source_corrupted"}
    assert sql(owner_engine, "SELECT count(*) FROM document_sources s JOIN ingestion_jobs j ON j.source_id = s.id WHERE j.status = 'FAILED'")[0][0] == 0  # permanent failure keeps no content


# ---------------------------------------------------------------------------------------------------------------------------- crashes, leases, claims
def _retry_job(client, world, owner_engine, monkeypatch):
    real = fail_embedding(monkeypatch)
    upload(client, world["eng"])
    monkeypatch.setattr(embeddings.DeterministicEmbedder, "embed", real)
    make_due(owner_engine)


def test_a_worker_that_dies_after_claiming_is_recovered_when_the_lease_expires(client, world, owner_engine, worker_db, monkeypatch):
    _retry_job(client, world, owner_engine, monkeypatch)
    claimed = jobs.claim_next(worker_db, 60)
    assert claimed is not None and sql(owner_engine, "SELECT status, attempts FROM ingestion_jobs WHERE id = :i", i=claimed.id)[0] == ("PROCESSING", 2)
    assert jobs.claim_next(worker_db, 60) is None  # nobody else may take it while the lease is valid
    expire_lease(owner_engine)
    assert worker.drain(worker_db, FAST) == ["ingestion_completed"]  # the lost attempt counted (attempt 3 succeeded)
    job = job_list(client, world["eng"])[0]
    assert job["status"] == "COMPLETED" and job["attempts"] == 3
    assert [a["action"] for a in client.get("/api/v1/audit", headers=world["aud"], params={"entity_id": job["id"], "limit": 50}).json()["items"]].count("ingestion.attempt_abandoned") == 1


@pytest.mark.parametrize("stage", ["embedding", "before_final_commit", "after_final_commit"])
def test_a_crash_at_each_processing_stage_never_duplicates_chunks_or_versions(client, world, owner_engine, worker_db, monkeypatch, stage):
    _retry_job(client, world, owner_engine, monkeypatch)
    real_embed = embeddings.DeterministicEmbedder.embed
    if stage == "embedding":
        monkeypatch.setattr(embeddings.DeterministicEmbedder, "embed", lambda self, texts: (_ for _ in ()).throw(Crash()))
    elif stage == "before_final_commit":  # content written inside the transaction, then the process dies before it commits
        monkeypatch.setattr(jobs, "complete", lambda *a, **k: (_ for _ in ()).throw(Crash()))
    else:  # the transaction committed, then the process dies before it can report anything
        monkeypatch.setattr(jobs.METRICS, "observe", lambda *a, **k: (_ for _ in ()).throw(Crash()))
    with pytest.raises(Crash):
        worker.process_ingestion_one(worker_db, FAST)
    monkeypatch.undo()
    monkeypatch.setattr(embeddings.DeterministicEmbedder, "embed", real_embed)
    state = sql(owner_engine, "SELECT status FROM ingestion_jobs WHERE job_type = 'ingest' AND tenant_id = :t ORDER BY created_at DESC LIMIT 1", t=world["t"].id)[0][0]
    if stage == "after_final_commit":
        assert state == "COMPLETED" and worker.drain(worker_db, FAST) == []  # nothing left to redo
    else:
        assert state == "PROCESSING"
        assert sql(owner_engine, "SELECT count(*) FROM documents WHERE filename = 'gasket.txt' AND tenant_id = :t", t=world["t"].id)[0][0] == 0  # rolled back: no partial document
        expire_lease(owner_engine)
        assert worker.drain(worker_db, FAST) == ["ingestion_completed"]
    assert sql(owner_engine, "SELECT count(*) FROM documents WHERE filename = 'gasket.txt' AND tenant_id = :t", t=world["t"].id)[0][0] == 1
    assert sql(owner_engine, "SELECT count(*) FROM document_versions v JOIN documents d ON d.id = v.document_id WHERE d.filename = 'gasket.txt' AND d.tenant_id = :t", t=world["t"].id)[0][0] == 1
    chunks = sql(owner_engine, "SELECT count(*), count(*) FILTER (WHERE is_current) FROM document_chunks c JOIN documents d ON d.id = c.document_id WHERE d.filename = 'gasket.txt' AND d.tenant_id = :t", t=world["t"].id)[0]
    assert chunks[0] == chunks[1] >= 1
    assert len([j for j in job_list(client, world["eng"], job_type="ingest") if j["status"] == "COMPLETED"]) == 1


def test_concurrent_workers_never_claim_the_same_job(client, world, owner_engine, worker_db, monkeypatch):
    real = fail_embedding(monkeypatch)
    for i in range(4):
        upload(client, world["eng"], name=f"concurrent{i}.txt", data=NOTE + f" variant {i}".encode())
    monkeypatch.setattr(embeddings.DeterministicEmbedder, "embed", real)
    make_due(owner_engine)
    got, barrier = [], threading.Barrier(8)

    def worker_thread():
        barrier.wait()
        got.append(jobs.claim_next(worker_db, 60))

    threads = [threading.Thread(target=worker_thread) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    claimed = [c for c in got if c is not None]
    assert len(claimed) == 4 and len({c.id for c in claimed}) == 4  # four jobs, eight racing workers: each job claimed exactly once
    assert sql(owner_engine, "SELECT count(*) FROM ingestion_jobs WHERE status = 'PROCESSING' AND tenant_id = :t", t=world["t"].id)[0][0] == 4


def test_a_stale_claim_cannot_overwrite_newer_state_and_a_job_completes_exactly_once(client, world, owner_engine, worker_db, app_db, monkeypatch):
    _retry_job(client, world, owner_engine, monkeypatch)
    old = jobs.claim_next(worker_db, 60)
    expire_lease(owner_engine)
    new = jobs.claim_next(worker_db, 60)  # reclaimed by a newer worker
    assert new is not None and new.id == old.id and new.token != old.token
    tenant = world["t"].id
    assert jobs.retry_later(worker_db, tenant, old.id, old.token, "embedding_unavailable") == "stale"
    assert jobs.fail(worker_db, tenant, old.id, old.token, "unexpected_error") == "stale"
    with worker_db.session(tenant_id=tenant) as s, pytest.raises(jobs.StaleClaim):
        jobs.complete(s, old.id, old.token, outcome="created")
    assert sql(owner_engine, "SELECT status, claim_token FROM ingestion_jobs WHERE id = :i", i=new.id)[0] == ("PROCESSING", new.token)  # untouched by the stale worker
    assert jobs.execute(worker_db, old, EMB) == "stale"  # a stale worker that tries to process writes nothing
    assert sql(owner_engine, "SELECT count(*) FROM documents WHERE filename = 'gasket.txt' AND tenant_id = :t", t=world["t"].id)[0][0] == 0
    assert jobs.execute(worker_db, new, EMB) == "completed"
    assert jobs.execute(worker_db, new, EMB) == "stale"  # a finished job is never completed (or processed) again
    assert sql(owner_engine, "SELECT count(*) FROM document_versions v JOIN documents d ON d.id = v.document_id WHERE d.filename = 'gasket.txt' AND d.tenant_id = :t", t=world["t"].id)[0][0] == 1


# ---------------------------------------------------------------------------------------------------------------------------- state machine and server control
def test_the_state_machine_allows_only_the_documented_transitions_and_the_database_rejects_forged_states(client, world, owner_engine, app_db):
    job = type("J", (), {})()
    for start, bad in ((jobs.COMPLETED, jobs.PROCESSING), (jobs.FAILED, jobs.PROCESSING), (jobs.QUEUED, jobs.COMPLETED), (jobs.CANCELLED, jobs.QUEUED), (jobs.RETRY_PENDING, jobs.COMPLETED)):
        job.status = start
        with pytest.raises(jobs.InvalidJobTransition):
            jobs.set_status(job, bad)
    upload(client, world["eng"])
    jid = job_list(client, world["eng"])[0]["id"]
    for statement in ("UPDATE ingestion_jobs SET completed_at = NULL",  # completed without a time
                      "UPDATE ingestion_jobs SET status = 'PROCESSING'",  # processing without a lease
                      "UPDATE ingestion_jobs SET payload = '{}'::jsonb",  # content kept after the job ended
                      "UPDATE ingestion_jobs SET status = 'DONE'",  # unknown state
                      "UPDATE ingestion_jobs SET attempts = max_attempts + 1"):  # unbounded retries
        with owner_engine.connect() as c, pytest.raises(DBAPIError):
            c.execute(text(statement + " WHERE id = :i"), {"i": jid})
            c.commit()
    assert client.post(f"/api/v1/ingestion/jobs/{jid}/retry", headers=world["sup"]).status_code == 409  # a completed job cannot be re-run through the API
    assert not any(p.startswith("/api/v1/ingestion/jobs") and m in ("put", "patch", "delete") for p, ops in client.get("/openapi.json").json()["paths"].items() for m in ops)  # clients cannot set a state


# ---------------------------------------------------------------------------------------------------------------------------- reprocessing
def _multi(client, world):
    r = client.post("/api/v1/documents", headers=world["eng"], data={"kind": SAMPLE_KINDS["maintenance_log.csv"]}, files={"file": ("maintenance_log.csv", (SAMPLES / "maintenance_log.csv").read_bytes())})
    return r.json()["document_id"]


def test_authorised_reprocessing_builds_a_replacement_generation_and_preserves_lineage(client, world, owner_engine, worker_db):
    doc = _multi(client, world)
    old = sql(owner_engine, "SELECT id, text, chunk_index FROM document_chunks WHERE document_id = :d ORDER BY chunk_index", d=doc)
    for who in ("eng", "aud"):
        assert client.post(f"/api/v1/documents/{doc}/reprocess", headers=world[who]).status_code == 403
    r = client.post(f"/api/v1/documents/{doc}/reprocess", headers=world["sup"])
    assert r.status_code == 202
    job = r.json()
    assert job["job_type"] == "reprocess" and job["status"] == "QUEUED" and job["document_id"] == doc and job["from_generation"] == 1 and job["source_version"] == 1
    assert client.post(f"/api/v1/documents/{doc}/reprocess", headers=world["adm"]).json()["id"] == job["id"]  # duplicate request: the same active job
    assert worker.drain(worker_db, FAST) == ["ingestion_completed"]
    done = client.get(f"/api/v1/ingestion/jobs/{job['id']}", headers=world["eng"]).json()
    assert done["status"] == "COMPLETED" and done["outcome"] == "reprocessed" and done["from_generation"] == 1 and done["to_generation"] == 2 and done["chunks"] == len(old)
    detail = client.get(f"/api/v1/documents/{doc}", headers=world["eng"]).json()
    assert detail["current_version"] == 1 and len(detail["versions"]) == 1  # the logical document and its version are preserved
    gens = sql(owner_engine, "SELECT generation, count(*), count(*) FILTER (WHERE is_current) FROM document_chunks WHERE document_id = :d GROUP BY generation ORDER BY generation", d=doc)
    assert gens == [(1, len(old), 0), (2, len(old), len(old))]  # exactly one generation is current; the retired one is kept
    new = sql(owner_engine, "SELECT text, chunk_index, page_number, record_id FROM document_chunks WHERE document_id = :d AND generation = 2 ORDER BY chunk_index", d=doc)
    assert [(r[0], r[1]) for r in new] == [(r[1], r[2]) for r in old]  # same content and order: lineage preserved
    version = sql(owner_engine, "SELECT active_generation, processing_job_id FROM document_versions WHERE document_id = :d", d=doc)[0]
    assert version[0] == 2 and str(version[1]) == job["id"]
    found = [h for h in hits(client, world["eng"], "Weekly bearing inspection lubricant topped up") if h["filename"] == "maintenance_log.csv"]
    assert found and len({h["chunk_id"] for h in found}) == len(found)  # retrieval serves the new generation, no duplicates
    assert not {h["chunk_id"] for h in found} & {str(r[0]) for r in old}
    with worker_db.session(tenant_id=world["t"].id) as s:  # a historical citation of a retired chunk is still stored, but is no longer a citable current chunk
        assert verify_citation_sources(s, world["t"].id, [{"chunk_id": str(old[0][0])}])
    audit = {a["action"]: a for a in client.get("/api/v1/audit", headers=world["adm"], params={"entity_id": doc, "limit": 50}).json()["items"]}
    assert "document.reprocess_requested" in audit and "document.reprocessed" in audit and audit["document.reprocessed"]["details"]["to_generation"] == 2
    assert audit["document.reprocess_requested"]["details"]["processing_config"]["embedding_backend"] == "deterministic"
    assert lifecycle.REDACTED not in str(audit)


def test_incomplete_replacement_content_is_never_retrievable_and_a_failed_reprocess_keeps_the_active_version(client, world, owner_engine, worker_db, monkeypatch):
    doc = _multi(client, world)
    # staged but not activated content (as it exists mid-transaction) is invisible to retrieval: it is not current
    run(owner_engine, "INSERT INTO document_chunks (tenant_id, document_id, version_id, version, chunk_index, text, is_current, generation, embedding, embedding_profile_id, suspicious) "
                      "SELECT tenant_id, document_id, version_id, version, chunk_index + 100, 'STAGED-ONLY-PHRASE quartz-staged-7731', false, 2, embedding, embedding_profile_id, false "
                      "FROM document_chunks WHERE document_id = :d LIMIT 1", d=doc)
    assert not [h for h in hits(client, world["eng"], "STAGED-ONLY-PHRASE quartz-staged-7731") if "STAGED" in h["text"]]
    run(owner_engine, "DELETE FROM document_chunks WHERE generation = 2 AND document_id = :d", d=doc)
    before = sql(owner_engine, "SELECT id FROM document_chunks WHERE document_id = :d AND is_current ORDER BY id", d=doc)
    job = client.post(f"/api/v1/documents/{doc}/reprocess", headers=world["sup"]).json()
    real = fail_embedding(monkeypatch)
    outcomes = []
    for _ in range(6):
        got = worker.drain(worker_db, FAST)
        outcomes += got
        if not got:
            break
    assert outcomes == ["ingestion_retry_scheduled"] * 4 + ["ingestion_failed"]  # a reprocess job starts at attempt 0: attempts 1 to 4 retry, attempt 5 reaches max_attempts
    failed = client.get(f"/api/v1/ingestion/jobs/{job['id']}", headers=world["eng"]).json()
    assert failed["status"] == "FAILED"
    assert sql(owner_engine, "SELECT id FROM document_chunks WHERE document_id = :d AND is_current ORDER BY id", d=doc) == before  # the previously usable content is untouched
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d AND generation = 2", d=doc)[0][0] == 0
    for who in ("eng", "aud"):
        assert client.post(f"/api/v1/ingestion/jobs/{failed['id']}/retry", headers=world[who]).status_code == 403
    monkeypatch.setattr(embeddings.DeterministicEmbedder, "embed", real)
    assert any(h["filename"] == "maintenance_log.csv" for h in hits(client, world["eng"], "Weekly bearing inspection lubricant topped up"))  # still served after the failure
    again = client.post(f"/api/v1/ingestion/jobs/{failed['id']}/retry", headers=world["sup"])  # authorised manual retry of a failed reprocessing job
    assert again.status_code == 202 and again.json()["status"] == "QUEUED" and again.json()["attempts"] == 0
    assert worker.drain(worker_db, FAST) == ["ingestion_completed"]
    assert sql(owner_engine, "SELECT active_generation FROM document_versions WHERE document_id = :d", d=doc)[0][0] == 2


def test_a_failure_between_staging_and_activation_rolls_back_the_staged_generation(client, world, owner_engine, worker_db, monkeypatch):
    doc = _multi(client, world)
    client.post(f"/api/v1/documents/{doc}/reprocess", headers=world["sup"])
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("injected failure after staging and activation statements")))
    assert worker.drain(worker_db, FAST, max_iterations=1) == ["ingestion_retry_scheduled"]
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d AND generation = 2", d=doc)[0][0] == 0  # the whole transaction rolled back
    assert sql(owner_engine, "SELECT active_generation FROM document_versions WHERE document_id = :d", d=doc)[0][0] == 1
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d AND is_current", d=doc)[0][0] > 0
    monkeypatch.undo()
    assert worker.drain(worker_db, FAST) == ["ingestion_completed"]


# ---------------------------------------------------------------------------------------------------------------------------- deletion races
def test_deletion_cancels_queued_and_retrying_jobs_and_the_content_never_returns(client, world, owner_engine, worker_db, monkeypatch):
    doc = upload(client, world["eng"]).json()["document_id"]
    real = fail_embedding(monkeypatch)
    assert upload(client, world["eng"], data=NOTE + b" Second edition.").status_code == 503  # a new-version job waiting for a retry
    reprocess = client.post(f"/api/v1/documents/{doc}/reprocess", headers=world["sup"]).json()
    active = [j for j in job_list(client, world["eng"]) if j["status"] in ("QUEUED", "RETRY_PENDING")]
    assert len(active) == 2
    assert client.delete(f"/api/v1/documents/{doc}", headers=world["sup"]).status_code == 200
    states = {j["id"]: j for j in job_list(client, world["eng"])}
    assert states[reprocess["id"]]["status"] == "CANCELLED" and states[reprocess["id"]]["error_code"] == "document_deleted"
    cancelled = [j for j in states.values() if j["status"] == "CANCELLED"]
    assert len(cancelled) >= 1 and all(sql(owner_engine, "SELECT payload FROM ingestion_jobs WHERE id = :i", i=j["id"])[0][0] is None for j in cancelled)
    monkeypatch.setattr(embeddings.DeterministicEmbedder, "embed", real)
    make_due(owner_engine)
    outcomes = worker.drain(worker_db, FAST)
    assert "ingestion_completed" not in outcomes and sql(owner_engine, "SELECT lifecycle_status FROM documents WHERE id = :d", d=doc)[0][0] == "deleted"
    assert client.get(f"/api/v1/documents/{doc}", headers=world["eng"]).status_code == 404
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d AND is_current", d=doc)[0][0] == 0
    audit = [a["action"] for a in client.get("/api/v1/audit", headers=world["aud"], params={"entity_id": reprocess["id"]}).json()["items"]]
    assert "ingestion.job_cancelled" in audit


def test_deletion_after_a_worker_claimed_or_during_reprocessing_discards_the_late_write(client, world, owner_engine, worker_db):
    doc = _multi(client, world)
    client.post(f"/api/v1/documents/{doc}/reprocess", headers=world["sup"])
    claimed = jobs.claim_next(worker_db, 60)
    info, segments = jobs._reprocess_read(worker_db, claimed)
    vectors = jobs.embed_segments(EMB, info["kind"], info["filename"], segments)  # the worker is mid-flight with replacement content ready
    assert client.delete(f"/api/v1/documents/{doc}", headers=world["sup"]).status_code == 200
    with pytest.raises(jobs.StaleClaim):  # the fenced write is refused: the job was cancelled by the deletion
        jobs._reprocess_write(worker_db, claimed, info, segments, vectors, EMB)
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d AND generation = 2", d=doc)[0][0] == 0
    assert sql(owner_engine, "SELECT status FROM ingestion_jobs WHERE id = :i", i=claimed.id)[0][0] == "CANCELLED"
    assert jobs.execute(worker_db, claimed, EMB) == "stale"  # a restarted worker holding the old claim writes nothing
    assert worker.drain(worker_db, FAST) == ["cleanup_completed"]  # only the cleanup runs; nothing is reprocessed
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d", d=doc)[0][0] == 0


def test_the_activation_boundary_rechecks_the_lifecycle_even_if_no_job_was_cancelled(client, world, owner_engine, worker_db):
    doc = _multi(client, world)
    client.post(f"/api/v1/documents/{doc}/reprocess", headers=world["sup"])
    claimed = jobs.claim_next(worker_db, 60)
    info, segments = jobs._reprocess_read(worker_db, claimed)
    vectors = jobs.embed_segments(EMB, info["kind"], info["filename"], segments)
    run(owner_engine, "UPDATE documents SET lifecycle_status = 'deleted', deleted_at = now(), cleanup_state = 'pending' WHERE id = :d", d=doc)  # the document flips without the job being touched
    with pytest.raises(jobs.JobCancelled):
        jobs._reprocess_write(worker_db, claimed, info, segments, vectors, EMB)
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d AND generation = 2", d=doc)[0][0] == 0
    assert jobs.execute(worker_db, claimed, EMB) == "cancelled"


def test_concurrent_deletion_and_reprocessing_requests_serialise(client, world, owner_engine, app_db):
    doc = _multi(client, world)
    tenant = world["t"].id
    deleting = app_db.session(tenant_id=tenant)
    lifecycle.delete_document(deleting, tenant_id=tenant, user_id=uuid.uuid4(), document_id=doc)  # holds the document lock, uncommitted
    result = {}

    def request():
        with app_db.session(tenant_id=tenant) as s:
            try:
                jobs.request_reprocess(s, tenant_id=tenant, user_id=None, document_id=uuid.UUID(doc), embedder=EMB)
                s.commit()
                result["r"] = "queued"
            except Exception as exc:  # noqa: BLE001
                result["r"] = type(exc).__name__

    thread = threading.Thread(target=request)
    thread.start()
    thread.join(1.5)
    assert thread.is_alive()  # the reprocess request waits for the deletion
    deleting.commit()
    deleting.close()
    thread.join(30)
    assert result["r"] == "NotFound"  # a deleted document cannot be reprocessed
    assert sql(owner_engine, "SELECT count(*) FROM ingestion_jobs WHERE job_type = 'reprocess' AND document_id = :d", d=doc)[0][0] == 0


def test_reupload_after_deletion_and_cleanup_of_the_old_document_leave_the_new_one_processable(client, world, owner_engine, worker_db):
    old = upload(client, world["eng"]).json()["document_id"]
    client.delete(f"/api/v1/documents/{old}", headers=world["sup"])
    new = upload(client, world["eng"])
    assert new.status_code == 201 and new.json()["status"] == "created" and new.json()["document_id"] != old
    assert worker.drain(worker_db, FAST) == ["cleanup_completed"]
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d AND is_current", d=new.json()["document_id"])[0][0] >= 1
    assert client.post(f"/api/v1/documents/{old}/reprocess", headers=world["sup"]).status_code == 404  # the deleted one is gone for reprocessing too
    assert client.post(f"/api/v1/documents/{new.json()['document_id']}/reprocess", headers=world["sup"]).status_code == 202
    assert worker.drain(worker_db, FAST) == ["ingestion_completed"]


# ---------------------------------------------------------------------------------------------------------------------------- tenant isolation
def test_jobs_are_tenant_private_and_a_forged_job_cannot_touch_another_tenants_document(client, world, owner_engine, worker_db, ticketing, inventory_server):
    other = make_tenant(owner_engine, "jobiso", ticketing.url, inventory_server.url)
    other_eng, other_sup = login(client, other, "support_engineer"), login(client, other, "maintenance_supervisor")
    ingest_samples(client, other_eng)
    mine = _multi(client, world)
    theirs = client.get("/api/v1/documents", headers=other_eng, params={"limit": 100}).json()["items"][0]["id"]
    my_job = client.post(f"/api/v1/documents/{mine}/reprocess", headers=world["sup"]).json()
    assert client.get(f"/api/v1/ingestion/jobs/{my_job['id']}", headers=other_eng).status_code == 404
    assert client.get(f"/api/v1/ingestion/jobs/{uuid.uuid4()}", headers=other_eng).status_code == 404  # unknown and foreign look the same
    assert my_job["id"] not in [j["id"] for j in job_list(client, other_eng)] and all(j["document_id"] != mine for j in job_list(client, other_eng))
    assert client.post(f"/api/v1/documents/{mine}/reprocess", headers=other_sup).status_code == 404
    assert client.post(f"/api/v1/ingestion/jobs/{my_job['id']}/retry", headers=other_sup).status_code == 404
    assert client.get("/api/v1/ingestion/jobs", headers=other_eng, params={"document_id": mine}).json()["total"] == 0
    gens_before = sql(owner_engine, "SELECT generation, count(*) FROM document_chunks WHERE document_id = :d GROUP BY generation", d=theirs)
    worker.drain(worker_db, FAST)  # process my own job first
    with owner_engine.begin() as c:  # a forged job: this tenant's job naming ANOTHER tenant's document
        forged = c.execute(text("INSERT INTO ingestion_jobs (tenant_id, job_type, status, document_id, source_version, filename, kind, idempotency_key) "
                                "VALUES (:t, 'reprocess', 'QUEUED', :d, 1, 'x', 'other', 'reprocess:forged') RETURNING id"), {"t": world["t"].id, "d": theirs}).scalar()
    assert worker.drain(worker_db, FAST) == ["ingestion_cancelled"]
    assert sql(owner_engine, "SELECT generation, count(*) FROM document_chunks WHERE document_id = :d GROUP BY generation", d=theirs) == gens_before  # untouched
    assert sql(owner_engine, "SELECT status, error_code FROM ingestion_jobs WHERE id = :i", i=forged)[0] == ("CANCELLED", "document_deleted")
    assert str(forged) not in [j["id"] for j in job_list(client, other_eng)]


def test_the_worker_cannot_read_or_write_document_tables_outside_a_tenant_context(worker_db, world, client):
    upload(client, world["eng"])
    with worker_db.session() as s:
        assert s.execute(text("SELECT count(*) FROM documents")).scalar() == 0
        assert s.execute(text("SELECT count(*) FROM document_chunks")).scalar() == 0
    with worker_db.session(tenant_id=world["t"].id) as s:
        assert s.execute(text("SELECT count(*) FROM documents WHERE tenant_id = :t"), {"t": world["t"].id}).scalar() >= 1
        with pytest.raises(DBAPIError):  # it can insert chunks only for the tenant in its context
            s.execute(text("INSERT INTO documents (tenant_id, source_key, filename, kind) VALUES (:t, 'x', 'x', 'other')"), {"t": str(uuid.uuid4())})
            s.commit()


# ---------------------------------------------------------------------------------------------------------------------------- observability
def test_job_activity_is_visible_in_the_existing_metrics_without_leaking_content(client, world, owner_engine, monkeypatch):
    fail_embedding(monkeypatch)
    upload(client, world["eng"])
    summary = client.get("/api/v1/observability/summary", headers=world["adm"]).json()
    names = {(c["name"], c["labels"].get("outcome")) for c in summary["process"]["counters"]}
    assert ("ingestion_jobs_total", "created") in names
    assert "zebra-quartz" not in str(summary) and "secret" not in str(summary)
    audit = client.get("/api/v1/audit", headers=world["aud"], params={"limit": 100}).json()["items"]
    assert all("zebra-quartz" not in str(a) and "payload" not in str(a["details"]) for a in audit)
