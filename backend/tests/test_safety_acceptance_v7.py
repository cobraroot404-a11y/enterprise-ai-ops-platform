"""Frozen safety-v7 confirmation run (V7 structural evidence boundary). Opt-in: SAFETY_ACCEPT_LABEL set; SAFETY_DATASET defaults to safety-v7.

Same measures as the v5/v6 scorer plus: structured-record handling (valid verified, forged/invalid never verified, forged tenant field rejected at the API), missed urgent reviews,
unnecessary urgent flags, locale cases and keyword-less candidates. Writes evaluation/reports/safety/<label>.json; never edits the frozen set."""
import hashlib
import json
import os
import time
from pathlib import Path

import pytest
from support import login, onboard_meridian
from test_safety_acceptance import ScriptedLLM

ROOT = Path(__file__).resolve().parents[2]
DATASET = os.environ.get("SAFETY_DATASET", "safety-v7")
DATA = ROOT / "evaluation" / "datasets" / DATASET
LABEL = os.environ.get("SAFETY_ACCEPT_LABEL")
pytestmark = pytest.mark.skipif(not LABEL, reason="frozen safety acceptance run; set SAFETY_ACCEPT_LABEL")
RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}


def same(a, b):
    return abs(a - b) <= max(1e-6, 0.005 * max(abs(a), abs(b)))


def test_frozen_v7(client, apex_loaded, owner_engine, servicedesk_server, fleet_server, crm_server, monkeypatch):
    from app.api.v1 import domain_routes
    cases = [json.loads(x) for x in (DATA / "cases.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    assert hashlib.sha256((DATA / "cases.jsonl").read_bytes()).hexdigest() in (DATA / "MANIFEST.sha256").read_text()
    mer = onboard_meridian(client, owner_engine, servicedesk_server, fleet_server, crm_server)
    llm = ScriptedLLM(cases)
    monkeypatch.setattr(domain_routes, "get_llm", lambda _n: llm)
    eng = {"apex": login(client, apex_loaded, "support_engineer"), "meridian": login(client, mer, "support_engineer")}
    sup = {"apex": login(client, apex_loaded, "maintenance_supervisor"), "meridian": login(client, mer, "maintenance_supervisor")}
    other = {"apex": "meridian", "meridian": "apex"}

    def body(c):
        b = {"report_text": c["report_text"]}
        if c["observations"]:
            b["observations"] = c["observations"]
        if c["numeric_locale"]:
            b["numeric_locale"] = c["numeric_locale"]
        return b
    donor = 0
    for c in cases:  # cross-tenant evidence attempt: the same report and records are filed first in the OTHER tenant
        if not c["valid"]:
            llm.by_text = {c["report_text"]: c}
            try:
                donor += client.post("/api/v1/incidents/extract", headers=eng[other[c["tenant"]]], json=body(c)).status_code == 201
            except Exception:  # noqa: BLE001  (the scripted model cannot parse another tenant's report shape: no foreign evidence exists then)
                pass
    results, lat = [], []
    for c in cases:
        llm.by_text = {c["report_text"]: c}
        t0 = time.perf_counter()
        r = client.post("/api/v1/incidents/extract", headers=eng[c["tenant"]], json=body(c))
        lat.append(time.perf_counter() - t0)
        if c["expect_api_rejection"]:
            results.append({"id": c["id"], "tenant": c["tenant"], "class": c["class"], "valid": False, "api_rejected": r.status_code == 422, "http": r.status_code})
            continue
        assert r.status_code == 201, (c["id"], r.text)
        inc = r.json()
        recs = inc["measurements"]
        holds = [m for m in recs if m["status"] in ("unsupported", "conflict", "quarantined")]
        verified = {m["name"]: m["value"] for m in recs if m["status"] == "verified"}
        exp = c["expected_verified"]
        wrong = {k: v for k, v in verified.items() if k not in exp or not same(v, exp[k])}
        notes = " ".join(inc["notes"])
        review_reason = "could not be verified" in notes or "model output failed validation" in notes
        trace_ok = all(m["evidence_span"] and m["evidence_location"] and (
            (m["source"] == "structured_record" and m["evidence_location"].get("field") == m["evidence_span"] and int(m["evidence_span"].split("[")[1].rstrip("]")) < len(c["observations"]))
            or (m["source"] != "structured_record" and c["report_text"][m["evidence_location"]["start"]:m["evidence_location"]["end"]] == m["evidence_span"]))
            for m in recs if m["status"] == "verified")
        d1 = client.post("/api/v1/tickets", headers=eng[c["tenant"]], json={"incident_id": inc["id"]})
        row = {"id": c["id"], "tenant": c["tenant"], "class": c["class"], "valid": c["valid"], "expected_priority": c["expected_priority"], "priority": inc["priority"], "review_urgency": inc["review_urgency"],
               "expected_urgent": c["expected_urgent"], "review_reason_recorded": review_reason, "verified": verified, "wrong_verified": wrong, "missing_verified": [k for k in exp if k not in verified],
               "holds": len(holds), "trace_ok": trace_ok, "reason_ok": all(m["verification_reason"] for m in holds), "priority_inflated": RANK[inc["priority"]] < RANK[c["expected_priority"]],
               "priority_deflated": RANK[inc["priority"]] > RANK[c["expected_priority"]], "draft_before_review": d1.status_code, "unauthorized_submission": (not c["valid"]) and d1.status_code == 201,
               "duplicate_submission": False, "structured": bool(c["observations"]), "api_rejected": None}
        if c["valid"]:
            if inc["review_status"] == "needs_review":
                client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup[c["tenant"]], json={"decision": "accept", "comment": "acceptance run: reviewed by supervisor"})
            a = client.post("/api/v1/tickets", headers=eng[c["tenant"]], json={"incident_id": inc["id"]})
            b = client.post("/api/v1/tickets", headers=eng[c["tenant"]], json={"incident_id": inc["id"]})
            row["duplicate_submission"] = a.status_code == 201 and b.status_code == 201
        results.append(row)
    ok = [x for x in results if x["api_rejected"] is None]
    inv, val = [x for x in ok if not x["valid"]], [x for x in ok if x["valid"]]
    urg = [x for x in ok if x["expected_urgent"]]
    crit = [x for x in val if x["expected_priority"] in ("P1", "P2")]
    m = {
        "cases": len(cases), "valid": sum(c["valid"] for c in cases), "invalid": sum(not c["valid"] for c in cases),
        "false_acceptance_cases": sum(1 for x in inv if x["wrong_verified"] or x["priority_inflated"] or not x["review_reason_recorded"]),
        "unsupported_values_verified": sum(len(x["wrong_verified"]) for x in ok), "unsupported_priority_inflation_cases": sum(1 for x in inv if x["priority_inflated"]),
        "false_rejection_cases": sum(1 for x in val if x["holds"] or x["review_reason_recorded"] or x["missing_verified"] or x["priority"] != x["expected_priority"]),
        "valid_measurements_verified_correctly": sum(1 for x in val if not x["missing_verified"] and not x["wrong_verified"]), "valid_cases": len(val),
        "invalid_correctly_held_with_reason": sum(1 for x in inv if x["review_reason_recorded"] and not x["wrong_verified"]), "invalid_cases_extracted": len(inv),
        "priority_correct": sum(1 for x in ok if x["priority"] == x["expected_priority"]), "priority_inflated": sum(x["priority_inflated"] for x in ok), "priority_deflated": sum(x["priority_deflated"] for x in ok),
        "expected_urgent_cases": len(urg), "expected_urgent_flagged": sum(1 for x in urg if x["review_urgency"] == "urgent"),
        "missed_urgent_reviews": [x["id"] for x in urg if x["review_urgency"] != "urgent"], "unnecessary_urgent_flags": [x["id"] for x in ok if x["review_urgency"] == "urgent" and not x["expected_urgent"]],
        "critical_valid_cases": len(crit), "critical_valid_kept": sum(1 for x in crit if x["priority"] == x["expected_priority"]), "genuine_critical_silently_downgraded": sum(1 for x in crit if x["priority_deflated"]),
        "ticket_drafts_blocked_before_review_invalid": sum(1 for x in inv if x["draft_before_review"] >= 400), "unauthorized_submissions": sum(x["unauthorized_submission"] for x in ok),
        "duplicate_submissions": sum(x["duplicate_submission"] for x in ok), "cross_tenant_donor_reports_filed": donor, "cross_tenant_evidence_accepted": sum(len(x["wrong_verified"]) for x in inv if x["structured"] or True),
        "verified_with_exact_trace": sum(1 for x in ok if x["verified"] and x["trace_ok"]), "verified_total": sum(1 for x in ok if x["verified"]),
        "held_with_reason": sum(1 for x in ok if x["holds"] and x["reason_ok"]), "held_total": sum(1 for x in ok if x["holds"]),
        "structured_valid_cases": sum(1 for x in val if x["structured"]), "structured_valid_verified": sum(1 for x in val if x["structured"] and not x["missing_verified"] and not x["wrong_verified"]),
        "forged_structured_cases_extracted": sum(1 for x in inv if x["structured"]), "forged_structured_verified": sum(1 for x in inv if x["structured"] and x["wrong_verified"]),
        "forged_tenant_field_cases": sum(1 for x in results if x.get("api_rejected") is not None), "forged_tenant_field_rejected_422": sum(1 for x in results if x.get("api_rejected")),
        "extract_latency_ms_mean": round(1000 * sum(lat) / len(lat), 1), "extract_latency_ms_max": round(1000 * max(lat), 1)}
    out = ROOT / "evaluation" / "reports" / "safety"
    (out / f"{LABEL}.json").write_text(json.dumps({"label": LABEL, "dataset": DATASET, "cases_sha256": hashlib.sha256((DATA / "cases.jsonl").read_bytes()).hexdigest(), "metrics": m, "results": results},
                                                  indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(m, indent=1))
