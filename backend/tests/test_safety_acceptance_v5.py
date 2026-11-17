"""Frozen safety-v5 confirmation run (hardening V5). Opt-in: SAFETY_ACCEPT_LABEL (and SAFETY_DATASET, default safety-v5) must be set.

Writes evaluation/reports/safety/<label>.json with exact numerators/denominators and per-case results; never edits the frozen set. Metrics: false acceptance
(an unsupported value verified, a wrong value verified, or priority above the label), false rejection (a valid case held / wrong priority / value not
verified), urgency (expected-urgent cases flagged), priority correctness, human review (reason recorded), ticket blocking before review, unauthorized and
duplicate submissions (valid cases: reviewed then ticketed twice), cross-tenant evidence (the same text submitted in the other tenant first), and audit
completeness (reason for every held measurement; span + location for every verified one).
"""
import hashlib
import json
import os
import time
from pathlib import Path

import pytest
from support import login, onboard_meridian
from test_safety_acceptance import ScriptedLLM

ROOT = Path(__file__).resolve().parents[2]
DATASET = os.environ.get("SAFETY_DATASET", "safety-v5")
DATA = ROOT / "evaluation" / "datasets" / DATASET
LABEL = os.environ.get("SAFETY_ACCEPT_LABEL")
pytestmark = pytest.mark.skipif(not LABEL, reason="frozen safety acceptance run; set SAFETY_ACCEPT_LABEL")
RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}


def same(a, b):
    return abs(a - b) <= max(1e-6, 0.005 * max(abs(a), abs(b)))


def test_frozen_v5(client, apex_loaded, owner_engine, servicedesk_server, fleet_server, crm_server, monkeypatch):
    from app.api.v1 import domain_routes
    cases = [json.loads(x) for x in (DATA / "cases.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    assert hashlib.sha256((DATA / "cases.jsonl").read_bytes()).hexdigest() in (DATA / "MANIFEST.sha256").read_text()
    mer = onboard_meridian(client, owner_engine, servicedesk_server, fleet_server, crm_server)
    llm = ScriptedLLM(cases)
    monkeypatch.setattr(domain_routes, "get_llm", lambda _n: llm)
    eng = {"apex": login(client, apex_loaded, "support_engineer"), "meridian": login(client, mer, "support_engineer")}
    sup = {"apex": login(client, apex_loaded, "maintenance_supervisor"), "meridian": login(client, mer, "maintenance_supervisor")}
    foreign = {"apex": "meridian", "meridian": "apex"}
    donor_ok = 0
    for c in cases:  # cross-tenant evidence attempt: the same text, stating the figures, is first filed in the OTHER tenant
        if not c["valid"]:
            try:  # the scripted model cannot always parse another tenant's report shape; a failed donor filing simply means no foreign evidence exists
                r = client.post("/api/v1/incidents/extract", headers=eng[foreign[c["tenant"]]], json={"report_text": c["report_text"]})
                donor_ok += r.status_code == 201
            except Exception:  # noqa: BLE001
                pass
    results, latencies = [], []
    for c in cases:
        t0 = time.perf_counter()
        r = client.post("/api/v1/incidents/extract", headers=eng[c["tenant"]], json={"report_text": c["report_text"]})
        latencies.append(time.perf_counter() - t0)
        assert r.status_code == 201, (c["id"], r.text)
        inc = r.json()
        recs = inc["measurements"]
        holds = [m for m in recs if m["status"] in ("unsupported", "conflict", "quarantined")]
        verified = {m["name"]: m["value"] for m in recs if m["status"] == "verified"}
        exp = c["expected_verified"]
        wrong_verified = {k: v for k, v in verified.items() if k not in exp or not same(v, exp[k])}
        missing_verified = [k for k in exp if k not in verified]
        notes = " ".join(inc["notes"])
        review_reason = "could not be verified" in notes or "model output failed validation" in notes
        trace_ok = all(m["evidence_span"] and m["evidence_location"] and c["report_text"][m["evidence_location"]["start"]:m["evidence_location"]["end"]] == m["evidence_span"]
                       for m in recs if m["status"] == "verified")
        reason_ok = all(m["verification_reason"] for m in holds)
        draft1 = client.post("/api/v1/tickets", headers=eng[c["tenant"]], json={"incident_id": inc["id"]})
        row = {"id": c["id"], "tenant": c["tenant"], "class": c["class"], "valid": c["valid"], "expected_priority": c["expected_priority"], "priority": inc["priority"],
               "review_urgency": inc["review_urgency"], "expected_urgent": c["expected_urgent"], "review_reason_recorded": review_reason, "verified": verified,
               "wrong_verified": wrong_verified, "missing_verified": missing_verified, "holds": len(holds), "trace_ok": trace_ok, "reason_ok": reason_ok,
               "priority_inflated": RANK[inc["priority"]] < RANK[c["expected_priority"]], "priority_deflated": RANK[inc["priority"]] > RANK[c["expected_priority"]],
               "draft_before_review": draft1.status_code, "unauthorized_submission": (not c["valid"]) and draft1.status_code == 201, "duplicate_submission": False}
        if c["valid"]:  # human accepts the review, then ticket creation is attempted twice: exactly one may exist
            if inc["review_status"] == "needs_review":
                client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup[c["tenant"]], json={"decision": "accept", "comment": "acceptance run: reviewed by supervisor"})
            a = client.post("/api/v1/tickets", headers=eng[c["tenant"]], json={"incident_id": inc["id"]})
            b = client.post("/api/v1/tickets", headers=eng[c["tenant"]], json={"incident_id": inc["id"]})
            row["duplicate_submission"] = a.status_code == 201 and b.status_code == 201
            row["ticket_after_review"] = [a.status_code, b.status_code]
        results.append(row)
    inv, val = [x for x in results if not x["valid"]], [x for x in results if x["valid"]]
    urg = [x for x in results if x["expected_urgent"]]
    crit_valid = [x for x in val if x["expected_priority"] in ("P1", "P2")]
    m = {
        "cases": len(results), "valid": len(val), "invalid": len(inv),
        "false_acceptance_cases": sum(1 for x in inv if x["wrong_verified"] or x["priority_inflated"] or not x["review_reason_recorded"] or x["verified"]),
        "unsupported_values_verified": sum(len(x["wrong_verified"]) for x in results),
        "unsupported_priority_inflation_cases": sum(1 for x in inv if x["priority_inflated"]),
        "false_rejection_cases": sum(1 for x in val if x["holds"] or x["review_reason_recorded"] or x["missing_verified"] or x["priority"] != x["expected_priority"]),
        "valid_with_expected_measurement": sum(1 for x in val if x["verified"] or x["missing_verified"]),
        "valid_measurements_verified_correctly": sum(1 for x in val if (x["verified"] or x["missing_verified"]) and not x["missing_verified"] and not x["wrong_verified"]),
        "invalid_correctly_held_with_reason": sum(1 for x in inv if x["review_reason_recorded"] and not x["verified"]),
        "priority_correct": sum(1 for x in results if x["priority"] == x["expected_priority"]),
        "priority_inflated": sum(x["priority_inflated"] for x in results), "priority_deflated_not_flagged": sum(1 for x in results if x["priority_deflated"] and x["review_urgency"] != "urgent"),
        "priority_deflated_total": sum(x["priority_deflated"] for x in results),
        "expected_urgent_cases": len(urg), "expected_urgent_flagged": sum(1 for x in urg if x["review_urgency"] == "urgent"),
        "urgent_flag_on_unexpected_cases": sum(1 for x in results if x["review_urgency"] == "urgent" and not x["expected_urgent"]),
        "critical_valid_cases": len(crit_valid), "critical_valid_kept": sum(1 for x in crit_valid if x["priority"] == x["expected_priority"]),
        "genuine_critical_silently_downgraded": sum(1 for x in crit_valid if x["priority_deflated"]),
        "ticket_drafts_blocked_before_review_invalid": sum(1 for x in inv if x["draft_before_review"] >= 400),
        "unauthorized_submissions": sum(x["unauthorized_submission"] for x in results), "duplicate_submissions": sum(x["duplicate_submission"] for x in results),
        "cross_tenant_donor_reports_filed": donor_ok, "cross_tenant_evidence_accepted": sum(len(x["wrong_verified"]) for x in inv),
        "verified_with_exact_trace": sum(1 for x in results if x["verified"] and x["trace_ok"]), "verified_total": sum(1 for x in results if x["verified"]),
        "held_with_reason": sum(1 for x in results if x["holds"] and x["reason_ok"]), "held_total": sum(1 for x in results if x["holds"]),
        "extract_latency_ms_mean": round(1000 * sum(latencies) / len(latencies), 1), "extract_latency_ms_max": round(1000 * max(latencies), 1),
    }
    out = ROOT / "evaluation" / "reports" / "safety"
    out.mkdir(parents=True, exist_ok=True)
    payload = {"label": LABEL, "dataset": DATASET, "cases_sha256": hashlib.sha256((DATA / "cases.jsonl").read_bytes()).hexdigest(), "metrics": m, "results": results}
    (out / f"{LABEL}.json").write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(m, indent=1))
