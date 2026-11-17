"""Batch 11A, Checkpoint B: durable REST pull synchronization (V41-12.01 REST part, V41-11.01, V41-11.02).

Real HTTP to the local records mock; the application, worker, database, RLS, jobs, sources and retrieval are the real ones. Failures are CONTROLLED INJECTIONS (a mock that answers 429, 503, bad
shapes or redirects; a patched embedder; a process "crash" raised as a BaseException; owner-level SQL that alters stored configuration); none is a real upstream outage."""
import json
import threading
import time

import pytest
from app.ingestion import jobs, sync
from app.workflows import worker
from sqlalchemy import text
from support import RECORDS_KEY, login, make_tenant
from test_ingestion_jobs import (  # noqa: F401
    FAST,
    Crash,
    db_clean,
    expire_lease,
    fail_embedding,
    hits,
    job_list,
    make_due,
    run,
    sql,
    world,
)

SECRET_ENV = "RECORDS_SYNC_TEST_KEY"


def config(mode="cursor", dataset="apex", **over):
    pagination = {"mode": mode, "page_size": 3}
    if mode == "cursor":
        pagination["has_more_field"] = "has_more"
    elif mode in ("offset", "page"):
        pagination["total_field"] = "total"
    records = {"path": f"/v1/{dataset}/{mode}", "id_field": "id", "version_field": "updated_at", "required_fields": ["title", "body"], "pagination": pagination,
               "rate": {"requests_per_second": 50, "burst": 20}}
    records.update(over)
    return {"records": records}


@pytest.fixture(autouse=True)
def fresh_mock(records_server, monkeypatch):
    import records_app
    from app.connectors.ratelimit import LIMITERS
    with records_server.state.lock:
        records_server.state.failures.clear()
        records_server.state.requests.clear()
        records_server.state.datasets["apex"] = records_app._apex()
        records_server.state.datasets["meridian"] = records_app._meridian()
    LIMITERS.clear()
    monkeypatch.setenv(SECRET_ENV, RECORDS_KEY)


def inject(records_server, mode, count=1, after=0, delay=0.6):
    from records_app import FailureConfig
    with records_server.state.lock:
        records_server.state.failures.append(FailureConfig(mode=mode, count=count, after=after, delay=delay))


def connector(client, world, records_server, mode="cursor", dataset="apex", name=None, secret=SECRET_ENV, **over):
    body = {"kind": "rest", "name": name or f"records-{mode}-{dataset}-{int(time.time() * 1000) % 100000}", "base_url": records_server.url, "config": config(mode, dataset, **over)}
    if secret:
        body["secret_ref"] = secret
    r = client.post("/api/v1/connectors", headers=world["adm"], json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def start(client, world, cid, who="sup"):
    r = client.post(f"/api/v1/connectors/{cid}/sync", headers=world[who])
    assert r.status_code == 202, r.text
    return r.json()


def finish(client, world, worker_db, job_id, config_=FAST):
    worker.drain(worker_db, config_)
    return client.get(f"/api/v1/ingestion/jobs/{job_id}", headers=world["eng"]).json()


def docs(owner_engine, world):
    return sql(owner_engine, "SELECT filename, current_version FROM documents WHERE tenant_id = :t AND lifecycle_status = 'active' AND filename LIKE 'rest-%' ORDER BY filename", t=world["t"].id)


# ----------------------------------------------------------------------------------------------------------------------- API, authorization, tenant isolation
def test_the_sync_endpoint_returns_an_accurate_202_only_after_the_job_is_committed(client, world, records_server, owner_engine):
    cid = connector(client, world, records_server)
    r = client.post(f"/api/v1/connectors/{cid}/sync", headers=world["sup"])
    assert r.status_code == 202 and r.headers["X-Correlation-ID"]
    job = r.json()
    assert job["job_type"] == "sync" and job["status"] == "QUEUED" and job["connector_id"] == cid and job["attempts"] == 0 and job["outcome"] is None and job["completed_at"] is None
    assert job["sync"]["seen"] == 0 and sql(owner_engine, "SELECT status, connector_id::text FROM ingestion_jobs WHERE id = :i", i=job["id"]) == [("QUEUED", cid)]  # durable before the answer
    assert not records_server.state.requests  # nothing was fetched by the request itself: the worker does the work
    assert docs(owner_engine, world) == []
    again = client.post(f"/api/v1/connectors/{cid}/sync", headers=world["adm"])
    assert again.status_code == 202 and again.json()["id"] == job["id"]  # duplicate synchronisation: the active job is returned, nothing queued twice
    assert sql(owner_engine, "SELECT count(*) FROM ingestion_jobs WHERE job_type = 'sync' AND tenant_id = :t", t=world["t"].id)[0][0] == 1


def test_only_administrators_and_supervisors_may_synchronise_and_ids_are_tenant_private(client, world, records_server, owner_engine):
    cid = connector(client, world, records_server)
    for who in ("eng", "aud"):
        assert client.post(f"/api/v1/connectors/{cid}/sync", headers=world[who]).status_code == 403
    assert client.post(f"/api/v1/connectors/{cid}/sync").status_code == 401
    other = make_tenant(owner_engine, "syncother")
    theirs = login(client, other, "tenant_admin")
    assert client.post(f"/api/v1/connectors/{cid}/sync", headers=theirs).status_code == 404  # another tenant's connector id is indistinguishable from an unknown id
    assert client.post("/api/v1/connectors/00000000-0000-0000-0000-000000000000/sync", headers=world["sup"]).status_code == 404
    job = start(client, world, cid)
    assert client.get(f"/api/v1/ingestion/jobs/{job['id']}", headers=theirs).status_code == 404 and not job_list(client, theirs)
    assert sql(owner_engine, "SELECT count(*) FROM ingestion_jobs WHERE tenant_id = :t", t=other.id)[0][0] == 0


def test_invalid_or_unapproved_connectors_cannot_be_saved_or_synchronised(client, world, records_server, owner_engine):
    bad = client.post("/api/v1/connectors", headers=world["adm"], json={"kind": "rest", "name": "bad-config", "base_url": records_server.url, "config": {"records": {"path": "//evil/x", "id_field": "id"}}})
    assert bad.status_code == 422 and "evil" not in bad.text  # rejected at creation, without echoing the value
    wrong_kind = client.post("/api/v1/connectors", headers=world["adm"], json={"kind": "crm", "name": "wrong-kind", "base_url": records_server.url, "config": config()})
    assert wrong_kind.status_code == 422
    with owner_engine.begin() as c:  # connectors created before this feature, or edited in the database, are validated again when a sync is requested
        plain = c.execute(text("INSERT INTO connectors (tenant_id, kind, name, base_url, config) VALUES (:t, 'rest', 'plain', :u, '{}') RETURNING id"), {"t": world["t"].id, "u": records_server.url}).scalar()
        metadata = c.execute(text("INSERT INTO connectors (tenant_id, kind, name, base_url, config) VALUES (:t, 'rest', 'metadata', 'http://169.254.169.254', CAST(:c AS jsonb)) RETURNING id"),
                             {"t": world["t"].id, "c": json.dumps(config())}).scalar()
        ticketing = c.execute(text("INSERT INTO connectors (tenant_id, kind, name, base_url, config) VALUES (:t, 'ticketing', 'tk', :u, '{}') RETURNING id"), {"t": world["t"].id, "u": records_server.url}).scalar()
    r0 = client.post(f"/api/v1/connectors/{plain}/sync", headers=world["sup"])
    assert r0.status_code == 409 and r0.json()["error"]["code"] == "invalid_connector_config"
    r = client.post(f"/api/v1/connectors/{metadata}/sync", headers=world["sup"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "connector_destination_not_allowed"  # the link-local metadata address is refused before any job exists
    assert client.post(f"/api/v1/connectors/{ticketing}/sync", headers=world["sup"]).status_code == 409
    assert sql(owner_engine, "SELECT count(*) FROM ingestion_jobs WHERE job_type = 'sync' AND tenant_id = :t", t=world["t"].id)[0][0] == 0


# ----------------------------------------------------------------------------------------------------------------------- the happy path and provenance
@pytest.mark.parametrize("mode", ["cursor", "offset", "page"])
def test_a_sync_pulls_every_page_through_the_real_pipeline_and_records_provenance(client, world, records_server, owner_engine, worker_db, mode):
    cid = connector(client, world, records_server, mode)
    job = start(client, world, cid)
    assert worker.drain(worker_db, FAST) == ["ingestion_completed"]
    done = client.get(f"/api/v1/ingestion/jobs/{job['id']}", headers=world["eng"]).json()
    assert done["status"] == "COMPLETED" and done["outcome"] == "synced" and done["attempts"] == 1 and done["sync"]["pages"] == 3 and done["sync"]["created"] == 7 and done["sync"]["seen"] == 7
    assert len(docs(owner_engine, world)) == 7 and len([r for r in records_server.state.requests if r["key_ok"]]) == 3
    rows = sql(owner_engine, "SELECT source_record_id, source_version, document_version, status, last_job_id::text, content_hash FROM connector_sync_records WHERE tenant_id = :t ORDER BY source_record_id", t=world["t"].id)
    assert [r[0] for r in rows] == [f"APX-N-{i:03d}" for i in range(1, 8)] and all(r[2] == 1 and r[3] == "active" and r[4] == job["id"] and r[1] for r in rows)
    chunk = sql(owner_engine, "SELECT c.record_id, d.filename FROM document_chunks c JOIN documents d ON d.id = c.document_id WHERE c.tenant_id = :t AND d.filename LIKE '%APX-N-001%'", t=world["t"].id)
    assert chunk and chunk[0][0] == "APX-N-001"  # the source record id is the chunk's provenance
    assert sql(owner_engine, "SELECT count(*) FROM document_sources s JOIN document_versions v ON v.source_id = s.id WHERE s.tenant_id = :t", t=world["t"].id)[0][0] == 7  # originals retained
    assert any("seal" in h["text"].lower() for h in hits(client, world["eng"], "mechanical seal weeps pump P-101"))  # actually retrievable by the tenant


def test_a_repeated_sync_is_idempotent_and_an_updated_record_becomes_a_new_version(client, world, records_server, owner_engine, worker_db):
    cid = connector(client, world, records_server)
    finish(client, world, worker_db, start(client, world, cid)["id"])
    second = finish(client, world, worker_db, start(client, world, cid)["id"])
    assert second["outcome"] == "synced" and second["sync"]["unchanged"] == 7 and second["sync"]["created"] == 0 and second["sync"]["updated"] == 0
    assert sql(owner_engine, "SELECT count(*) FROM document_versions WHERE tenant_id = :t", t=world["t"].id)[0][0] == 7  # nothing was stored twice
    with records_server.state.lock:
        records_server.state.datasets["apex"][1]["body"] = "Bearing temperature is now stable after lubrication."
        records_server.state.datasets["apex"][1]["updated_at"] = "2026-11-12T10:00:00Z"
    third = finish(client, world, worker_db, start(client, world, cid)["id"])
    assert third["sync"]["updated"] == 1 and third["sync"]["unchanged"] == 6
    assert sql(owner_engine, "SELECT current_version FROM documents WHERE tenant_id = :t AND filename LIKE '%APX-N-002%'", t=world["t"].id)[0][0] == 2
    assert sql(owner_engine, "SELECT document_version, source_version FROM connector_sync_records WHERE tenant_id = :t AND source_record_id = 'APX-N-002'", t=world["t"].id)[0] == (2, "2026-11-12T10:00:00Z")
    assert any("stable after lubrication" in h["text"] for h in hits(client, world["eng"], "bearing temperature stable lubrication"))
    assert not any("trends up" in h["text"] for h in hits(client, world["eng"], "bearing temperature trends up lubrication") if "APX-N-002" in h.get("filename", ""))  # the old version is not current


def test_duplicate_conflicting_and_identical_content_records_are_handled_by_policy(client, world, records_server, owner_engine, worker_db):
    first = {"id": "D-1", "title": "Pump note", "body": "Alpha note about pump seals.", "updated_at": "v1"}
    with records_server.state.lock:
        records_server.state.datasets["apex"] = [first, dict(first), {"id": "D-1", "title": "Pump note", "body": "A DIFFERENT body under the same id.", "updated_at": "v2"},
                                                  {"id": "D-2", "title": "Pump note", "body": "Alpha note about pump seals.", "updated_at": "v1"}]
    cid = connector(client, world, records_server)
    done = finish(client, world, worker_db, start(client, world, cid)["id"])
    c = done["sync"]
    assert c["created"] == 2 and c["duplicate_in_sync"] == 1 and c["conflict"] == 1 and c["seen"] == 4  # D-1 and D-2; the repeat and the conflicting copy are not stored
    assert done["outcome"] == "synced_with_rejections"  # a conflicting record is reported honestly, never silently merged
    assert len(docs(owner_engine, world)) == 2
    stored = sql(owner_engine, "SELECT content_hash FROM connector_sync_records WHERE tenant_id = :t AND source_record_id = 'D-1'", t=world["t"].id)
    assert len(stored) == 1  # the FIRST occurrence won


def test_invalid_records_are_skipped_and_counted_or_fail_the_job_by_policy(client, world, records_server, owner_engine, worker_db):
    with records_server.state.lock:
        records_server.state.datasets["apex"] = [{"id": "OK-1", "title": "t", "body": "good record one"}, {"id": "BAD-1", "title": "", "body": "no title"},
                                                  {"title": "t", "body": "no id"}, "not an object", {"id": "OK-2", "title": "t", "body": "good record two"}]
    skip = connector(client, world, records_server, name="skip-policy")
    done = finish(client, world, worker_db, start(client, world, skip)["id"])
    assert done["status"] == "COMPLETED" and done["outcome"] == "synced_with_rejections" and done["sync"]["created"] == 2 and done["sync"]["invalid"] == 3
    assert done["sync"]["rejections"] == {"missing_required_field": 1, "invalid_id": 1, "not_an_object": 1} and len(docs(owner_engine, world)) == 2
    strict = connector(client, world, records_server, name="fail-policy", reject_policy="fail")
    failed = finish(client, world, worker_db, start(client, world, strict)["id"])
    assert failed["status"] == "FAILED" and failed["error_code"] == "source_record_invalid" and failed["attempts"] == 1  # permanent: not retried


# ----------------------------------------------------------------------------------------------------------------------- upstream failures, retry and recovery
def test_a_transient_failure_mid_sync_retries_resumes_and_never_duplicates(client, world, records_server, owner_engine, worker_db):
    cid = connector(client, world, records_server)
    inject(records_server, "503", count=10, after=1)  # the first page succeeds, then the source fails
    job = start(client, world, cid)
    assert worker.drain(worker_db, FAST, max_iterations=1) == ["ingestion_retry_scheduled"]
    j = client.get(f"/api/v1/ingestion/jobs/{job['id']}", headers=world["eng"]).json()
    assert j["status"] == "RETRY_PENDING" and j["error_code"] == "source_unavailable" and j["sync"]["pages"] == 1 and j["sync"]["created"] == 3  # partial progress is persisted
    assert "503" not in json.dumps(j) and RECORDS_KEY not in json.dumps(j)
    with records_server.state.lock:
        records_server.state.failures.clear()
        records_server.state.requests.clear()
    make_due(owner_engine)
    done = finish(client, world, worker_db, job["id"])
    assert done["status"] == "COMPLETED" and done["attempts"] == 2 and done["sync"]["created"] == 7 and done["sync"]["pages"] == 3
    assert len(docs(owner_engine, world)) == 7 and all(v == 1 for _, v in docs(owner_engine, world))
    assert [r["params"]["cursor"] for r in records_server.state.requests][0] is not None  # the retry RESUMED at the saved cursor: page 1 was not fetched again


def test_retry_exhaustion_fails_the_job_and_a_manual_retry_completes_it(client, world, records_server, owner_engine, worker_db):
    cid = connector(client, world, records_server)
    inject(records_server, "503", count=1000)
    job = start(client, world, cid)
    for _ in range(8):
        make_due(owner_engine)
        if not worker.drain(worker_db, FAST):
            break
    failed = client.get(f"/api/v1/ingestion/jobs/{job['id']}", headers=world["eng"]).json()
    assert failed["status"] == "FAILED" and failed["error_code"] == "retries_exhausted" and failed["attempts"] == failed["max_attempts"] == 5
    with records_server.state.lock:
        records_server.state.failures.clear()
    assert client.post(f"/api/v1/ingestion/jobs/{job['id']}/retry", headers=world["eng"]).status_code == 403
    assert client.post(f"/api/v1/ingestion/jobs/{job['id']}/retry", headers=world["sup"]).status_code == 202
    assert finish(client, world, worker_db, job["id"])["status"] == "COMPLETED" and len(docs(owner_engine, world)) == 7


def test_http_429_mid_sync_is_absorbed_within_the_bounded_retry_after(client, world, records_server, owner_engine, worker_db):
    cid = connector(client, world, records_server)
    inject(records_server, "429", count=1, after=1)
    started = time.monotonic()
    done = finish(client, world, worker_db, start(client, world, cid)["id"])
    assert done["status"] == "COMPLETED" and done["attempts"] == 1 and done["sync"]["created"] == 7 and 0.9 <= time.monotonic() - started < 10


def test_permanent_source_failures_fail_at_once_with_fixed_codes_and_no_secret_exposure(client, world, records_server, owner_engine, worker_db, monkeypatch):
    # authentication rejected by the source
    monkeypatch.setenv(SECRET_ENV, "WRONG-SECRET-VALUE")
    cid = connector(client, world, records_server, name="wrong-key")
    bad = finish(client, world, worker_db, start(client, world, cid)["id"])
    assert bad["status"] == "FAILED" and bad["error_code"] == "source_unauthorized" and bad["attempts"] == 1
    # the named secret is not configured at all: nothing is sent
    monkeypatch.delenv(SECRET_ENV)
    records_server.state.requests.clear()
    missing = finish(client, world, worker_db, start(client, world, connector(client, world, records_server, name="no-secret"))["id"])
    assert missing["error_code"] == "credentials_missing" and missing["attempts"] == 1 and not records_server.state.requests
    monkeypatch.setenv(SECRET_ENV, RECORDS_KEY)
    # schema, loop, cursor and redirect failures
    for mode, code in (("bad_shape", "source_schema_invalid"), ("url_cursor", "invalid_cursor"), ("repeat_cursor", "pagination_loop"), ("redirect", "source_rejected")):
        inject(records_server, mode, count=(1 if mode == "bad_shape" else 1), after=(0 if mode in ("bad_shape", "redirect") else 1))
        records_server.state.requests.clear()
        j = finish(client, world, worker_db, start(client, world, connector(client, world, records_server, name=f"fail-{mode}"))["id"])
        assert j["status"] == "FAILED" and j["error_code"] == code and j["attempts"] == 1, (mode, j["error_code"])
        assert not any("169.254" in json.dumps(r) for r in records_server.state.requests)  # the metadata address was never contacted
    blob = json.dumps(job_list(client, world["eng"])) + json.dumps(client.get("/api/v1/audit", headers=world["aud"], params={"limit": 100}).json())
    assert RECORDS_KEY not in blob and "WRONG-SECRET-VALUE" not in blob and "X-API-Key" not in blob


def test_a_connector_edited_in_the_database_cannot_redirect_or_widen_a_queued_sync(client, world, records_server, owner_engine, worker_db):
    cid = connector(client, world, records_server)
    job = start(client, world, cid)
    run(owner_engine, "UPDATE connectors SET base_url = 'http://169.254.169.254' WHERE id = :c", c=cid)  # forged configuration after the job was queued
    j = finish(client, world, worker_db, job["id"])
    assert j["status"] == "FAILED" and j["error_code"] == "egress_denied" and j["attempts"] == 1 and not records_server.state.requests
    run(owner_engine, "UPDATE connectors SET base_url = :u, config = CAST(:c AS jsonb) WHERE id = :i", u=records_server.url, c=json.dumps({"records": {"path": "//evil.example/x", "id_field": "id"}}), i=cid)
    assert client.post(f"/api/v1/ingestion/jobs/{job['id']}/retry", headers=world["sup"]).status_code == 202
    j2 = finish(client, world, worker_db, job["id"])
    assert j2["status"] == "FAILED" and j2["error_code"] == "invalid_connector_config" and not records_server.state.requests


def test_the_rate_limit_spaces_the_real_requests(client, world, records_server, worker_db):
    cid = connector(client, world, records_server, rate={"requests_per_second": 2.0, "burst": 1})
    started = time.monotonic()
    done = finish(client, world, worker_db, start(client, world, cid)["id"])
    assert done["status"] == "COMPLETED" and time.monotonic() - started >= 0.9  # three requests at 2 per second with a burst of 1: at least one second in total


def test_the_embedding_model_failing_retries_the_page_idempotently(client, world, records_server, owner_engine, worker_db, monkeypatch):
    real = fail_embedding(monkeypatch)
    cid = connector(client, world, records_server)
    job = start(client, world, cid)
    assert worker.drain(worker_db, FAST, max_iterations=1) == ["ingestion_retry_scheduled"]
    assert client.get(f"/api/v1/ingestion/jobs/{job['id']}", headers=world["eng"]).json()["error_code"] == "embedding_unavailable" and docs(owner_engine, world) == []
    from app.ai import embeddings
    monkeypatch.setattr(embeddings.DeterministicEmbedder, "embed", real)
    make_due(owner_engine)
    done = finish(client, world, worker_db, job["id"])
    assert done["status"] == "COMPLETED" and len(docs(owner_engine, world)) == 7


# ----------------------------------------------------------------------------------------------------------------------- crashes, claims, stale jobs
def test_a_worker_crash_mid_sync_is_recovered_after_the_lease_expires_without_duplicates(client, world, records_server, owner_engine, worker_db, monkeypatch):
    cid = connector(client, world, records_server)
    job = start(client, world, cid)
    real, calls = sync.embed_segments, {"n": 0}

    def crashing(*a, **k):
        calls["n"] += 1
        if calls["n"] == 5:
            raise Crash()  # the process dies while processing a record of page 2
        return real(*a, **k)
    monkeypatch.setattr(sync, "embed_segments", crashing)
    with pytest.raises(Crash):
        worker.drain(worker_db, FAST)
    monkeypatch.setattr(sync, "embed_segments", real)
    assert sql(owner_engine, "SELECT status FROM ingestion_jobs WHERE id = :i", i=job["id"])[0][0] == "PROCESSING"
    assert worker.drain(worker_db, FAST) == []  # the lease is still valid: nobody else touches it
    expire_lease(owner_engine)
    records_server.state.requests.clear()
    done = finish(client, world, worker_db, job["id"])  # worker restart: reclaimed, resumed from the saved page
    assert done["status"] == "COMPLETED" and done["attempts"] == 2 and len(docs(owner_engine, world)) == 7 and all(v == 1 for _, v in docs(owner_engine, world))
    assert sql(owner_engine, "SELECT count(*) FROM connector_sync_records WHERE tenant_id = :t", t=world["t"].id)[0][0] == 7


def test_concurrent_claims_give_one_worker_the_job_and_a_stale_claim_cannot_write(client, world, records_server, owner_engine, worker_db):
    cid = connector(client, world, records_server)
    start(client, world, cid)
    results = []
    threads = [threading.Thread(target=lambda: results.append(jobs.claim_next(worker_db, 60))) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    claims = [r for r in results if r is not None]
    assert len(claims) == 1 and claims[0].job_type == "sync"  # exactly one claim wins
    old = claims[0]
    expire_lease(owner_engine)
    newer = jobs.claim_next(worker_db, 60)  # the lease expired: another worker takes over
    assert newer is not None and newer.token != old.token
    with pytest.raises(jobs.StaleClaim):
        sync._save_progress(worker_db, old, {"pager": {}, "counts": {}})  # the old worker can not overwrite newer state
    assert jobs.execute(worker_db, old, jobs.get_embedder("deterministic") if hasattr(jobs, "get_embedder") else __import__("app.ai.embeddings", fromlist=["x"]).get_embedder("deterministic")) == "stale"
    assert docs(owner_engine, world) == []  # the stale worker ingested nothing
    assert jobs.execute(worker_db, newer, __import__("app.ai.embeddings", fromlist=["x"]).get_embedder("deterministic")) == "completed"
    assert len(docs(owner_engine, world)) == 7


# ----------------------------------------------------------------------------------------------------------------------- deletion interaction
def test_a_deleted_synced_document_stays_deleted_even_when_its_source_record_changes(client, world, records_server, owner_engine, worker_db):
    cid = connector(client, world, records_server)
    finish(client, world, worker_db, start(client, world, cid)["id"])
    doc = sql(owner_engine, "SELECT document_id::text FROM connector_sync_records WHERE tenant_id = :t AND source_record_id = 'APX-N-003'", t=world["t"].id)[0][0]
    assert client.delete(f"/api/v1/documents/{doc}", headers=world["sup"]).status_code == 200
    assert sql(owner_engine, "SELECT status FROM connector_sync_records WHERE tenant_id = :t AND source_record_id = 'APX-N-003'", t=world["t"].id)[0][0] == "deleted"
    worker.drain(worker_db, FAST)  # the cleanup
    again = finish(client, world, worker_db, start(client, world, cid)["id"])
    assert again["sync"]["skipped_deleted"] == 1 and again["sync"]["unchanged"] == 6 and again["sync"]["created"] == 0
    with records_server.state.lock:
        records_server.state.datasets["apex"][2]["body"] = "Compressor filter replaced; differential pressure normal."
        records_server.state.datasets["apex"][2]["updated_at"] = "2026-11-12T11:00:00Z"
    third = finish(client, world, worker_db, start(client, world, cid)["id"])
    # a changed content hash is NOT authorisation to recreate deleted content: the tombstone and the source identity are preserved
    assert third["sync"]["tombstoned_changed"] == 1 and third["sync"]["created"] == 0 and third["sync"]["updated"] == 0 and third["status"] == "COMPLETED"
    assert len(docs(owner_engine, world)) == 6 and client.get(f"/api/v1/documents/{doc}", headers=world["eng"]).status_code == 404
    assert sql(owner_engine, "SELECT document_id::text, status FROM connector_sync_records WHERE tenant_id = :t AND source_record_id = 'APX-N-003'", t=world["t"].id)[0] == (doc, "deleted")
    assert not any("Compressor filter replaced" in h["text"] for h in hits(client, world["eng"], "compressor filter replaced differential pressure normal"))
    assert sql(owner_engine, "SELECT count(*) FROM document_sources WHERE tenant_id = :t AND content LIKE '%Compressor filter replaced%'::bytea", t=world["t"].id)[0][0] == 0  # the changed content was never stored


def test_a_deletion_that_commits_between_the_check_and_the_write_is_honoured(client, world, records_server, owner_engine, worker_db):
    cid = connector(client, world, records_server)
    finish(client, world, worker_db, start(client, world, cid)["id"])
    row = sql(owner_engine, "SELECT document_id::text, content_hash FROM connector_sync_records WHERE tenant_id = :t AND source_record_id = 'APX-N-001'", t=world["t"].id)[0]
    second = start(client, world, cid)
    claimed = jobs.claim_next(worker_db, 60)
    info, progress, slug, user_id, kind = sync._load(worker_db, claimed)
    assert client.delete(f"/api/v1/documents/{row[0]}", headers=world["sup"]).status_code == 200  # the user deletes it after the sync decided the record is unchanged
    from app.connectors.rest_records import parse_config
    outcome = sync._write_record(worker_db, claimed, info, parse_config(info.config), "APX-N-001", None, row[1], b"[]", "x.json", kind, user_id, None, "application/json", [], None)
    assert outcome == "skipped_deleted"  # the stale decision did not resurrect the document
    assert second["id"] == str(claimed.id) and client.get(f"/api/v1/documents/{row[0]}", headers=world["eng"]).status_code == 404


def test_synced_documents_support_source_reprocessing_and_cleanup_removes_their_originals(client, world, records_server, owner_engine, worker_db):
    cid = connector(client, world, records_server)
    finish(client, world, worker_db, start(client, world, cid)["id"])
    doc = sql(owner_engine, "SELECT document_id::text FROM connector_sync_records WHERE tenant_id = :t AND source_record_id = 'APX-N-001'", t=world["t"].id)[0][0]
    run(owner_engine, "UPDATE document_chunks SET text = 'TAMPERED' WHERE document_id = :d", d=doc)
    assert client.post(f"/api/v1/documents/{doc}/reprocess", headers=world["sup"]).status_code == 202
    assert worker.drain(worker_db, FAST) == ["ingestion_completed"]
    fresh = sql(owner_engine, "SELECT text, record_id FROM document_chunks WHERE document_id = :d AND is_current", d=doc)
    assert len(fresh) == 1 and "TAMPERED" not in fresh[0][0] and fresh[0][1] == "APX-N-001" and "Mechanical seal" in fresh[0][0]  # re-parsed from the retained original record
    assert client.delete(f"/api/v1/documents/{doc}", headers=world["sup"]).status_code == 200
    assert worker.drain(worker_db, FAST) == ["cleanup_completed"]
    assert sql(owner_engine, "SELECT count(*) FROM document_sources WHERE document_id = :d", d=doc)[0][0] == 0


def test_sync_provenance_and_documents_are_isolated_between_tenants(client, world, records_server, owner_engine, worker_db, monkeypatch):
    cid = connector(client, world, records_server, dataset="apex")
    other = make_tenant(owner_engine, "syncmeridian")
    theirs = {"adm": login(client, other, "tenant_admin"), "sup": login(client, other, "maintenance_supervisor"), "eng": login(client, other, "support_engineer"), "t": other}
    their_cid = connector(client, theirs, records_server, dataset="meridian", name="meridian-bulletins")
    a, b = start(client, world, cid), start(client, theirs, their_cid)
    worker.drain(worker_db, FAST)
    assert client.get(f"/api/v1/ingestion/jobs/{a['id']}", headers=world["eng"]).json()["sync"]["created"] == 7
    assert client.get(f"/api/v1/ingestion/jobs/{b['id']}", headers=theirs["eng"]).json()["sync"]["created"] == 5
    for tenant, own in ((world["t"], "APX-N"), (other, "MER-B")):
        ids = [r[0] for r in sql(owner_engine, "SELECT source_record_id FROM connector_sync_records WHERE tenant_id = :t", t=tenant.id)]
        assert ids and all(i.startswith(own) for i in ids)
    assert not any("VH-21" in h["text"] for h in hits(client, world["eng"], "brake pad coolant leak VH-2101"))  # Meridian content is invisible to Apex retrieval
    assert any("VH-21" in h["text"] for h in hits(client, theirs["eng"], "brake pad coolant leak VH-2101"))
    with worker_db.session(tenant_id=other.id) as s:  # the worker's tenant context for Meridian shows no Apex provenance
        assert s.execute(text("SELECT count(*) FROM connector_sync_records WHERE source_record_id LIKE 'APX-%'")).scalar() == 0


# ----------------------------------------------------------------------------------------------------------------------- live health probe through the API
def test_the_health_probe_is_opt_in_makes_one_real_request_and_reports_classes(client, world, records_server, owner_engine):
    cid = connector(client, world, records_server)
    plain = client.get("/api/v1/connectors/health", headers=world["adm"]).json()["items"]
    assert not records_server.state.requests and all("live_probe" not in i for i in plain)  # without probe=true: no network call, response unchanged
    assert [i["probe"] for i in plain][0].startswith("none")
    probed = client.get("/api/v1/connectors/health", headers=world["adm"], params={"probe": "true"}).json()["items"]
    item = next(i for i in probed if i["id"] == cid)
    assert item["live_probe"]["status"] == "ok" and item["status"] == "ok" and item["live_probe"]["duration_ms"] >= 0 and len(records_server.state.requests) == 1
    assert records_server.state.requests[0]["params"]["limit"] == 1 and sql(owner_engine, "SELECT count(*) FROM documents WHERE tenant_id = :t", t=world["t"].id)[0][0] == 0  # nothing ingested
    inject(records_server, "503")
    assert next(i for i in client.get("/api/v1/connectors/health", headers=world["adm"], params={"probe": "true"}).json()["items"] if i["id"] == cid)["live_probe"]["status"] == "upstream_error"
    wrong = connector(client, world, records_server, name="probe-no-secret", secret=None)  # the source requires a key and this connector sends none
    statuses = {i["id"]: i for i in client.get("/api/v1/connectors/health", headers=world["adm"], params={"probe": "true"}).json()["items"]}
    assert statuses[wrong]["live_probe"]["status"] == "authentication" and statuses[wrong]["status"] == "degraded"
    for who in ("eng", "sup", "aud"):
        assert client.get("/api/v1/connectors/health", headers=world[who], params={"probe": "true"}).status_code == 403
    actions = [a["action"] for a in client.get("/api/v1/audit", headers=world["aud"], params={"limit": 100}).json()["items"]]
    assert actions.count("connector.probed") >= 3 and RECORDS_KEY not in json.dumps(statuses)


def test_audit_records_the_sync_without_content_or_credentials(client, world, records_server, owner_engine, worker_db):
    cid = connector(client, world, records_server)
    job = start(client, world, cid)
    finish(client, world, worker_db, job["id"])
    items = client.get("/api/v1/audit", headers=world["aud"], params={"limit": 100}).json()["items"]
    actions = {a["action"] for a in items}
    assert {"connector.sync_requested", "connector.record_ingested", "connector.sync_completed", "ingestion.job_created", "ingestion.job_completed"} <= actions
    blob = json.dumps(items)
    assert "Mechanical seal" not in blob and RECORDS_KEY not in blob and "weeps" not in blob  # counts, ids and hashes only
    completed = next(a for a in items if a["action"] == "connector.sync_completed")
    assert completed["details"]["created"] == 7 and completed["details"]["outcome"] == "synced"
