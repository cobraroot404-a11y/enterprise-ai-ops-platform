"""Batch 11B: signed inbound webhooks (V41-12.01 webhook part, V41-11.01).

The real application, database, RLS, worker and ingestion pipeline; deliveries are produced by the test as a sender would (HMAC-SHA256 over `timestamp.delivery_id.raw_body`). Failures
(tampering, replay, stale timestamps, floods, a "crashed" worker) are controlled injections, never real outages."""
import json
import threading
import time
import uuid

import pytest
from app.ingestion import webhooks
from app.workflows import worker
from sqlalchemy import text
from support import login, make_tenant
from test_ingestion_jobs import FAST, Crash, db_clean, expire_lease, hits, job_list, make_due, run, sql, world  # noqa: F401

SECRET = "whsec-test-secret-0123456789abcdef"
ENV = "WEBHOOK_TEST_SECRET"
NEW_ENV = "WEBHOOK_TEST_SECRET_NEXT"
NEW_SECRET = "whsec-rotated-secret-fedcba9876543210"
CFG = {"id_field": "id", "version_field": "updated_at", "required_fields": ["title", "body"], "document_kind": "other", "max_records": 10}
RECORD = {"id": "WH-001", "title": "Pump seal bulletin", "body": "Mechanical seal on pump P-101 weeps under load; replace the seal.", "updated_at": "v1"}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    from app.connectors.ratelimit import LIMITERS
    LIMITERS.clear()
    monkeypatch.setenv(ENV, SECRET)
    monkeypatch.delenv(NEW_ENV, raising=False)


def make_endpoint(client, world, name=None, secret_ref=ENV, config=None):
    r = client.post("/api/v1/webhook-endpoints", headers=world["adm"], json={"name": name or f"hook-{uuid.uuid4().hex[:6]}", "secret_ref": secret_ref, "config": config or CFG})
    assert r.status_code == 201, r.text
    return r.json()


def deliver(client, endpoint_id, payload, *, secret=SECRET, timestamp=None, delivery_id=None, signature=None, content_type="application/json", raw=None, extra=None, omit=()):
    body = raw if raw is not None else json.dumps(payload).encode()
    ts = str(int(time.time()) if timestamp is None else timestamp)
    did = delivery_id or f"d-{uuid.uuid4().hex[:16]}"
    headers = {"Content-Type": content_type, "X-Webhook-Timestamp": ts, "X-Webhook-Delivery-Id": did,
               "X-Webhook-Signature": signature or webhooks.sign(secret, ts, did, body), **(extra or {})}
    for h in omit:
        headers.pop(h, None)
    r = client.post(f"/api/v1/webhooks/{endpoint_id}", content=body, headers=headers)
    r.delivery_id = did
    return r


def counts(owner_engine, tenant):
    return sql(owner_engine, "SELECT (SELECT count(*) FROM webhook_deliveries WHERE tenant_id = :t), (SELECT count(*) FROM ingestion_jobs WHERE tenant_id = :t AND job_type = 'webhook'), "
                             "(SELECT count(*) FROM document_sources WHERE tenant_id = :t), (SELECT count(*) FROM documents WHERE tenant_id = :t)", t=tenant)[0]


def docs(owner_engine, world):
    return sql(owner_engine, "SELECT filename, current_version FROM documents WHERE tenant_id = :t AND lifecycle_status = 'active' AND filename LIKE 'webhook-%' ORDER BY filename", t=world["t"].id)


# ----------------------------------------------------------------------------------------------------------------------- endpoint provisioning
def test_only_a_tenant_administrator_provisions_endpoints_and_no_secret_is_ever_returned(client, world, owner_engine):
    ep = make_endpoint(client, world, name="apex-bulletins")
    assert ep["receive_path"] == f"/api/v1/webhooks/{ep['id']}" and ep["status"] == "active" and ep["secret_configured"] is True and ep["has_previous_secret"] is False
    assert SECRET not in json.dumps(ep) and "secret_ref" not in ep  # only whether the server has the variable
    body = {"name": "x-hook", "secret_ref": ENV, "config": CFG}
    for who in ("eng", "sup", "aud"):
        assert client.post("/api/v1/webhook-endpoints", headers=world[who], json=body).status_code == 403
        assert client.get("/api/v1/webhook-endpoints", headers=world[who]).status_code == 403
    assert client.post("/api/v1/webhook-endpoints", json=body).status_code == 401
    assert client.post("/api/v1/webhook-endpoints", headers=world["adm"], json={**body, "name": "apex-bulletins"}).status_code == 409
    for bad in ({"secret_ref": "lower_case"}, {"secret_ref": SECRET}, {"config": {"id_field": "bad field"}}, {"config": {}}, {"config": {**CFG, "max_records": 100000}}, {"config": {**CFG, "extra": 1}}, {"name": "!"}):
        assert client.post("/api/v1/webhook-endpoints", headers=world["adm"], json={**body, "name": f"n-{uuid.uuid4().hex[:5]}", **bad}).status_code == 422
    listed = client.get("/api/v1/webhook-endpoints", headers=world["adm"]).json()["items"]
    assert [e["name"] for e in listed] == ["apex-bulletins"]
    actions = [a["action"] for a in client.get("/api/v1/audit", headers=world["aud"], params={"limit": 50}).json()["items"]]
    assert "webhook.endpoint_created" in actions


def test_endpoints_are_tenant_private(client, world, owner_engine):
    ep = make_endpoint(client, world)
    other = make_tenant(owner_engine, "whother")
    theirs = login(client, other, "tenant_admin")
    assert client.get("/api/v1/webhook-endpoints", headers=theirs).json()["items"] == []
    assert client.patch(f"/api/v1/webhook-endpoints/{ep['id']}", headers=theirs, json={"status": "disabled"}).status_code == 404
    assert client.patch("/api/v1/webhook-endpoints/00000000-0000-0000-0000-000000000000", headers=theirs, json={"status": "disabled"}).status_code == 404


def test_disable_enable_and_rotation_with_an_overlap_window(client, world, owner_engine, monkeypatch):
    ep = make_endpoint(client, world)
    url = ep["id"]
    assert deliver(client, url, RECORD).status_code == 202
    assert client.patch(f"/api/v1/webhook-endpoints/{url}", headers=world["sup"], json={"status": "disabled"}).status_code == 403
    assert client.patch(f"/api/v1/webhook-endpoints/{url}", headers=world["adm"], json={}).status_code == 422  # nothing to change
    assert client.patch(f"/api/v1/webhook-endpoints/{url}", headers=world["adm"], json={"status": "disabled"}).json()["status"] == "disabled"
    assert deliver(client, url, RECORD).status_code == 401  # a disabled endpoint looks like a bad signature
    assert client.patch(f"/api/v1/webhook-endpoints/{url}", headers=world["adm"], json={"status": "active"}).json()["status"] == "active"
    assert deliver(client, url, RECORD).status_code == 202
    # rotation: the new variable must exist, the old one stays acceptable until it is dropped
    monkeypatch.setenv(NEW_ENV, NEW_SECRET)
    rotated = client.patch(f"/api/v1/webhook-endpoints/{url}", headers=world["adm"], json={"secret_ref": NEW_ENV}).json()
    assert rotated["has_previous_secret"] is True and NEW_SECRET not in json.dumps(rotated)
    assert deliver(client, url, RECORD, secret=NEW_SECRET).status_code == 202 and deliver(client, url, RECORD, secret=SECRET).status_code == 202  # both during the overlap
    assert client.patch(f"/api/v1/webhook-endpoints/{url}", headers=world["adm"], json={"secret_ref": ENV}).status_code == 409  # cannot swap straight back to the previous reference
    assert client.patch(f"/api/v1/webhook-endpoints/{url}", headers=world["adm"], json={"drop_previous_secret": True}).json()["has_previous_secret"] is False
    assert deliver(client, url, RECORD, secret=SECRET).status_code == 401 and deliver(client, url, RECORD, secret=NEW_SECRET).status_code == 202  # the old secret no longer works
    monkeypatch.delenv(NEW_ENV)  # the server lost the current secret: fail closed, never accept
    bad = deliver(client, url, RECORD, secret=NEW_SECRET)
    assert bad.status_code == 503 and bad.json()["error"]["code"] == "webhook_not_configured"
    changes = [a["details"]["changes"] for a in client.get("/api/v1/audit", headers=world["aud"], params={"limit": 100}).json()["items"] if a["action"] == "webhook.endpoint_updated"]
    assert ["secret_rotated"] in changes and ["previous_secret_dropped"] in changes and ["status_disabled"] in changes


# ----------------------------------------------------------------------------------------------------------------------- authentication
def test_a_valid_delivery_is_durably_queued_and_202_does_not_mean_processed(client, world, owner_engine, worker_db):
    ep = make_endpoint(client, world)
    r = deliver(client, ep["id"], {"items": [RECORD]} if False else RECORD)
    assert r.status_code == 202 and r.headers["X-Correlation-ID"]
    accepted = r.json()
    assert accepted["status"] == "QUEUED" and accepted["delivery_id"] == r.delivery_id and set(accepted) == {"delivery_id", "job_id", "status"}
    assert docs(owner_engine, world) == []  # nothing was processed by the request itself
    job = client.get(f"/api/v1/ingestion/jobs/{accepted['job_id']}", headers=world["eng"]).json()
    assert job["job_type"] == "webhook" and job["status"] == "QUEUED" and job["endpoint_id"] == ep["id"] and job["connector_id"] is None
    assert counts(owner_engine, world["t"].id) == (1, 1, 1, 0)  # delivery ledger row, job, the raw body as a retained original; no document yet
    assert worker.drain(worker_db, FAST) == ["ingestion_completed"]
    done = client.get(f"/api/v1/ingestion/jobs/{accepted['job_id']}", headers=world["eng"]).json()
    assert done["status"] == "COMPLETED" and done["outcome"] == "synced" and done["sync"]["created"] == 1 and done["attempts"] == 1
    assert [d[0] for d in docs(owner_engine, world)] == [f"webhook-{ep['name']}-WH-001.json"]
    assert sql(owner_engine, "SELECT c.record_id FROM document_chunks c JOIN documents d ON d.id = c.document_id WHERE d.tenant_id = :t AND d.filename LIKE 'webhook-%'", t=world["t"].id)[0][0] == "WH-001"
    row = sql(owner_engine, "SELECT endpoint_id::text, connector_id, source_record_id, status FROM connector_sync_records WHERE tenant_id = :t", t=world["t"].id)[0]
    assert row == (ep["id"], None, "WH-001", "active")
    assert counts(owner_engine, world["t"].id)[2] == 1  # the raw delivery body was released after processing; only the record's own original remains
    assert any("seal" in h["text"].lower() for h in hits(client, world["eng"], "mechanical seal weeps pump P-101"))


def test_every_authentication_failure_is_the_same_401_and_stores_nothing(client, world, owner_engine):
    ep = make_endpoint(client, world)
    other = make_tenant(owner_engine, "whforeign")
    before = counts(owner_engine, world["t"].id)
    body = json.dumps(RECORD).encode()
    ts = str(int(time.time()))
    did = "delivery-0001"
    good = webhooks.sign(SECRET, ts, did, body)
    cases = {
        "wrong secret": deliver(client, ep["id"], RECORD, secret="not-the-secret"),
        "tampered body": deliver(client, ep["id"], None, raw=body.replace(b"P-101", b"P-999"), signature=good, timestamp=ts, delivery_id=did),
        "tampered delivery id": deliver(client, ep["id"], None, raw=body, signature=good, timestamp=ts, delivery_id="delivery-0002"),
        "tampered timestamp": deliver(client, ep["id"], None, raw=body, signature=good, timestamp=int(ts) + 1, delivery_id=did),
        "missing signature": deliver(client, ep["id"], RECORD, omit=("X-Webhook-Signature",)),
        "missing timestamp": deliver(client, ep["id"], RECORD, omit=("X-Webhook-Timestamp",)),
        "missing delivery id": deliver(client, ep["id"], RECORD, omit=("X-Webhook-Delivery-Id",)),
        "bare hex signature": deliver(client, ep["id"], None, raw=body, signature=good[7:], timestamp=ts, delivery_id=did),
        "short delivery id": deliver(client, ep["id"], RECORD, delivery_id="x"),
        "non numeric timestamp": deliver(client, ep["id"], RECORD, timestamp="yesterday", signature="sha256=" + "0" * 64),
        "unknown endpoint": deliver(client, str(uuid.uuid4()), RECORD),
    }
    shapes = set()
    for name, r in cases.items():
        assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_signature", name
        shapes.add(json.dumps({k: v for k, v in r.json()["error"].items() if k != "correlation_id"}, sort_keys=True))
    assert len(shapes) == 1  # no oracle: unknown endpoint, disabled endpoint and bad signature are indistinguishable
    assert counts(owner_engine, world["t"].id) == before and counts(owner_engine, other.id) == (0, 0, 0, 0)  # nothing recorded, queued or stored


def test_the_timestamp_window_applies_only_after_the_signature_is_proven(client, world, owner_engine):
    ep = make_endpoint(client, world)
    now = int(time.time())
    for offset in (-webhooks.TOLERANCE_SECONDS - 5, webhooks.TOLERANCE_SECONDS + 5):
        r = deliver(client, ep["id"], RECORD, timestamp=now + offset)
        assert r.status_code == 401 and r.json()["error"]["code"] == "timestamp_out_of_window"  # validly signed but outside the window
    assert deliver(client, ep["id"], RECORD, timestamp=now - webhooks.TOLERANCE_SECONDS + 20).status_code == 202  # inside the window
    assert deliver(client, ep["id"], RECORD, timestamp=now - 10_000, secret="forged").json()["error"]["code"] == "invalid_signature"  # an anonymous caller learns nothing about the window
    assert sql(owner_engine, "SELECT count(*) FROM webhook_deliveries WHERE tenant_id = :t", t=world["t"].id)[0][0] == 1  # stale deliveries did not consume anything


def test_the_tenant_comes_only_from_the_endpoint_never_from_the_request(client, world, owner_engine, worker_db):
    ep = make_endpoint(client, world)
    other = make_tenant(owner_engine, "whvictim")
    record = {**RECORD, "tenant_id": str(other.id), "tenant": other.slug}
    r = deliver(client, ep["id"], record, extra={"X-Tenant-Id": str(other.id), "X-Tenant": other.slug})
    assert r.status_code == 202
    worker.drain(worker_db, FAST)
    assert len(docs(owner_engine, world)) == 1  # in the endpoint's tenant
    assert sql(owner_engine, "SELECT count(*) FROM documents WHERE tenant_id = :t", t=other.id)[0][0] == 0
    assert counts(owner_engine, other.id) == (0, 0, 0, 0)
    assert sql(owner_engine, "SELECT tenant_id::text FROM webhook_deliveries WHERE delivery_id = :d", d=r.delivery_id)[0][0] == str(world["t"].id)


def test_a_signature_for_one_endpoint_does_not_work_on_another(client, world, owner_engine, monkeypatch):
    monkeypatch.setenv("WEBHOOK_OTHER_SECRET", "a-completely-different-signing-secret-value")
    a, b = make_endpoint(client, world), make_endpoint(client, world, secret_ref="WEBHOOK_OTHER_SECRET")
    assert deliver(client, a["id"], RECORD, secret="a-completely-different-signing-secret-value").status_code == 401
    assert deliver(client, b["id"], RECORD, secret=SECRET).status_code == 401
    assert deliver(client, b["id"], RECORD, secret="a-completely-different-signing-secret-value").status_code == 202


# ----------------------------------------------------------------------------------------------------------------------- replay protection
def test_a_replayed_delivery_is_rejected_durably_and_the_work_is_done_once(client, world, owner_engine, worker_db):
    ep = make_endpoint(client, world)
    first = deliver(client, ep["id"], RECORD, delivery_id="delivery-replay-1")
    assert first.status_code == 202
    for body in (RECORD, {**RECORD, "body": "a different body under the same delivery id"}):
        r = deliver(client, ep["id"], body, delivery_id="delivery-replay-1")  # even a freshly signed copy, even with a different body
        assert r.status_code == 409 and r.json()["error"]["code"] == "webhook_replayed"
    assert counts(owner_engine, world["t"].id)[:2] == (1, 1)
    worker.drain(worker_db, FAST)
    assert len(docs(owner_engine, world)) == 1
    other_ep = make_endpoint(client, world)  # the same delivery id on a different endpoint is independent
    assert deliver(client, other_ep["id"], RECORD, delivery_id="delivery-replay-1").status_code == 202
    actions = [a["action"] for a in client.get("/api/v1/audit", headers=world["aud"], params={"limit": 100}).json()["items"]]
    assert actions.count("webhook.delivery_replayed") == 2 and actions.count("webhook.delivery_accepted") == 2


def test_concurrent_identical_deliveries_produce_exactly_one_job(client, world, owner_engine):
    from starlette.testclient import TestClient
    ep = make_endpoint(client, world)
    body = json.dumps(RECORD).encode()
    ts, did = str(int(time.time())), "delivery-concurrent-1"
    sig = webhooks.sign(SECRET, ts, did, body)
    results = []

    def go():
        c = TestClient(client.app)
        r = c.post(f"/api/v1/webhooks/{ep['id']}", content=body, headers={"Content-Type": "application/json", "X-Webhook-Timestamp": ts, "X-Webhook-Delivery-Id": did, "X-Webhook-Signature": sig})
        results.append(r.status_code)
    threads = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [202] + [409] * 7
    assert counts(owner_engine, world["t"].id)[:2] == (1, 1)


def test_the_replay_ledger_is_append_only_for_the_application(client, world, owner_engine, app_db):
    ep = make_endpoint(client, world)
    deliver(client, ep["id"], RECORD)
    from sqlalchemy.exc import DBAPIError
    with app_db.session(tenant_id=world["t"].id) as s, pytest.raises(DBAPIError):
        s.execute(text("DELETE FROM webhook_deliveries"))
    with app_db.session(tenant_id=world["t"].id) as s, pytest.raises(DBAPIError):
        s.execute(text("UPDATE webhook_deliveries SET delivery_id = 'rewritten-id-00'"))


# ----------------------------------------------------------------------------------------------------------------------- size, type, payload
def test_oversized_and_wrongly_typed_deliveries_are_refused_before_anything_else(client, world, owner_engine):
    ep = make_endpoint(client, world)
    big = b'{"id":"X","title":"t","body":"' + b"x" * (webhooks.MAX_BODY_BYTES + 10) + b'"}'
    r = deliver(client, ep["id"], None, raw=big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"
    streamed = client.post(f"/api/v1/webhooks/{ep['id']}", content=(big[i:i + 4096] for i in range(0, len(big), 4096)), headers={"Content-Type": "application/json"})  # chunked, no declared length
    assert streamed.status_code == 413
    assert deliver(client, ep["id"], RECORD, content_type="text/plain").status_code == 415
    assert deliver(client, ep["id"], RECORD, content_type="application/x-www-form-urlencoded").status_code == 415
    assert deliver(client, ep["id"], RECORD, content_type="application/json; charset=utf-8").status_code == 202
    assert counts(owner_engine, world["t"].id)[0] == 1


def test_payloads_that_can_never_be_processed_are_rejected_after_authentication_and_consume_the_delivery_id(client, world, owner_engine):
    ep = make_endpoint(client, world, config={**CFG, "max_records": 2})
    cases = {"not json": b"{broken", "scalar": b"42", "list of scalars": b"[1, 2]", "empty list": b"[]", "too many records": json.dumps([RECORD, RECORD, RECORD]).encode()}
    for name, raw in cases.items():
        r = deliver(client, ep["id"], None, raw=raw, delivery_id=f"delivery-bad-{name.replace(' ', '-')}")
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_payload", name
    assert counts(owner_engine, world["t"].id) == (len(cases), 0, 0, 0)  # recorded as rejected deliveries; no job, no stored body
    again = deliver(client, ep["id"], RECORD, delivery_id="delivery-bad-not-json")  # the id was consumed: a corrected payload needs a new delivery id
    assert again.status_code == 409
    actions = [a["action"] for a in client.get("/api/v1/audit", headers=world["aud"], params={"limit": 100}).json()["items"]]
    assert actions.count("webhook.delivery_rejected") == len(cases)
    nested = make_endpoint(client, world, config={**CFG, "record_path": "items"})
    assert deliver(client, nested["id"], {"other": []}).status_code == 422
    assert deliver(client, nested["id"], {"items": [RECORD]}).status_code == 202


def test_a_flood_is_limited_per_endpoint_without_touching_other_endpoints(client, world, owner_engine, monkeypatch):
    monkeypatch.setattr(webhooks, "RATE_BURST", 3)
    monkeypatch.setattr(webhooks, "RATE_PER_SECOND", 0.2)
    a, b = make_endpoint(client, world), make_endpoint(client, world)
    statuses = [deliver(client, a["id"], RECORD).status_code for _ in range(6)]
    assert statuses[:3] == [202, 202, 202] and set(statuses[3:]) == {429}
    limited = deliver(client, a["id"], RECORD)
    assert limited.json()["error"]["code"] == "webhook_rate_limited" and limited.headers["Retry-After"]
    assert deliver(client, b["id"], RECORD).status_code == 202  # another endpoint is unaffected


# ----------------------------------------------------------------------------------------------------------------------- processing semantics
def test_redeliveries_are_idempotent_updates_become_versions_and_deletions_are_tombstones(client, world, owner_engine, worker_db):
    ep = make_endpoint(client, world)
    batch = [RECORD, {"id": "WH-002", "title": "Valve note", "body": "Gland packing on valve V-330 leaks slightly.", "updated_at": "v1"}]
    first = deliver(client, ep["id"], batch).json()
    worker.drain(worker_db, FAST)
    assert client.get(f"/api/v1/ingestion/jobs/{first['job_id']}", headers=world["eng"]).json()["sync"]["created"] == 2
    again = deliver(client, ep["id"], batch).json()  # the sender delivers the same records again under a new delivery id
    worker.drain(worker_db, FAST)
    s2 = client.get(f"/api/v1/ingestion/jobs/{again['job_id']}", headers=world["eng"]).json()["sync"]
    assert s2["unchanged"] == 2 and s2["created"] == 0 and len(docs(owner_engine, world)) == 2
    changed = deliver(client, ep["id"], [{**RECORD, "body": "Seal replaced; pump P-101 is dry now.", "updated_at": "v2"}]).json()
    worker.drain(worker_db, FAST)
    assert client.get(f"/api/v1/ingestion/jobs/{changed['job_id']}", headers=world["eng"]).json()["sync"]["updated"] == 1
    assert sql(owner_engine, "SELECT current_version FROM documents WHERE tenant_id = :t AND filename LIKE '%WH-001%'", t=world["t"].id)[0][0] == 2
    doc = sql(owner_engine, "SELECT document_id::text FROM connector_sync_records WHERE tenant_id = :t AND source_record_id = 'WH-002'", t=world["t"].id)[0][0]
    assert client.delete(f"/api/v1/documents/{doc}", headers=world["sup"]).status_code == 200
    worker.drain(worker_db, FAST)
    revived = deliver(client, ep["id"], [{"id": "WH-002", "title": "Valve note", "body": "Completely new content after deletion.", "updated_at": "v9"}]).json()
    worker.drain(worker_db, FAST)
    s3 = client.get(f"/api/v1/ingestion/jobs/{revived['job_id']}", headers=world["eng"]).json()
    assert s3["sync"]["tombstoned_changed"] == 1 and s3["sync"]["created"] == 0 and client.get(f"/api/v1/documents/{doc}", headers=world["eng"]).status_code == 404
    assert len(docs(owner_engine, world)) == 1  # the customer's deletion was not reversed by a changed delivery


def test_invalid_records_are_counted_or_fail_the_job_by_policy(client, world, owner_engine, worker_db):
    ep = make_endpoint(client, world)
    mixed = [RECORD, {"id": "WH-BAD", "title": "", "body": "no title"}, {"title": "t", "body": "no id"}]
    job = deliver(client, ep["id"], mixed).json()
    worker.drain(worker_db, FAST)
    done = client.get(f"/api/v1/ingestion/jobs/{job['job_id']}", headers=world["eng"]).json()
    assert done["status"] == "COMPLETED" and done["outcome"] == "synced_with_rejections" and done["sync"]["created"] == 1 and done["sync"]["invalid"] == 2
    strict = make_endpoint(client, world, config={**CFG, "reject_policy": "fail"})
    failed = deliver(client, strict["id"], mixed).json()
    worker.drain(worker_db, FAST)
    j = client.get(f"/api/v1/ingestion/jobs/{failed['job_id']}", headers=world["eng"]).json()
    assert j["status"] == "FAILED" and j["error_code"] == "source_record_invalid" and j["attempts"] == 1
    assert sql(owner_engine, "SELECT count(*) FROM document_sources s JOIN ingestion_jobs j ON j.source_id = s.id WHERE j.id = :i", i=failed["job_id"])[0][0] == 0  # a permanent failure keeps nothing


def test_a_worker_crash_mid_delivery_is_recovered_without_duplicates(client, world, owner_engine, worker_db, monkeypatch):
    from app.ingestion import sync
    ep = make_endpoint(client, world)
    batch = [{"id": f"WH-{i:03d}", "title": f"Note {i}", "body": f"Maintenance note number {i} about pump seals.", "updated_at": "v1"} for i in range(1, 5)]
    job = deliver(client, ep["id"], batch).json()
    real, calls = sync.embed_segments, {"n": 0}

    def crashing(*a, **k):
        calls["n"] += 1
        if calls["n"] == 3:
            raise Crash()
        return real(*a, **k)
    monkeypatch.setattr(sync, "embed_segments", crashing)
    with pytest.raises(Crash):
        worker.drain(worker_db, FAST)
    monkeypatch.setattr(sync, "embed_segments", real)
    assert worker.drain(worker_db, FAST) == []  # the lease is still valid
    expire_lease(owner_engine)
    assert worker.drain(worker_db, FAST) == ["ingestion_completed"]
    done = client.get(f"/api/v1/ingestion/jobs/{job['job_id']}", headers=world["eng"]).json()
    assert done["status"] == "COMPLETED" and done["attempts"] == 2 and len(docs(owner_engine, world)) == 4 and all(v == 1 for _, v in docs(owner_engine, world))
    assert done["sync"]["created"] + done["sync"]["unchanged"] == 4


def test_a_missing_or_corrupted_delivery_body_fails_permanently(client, world, owner_engine, worker_db):
    ep = make_endpoint(client, world)
    job = deliver(client, ep["id"], RECORD).json()
    run(owner_engine, "UPDATE document_sources SET content = overlay(content placing 'X'::bytea from 3 for 1) WHERE id IN (SELECT source_id FROM ingestion_jobs WHERE id = :i)", i=job["job_id"])
    worker.drain(worker_db, FAST)
    j = client.get(f"/api/v1/ingestion/jobs/{job['job_id']}", headers=world["eng"]).json()
    assert j["status"] == "FAILED" and j["error_code"] == "source_corrupted" and j["attempts"] == 1 and docs(owner_engine, world) == []


def test_credentials_and_content_never_appear_in_logs_jobs_or_audit(client, world, owner_engine, worker_db, caplog):
    ep = make_endpoint(client, world)
    with caplog.at_level("DEBUG"):
        deliver(client, ep["id"], RECORD)
        deliver(client, ep["id"], RECORD, secret="wrong-secret-value-123")
        worker.drain(worker_db, FAST)
    blob = caplog.text + json.dumps(job_list(client, world["eng"])) + json.dumps(client.get("/api/v1/audit", headers=world["aud"], params={"limit": 100}).json())
    assert SECRET not in blob and "wrong-secret-value-123" not in blob and "Mechanical seal" not in blob and "weeps under load" not in blob
    assert webhooks.sign(SECRET, "1", "d" * 8, b"x")[7:] not in blob


def test_the_receiver_accepts_only_post(client, world):
    ep = make_endpoint(client, world)
    for method in ("get", "put", "delete", "patch"):
        assert getattr(client, method)(f"/api/v1/webhooks/{ep['id']}").status_code == 405


# ----------------------------------------------------------------------------------------------------------------------- security follow-up (owner review of the two API-quality exceptions)
def test_the_timestamp_boundary_is_exact_and_the_clock_is_the_servers():
    now = 1_800_000_000.0
    webhooks.check_timestamp(int(now) - webhooks.TOLERANCE_SECONDS, now)  # exactly at the limit: accepted
    webhooks.check_timestamp(int(now) + webhooks.TOLERANCE_SECONDS, now)
    for signed in (int(now) - webhooks.TOLERANCE_SECONDS - 1, int(now) + webhooks.TOLERANCE_SECONDS + 1, 0):
        with pytest.raises(webhooks.AppError) as err:
            webhooks.check_timestamp(signed, now)
        assert err.value.code == "timestamp_out_of_window" and err.value.status_code == 401


def test_the_signature_format_is_strict_and_the_signed_string_covers_every_header_and_the_raw_bytes(client, world):
    ep = make_endpoint(client, world)
    body, ts, did = json.dumps(RECORD).encode(), str(int(time.time())), "delivery-strict-1"
    good = webhooks.sign(SECRET, ts, did, body)
    assert good.startswith("sha256=") and len(good) == 7 + 64
    variants = {"upper-case hex": "sha256=" + good[7:].upper(), "upper-case scheme": "SHA256=" + good[7:], "trailing space": good + " ", "sha1 scheme": "sha1=" + good[7:47], "empty": "", "truncated": good[:-2]}
    for name, sig in variants.items():
        r = deliver(client, ep["id"], None, raw=body, signature=sig or "sha256=", timestamp=ts, delivery_id=f"delivery-strict-{abs(hash(name)) % 10**6}")
        assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_signature", name
    assert webhooks.sign(SECRET, ts, did, body) != webhooks.sign(SECRET, ts, did, body + b" ")  # whitespace in the raw body changes the signature: the raw bytes are signed, not a parsed form
    assert webhooks.sign(SECRET, ts, did, body) != webhooks.sign(SECRET, int(ts) + 1, did, body) != webhooks.sign(SECRET, ts, "delivery-strict-2", body)
    assert deliver(client, ep["id"], None, raw=body, signature=good, timestamp=ts, delivery_id=did).status_code == 202


def test_verification_compares_in_constant_time_against_every_candidate_secret():
    import inspect
    source = inspect.getsource(webhooks.verify)
    assert "hmac.compare_digest" in source and "== m.group" not in source and "== signature" not in source  # no early-exit string comparison anywhere in the check
    assert "ok = hmac.compare_digest" in source and "or ok" in source  # every candidate (current and previous) is compared, with no short circuit
