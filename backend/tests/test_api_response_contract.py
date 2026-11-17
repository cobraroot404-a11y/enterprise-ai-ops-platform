"""V41-17.03 Batch 3: runtime response-contract harness.

`capture_all` exercises every one of the 45 API operations with deterministic fixtures and records, per operation, the success status, content type, the selected response
headers and a structural SHAPE of the JSON body (key names, value types, null versus omitted, nesting, list item shapes, UUID/timestamp string formats, and the concrete value of a few
enumeration-like fields). The pre-change shapes were captured once, before any response model existed, into evaluation/api-quality/response-baseline-pre-batch3.json (development
evidence; never regenerated to hide a change). `test_runtime_responses_are_unchanged_from_the_pre_batch3_baseline` fails on ANY difference. A second group of tests validates each captured
response against the OpenAPI success schema the application now declares.

Capture the baseline only on pre-change code:  CAPTURE_RESPONSE_BASELINE=1 python -m pytest tests/test_api_response_contract.py -k capture_baseline"""
import json
import os
import re
import uuid

import pytest
from app.core.security import hash_password
from sqlalchemy import text
from support import PASSWORD, ROOT, SAMPLES, login

BASELINE = ROOT / "evaluation" / "api-quality" / "response-baseline-pre-batch3.json"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
ENUM_KEYS = {"priority", "state", "status", "review_status", "decision", "kind", "category", "role", "topic", "trust_status", "evidence_class", "review_urgency", "outcome", "result", "mode"}
HEADERS = ("content-type", "x-correlation-id", "retry-after")
REPORT = "Pump P-101 shows abnormal vibration at the drive end, measured at 8.4 mm/s, with a grinding noise since this morning."
UNREGISTERED = "Pump Z-999 shows abnormal vibration at 8.4 mm/s with grinding noise."


def shape(value, key=None):
    """Structural signature of a JSON value (types, formats, nesting); values are not recorded except for enumeration-like keys."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        if UUID_RE.match(value):
            return "str:uuid"
        if ISO_RE.match(value):
            return "str:datetime"
        return f"str={value}" if key in ENUM_KEYS and len(value) < 40 else "str"
    if isinstance(value, list):
        return sorted({json.dumps(shape(v, key), sort_keys=True) for v in value}) or "empty-list"
    if isinstance(value, dict):
        if not value:
            return "empty-object"
        return {k: shape(value[k], k) for k in sorted(value)}
    return type(value).__name__


def op_key(method, path):
    return f"{method.upper()} {path}"


class Recorder:
    def __init__(self):
        self.ops = {}
        self.errors = []

    def rec(self, key, resp, expect=(200, 201)):
        if resp.status_code not in expect:
            self.errors.append(f"{key}: unexpected status {resp.status_code}: {resp.text[:160]}")
            return resp
        ctype = resp.headers.get("content-type", "")
        body = resp.json() if "json" in ctype else None
        self.ops.setdefault(key, {"status": resp.status_code, "content_type": ctype.split(";")[0], "headers": sorted(h for h in HEADERS if h in resp.headers),
                                  "shape": shape(body), "body": body})
        return resp


def capture_all(client, apex, owner_engine, ticketing, servicedesk_server, fleet_server, crm_server):
    """Drive all 45 operations; returns the Recorder (with raw bodies for schema validation)."""
    from support import onboard_meridian
    R = Recorder()
    eng, sup, adm, aud = (login(client, apex, r) for r in ("support_engineer", "maintenance_supervisor", "tenant_admin", "read_only_auditor"))
    tid = str(apex.id)
    # --- public / session
    R.rec(op_key("get", "/api/v1/health"), client.get("/api/v1/health"))
    R.rec(op_key("post", "/api/v1/auth/login"), client.post("/api/v1/auth/login", json={"email": apex.users["tenant_admin"], "password": PASSWORD, "tenant": apex.slug}))
    R.rec(op_key("get", "/api/v1/auth/me"), client.get("/api/v1/auth/me", headers=adm))
    R.rec(op_key("get", "/api/v1/tenants/mine"), client.get("/api/v1/tenants/mine", headers=adm))
    # --- platform admin
    email = f"platform.contract.{uuid.uuid4().hex[:6]}@example.test"
    with owner_engine.begin() as conn:
        conn.execute(text("INSERT INTO users (email, full_name, password_hash, is_platform_admin) VALUES (:e, 'Platform', :p, true)"), {"e": email, "p": hash_password(PASSWORD)})
    ptok = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
    padm = {"Authorization": f"Bearer {ptok}"}
    R.rec(op_key("post", "/api/v1/tenants"), client.post("/api/v1/tenants", headers=padm, json={"slug": f"contract-{uuid.uuid4().hex[:8]}", "name": "Contract Tenant"}))
    R.rec(op_key("get", "/api/v1/platform/audit"), client.get("/api/v1/platform/audit", headers=padm))
    # --- members
    member = {"email": f"member.{uuid.uuid4().hex[:6]}@example.test", "full_name": "Member Test", "password": "A-long-password-123", "role": "support_engineer"}
    R.rec(op_key("get", "/api/v1/tenants/{tenant_id}/members"), client.get(f"/api/v1/tenants/{tid}/members", headers=adm))
    created = R.rec(op_key("post", "/api/v1/tenants/{tenant_id}/members"), client.post(f"/api/v1/tenants/{tid}/members", headers=adm, json=member))
    if created.status_code == 201:
        uid = created.json().get("user_id") or created.json().get("id")
        R.rec(op_key("patch", "/api/v1/tenants/{tenant_id}/members/{user_id}"), client.patch(f"/api/v1/tenants/{tid}/members/{uid}", headers=adm, json={"role": "maintenance_supervisor"}))
        R.rec(op_key("delete", "/api/v1/tenants/{tenant_id}/members/{user_id}"), client.delete(f"/api/v1/tenants/{tid}/members/{uid}", headers=adm))
    # --- connectors, profile, operational read endpoints
    R.rec(op_key("get", "/api/v1/connectors"), client.get("/api/v1/connectors", headers=adm))
    R.rec(op_key("post", "/api/v1/connectors"), client.post("/api/v1/connectors", headers=adm, json={"kind": "ticketing", "name": f"contract-{uuid.uuid4().hex[:6]}", "base_url": ticketing.url, "config": {}}))
    R.rec(op_key("get", "/api/v1/connectors/health"), client.get("/api/v1/connectors/health", headers=adm))
    R.rec(op_key("get", "/api/v1/tenant-profile"), client.get("/api/v1/tenant-profile", headers=adm))
    R.rec(op_key("get", "/api/v1/onboarding/health"), client.get("/api/v1/onboarding/health", headers=adm))
    R.rec(op_key("get", "/api/v1/metrics"), client.get("/api/v1/metrics", headers=adm))
    R.rec(op_key("get", "/api/v1/observability/summary"), client.get("/api/v1/observability/summary", headers=adm))
    R.rec(op_key("get", "/api/v1/evaluation/reports"), client.get("/api/v1/evaluation/reports", headers=adm))
    # --- documents, ingestion, search, ask
    R.rec(op_key("post", "/api/v1/documents"), client.post("/api/v1/documents", headers=eng, data={"kind": "incident_history"}, files={"file": ("contract_history.csv", (SAMPLES / "incident_history.csv").read_bytes())}))
    docs = R.rec(op_key("get", "/api/v1/documents"), client.get("/api/v1/documents", headers=eng))
    R.rec(op_key("get", "/api/v1/documents/{document_id}"), client.get(f"/api/v1/documents/{docs.json()['items'][0]['id']}", headers=eng))
    R.rec(op_key("get", "/api/v1/ingestion/status"), client.get("/api/v1/ingestion/status", headers=eng))
    R.rec(op_key("post", "/api/v1/search"), client.post("/api/v1/search", headers=eng, json={"query": "pump vibration bearing", "k": 3}))
    R.rec(op_key("post", "/api/v1/ai/ask"), client.post("/api/v1/ai/ask", headers=eng, json={"question": "What should I check when pump P-101 vibrates?"}))
    # --- incidents
    ext = R.rec(op_key("post", "/api/v1/incidents/extract"), client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": REPORT}))
    inc = ext.json()
    unreg = client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": UNREGISTERED}).json()
    R.rec(op_key("get", "/api/v1/incidents"), client.get("/api/v1/incidents", headers=eng))
    R.rec(op_key("get", "/api/v1/incidents/{incident_id}"), client.get(f"/api/v1/incidents/{inc['id']}", headers=eng))
    R.rec(op_key("get", "/api/v1/incidents/{incident_id}/history"), client.get(f"/api/v1/incidents/{inc['id']}/history", headers=eng))
    R.rec(op_key("post", "/api/v1/incidents/{incident_id}/verify-asset"), client.post(f"/api/v1/incidents/{unreg['id']}/verify-asset", headers=sup))
    R.rec(op_key("post", "/api/v1/incidents/{incident_id}/review"), client.post(f"/api/v1/incidents/{unreg['id']}/review", headers=sup, json={"decision": "accept", "comment": "Newly installed, checked on site."}))
    R.rec(op_key("post", "/api/v1/incidents/{incident_id}/measurements/{name}/verify"),
          client.post(f"/api/v1/incidents/{inc['id']}/measurements/vibration_mm_s/verify", headers=sup, json={"decision": "approve", "comment": "Checked the printout.", "expected_trust_status": "UNVERIFIED"}))
    # --- tickets and approvals
    tickets = []
    for asset, v in (("P-102", 7.9), ("P-103", 9.1), ("P-101", 6.2), ("M-201", 5.5)):
        i = client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": f"Pump {asset} shows abnormal vibration at the drive end, measured at {v} mm/s, with a grinding noise since this morning."}).json()
        tickets.append(i)
    t1 = R.rec(op_key("post", "/api/v1/tickets"), client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]})).json()
    t_pend = client.post("/api/v1/tickets", headers=eng, json={"incident_id": tickets[0]["id"]}).json()
    t_cancel = client.post("/api/v1/tickets", headers=eng, json={"incident_id": tickets[1]["id"]}).json()
    t_fail = client.post("/api/v1/tickets", headers=eng, json={"incident_id": tickets[2]["id"]}).json()
    R.rec(op_key("get", "/api/v1/tickets"), client.get("/api/v1/tickets", headers=eng))
    R.rec(op_key("get", "/api/v1/tickets/{ticket_id}"), client.get(f"/api/v1/tickets/{t1['id']}", headers=eng))
    R.rec(op_key("patch", "/api/v1/tickets/{ticket_id}"), client.patch(f"/api/v1/tickets/{t1['id']}", headers=eng, json={"title": "Contract title edit"}))
    R.rec(op_key("post", "/api/v1/tickets/{ticket_id}/request-approval"), client.post(f"/api/v1/tickets/{t1['id']}/request-approval", headers=eng))
    client.post(f"/api/v1/tickets/{t_pend['id']}/request-approval", headers=eng)  # stays pending for the queue
    R.rec(op_key("get", "/api/v1/approvals"), client.get("/api/v1/approvals", headers=sup))
    R.rec(op_key("post", "/api/v1/approvals/{ticket_id}/decision"), client.post(f"/api/v1/approvals/{t1['id']}/decision", headers=sup, json={"decision": "approved", "comment": "ok"}))
    R.rec("GET /api/v1/approvals [status=decided]", client.get("/api/v1/approvals", headers=sup, params={"status": "decided"}))
    R.rec(op_key("get", "/api/v1/tickets/{ticket_id}/history"), client.get(f"/api/v1/tickets/{t1['id']}/history", headers=eng))
    R.rec(op_key("post", "/api/v1/tickets/{ticket_id}/cancel"), client.post(f"/api/v1/tickets/{t_cancel['id']}/cancel", headers=eng))
    client.post(f"/api/v1/tickets/{t_fail['id']}/request-approval", headers=eng)  # retry only applies to a FAILED ticket that was approved
    client.post(f"/api/v1/approvals/{t_fail['id']}/decision", headers=sup, json={"decision": "approved", "comment": "ok"})
    with owner_engine.begin() as conn:  # controlled state for the manual retry operation
        conn.execute(text("UPDATE tickets SET state = 'FAILED', last_error = 'contract fixture' WHERE id = :i"), {"i": t_fail["id"]})
    R.rec(op_key("post", "/api/v1/tickets/{ticket_id}/retry"), client.post(f"/api/v1/tickets/{t_fail['id']}/retry", headers=sup))
    # submit: an approved ticket
    t_sub = client.post("/api/v1/tickets", headers=eng, json={"incident_id": tickets[3]["id"]}).json()
    client.post(f"/api/v1/tickets/{t_sub['id']}/request-approval", headers=eng)
    client.post(f"/api/v1/approvals/{t_sub['id']}/decision", headers=sup, json={"decision": "approved", "comment": "ok"})
    R.rec(op_key("post", "/api/v1/tickets/{ticket_id}/submit"), client.post(f"/api/v1/tickets/{t_sub['id']}/submit", headers=eng))
    # --- workflows and audit
    R.rec(op_key("get", "/api/v1/workflows"), client.get("/api/v1/workflows", headers=sup))
    R.rec(op_key("get", "/api/v1/audit"), client.get("/api/v1/audit", headers=aud))
    # --- extra variants (added in Batch 3; not part of the pre-change baseline): structured submission, rejected record, empty pages, unsupported candidate
    o = {"asset_id": "P-101", "measurement_type": "vibration", "value": 12.5, "unit": "mm/s", "observed_at": "2026-11-12T09:00:00-05:00", "source": "contract fixture"}
    R.rec("POST /api/v1/incidents/extract [structured]", client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": REPORT, "observations": [o]}))
    R.rec("POST /api/v1/incidents/extract [rejected-structured]", client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": REPORT, "observations": [{**o, "asset_id": "P-102"}]}))
    R.rec("POST /api/v1/incidents/extract [no-number]", client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": "Strong vibration felt on the base of pump P-101, the handrail is humming."}))
    R.rec("GET /api/v1/incidents [empty]", client.get("/api/v1/incidents", headers=eng, params={"asset_id": "NO-SUCH-ASSET"}))
    R.rec("GET /api/v1/tickets [empty]", client.get("/api/v1/tickets", headers=eng, params={"state": "SUBMITTING", "q": "no-such-ticket"}))
    R.rec("GET /api/v1/audit [filtered]", client.get("/api/v1/audit", headers=aud, params={"action": "incident.extracted", "limit": 3}))
    R.rec("GET /api/v1/onboarding/health [non-admin]", client.get("/api/v1/onboarding/health", headers=sup))  # connector checks become "unavailable" for non-administrators
    # --- a Meridian tenant for profile variants
    mer = onboard_meridian(client, owner_engine, servicedesk_server, fleet_server, crm_server)
    madm = login(client, mer, "tenant_admin")
    R.rec("GET /api/v1/tenant-profile [meridian]", client.get("/api/v1/tenant-profile", headers=madm))
    prof = json.loads((ROOT / "onboarding" / "meridian.json").read_text(encoding="utf-8"))["profile"]
    R.rec(op_key("put", "/api/v1/tenant-profile"), client.put("/api/v1/tenant-profile", headers=madm, json=prof))
    R.rec("GET /api/v1/connectors [meridian]", client.get("/api/v1/connectors", headers=madm))
    R.rec("GET /api/v1/onboarding/health [meridian]", client.get("/api/v1/onboarding/health", headers=madm))
    return R


def _strip(ops):
    return {k: {f: v[f] for f in ("status", "content_type", "headers", "shape")} for k, v in ops.items()}


@pytest.fixture()
def recorder(client, apex_loaded, owner_engine, ticketing, servicedesk_server, fleet_server, crm_server):
    return capture_all(client, apex_loaded, owner_engine, ticketing, servicedesk_server, fleet_server, crm_server)


def test_capture_baseline(recorder):
    """Writes the pre-change baseline when CAPTURE_RESPONSE_BASELINE=1; otherwise only checks that every operation was exercised with a success status."""
    assert recorder.errors == [], recorder.errors
    base_ops = {k for k in recorder.ops if "[" not in k}
    assert len(base_ops) == 45, f"only {len(base_ops)} of 45 operations captured: missing {sorted(set(op_key(m, p) for m, p in []) - base_ops)}"
    if os.environ.get("CAPTURE_RESPONSE_BASELINE") == "1":
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(_strip(recorder.ops), indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


# Two responses are unions of per-event shapes that legitimately GROW when a feature adds audit events (their `details` are free-form per action) or metric counters
# (Batch 9 added ingestion job events and counters). For exactly these operations the baseline's shapes must all still be present and the structure must be identical;
# a removed or changed shape, a new key in the first levels of the response, or any other operation's difference still fails.
VOCABULARY_GROWTH = {"GET /api/v1/audit", "GET /api/v1/observability/summary"}


def _superset(baseline, current, depth=0) -> bool:
    """Structure down to the response's top-level keys must be identical; below that, maps keyed by event or metric names may gain keys and lists of shapes may gain shapes."""
    if isinstance(baseline, dict) and isinstance(current, dict):
        keys_ok = set(baseline) == set(current) if depth <= 2 else set(baseline) <= set(current)
        return keys_ok and all(_superset(baseline[k], current[k], depth + 1) for k in baseline)
    if isinstance(baseline, list) and isinstance(current, list):
        return set(baseline) <= set(current)
    if baseline == "empty-list" and isinstance(current, list):  # a list that was empty when captured may now hold items
        return True
    return baseline == current


def test_runtime_responses_are_unchanged_from_the_pre_batch3_baseline(recorder):
    """Every operation and variant captured BEFORE any response model existed must still return the same status, content type, headers and JSON shape."""
    if not BASELINE.exists():
        pytest.skip("baseline not captured yet")
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    current = json.loads(json.dumps(_strip(recorder.ops), sort_keys=True))
    missing = sorted(set(baseline) - set(current))
    assert missing == [], f"baseline entries no longer captured: {missing}"
    diffs = {k: {"baseline": baseline[k], "current": current[k]} for k in baseline
             if baseline[k] != current[k] and not (k in VOCABULARY_GROWTH and _superset(baseline[k], current[k]))}
    assert diffs == {}, f"runtime response contract changed for {sorted(diffs)}"
    assert len([k for k in baseline if "[" not in k]) == 45
