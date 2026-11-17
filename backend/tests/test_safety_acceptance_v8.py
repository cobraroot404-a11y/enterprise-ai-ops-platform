"""Frozen safety-v8 confirmation run (V8 numeric evidence trust policy). Opt-in: SAFETY_ACCEPT_LABEL set; SAFETY_DATASET defaults to safety-v8.

Runs each case through the real extract endpoint (scripted model), builds signed or forged simulator provenance at run time, plays the scripted human-verification actions and checks the
final state against labels derived from the requirement. Writes evaluation/reports/safety/<label>.json with exact numerators and denominators. Never edits the frozen set."""
import hashlib
import json
import os
import time
from pathlib import Path

import pytest
from app.ai.measurement_trust import SIMULATION_KEY_ENV, sign_simulated_observation
from support import login, onboard_meridian
from test_safety_acceptance import ScriptedLLM

ROOT = Path(__file__).resolve().parents[2]
DATASET = os.environ.get("SAFETY_DATASET", "safety-v8")
DATA = ROOT / "evaluation" / "datasets" / DATASET
LABEL = os.environ.get("SAFETY_ACCEPT_LABEL")
pytestmark = pytest.mark.skipif(not LABEL, reason="frozen safety acceptance run; set SAFETY_ACCEPT_LABEL")
RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
KEY, OTHER_KEY = b"v8-acceptance-fixture-key", b"a-key-the-server-does-not-hold"
NAMES = {"vibration": "vibration_mm_s", "brake_pressure": "brake_pressure_psi", "coolant_temperature": "coolant_temp_c"}
PROVENANCE_KEYS = ("tenant_id", "incident_id", "asset_id", "numeric_rules_executed", "applied_rule", "resulting_priority", "decided_at", "reason")


def same(a, b):
    return abs(a - b) <= max(1e-6, 0.005 * max(abs(a), abs(b)))


def test_frozen_v8(client, apex_loaded, owner_engine, servicedesk_server, fleet_server, crm_server, monkeypatch):
    from app.api.v1 import domain_routes
    monkeypatch.setenv(SIMULATION_KEY_ENV, KEY.decode())
    cases = [json.loads(x) for x in (DATA / "cases.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    assert hashlib.sha256((DATA / "cases.jsonl").read_bytes()).hexdigest() in (DATA / "MANIFEST.sha256").read_text()
    mer = onboard_meridian(client, owner_engine, servicedesk_server, fleet_server, crm_server)
    tenants = {"apex": apex_loaded, "meridian": mer}
    tok = {t: {"engineer": login(client, env, "support_engineer"), "supervisor": login(client, env, "maintenance_supervisor"), "auditor": login(client, env, "read_only_auditor")} for t, env in tenants.items()}
    other = {"apex": "meridian", "meridian": "apex"}
    llm = ScriptedLLM(cases)
    monkeypatch.setattr(domain_routes, "get_llm", lambda _n: llm)

    def payload(c):
        obs = []
        for item in c["observations"]:
            o, sim = dict(item["o"]), item["sim"]
            if sim:
                tid = str(tenants[c["tenant"]].id)
                sid = "fixture-" + c["tenant"]
                if sim == "valid":
                    sig = sign_simulated_observation(KEY, tid, o, sid)
                elif sim == "bad_signature":
                    sig = "0" * 64
                elif sim == "tampered":
                    sig = sign_simulated_observation(KEY, tid, o, sid)
                    o = {**o, "value": o["value"] + 1.0}
                elif sim == "wrong_tenant":
                    sig = sign_simulated_observation(KEY, str(tenants[other[c["tenant"]]].id), o, sid)
                elif sim == "wrong_key":
                    sig = sign_simulated_observation(OTHER_KEY, tid, o, sid)
                else:  # unsigned_claim
                    sig = "f" * 64
                o = {**o, "simulation": {"source_id": sid, "signature": sig}}
            obs.append(o)
        body = {"report_text": c["report_text"]}
        if obs:
            body["observations"] = obs
        return body
    rows, lat = [], []
    for c in cases:
        llm.by_text = {c["report_text"]: c}
        t0 = time.perf_counter()
        r = client.post("/api/v1/incidents/extract", headers=tok[c["tenant"]][c["creator"]], json=payload(c))
        lat.append(time.perf_counter() - t0)
        if c["expect_api_rejection"]:
            rows.append({"id": c["id"], "class": c["class"], "api_rejection_expected": True, "rejected_422": r.status_code == 422})
            continue
        assert r.status_code == 201, (c["id"], r.text)
        inc = r.json()
        row = {"id": c["id"], "tenant": c["tenant"], "class": c["class"], "api_rejection_expected": False, "priority_at_extraction": inc["priority"], "expected_priority_at_extraction": c["expected_priority_at_extraction"],
               "review_urgency": inc["review_urgency"], "expected_urgent": c["expected_urgent"], "records_at_extraction": [(m["name"], m["evidence_class"], m["trust_status"], m["eligible_for_numeric_priority"]) for m in inc["measurements"]]}
        results = []
        for a in c["actions"]:
            who = tok[other[c["tenant"]]]["supervisor"] if a["by"] == "other_tenant_supervisor" else tok[c["tenant"]][a["by"]]
            resp = client.post(f"/api/v1/incidents/{inc['id']}/measurements/{a['name']}/verify", headers=who,
                               json={"decision": a["decision"], "comment": a["comment"], "expected_trust_status": a["status"]})
            results.append({"expect": a["expect_http"], "got": resp.status_code})
        final = client.get(f"/api/v1/incidents/{inc['id']}", headers=tok[c["tenant"]]["engineer"]).json()
        eligible = {m["name"]: m["value"] for m in final["measurements"] if m["eligible_for_numeric_priority"]}
        classes = {m["name"]: m["evidence_class"] for m in final["measurements"] if m["eligible_for_numeric_priority"]}
        wrong_elig = {k: v for k, v in eligible.items() if k not in c["expected_eligible"] or not same(v, c["expected_eligible"][k])}
        missing_elig = [k for k in c["expected_eligible"] if k not in eligible]
        wrong_class = [k for k, cl in classes.items() if cl != c["expected_eligible_class"] and not (c["expected_eligible_class"] == "D" and cl == "D")]
        audit = client.get("/api/v1/audit", headers=tok[c["tenant"]]["auditor"], params={"entity_id": inc["id"], "action": "incident.priority_decided", "limit": 20}).json()["items"]
        decided = [a["details"] for a in audit]
        prov_ok = bool(decided) and all(all(k in d for k in PROVENANCE_KEYS) for d in decided) and all(
            all(o.get("observation_id") and o.get("evidence_class") and o.get("verification_status") and o.get("provenance") is not None for o in d.get("observations", [])) for d in decided
            if d.get("numeric_rules_executed"))
        d1 = client.post("/api/v1/tickets", headers=tok[c["tenant"]]["engineer"], json={"incident_id": inc["id"]})
        dup = None
        if d1.status_code == 201:
            dup = client.post("/api/v1/tickets", headers=tok[c["tenant"]]["engineer"], json={"incident_id": inc["id"]}).status_code
        row.update({"priority_final": final["priority"], "expected_priority_final": c["expected_priority_final"], "eligible_final": eligible, "wrong_eligible": wrong_elig, "missing_eligible": missing_elig,
                    "wrong_class": wrong_class, "actions": results, "provenance_complete": prov_ok, "ticket_draft_status": d1.status_code, "review_status": final["review_status"], "duplicate_ticket_status": dup,
                    "genuine_critical": c["genuine_critical"], "unauthorized_submission": final["review_status"] == "needs_review" and d1.status_code == 201,
                    "duplicate_submission": d1.status_code == 201 and dup == 201,
                    "free_text_or_llm_eligible": any(m["evidence_class"] == "A" and m["eligible_for_numeric_priority"] for m in final["measurements"]),
                    "c_class_eligible_without_human": any(m["evidence_class"] == "C" and m["eligible_for_numeric_priority"] for m in inc["measurements"]),
                    "forged_sim_eligible": c["class"].startswith("D2") and any(m["eligible_for_numeric_priority"] for m in final["measurements"])})
        rows.append(row)
    ok = [x for x in rows if not x["api_rejection_expected"]]
    acts = [(x["id"], a) for x in ok for a in x["actions"]]
    crit = [x for x in ok if x["genuine_critical"]]
    m = {
        "cases": len(cases), "extracted": len(ok), "api_rejection_cases": len(rows) - len(ok), "api_rejections_correct_422": sum(1 for x in rows if x["api_rejection_expected"] and x["rejected_422"]),
        "free_text_or_llm_measurements_eligible": sum(1 for x in ok if x["free_text_or_llm_eligible"]),
        "values_influencing_priority_without_eligibility (priority inflated vs label)": sum(1 for x in ok if RANK[x["priority_final"]] < RANK[x["expected_priority_final"]]),
        "unsupported_structured_promoted_to_trusted": sum(1 for x in ok if x["c_class_eligible_without_human"] or (x["wrong_eligible"] and x["class"].startswith(("C", "D")))),
        "unexpected_eligible_observations": sum(len(x["wrong_eligible"]) for x in ok), "forged_simulator_provenance_accepted": sum(1 for x in ok if x["forged_sim_eligible"]),
        "verification_actions": len(acts), "verification_actions_with_expected_outcome": sum(1 for _, a in acts if a["got"] == a["expect"]),
        "unauthorized_verification_transitions": sum(1 for _, a in acts if a["expect"] in (403, 404, 409) and a["got"] == 200),
        "authorized_verifications_rejected": sum(1 for _, a in acts if a["expect"] == 200 and a["got"] != 200),
        "unauthorized_submissions": sum(x["unauthorized_submission"] for x in ok), "duplicate_submissions": sum(x["duplicate_submission"] for x in ok),
        "cross_tenant_evidence_accepted": sum(1 for x in ok if x["class"].startswith("H7") and any(a["got"] == 200 for a in x["actions"])) + sum(1 for x in ok if x["class"] == "D2_forged_simulator_provenance" and x["forged_sim_eligible"]),
        "genuine_critical_cases": len(crit), "genuine_critical_priority_correct": sum(1 for x in crit if x["priority_final"] == x["expected_priority_final"]),
        "genuine_critical_silently_downgraded": sum(1 for x in crit if RANK[x["priority_final"]] > RANK[x["expected_priority_final"]]),
        "priority_final_correct": sum(1 for x in ok if x["priority_final"] == x["expected_priority_final"]), "priority_deflated": sum(1 for x in ok if RANK[x["priority_final"]] > RANK[x["expected_priority_final"]]),
        "priority_at_extraction_correct": sum(1 for x in ok if x["priority_at_extraction"] == x["expected_priority_at_extraction"]),
        "eligible_expected_cases": sum(1 for x in ok if x["expected_priority_final"] and x["missing_eligible"] is not None and (x["eligible_final"] or x["missing_eligible"])),
        "eligible_correct": sum(1 for x in ok if not x["wrong_eligible"] and not x["missing_eligible"]), "false_rejections_of_legitimate_eligibility": sum(1 for x in ok if x["missing_eligible"]),
        "priority_decision_provenance_complete": sum(x["provenance_complete"] for x in ok), "priority_decisions_checked": len(ok),
        "expected_urgent": sum(1 for x in ok if x["expected_urgent"]), "urgent_flagged_correctly": sum(1 for x in ok if x["expected_urgent"] and x["review_urgency"] == "urgent"),
        "missed_urgent_reviews": [x["id"] for x in ok if x["expected_urgent"] and x["review_urgency"] != "urgent"], "unnecessary_urgent_flags": [x["id"] for x in ok if x["review_urgency"] == "urgent" and not x["expected_urgent"]],
        "extract_latency_ms_mean": round(1000 * sum(lat) / len(lat), 1), "extract_latency_ms_max": round(1000 * max(lat), 1)}
    out = ROOT / "evaluation" / "reports" / "safety"
    (out / f"{LABEL}.json").write_text(json.dumps({"label": LABEL, "dataset": DATASET, "cases_sha256": hashlib.sha256((DATA / "cases.jsonl").read_bytes()).hexdigest(), "metrics": m, "results": rows}, indent=1) + "\n",
                                       encoding="utf-8", newline="\n")
    print(json.dumps(m, indent=1))
