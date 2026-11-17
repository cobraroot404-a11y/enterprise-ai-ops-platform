"""Smoke checks for the one-command demonstration (called by scripts/demo.py smoke). Everything here exercises the REAL running application through its public HTTP API
and the real browser UI; nothing is stubbed and no response is hard-coded. The external ticketing and service-desk systems are local mock services (simulated)."""
import json
import shutil
import uuid
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TENANT_FLOWS = [
    {"slug": "apex-industrial", "domain": "apex.example.test", "asset": "P-101", "type": "vibration", "name": "vibration_mm_s", "unit": "mm/s", "value": 8.4,
     "report": "Pump P-101 shows abnormal vibration at the drive end, with a grinding noise since this morning.",
     "delete_file": "maintenance_log.csv", "delete_query": "Weekly bearing inspection lubricant topped up technician Okafor"},
    {"slug": "meridian-fleet", "domain": "meridian.example.test", "asset": "VH-2101", "type": "brake_pressure", "name": "brake_pressure_psi", "unit": "psi", "value": 52.0,
     "report": "Vehicle VH-2101 shows low brake pressure with a hissing noise at the rear axle.",
     "delete_file": "telematics_alerts.csv", "delete_query": "Service brake line pressure low alert BRK-LOW"},
]


class SmokeFailure(Exception):
    pass


def call(api: str, method: str, path: str, token: str | None = None, body=None, timeout: float = 120.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(api + path, data=data, method=method, headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - local URL
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"raw": raw[:200].decode("utf-8", "replace")}


class Steps:
    def __init__(self, tenant: str):
        self.tenant, self.items = tenant, []

    def expect(self, name: str, ok: bool, detail: str = "") -> None:
        self.items.append({"tenant": self.tenant, "step": name, "ok": bool(ok), "detail": detail})
        if not ok:
            raise SmokeFailure(f"{self.tenant}: {name} failed {detail}")


def login(api, slug, domain, role, password):
    status, body = call(api, "POST", "/auth/login", body={"email": f"{role}@{domain}", "password": password, "tenant": slug})
    if status != 200:
        raise SmokeFailure(f"sign-in failed for {role}@{domain} (HTTP {status})")
    return body["access_token"]


def run_tenant(api: str, password: str, flow: dict, other: dict, tokens_other: dict) -> list[dict]:
    s = Steps(flow["slug"])
    tok = {r: login(api, flow["slug"], flow["domain"], r, password) for r in ("engineer", "supervisor", "admin", "auditor")}
    s.expect("sign in as engineer, supervisor, administrator and auditor", True)
    obs = [{"asset_id": flow["asset"], "measurement_type": flow["type"], "value": flow["value"], "unit": flow["unit"], "source": "demo smoke gauge"}]
    code, inc = call(api, "POST", "/incidents/extract", tok["engineer"], {"report_text": flow["report"], "observations": obs})
    s.expect("engineer analyses a fault report with a structured observation (HTTP 201)", code == 201, f"HTTP {code}")
    meas = next((m for m in inc.get("measurements", []) if m["name"] == flow["name"]), None)
    s.expect("the observation is stored as a submitted observation awaiting verification (class C, VALIDATED, not used for priority)",
             bool(meas) and meas["trust_status"] == "VALIDATED" and meas["evidence_class"] == "C" and meas["eligible_for_numeric_priority"] is False, json.dumps({k: (meas or {}).get(k) for k in ("trust_status", "evidence_class", "eligible_for_numeric_priority")}))
    s.expect("asset is registered", inc["asset_verified"] is True, inc["asset_id"])
    before = inc["priority"]
    if inc["review_status"] == "needs_review":
        code, _ = call(api, "POST", f"/incidents/{inc['id']}/review", tok["supervisor"], {"decision": "accept", "comment": "Demo smoke supervisor review."})
        s.expect("supervisor review of a blocked incident", code == 200, f"HTTP {code}")
    verify = f"/incidents/{inc['id']}/measurements/{flow['name']}/verify"
    decision = {"decision": "approve", "comment": "Demo smoke: checked against the source reading.", "expected_trust_status": "VALIDATED"}
    for role in ("engineer", "auditor"):
        code, body = call(api, "POST", verify, tok[role], decision)
        s.expect(f"{role} cannot verify (403 insufficient_role)", code == 403 and body["error"]["code"] == "insufficient_role", f"HTTP {code}")
    code, _ = call(api, "POST", verify, tokens_other["supervisor"], decision)
    s.expect("another tenant's supervisor gets 404 (tenant isolation)", code == 404, f"HTTP {code}")
    code, _ = call(api, "GET", f"/incidents/{inc['id']}", tokens_other["engineer"])
    s.expect("another tenant's engineer cannot read the incident (404)", code == 404, f"HTTP {code}")
    code, done = call(api, "POST", verify, tok["supervisor"], decision)
    m2 = next((m for m in done.get("measurements", []) if m["name"] == flow["name"]), {}) if code == 200 else {}
    s.expect("supervisor verifies; the server returns HUMAN_VERIFIED, class D, eligible", code == 200 and m2.get("trust_status") == "HUMAN_VERIFIED" and m2.get("evidence_class") == "D" and m2.get("eligible_for_numeric_priority") is True, f"HTTP {code}")
    code, fresh = call(api, "GET", f"/incidents/{inc['id']}", tok["engineer"])
    s.expect(f"priority comes from the server: {before} -> {fresh['priority']} (verification block says {m2['verification']['priority_before']} -> {m2['verification']['priority_after']})",
             fresh["priority"] == done["priority"] == m2["verification"]["priority_after"] and m2["verification"]["priority_before"] == before)
    code, body = call(api, "POST", verify, tok["supervisor"], decision)
    s.expect("a repeated decision is refused (409)", code == 409, f"HTTP {code} {body.get('error', {}).get('code')}")
    code, mine = call(api, "POST", "/incidents/extract", tok["supervisor"], {"report_text": flow["report"], "observations": obs})
    code, body = call(api, "POST", f"/incidents/{mine['id']}/measurements/{flow['name']}/verify", tok["supervisor"], decision)
    s.expect("the creator cannot verify their own incident's measurement (403 separation_of_duties)", code == 403 and body["error"]["code"] == "separation_of_duties", f"HTTP {code}")
    code, ticket = call(api, "POST", "/tickets", tok["engineer"], {"incident_id": inc["id"]})
    s.expect("engineer drafts a ticket (201, DRAFT)", code == 201 and ticket["state"] == "DRAFT", f"HTTP {code}")
    code, t2 = call(api, "POST", f"/tickets/{ticket['id']}/request-approval", tok["engineer"])
    s.expect("approval requested (PENDING_APPROVAL)", code == 200 and t2["state"] == "PENDING_APPROVAL", f"HTTP {code}")
    code, body = call(api, "POST", f"/approvals/{ticket['id']}/decision", tok["engineer"], {"decision": "approved", "comment": "x"})
    s.expect("the author cannot approve (403)", code == 403, f"HTTP {code}")
    code, _ = call(api, "POST", f"/approvals/{ticket['id']}/decision", tok["supervisor"], {"decision": "approved", "comment": "Demo smoke approval."})
    s.expect("supervisor approves", code == 200, f"HTTP {code}")
    final, deadline = {}, time.time() + 40
    while time.time() < deadline:
        _, final = call(api, "GET", f"/tickets/{ticket['id']}", tok["engineer"])
        if final.get("state") in ("SUBMITTED", "FAILED"):
            break
        time.sleep(1)
    s.expect("the worker submits it to the (simulated) external system: SUBMITTED with an external id", final.get("state") == "SUBMITTED" and bool(final.get("external_ticket_id")), f"state {final.get('state')} external id {final.get('external_ticket_id')}")
    _, audit = call(api, "GET", "/audit?limit=100", tok["auditor"])
    actions = {a["action"] for a in audit["items"]}
    need = {"incident.extracted", "measurement.verified", "incident.priority_decided", "ticket.drafted", "approval.approved", "ticket.submitted"}
    s.expect("the audit log shows the whole chain", need <= actions, f"missing {sorted(need - actions)}")
    delete_document(api, s, flow, tok, tokens_other)
    return s.items


def delete_document(api: str, s: "Steps", flow: dict, tok: dict, tokens_other: dict) -> None:
    """Audited document deletion through the real API and worker: refusal for an engineer, 404 across tenants, immediate exclusion, then verified content cleanup."""
    _, listing = call(api, "GET", "/documents?limit=100", tok["engineer"])
    doc = next((d for d in listing["items"] if d["filename"] == flow["delete_file"]), None)
    s.expect(f"document {flow['delete_file']} is listed and searchable before deletion", doc is not None and any(
        h["filename"] == flow["delete_file"] for h in call(api, "POST", "/search", tok["engineer"], {"query": flow["delete_query"], "k": 8})[1]["items"]))
    code, body = call(api, "DELETE", f"/documents/{doc['id']}", tok["engineer"])
    s.expect("an engineer cannot delete a document (403)", code == 403 and body["error"]["code"] == "insufficient_role", f"HTTP {code}")
    code, _ = call(api, "DELETE", f"/documents/{doc['id']}", tokens_other["supervisor"])
    s.expect("another tenant's supervisor cannot delete it or see it (404)", code == 404, f"HTTP {code}")
    code, state = call(api, "DELETE", f"/documents/{doc['id']}", tok["supervisor"])
    s.expect("supervisor deletes: logically deleted at once, cleanup pending or already running", code == 200 and state["lifecycle_status"] == "deleted" and state["cleanup_state"] in ("pending", "completed"), f"HTTP {code} {state.get('cleanup_state')}")
    _, listing = call(api, "GET", "/documents?limit=100", tok["engineer"])
    code, _ = call(api, "GET", f"/documents/{doc['id']}", tok["engineer"])
    hits = call(api, "POST", "/search", tok["engineer"], {"query": flow["delete_query"], "k": 8})[1]["items"]
    s.expect("the deleted document is gone from the listing, direct access (404) and search", all(d["id"] != doc["id"] for d in listing["items"]) and code == 404 and not any(h["filename"] == flow["delete_file"] for h in hits))
    final, deadline = {}, time.time() + 40
    while time.time() < deadline:
        _, final = call(api, "DELETE", f"/documents/{doc['id']}", tok["supervisor"])
        if final.get("cleanup_state") == "completed":
            break
        time.sleep(1)
    s.expect("the worker removed the content and verified it (cleanup completed), a repeated delete is idempotent", final.get("cleanup_state") == "completed" and final.get("already_deleted") is True, f"state {final.get('cleanup_state')}")
    _, audit = call(api, "GET", f"/audit?entity_id={doc['id']}&limit=50", tok["auditor"])
    actions = [a["action"] for a in audit["items"]]
    s.expect("the audit log holds the deletion and the cleanup without content", "document.deleted" in actions and "document.cleanup_completed" in actions and all("Okafor" not in str(a) for a in audit["items"]), ", ".join(sorted(set(actions))))


def run_workflows(api: str, password: str) -> dict:
    tokens = {f["slug"]: {r: login(api, f["slug"], f["domain"], r, password) for r in ("engineer", "supervisor")} for f in TENANT_FLOWS}
    out = {"external_systems": "simulated: local mock ticketing (8101) and service desk (8105)", "tenants": {}}
    for flow in TENANT_FLOWS:
        other = next(f for f in TENANT_FLOWS if f is not flow)
        out["tenants"][flow["slug"]] = run_tenant(api, password, flow, other, tokens[other["slug"]])
    return out


def run_ingestion(api: str, password: str, fault_file: Path) -> dict:
    """Live ingestion checkpoint on both tenants: durable jobs, bounded retry and recovery under a SIMULATED embedding outage (a fault switch in scripts/fault_boot.py, the same failure
    mode as an unloadable embedding model; it is not a real infrastructure outage), authorised reprocessing, deletion racing a queued reprocessing job, tenant isolation, audit."""
    tokens = {f["slug"]: {r: login(api, f["slug"], f["domain"], r, password) for r in ("engineer", "supervisor", "auditor")} for f in TENANT_FLOWS}
    out = {"fault": "simulated: the embedding step raises while the fault switch file exists (scripts/fault_boot.py); the retry logic is exercised against that failure mode", "tenants": {}}
    for flow in TENANT_FLOWS:
        out["tenants"][flow["slug"]] = _ingestion_tenant(api, flow, tokens[flow["slug"]], tokens[next(f["slug"] for f in TENANT_FLOWS if f is not flow)], fault_file)
    return out


def _ingestion_tenant(api: str, flow: dict, tok: dict, other: dict, fault_file: Path) -> list[dict]:
    s = Steps(flow["slug"])
    phrase = f"livecheck-{flow['slug']}-{uuid.uuid4().hex[:8]}"
    note = f"Live ingestion note for {flow['asset']}: replace the gasket when it weeps and torque the bolts. Marker {phrase}.".encode()

    def upload(name, data):
        boundary = "----eaopboundary" + uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"kind\"\r\n\r\nother\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
                f"Content-Type: text/plain\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(api + "/documents", data=body, method="POST", headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Authorization": f"Bearer {tok['engineer']}"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - local URL
                return resp.status, json.loads(resp.read()), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"null"), dict(exc.headers)

    def found(token, p=phrase):
        return [h for h in call(api, "POST", "/search", token, {"query": p, "k": 8})[1]["items"] if p in h["text"]]

    def wait(label, predicate, seconds=60):
        deadline = time.time() + seconds
        while time.time() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(1)
        s.expect(label, False, "timed out")

    def job_for(doc_id, job_type=None):
        items = call(api, "GET", f"/ingestion/jobs?document_id={doc_id}&limit=20", tok["engineer"])[1]["items"]
        return next((j for j in items if job_type is None or j["job_type"] == job_type), None)

    code, first, _ = upload(f"live-ok-{flow['slug']}.txt", note)
    s.expect("a supported document uploads synchronously (201) as before", code == 201 and first["status"] == "created" and set(first) == {"document_id", "version", "chunk_count", "status"}, f"HTTP {code}")
    ok_job = job_for(first["document_id"], "ingest")
    s.expect("the upload left a COMPLETED durable ingestion job with its outcome and chunk count", bool(ok_job) and ok_job["status"] == "COMPLETED" and ok_job["outcome"] == "created" and ok_job["chunks"] == first["chunk_count"], json.dumps({k: (ok_job or {}).get(k) for k in ("status", "outcome", "attempts")}))
    s.expect("the content is retrievable once indexed", len(found(tok["engineer"])) >= 1)

    retry_phrase = f"retrycheck-{flow['slug']}-{uuid.uuid4().hex[:8]}"
    retry_note = f"Retry note for {flow['asset']}: bearing grease interval is two weeks. Marker {retry_phrase}.".encode()
    fault_file.write_text("simulated embedding outage", encoding="utf-8")
    code, body, headers = upload(f"live-retry-{flow['slug']}.txt", retry_note)
    s.expect("during the SIMULATED embedding outage the upload keeps its contract: 503 embedding_unavailable with Retry-After", code == 503 and body["error"]["code"] == "embedding_unavailable" and "retry-after" in {k.lower() for k in headers}, f"HTTP {code}")
    pending = call(api, "GET", "/ingestion/jobs?status=RETRY_PENDING&limit=50", tok["engineer"])[1]["items"]
    job = next((j for j in pending if j["filename"] == f"live-retry-{flow['slug']}.txt"), None)
    s.expect("a RETRY_PENDING job with a sanitised error and a next attempt time exists", bool(job) and job["error_code"] == "embedding_unavailable" and bool(job["next_attempt_at"]) and "outage" not in json.dumps(job))
    wait("the worker retries during the outage (attempts increase, still bounded)", lambda: call(api, "GET", f"/ingestion/jobs/{job['id']}", tok["engineer"])[1]["attempts"] >= 2, 40)
    fault_file.unlink()
    done = wait("the job completes by itself after recovery", lambda: (lambda j: j if j["status"] == "COMPLETED" else None)(call(api, "GET", f"/ingestion/jobs/{job['id']}", tok["engineer"])[1]), 90)
    s.expect(f"bounded retry then recovery: COMPLETED after {done['attempts']} attempts (limit {done['max_attempts']}), document created, now retrievable",
             done["attempts"] >= 2 and done["attempts"] <= done["max_attempts"] and done["outcome"] == "created" and len(found(tok["engineer"], retry_phrase)) >= 1)
    code, again, _ = upload(f"live-retry-{flow['slug']}.txt", retry_note)
    s.expect("repeating the upload afterwards is a duplicate: nothing is stored twice", code == 201 and again["status"] == "duplicate")

    doc = first["document_id"]
    code, _ = call(api, "POST", f"/documents/{doc}/reprocess", tok["engineer"])
    s.expect("an engineer cannot reprocess (403)", code == 403, f"HTTP {code}")
    code, queued = call(api, "POST", f"/documents/{doc}/reprocess", tok["supervisor"])
    s.expect("a supervisor queues reprocessing (202)", code == 202 and queued["job_type"] == "reprocess", f"HTTP {code}")
    reproc = wait("reprocessing completes with a new generation", lambda: (lambda j: j if j["status"] == "COMPLETED" else None)(call(api, "GET", f"/ingestion/jobs/{queued['id']}", tok["engineer"])[1]), 60)
    hits = found(tok["engineer"])
    s.expect("replacement generation activated (1 to 2); retrieval serves the document once, no duplicates", reproc["outcome"] == "reprocessed" and reproc["from_generation"] == 1 and reproc["to_generation"] == 2 and len(hits) == len({h["chunk_id"] for h in hits}) >= 1)
    s.expect("another tenant cannot see this tenant's jobs (404, indistinguishable from unknown)", call(api, "GET", f"/ingestion/jobs/{reproc['id']}", other["engineer"])[0] == 404)
    code, _ = call(api, "POST", f"/documents/{doc}/reprocess", other["supervisor"])
    s.expect("another tenant's supervisor cannot reprocess it (404)", code == 404, f"HTTP {code}")

    fault_file.write_text("simulated embedding outage", encoding="utf-8")  # a queued reprocessing job that cannot finish...
    code, race = call(api, "POST", f"/documents/{doc}/reprocess", tok["supervisor"])
    code2, _ = call(api, "DELETE", f"/documents/{doc}", tok["supervisor"])  # ...is cancelled by the deletion
    fault_file.unlink()
    cancelled = call(api, "GET", f"/ingestion/jobs/{race['id']}", tok["engineer"])[1]
    s.expect("deletion while a reprocessing job is queued cancels it (document_deleted); the content never returns", code == 202 and code2 == 200 and cancelled["status"] == "CANCELLED" and cancelled["error_code"] == "document_deleted")
    time.sleep(3)
    s.expect("after recovery the cancelled job does not run: the document stays deleted, unsearchable, not reprocessable (404)",
             call(api, "GET", f"/documents/{doc}", tok["engineer"])[0] == 404 and not found(tok["engineer"]) and call(api, "POST", f"/documents/{doc}/reprocess", tok["supervisor"])[0] == 404)
    wait("the worker completes the deletion cleanup", lambda: call(api, "DELETE", f"/documents/{doc}", tok["supervisor"])[1]["cleanup_state"] == "completed", 40)
    audit = {a["action"] for a in call(api, "GET", "/audit?limit=100", tok["auditor"])[1]["items"]}
    need = {"ingestion.job_created", "ingestion.retry_scheduled", "ingestion.job_completed", "document.reprocess_requested", "document.reprocessed", "ingestion.job_cancelled", "document.cleanup_completed"}
    s.expect("the audit log records job creation, retry, completion, reprocessing, cancellation and cleanup", need <= audit, f"missing {sorted(need - audit)}")
    return s.items


def _mock(records_url: str, key: str, method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(records_url + path, data=data, method=method, headers={"Content-Type": "application/json", "X-API-Key": key})
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - local URL
        return json.loads(resp.read())


def run_rest(api: str, password: str, records_url: str, key: str) -> dict:
    """Live REST pull synchronization on both tenants: a real connector row, real HTTP to the local records mock (separate process), the real worker and ingestion pipeline, retrieval,
    audit. The upstream failure used here is a CONTROLLED INJECTION in the mock (a 503 burst), not a real outage."""
    tokens = {f["slug"]: {r: login(api, f["slug"], f["domain"], r, password) for r in ("engineer", "supervisor", "admin", "auditor")} for f in TENANT_FLOWS}
    plans = {"apex-industrial": {"dataset": "apex", "mode": "cursor", "count": 7, "probe_term": "mechanical seal weeps pump P-101", "needle": "seal"},
             "meridian-fleet": {"dataset": "meridian", "mode": "offset", "count": 5, "probe_term": "brake pad wear VH-2101 order pads", "needle": "brake pad"}}
    out = {"fault": "controlled injection in the records mock (a 503 burst after the first page): the retry logic is exercised against that failure, it is not a real upstream outage",
           "records_source": "mock-services/records (separate local process, X-API-Key required; run-only key not recorded)", "tenants": {}}
    for flow in TENANT_FLOWS:
        other = next(f for f in TENANT_FLOWS if f is not flow)
        out["tenants"][flow["slug"]] = _rest_tenant(api, flow, plans[flow["slug"]], tokens[flow["slug"]], tokens[other["slug"]], records_url, key)
    return out


def _rest_tenant(api: str, flow: dict, plan: dict, tok: dict, other: dict, records_url: str, key: str) -> list[dict]:
    s = Steps(flow["slug"])
    ds, mode, n = plan["dataset"], plan["mode"], plan["count"]
    pagination = {"mode": mode, "page_size": 3}
    pagination.update({"has_more_field": "has_more"} if mode == "cursor" else {"total_field": "total"})
    cfg = {"records": {"path": f"/v1/{ds}/{mode}", "id_field": "id", "required_fields": ["title", "body"], "pagination": pagination, "rate": {"requests_per_second": 20, "burst": 10}}}
    suffix = uuid.uuid4().hex[:6]
    code, created = call(api, "POST", "/connectors", tok["admin"], {"kind": "rest", "name": f"records-{ds}-{suffix}", "base_url": records_url, "secret_ref": "RECORDS_API_KEY", "config": cfg})
    s.expect(f"the administrator registers a REST records connector ({mode} pagination) through the public API", code == 201, f"HTTP {code}")
    cid = created["id"]
    code, bad = call(api, "POST", "/connectors", tok["admin"], {"kind": "rest", "name": f"bad-{suffix}", "base_url": records_url, "config": {"records": {"path": "http://evil.example/x", "id_field": "id"}}})
    s.expect("an invalid connector configuration (an absolute URL as the path) is rejected at creation (422)", code == 422, f"HTTP {code}")
    s.expect("an engineer cannot start a synchronisation (403)", call(api, "POST", f"/connectors/{cid}/sync", tok["engineer"])[0] == 403)
    s.expect("another tenant's administrator gets 404 for this connector", call(api, "POST", f"/connectors/{cid}/sync", other["admin"])[0] == 404)

    def wait_job(job_id, want, seconds=90):
        deadline = time.time() + seconds
        while time.time() < deadline:
            job = call(api, "GET", f"/ingestion/jobs/{job_id}", tok["engineer"])[1]
            if job["status"] in want:
                return job
            time.sleep(1)
        s.expect(f"job {job_id} reaches {want}", False, "timed out")

    def search(term):
        return [h for h in call(api, "POST", "/search", tok["engineer"], {"query": term, "k": 8})[1]["items"] if h["filename"].startswith("rest-")]

    code, job = call(api, "POST", f"/connectors/{cid}/sync", tok["supervisor"])
    s.expect("a supervisor starts a synchronisation: 202 with a durable QUEUED sync job", code == 202 and job["job_type"] == "sync" and job["status"] == "QUEUED" and job["connector_id"] == cid, f"HTTP {code}")
    done = wait_job(job["id"], ("COMPLETED", "FAILED"))
    sy = done["sync"]
    s.expect(f"the worker pulled every page and ingested every record: COMPLETED, {n} records created over {sy['pages']} pages", done["status"] == "COMPLETED" and done["outcome"] == "synced" and sy["created"] == n and sy["pages"] >= 2,
             json.dumps({k: done[k] for k in ("status", "outcome", "error_code")}) + " " + json.dumps(sy))
    seen = _mock(records_url, key, "GET", "/admin/requests")["requests"]
    mine = [r for r in seen if r["dataset"] == ds and r["mode"] == mode]
    s.expect("the records mock saw real authenticated paginated requests from the connector", len(mine) >= sy["pages"] and all(r["key_ok"] for r in mine), f"{len(mine)} requests")
    hits = search(plan["probe_term"])
    s.expect("the synchronised content is retrievable by this tenant, with the source record id as provenance", any(plan["needle"] in h["text"].lower() and h["record_id"] for h in hits), f"{len(hits)} hits")
    other_hits = [h for h in call(api, "POST", "/search", other["engineer"], {"query": plan["probe_term"], "k": 8})[1]["items"] if flow["asset"] in h["text"]]
    s.expect("the other tenant's retrieval never returns this tenant's records (searching the same words)", not other_hits)
    s.expect("the other tenant cannot read this tenant's sync job (404)", call(api, "GET", f"/ingestion/jobs/{job['id']}", other["engineer"])[0] == 404)

    code, again = call(api, "POST", f"/connectors/{cid}/sync", tok["supervisor"])
    repeat = wait_job(again["id"], ("COMPLETED", "FAILED"))
    s.expect("a repeated synchronisation is safe: every record unchanged, nothing created twice", repeat["status"] == "COMPLETED" and repeat["sync"]["unchanged"] == n and repeat["sync"]["created"] == 0, json.dumps(repeat["sync"]))
    first_id = {"apex": "APX-N-001", "meridian": "MER-B-001"}[ds]
    # replace the first record with an updated copy at the source (the mock keeps the other records)
    import importlib.util
    spec = importlib.util.spec_from_file_location("records_app_demo", ROOT / "mock-services" / "records" / "records_app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    base = mod._apex() if ds == "apex" else mod._meridian()
    base[0] = {**base[0], "body": base[0]["body"] + " Updated after the live check.", **({"updated_at": "2026-11-13T09:00:00Z"} if ds == "apex" else {"revision": 99})}
    _mock(records_url, key, "POST", f"/admin/dataset/{ds}", {"records": base})
    code, upd = call(api, "POST", f"/connectors/{cid}/sync", tok["supervisor"])
    upd_done = wait_job(upd["id"], ("COMPLETED", "FAILED"))
    s.expect("a changed source record becomes a new document version, unchanged ones are skipped", upd_done["status"] == "COMPLETED" and upd_done["sync"]["updated"] == 1 and upd_done["sync"]["unchanged"] == n - 1, json.dumps(upd_done["sync"]))
    s.expect("the update is retrievable", any("updated after the live check" in h["text"].lower() for h in search(plan["probe_term"] + " updated after the live check")))

    # bounded rate limiting: a second connector limited to 2 requests per second with no burst
    slow_cfg = json.loads(json.dumps(cfg))
    slow_cfg["records"]["rate"] = {"requests_per_second": 2.0, "burst": 1}
    code, slow = call(api, "POST", "/connectors", tok["admin"], {"kind": "rest", "name": f"slow-{ds}-{suffix}", "base_url": records_url, "secret_ref": "RECORDS_API_KEY", "config": slow_cfg})
    code, sj = call(api, "POST", f"/connectors/{slow['id']}/sync", tok["supervisor"])
    sdone = wait_job(sj["id"], ("COMPLETED", "FAILED"))
    t0, t1 = sdone["created_at"], sdone["completed_at"]
    from datetime import datetime as _dt
    elapsed = (_dt.fromisoformat(t1) - _dt.fromisoformat(t0)).total_seconds()
    s.expect(f"a connector limited to 2 requests per second spaces its real requests ({sdone['sync']['pages']} pages took {elapsed:.1f} s)", sdone["status"] == "COMPLETED" and elapsed >= (sdone["sync"]["pages"] - 1) / 2.0 * 0.8,
             json.dumps({"elapsed_s": round(elapsed, 2), "pages": sdone["sync"]["pages"]}))

    # the opt-in live health probe
    plain = call(api, "GET", "/connectors/health", tok["admin"])[1]["items"]
    s.expect("without probe=true the health endpoint makes no live request (unchanged behaviour)", all("live_probe" not in i for i in plain))
    probed = {i["id"]: i for i in call(api, "GET", "/connectors/health?probe=true", tok["admin"])[1]["items"]}
    probe = probed[cid]["live_probe"]
    s.expect(f"probe=true makes one bounded real request to the source: ok in {probe['duration_ms']} ms (nothing ingested)", probe["status"] == "ok" and probed[cid]["status"] == "ok", json.dumps(probe))
    s.expect("an engineer cannot run the probe (403)", call(api, "GET", "/connectors/health?probe=true", tok["engineer"])[0] == 403)

    # error recovery: a controlled 503 burst on the second page of the next synchronisation
    _mock(records_url, key, "POST", "/admin/failure", {"mode": "503", "count": 3, "after": 1})
    code, rec = call(api, "POST", f"/connectors/{cid}/sync", tok["supervisor"])
    retry_seen = wait_job(rec["id"], ("RETRY_PENDING", "COMPLETED", "FAILED"), 60)
    recovered = wait_job(rec["id"], ("COMPLETED", "FAILED"), 90)
    s.expect(f"a controlled upstream failure is retried with backoff and the job recovers by itself ({recovered['attempts']} attempts)", recovered["status"] == "COMPLETED" and recovered["attempts"] >= 2 and retry_seen["status"] in ("RETRY_PENDING", "COMPLETED"),
             json.dumps({"seen": retry_seen["status"], "attempts": recovered["attempts"], "outcome": recovered["outcome"]}))

    # deletion: a deleted synchronised document is not resurrected by the next synchronisation
    code, docs_ = call(api, "GET", "/documents?limit=100", tok["engineer"])
    victim = next(d for d in docs_["items"] if d["filename"].startswith("rest-") and first_id.lower() not in d["filename"].lower())
    code_d, _ = call(api, "DELETE", f"/documents/{victim['id']}", tok["supervisor"])
    code, after = call(api, "POST", f"/connectors/{cid}/sync", tok["supervisor"])
    after_done = wait_job(after["id"], ("COMPLETED", "FAILED"))
    s.expect("a document the user deleted stays deleted after the next synchronisation", code_d == 200 and after_done["sync"]["skipped_deleted"] == 1 and call(api, "GET", f"/documents/{victim['id']}", tok["engineer"])[0] == 404, json.dumps(after_done["sync"]))

    audit = {a["action"] for a in call(api, "GET", "/audit?limit=100", tok["auditor"])[1]["items"]}
    need = {"connector.created", "connector.sync_requested", "connector.record_ingested", "connector.sync_completed", "connector.probed", "ingestion.retry_scheduled"}
    s.expect("the audit log records the connector, synchronisations, ingested records, the probe and the retry, without content or credentials", need <= audit, f"missing {sorted(need - audit)}")
    blob = json.dumps(call(api, "GET", "/audit?limit=100", tok["auditor"])[1]) + json.dumps(call(api, "GET", "/ingestion/jobs?limit=100", tok["engineer"])[1])
    s.expect("no credential and no record content appears in the audit log or the job list", key not in blob and "weeps under load" not in blob and "Front brake pads" not in blob)
    return s.items


def _raw(url: str, method: str, body: bytes | None, headers: dict) -> tuple[int, dict | None]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - local URL
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"raw": raw[:120].decode("utf-8", "replace")}


def _sign(secret: str, ts: str, delivery_id: str, body: bytes) -> str:
    import hashlib
    import hmac
    return "sha256=" + hmac.new(secret.encode(), f"{ts}.{delivery_id}.".encode() + body, hashlib.sha256).hexdigest()


def run_integrations(api: str, password: str, records_url: str, key: str, webhook_secrets: dict) -> dict:
    """Live CSV and signed-webhook integrations on both tenants (real HTTP to the local records mock for CSV; real signed HTTP deliveries to the API for webhooks; real worker and pipeline).
    The negative deliveries (bad signature, replay, stale timestamp, tampering, oversize, wrong type) are deliberate adversarial requests, not outages."""
    tokens = {f["slug"]: {r: login(api, f["slug"], f["domain"], r, password) for r in ("engineer", "supervisor", "admin", "auditor")} for f in TENANT_FLOWS}
    plans = {"apex-industrial": {"dataset": "apex", "count": 7, "csv_term": "mechanical seal weeps pump P-101", "needle": "seal", "hook_term": "gland packing valve V-330 leaks", "asset": "V-330"},
             "meridian-fleet": {"dataset": "meridian", "count": 5, "csv_term": "brake pad wear VH-2101 order pads", "needle": "brake pad", "hook_term": "coolant hose clamp VH-2102 leak", "asset": "VH-2102"}}
    out = {"note": "CSV: real HTTP pull from mock-services/records. Webhooks: real HMAC-signed deliveries to the API; adversarial deliveries are deliberate negative tests. Signing secrets are run-only and never recorded.", "tenants": {}}
    for flow in TENANT_FLOWS:
        other = next(f for f in TENANT_FLOWS if f is not flow)
        out["tenants"][flow["slug"]] = _integrations_tenant(api, flow, plans[flow["slug"]], tokens[flow["slug"]], tokens[other["slug"]], records_url, key, webhook_secrets)
    return out


def _integrations_tenant(api, flow, plan, tok, other, records_url, key, secrets_) -> list[dict]:
    s = Steps(flow["slug"])
    ds, n = plan["dataset"], plan["count"]
    suffix = uuid.uuid4().hex[:6]

    def wait_job(job_id, seconds=90):
        deadline = time.time() + seconds
        while time.time() < deadline:
            job = call(api, "GET", f"/ingestion/jobs/{job_id}", tok["engineer"])[1]
            if job["status"] in ("COMPLETED", "FAILED"):
                return job
            time.sleep(1)
        s.expect(f"job {job_id} finishes", False, "timed out")

    def search(term, token=None):
        return call(api, "POST", "/search", token or tok["engineer"], {"query": term, "k": 8})[1]["items"]

    # ---- CSV connector (its own dataset: identical content to the REST records would be a duplicate, by policy)
    import importlib.util
    spec = importlib.util.spec_from_file_location("records_app_demo_csv", ROOT / "mock-services" / "records" / "records_app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    base = mod._apex() if ds == "apex" else mod._meridian()
    csv_rows = [{"id": f"{r['id'][:3]}-C-{i + 1:03d}", "title": "CSV export: " + r["title"], "body": r["body"] + " (exported to CSV)"} for i, r in enumerate(base)]
    csv_rows[0]["title"] = "=SUM(1+1) CSV export row"  # formula-looking text must stay inert data
    _mock(records_url, key, "POST", f"/admin/dataset/{ds}-csv", {"records": csv_rows})
    cfg = {"csv": {"path": f"/v1/{ds}-csv/csv", "id_field": "id", "required_fields": ["title", "body"], "rate": {"requests_per_second": 20, "burst": 10}}}
    code, conn = call(api, "POST", "/connectors", tok["admin"], {"kind": "csv", "name": f"csv-{ds}-{suffix}", "base_url": records_url, "secret_ref": "RECORDS_API_KEY", "config": cfg})
    s.expect("the administrator registers a CSV connector through the public API", code == 201, f"HTTP {code}")
    code, bad = call(api, "POST", "/connectors", tok["admin"], {"kind": "csv", "name": f"badcsv-{suffix}", "base_url": records_url, "config": {"csv": {"path": "//evil/x", "id_field": "id"}}})
    s.expect("an invalid CSV configuration is rejected at creation (422)", code == 422, f"HTTP {code}")
    code, job = call(api, "POST", f"/connectors/{conn['id']}/sync", tok["supervisor"])
    s.expect("a supervisor starts the CSV synchronisation: 202 with a durable QUEUED job", code == 202 and job["status"] == "QUEUED" and job["job_type"] == "sync", f"HTTP {code}")
    done = wait_job(job["id"])
    s.expect(f"the worker fetched the CSV file and ingested every row: {n} records created", done["status"] == "COMPLETED" and done["outcome"] == "synced" and done["sync"]["created"] == n, json.dumps(done["sync"]))
    mine = [r for r in _mock(records_url, key, "GET", "/admin/requests")["requests"] if r["mode"] == "csv" and r["dataset"] == f"{ds}-csv"]
    s.expect("the records mock served the CSV to the authenticated connector", mine and all(r["key_ok"] for r in mine), f"{len(mine)} requests")
    s.expect("the rows are retrievable with their record id as provenance", any("exported to csv" in h["text"].lower() and h["record_id"] for h in search(plan["csv_term"] + " exported to CSV")))
    again = wait_job(call(api, "POST", f"/connectors/{conn['id']}/sync", tok["supervisor"])[1]["id"])
    s.expect("a repeated CSV synchronisation is idempotent: every row unchanged", again["sync"]["unchanged"] == n and again["sync"]["created"] == 0, json.dumps(again["sync"]))
    probed = {i["id"]: i for i in call(api, "GET", "/connectors/health?probe=true", tok["admin"])[1]["items"]}
    s.expect("the live probe validates the CSV source header (nothing ingested)", probed[conn["id"]]["live_probe"]["status"] == "ok")

    # ---- signed webhook endpoint
    hook_cfg = {"id_field": "id", "version_field": "updated_at", "required_fields": ["title", "body"], "max_records": 20}
    code, ep = call(api, "POST", "/webhook-endpoints", tok["admin"], {"name": f"hook-{ds}-{suffix}", "secret_ref": "WEBHOOK_DEMO_SECRET", "config": hook_cfg})
    s.expect("the administrator provisions a webhook endpoint (only the NAME of the secret variable is supplied; no secret is returned)", code == 201 and ep["secret_configured"] and secrets_["current"] not in json.dumps(ep), f"HTTP {code}")
    s.expect("an engineer cannot provision endpoints (403)", call(api, "POST", "/webhook-endpoints", tok["engineer"], {"name": f"x-{suffix}", "secret_ref": "WEBHOOK_DEMO_SECRET", "config": hook_cfg})[0] == 403)
    url = f"{api}/webhooks/{ep['id']}"
    record = {"id": f"WH-{ds}-1", "title": f"Live webhook note {ds}", "body": f"Live delivery: {plan['hook_term']}; inspect and report.", "updated_at": "v1"}
    body = json.dumps(record).encode()

    def send(raw, secret=None, ts=None, did=None, ctype="application/json", sig=None):
        ts = str(int(time.time())) if ts is None else str(ts)
        did = did or f"live-{uuid.uuid4().hex[:12]}"
        headers = {"Content-Type": ctype, "X-Webhook-Timestamp": ts, "X-Webhook-Delivery-Id": did, "X-Webhook-Signature": sig or _sign(secret or secrets_["current"], ts, did, raw)}
        code, resp = _raw(url, "POST", raw, headers)
        return code, resp, did

    code, acc, did = send(body)
    s.expect("a correctly signed delivery is acknowledged 202 QUEUED (durably queued, not yet processed)", code == 202 and acc["status"] == "QUEUED" and acc["delivery_id"] == did, f"HTTP {code}")
    job = wait_job(acc["job_id"])
    s.expect("the worker processed the delivery through the ingestion pipeline: 1 record created", job["status"] == "COMPLETED" and job["job_type"] == "webhook" and job["sync"]["created"] == 1, json.dumps(job["sync"]))
    s.expect("the delivered content is retrievable by this tenant and not by the other tenant", any(plan["hook_term"].split()[0] in h["text"].lower() for h in search(plan["hook_term"])) and not [h for h in search(plan["hook_term"], other["engineer"]) if plan["asset"] in h["text"]])
    c1, r1, _ = send(body, secret=uuid.uuid4().hex)  # a random wrong secret
    c2, r2, _ = send(body.replace(b"inspect", b"ignore"), sig=_sign(secrets_["current"], str(int(time.time())), "live-fixed-id-0001", body), did="live-fixed-id-0001")
    c3, r3, _ = send(body, ts=int(time.time()) - 3600)
    s.expect("a wrong secret and a tampered body are rejected with the same 401 invalid_signature", c1 == 401 and c2 == 401 and r1["error"]["code"] == r2["error"]["code"] == "invalid_signature", f"{c1} {c2}")
    s.expect("a validly signed but stale delivery is rejected by the timestamp window (401)", c3 == 401 and r3["error"]["code"] == "timestamp_out_of_window", f"HTTP {c3}")
    c4, r4, _ = send(body, did=did)
    s.expect("replaying a received delivery id is rejected (409 webhook_replayed)", c4 == 409 and r4["error"]["code"] == "webhook_replayed", f"HTTP {c4}")
    # Probe the declared-length check without racing a body write against the
    # server's early rejection. The backend tests cover actual oversized bodies.
    c5, r5 = _raw(url, "POST", None, {"Content-Type": "application/json", "Content-Length": str(256 * 1024 + 1)})
    c6, r6, _ = send(body, ctype="text/plain")
    s.expect("an oversized declared length is refused (413) and a non-JSON content type is refused (415)",
             c5 == 413 and r5["error"]["code"] == "payload_too_large" and c6 == 415, f"{c5} {c6}")
    c7, r7, _ = send(b"{not json")
    s.expect("a signed delivery that can never be processed is rejected after authentication (422)", c7 == 422 and r7["error"]["code"] == "invalid_payload", f"HTTP {c7}")
    update = {**record, "body": record["body"] + " Updated by a later delivery.", "updated_at": "v2"}
    c8, r8, _ = send(json.dumps(update).encode())
    upd = wait_job(r8["job_id"])
    s.expect("a later delivery with changed content becomes a new document version", upd["sync"]["updated"] == 1, json.dumps(upd["sync"]))
    # rotation with an overlap window
    code, rot = call(api, "PATCH", f"/webhook-endpoints/{ep['id']}", tok["admin"], {"secret_ref": "WEBHOOK_DEMO_SECRET_NEXT"})
    old_ok, old_resp, _ = send(json.dumps({**record, "id": f"WH-{ds}-2"}).encode())
    new_ok, new_resp, _ = send(json.dumps({**record, "id": f"WH-{ds}-3"}).encode(), secret=secrets_["next"])
    for resp in (old_resp, new_resp):  # let the queued deliveries finish: the demonstration leaves no work in flight (the backup proof that follows takes a consistent snapshot)
        if isinstance(resp, dict) and resp.get("job_id"):
            wait_job(resp["job_id"])
    call(api, "PATCH", f"/webhook-endpoints/{ep['id']}", tok["admin"], {"drop_previous_secret": True})
    old_after = send(json.dumps({**record, "id": f"WH-{ds}-4"}).encode())[0]
    s.expect("secret rotation: both secrets work during the overlap, the old one is rejected after it is dropped", code == 200 and rot["has_previous_secret"] and old_ok == 202 and new_ok == 202 and old_after == 401, f"{old_ok} {new_ok} {old_after}")
    s.expect("another tenant cannot see or change this endpoint", call(api, "PATCH", f"/webhook-endpoints/{ep['id']}", other["admin"], {"status": "disabled"})[0] == 404 and not any(e["id"] == ep["id"] for e in call(api, "GET", "/webhook-endpoints", other["admin"])[1]["items"]))
    call(api, "PATCH", f"/webhook-endpoints/{ep['id']}", tok["admin"], {"status": "disabled"})
    s.expect("a disabled endpoint rejects even a correctly signed delivery (401)", send(body, secret=secrets_["next"])[0] == 401)
    audit = {a["action"] for a in call(api, "GET", "/audit?limit=100", tok["auditor"])[1]["items"]}
    need = {"webhook.endpoint_created", "webhook.endpoint_updated", "webhook.delivery_accepted", "webhook.delivery_processed", "webhook.delivery_replayed", "webhook.delivery_rejected", "connector.sync_completed"}
    s.expect("the audit log records endpoint changes and every authenticated delivery outcome", need <= audit, f"missing {sorted(need - audit)}")
    blob = json.dumps(call(api, "GET", "/audit?limit=100", tok["auditor"])[1]) + json.dumps(call(api, "GET", "/ingestion/jobs?limit=100", tok["engineer"])[1]) + json.dumps(call(api, "GET", "/webhook-endpoints", tok["admin"])[1])
    s.expect("no signing secret, API key or delivery content appears in the audit log, job list or endpoint list", secrets_["current"] not in blob and secrets_["next"] not in blob and key not in blob and "Live delivery" not in blob)
    return s.items


def run_browser(demo, outdir: Path) -> dict:
    npx = shutil.which("npx")
    if not npx:
        raise SmokeFailure("npx was not found on PATH (Node installation)")
    outdir.mkdir(parents=True, exist_ok=True)
    env = {**demo.env, "DEMO_UI_URL": f"http://127.0.0.1:{demo.ports['ui']}", "DEMO_PASSWORD": demo.env["SEED_PASSWORD"], "DEMO_OUT": str(outdir.resolve())}
    log = demo.run_dir / "logs" / "playwright.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as handle:
        res = subprocess.run([npx, "playwright", "test", "-c", "playwright.demo.config.ts"], cwd=ROOT / "frontend", env=env, stdout=handle, stderr=subprocess.STDOUT, timeout=600)
    results = outdir / "playwright-results.json"
    if not results.exists():
        raise SmokeFailure(f"the browser run produced no results (exit {res.returncode}); see {log.relative_to(ROOT)}")
    summary = summarize_playwright(json.loads(results.read_text(encoding="utf-8")), outdir)
    if not summary["tests"] or summary["failed"] or summary["passed"] != len(summary["tests"]):
        raise SmokeFailure(f"browser smoke failed or incomplete: {summary['passed']} passed, {summary['failed']} failed of {len(summary['tests'])}; see {log.relative_to(ROOT)}")
    return summary


def summarize_playwright(data: dict, outdir: Path) -> dict:
    """Condense Playwright's JSON report: per-test status, counts, and every recorded initial-navigation retry (annotation type `navigation-retry`)."""
    tests, retries = [], []

    def walk(suite):
        for spec in suite.get("specs", []):
            for t in spec.get("tests", []):
                tests.append({"title": spec["title"], "status": t["status"], "seconds": round(sum(r["duration"] for r in t["results"]) / 1000, 1)})
                retries.extend(a.get("description", "") for a in t.get("annotations", []) if a.get("type") == "navigation-retry")
        for child in suite.get("suites", []):
            walk(child)
    for suite in data.get("suites", []):
        walk(suite)
    return {"browser": "Microsoft Edge (installed; nothing downloaded)", "stack": "this demo stack (real UI, API, worker, database; mock external systems)", "tests": tests, "navigation_retries": len(retries), "navigation_retry_details": retries,
            "passed": sum(t["status"] == "expected" for t in tests), "failed": sum(t["status"] in ("unexpected", "flaky") for t in tests), "skipped": sum(t["status"] == "skipped" for t in tests),
            "screenshots": sorted(p.name for p in (outdir / "screenshots").glob("*.png")) if (outdir / "screenshots").exists() else []}


def redact(text: str, env_file: dict) -> str:
    for name, value in env_file.items():
        if any(k in name for k in ("PASSWORD", "SECRET", "KEY", "TOKEN")) and len(value) >= 6:
            text = text.replace(value, "[redacted]")
    return text


def write_report(outdir: Path, report: dict, env_file: dict) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "report.json").write_text(redact(json.dumps(report, indent=1, default=str), env_file) + "\n", encoding="utf-8", newline="\n")
    lines = [f"# Demo smoke report {report['run_id']}", "", f"Result: **{'PASSED' if report.get('success') else 'FAILED'}** in {report.get('duration_seconds')} s (mode {report['mode']}, AI backends: {report['ai']}).",
             f"Git HEAD at run: `{report.get('git_head')}`. Started {report.get('started_at')}, finished {report.get('finished_at')}.", ""]
    if report.get("failures"):
        lines += ["## Failures", *[f"- {f}" for f in report["failures"]], ""]
    if report.get("skipped"):
        lines += ["## Skipped", *[f"- {s}" for s in report["skipped"]], ""]
    lines += ["## Timeline (executed)", "", "| Step | Result | Seconds | Detail |", "|---|---|---|---|"]
    lines += [f"| {t['step']} | {'ok' if t['ok'] else 'FAILED'} | {t['seconds']} | {t['detail']} |" for t in report.get("timeline", [])]
    if report.get("database"):
        d = report["database"]
        lines += ["", f"Database: disposable `{d['name']}` created by this run, migrated to revision `{d['revision']}` (head `{d['head']}`)."]
    for slug, steps in (report.get("workflows", {}).get("tenants", {})).items():
        lines += ["", f"## Workflow checks: {slug} (API, real application; external systems simulated)", "", *[f"- {'ok' if s['ok'] else 'FAILED'}: {s['step']} {('(' + s['detail'] + ')') if s['detail'] else ''}" for s in steps]]
    ing = report.get("ingestion") or {}
    if ing:
        lines += ["", "## Live ingestion checkpoint (durable jobs, retry, reprocessing, deletion races)", "", f"Fault model: {ing.get('fault', '')}", ""]
        for slug, steps in ing.get("tenants", {}).items():
            lines += [f"### {slug}", "", *[f"- {'ok' if s['ok'] else 'FAILED'}: {s['step']} {('(' + s['detail'] + ')') if s['detail'] else ''}" for s in steps], ""]
    integ = report.get("integrations") or {}
    if integ:
        lines += ["", "## Live CSV and signed-webhook integrations", "", integ.get("note", ""), ""]
        for slug, steps in integ.get("tenants", {}).items():
            lines += [f"### {slug}", "", *[f"- {'ok' if s['ok'] else 'FAILED'}: {s['step']} {('(' + s['detail'] + ')') if s['detail'] else ''}" for s in steps], ""]
    rest = report.get("rest") or {}
    if rest:
        lines += ["", "## Live REST pull synchronization (connector, pagination, rate limit, health probe, recovery)", "", f"Source: {rest.get('records_source', '')}", f"Fault model: {rest.get('fault', '')}", ""]
        for slug, steps in rest.get("tenants", {}).items():
            lines += [f"### {slug}", "", *[f"- {'ok' if s['ok'] else 'FAILED'}: {s['step']} {('(' + s['detail'] + ')') if s['detail'] else ''}" for s in steps], ""]
    if report.get("browser"):
        b = report["browser"]
        lines += ["", "## Browser smoke", "", f"{b['passed']} passed, {b['failed']} failed, {b['skipped']} skipped on {b['stack']}; {b['browser']}.", f"Initial-navigation retries: {b.get('navigation_retries', 0)}" + ("" if not b.get("navigation_retries") else " (" + " || ".join(b["navigation_retry_details"]) + ")") + ".", *[f"- {t['status']}: {t['title']} ({t['seconds']} s)" for t in b["tests"]]]
    if report.get("backup"):
        k = report["backup"]
        lines += ["", "## Backup and restore proof", "", f"`{k['file']}` ({k['bytes']} bytes, sha256 `{k['sha256'][:16]}...`) of `{k['source_database']}` ({k['tables']} tables, {k['rows']} rows; tenants {', '.join(k['tenants'])}) restored into the new isolated database `{k['restore_database']}` ({k['restore_database_state']}):", *[f"- {'ok' if c['ok'] else 'FAILED'}: {c['check']} ({c['detail']})" for c in k["checks"]]]
    lines += ["", "## Cleanup", "", *[f"- {c['resource']}: {c['result']}" for c in report.get("cleanup", [])], "", "Secrets and credentials are redacted from this report. Logs are kept under `.demo/<run id>/logs` (git-ignored)."]
    (outdir / "report.md").write_text(redact("\n".join(lines) + "\n", env_file), encoding="utf-8", newline="\n")
