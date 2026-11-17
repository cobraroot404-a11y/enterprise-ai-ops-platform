# ruff: noqa: F811  (pytest fixtures imported by name, then used as parameters)
"""V41-21 measurement list: INTEGRATION SUCCESS RATE over a defined suite (original specification Part 21).

THE DEFINED SUITE. Nominal integration runs against healthy local sources, through the real application, worker, database and retrieval:
  * REST pull: cursor, offset and page pagination, each over both fictional customers' record sets (6 runs)
  * CSV pull over both record sets (2 runs)
  * signed webhook deliveries: 6 distinct valid deliveries to 2 endpoints
A run SUCCEEDS only if the request is accepted, the durable job reaches COMPLETED with outcome `synced`, every record the source holds was seen and created, and the records exist as
active, chunked (therefore searchable) documents of the tenant. The rate is succeeded / attempted. Failure injection is NOT part of this suite (recovery is measured by tests/fault_injection/test_recovery_rate.py).
Adversarial and invalid inputs are NOT counted as failures here: their correct rejection is asserted elsewhere (test_webhooks.py, test_rest_sync.py).

Run: python -m pytest backend/tests/test_integration_success_rate.py -q      (set INTEGRATION_REPORT=1 to write evaluation/integration/integration-success-rate-report.json)
Limits: same-author suite, local mock sources, deterministic AI backends, 14 runs (one miss is 7%), no confidence claim."""
import datetime as dt
import json
import os
import sys
import time
import uuid
from pathlib import Path

import pytest
from app.workflows import worker
from sqlalchemy import text
from support import RECORDS_KEY
from test_ingestion_jobs import FAST, db_clean, world  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "evaluation" / "integration" / "integration-success-rate-report.json"
TARGET = 0.95
ENV = "INTEGRATION_RATE_KEY"
HOOK_ENV = "INTEGRATION_RATE_HOOK_SECRET"
HOOK_SECRET = "whsec-integration-rate-secret-0123456789abcdef"
RESULTS: list[dict] = []

REST_RUNS = [(mode, dataset) for dataset in ("apex", "meridian") for mode in ("cursor", "offset", "page")]
CSV_RUNS = ["apex", "meridian"]
WEBHOOK_RUNS = [(endpoint, n) for endpoint in (1, 2) for n in (1, 2, 3)]


@pytest.fixture(autouse=True)
def fresh_sources(records_server, monkeypatch):
    import records_app
    from app.connectors.ratelimit import LIMITERS

    with records_server.state.lock:
        records_server.state.failures.clear()
        records_server.state.requests.clear()
        records_server.state.datasets["apex"] = records_app._apex()
        records_server.state.datasets["meridian"] = records_app._meridian()
    LIMITERS.clear()
    monkeypatch.setenv(ENV, RECORDS_KEY)
    monkeypatch.setenv(HOOK_ENV, HOOK_SECRET)


def record(kind: str, run_id: str, succeeded: bool, **detail) -> None:
    RESULTS.append({"class": kind, "run": run_id, "succeeded": succeeded, **detail})


def job_of(client, world, job_id) -> dict:
    return client.get(f"/api/v1/ingestion/jobs/{job_id}", headers=world["eng"]).json()


def pull_succeeded(client, world, worker_db, job_id, expected: int, owner_engine) -> tuple[bool, dict]:
    worker.drain(worker_db, FAST)
    done = job_of(client, world, job_id)
    sync = done.get("sync") or {}
    with owner_engine.connect() as c:
        chunked = c.execute(text("SELECT count(DISTINCT d.id) FROM documents d JOIN document_chunks k ON k.document_id = d.id "
                                 "WHERE d.tenant_id = :t AND d.lifecycle_status = 'active'"), {"t": world["t"].id}).scalar()
    ok = done["status"] == "COMPLETED" and done["outcome"] == "synced" and sync.get("seen") == expected and sync.get("created") == expected and chunked >= expected
    return ok, done


def dataset_size(records_server, dataset: str) -> int:
    with records_server.state.lock:
        return len(records_server.state.datasets[dataset])


@pytest.mark.parametrize("mode,dataset", REST_RUNS, ids=[f"rest-{m}-{d}" for m, d in REST_RUNS])
def test_rest_pull_run(mode, dataset, client, world, records_server, worker_db, owner_engine):
    pagination = {"mode": mode, "page_size": 3}
    pagination.update({"has_more_field": "has_more"} if mode == "cursor" else {"total_field": "total"})
    config = {"records": {"path": f"/v1/{dataset}/{mode}", "id_field": "id", "version_field": "updated_at", "required_fields": ["title", "body"], "pagination": pagination,
                          "rate": {"requests_per_second": 50, "burst": 20}}}
    created = client.post("/api/v1/connectors", headers=world["adm"], json={"kind": "rest", "name": f"rate-{mode}-{dataset}-{uuid.uuid4().hex[:5]}", "base_url": records_server.url,
                                                                           "secret_ref": ENV, "config": config})
    accepted = created.status_code == 201
    ok, done = False, {}
    if accepted:
        started = client.post(f"/api/v1/connectors/{created.json()['id']}/sync", headers=world["sup"])
        accepted = started.status_code == 202
        if accepted:
            ok, done = pull_succeeded(client, world, worker_db, started.json()["id"], dataset_size(records_server, dataset), owner_engine)
    record("rest", f"{mode}-{dataset}", accepted and ok, status=done.get("status"), outcome=done.get("outcome"), sync=done.get("sync"))
    assert accepted and ok, RESULTS[-1]


@pytest.mark.parametrize("dataset", CSV_RUNS, ids=[f"csv-{d}" for d in CSV_RUNS])
def test_csv_pull_run(dataset, client, world, records_server, worker_db, owner_engine):
    config = {"csv": {"path": f"/v1/{dataset}/csv", "id_field": "id", "required_fields": ["title", "body"], "rate": {"requests_per_second": 50, "burst": 20}}}
    created = client.post("/api/v1/connectors", headers=world["adm"], json={"kind": "csv", "name": f"rate-csv-{dataset}-{uuid.uuid4().hex[:5]}", "base_url": records_server.url,
                                                                           "secret_ref": ENV, "config": config})
    accepted = created.status_code == 201
    ok, done = False, {}
    if accepted:
        started = client.post(f"/api/v1/connectors/{created.json()['id']}/sync", headers=world["sup"])
        accepted = started.status_code == 202
        if accepted:
            ok, done = pull_succeeded(client, world, worker_db, started.json()["id"], dataset_size(records_server, dataset), owner_engine)
    record("csv", dataset, accepted and ok, status=done.get("status"), outcome=done.get("outcome"), sync=done.get("sync"))
    assert accepted and ok, RESULTS[-1]


@pytest.mark.parametrize("endpoint,n", WEBHOOK_RUNS, ids=[f"webhook-ep{e}-delivery{n}" for e, n in WEBHOOK_RUNS])
def test_signed_webhook_run(endpoint, n, client, world, worker_db, owner_engine):
    from app.ingestion import webhooks

    cfg = {"id_field": "id", "version_field": "updated_at", "required_fields": ["title", "body"], "document_kind": "other", "max_records": 10}
    created = client.post("/api/v1/webhook-endpoints", headers=world["adm"], json={"name": f"rate-hook-{endpoint}-{n}-{uuid.uuid4().hex[:5]}", "secret_ref": HOOK_ENV, "config": cfg})
    accepted, ok, done = created.status_code == 201, False, {}
    if accepted:
        body = json.dumps({"id": f"RATE-{endpoint}-{n}", "title": f"Bulletin {endpoint}-{n}", "body": f"Mechanical seal on pump P-101 weeps under load ({endpoint}-{n}).",
                           "updated_at": "v1"}).encode()
        ts, did = str(int(time.time())), f"d-{uuid.uuid4().hex[:16]}"
        r = client.post(f"/api/v1/webhooks/{created.json()['id']}", content=body, headers={"Content-Type": "application/json", "X-Webhook-Timestamp": ts, "X-Webhook-Delivery-Id": did,
                                                                                           "X-Webhook-Signature": webhooks.sign(HOOK_SECRET, ts, did, body)})
        accepted = r.status_code == 202
        if accepted:
            ok, done = pull_succeeded(client, world, worker_db, r.json()["job_id"], 1, owner_engine)
    record("webhook", f"endpoint{endpoint}-delivery{n}", accepted and ok, status=done.get("status"), outcome=done.get("outcome"), sync=done.get("sync"))
    assert accepted and ok, RESULTS[-1]


def test_the_success_rate_over_the_defined_suite_meets_the_target_and_is_reported():
    expected = len(REST_RUNS) + len(CSV_RUNS) + len(WEBHOOK_RUNS)
    if len(RESULTS) != expected:
        pytest.skip("the whole suite must run in one session to compute a rate (do not select single cases)")
    succeeded = sum(r["succeeded"] for r in RESULTS)
    by_class = {k: {"attempted": sum(r["class"] == k for r in RESULTS), "succeeded": sum(r["class"] == k and r["succeeded"] for r in RESULTS)} for k in ("rest", "csv", "webhook")}
    rate = succeeded / len(RESULTS)
    report = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "command": "INTEGRATION_REPORT=1 python -m pytest backend/tests/test_integration_success_rate.py -q",
              "definition": "see the module docstring: a run succeeds iff the request is accepted, the durable job COMPLETES as synced, every source record was seen and created",
              "environment": {"backends": "deterministic test-only AI backends", "sources": "local mock records service and signed local deliveries", "python": sys.version.split()[0]},
              "denominator": len(RESULTS), "succeeded": succeeded, "rate": round(rate, 4), "target": TARGET, "target_met": rate >= TARGET, "by_class": by_class,
              "limits": "same-author suite; 14 nominal runs so the rate is coarse; local mocks; not a production measurement; failure handling is measured separately",
              "runs": sorted(RESULTS, key=lambda r: (r["class"], r["run"]))}
    if os.environ.get("INTEGRATION_REPORT") == "1":
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    assert rate >= TARGET, report
