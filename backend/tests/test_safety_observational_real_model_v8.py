"""Real-model OBSERVATIONAL assessment of the V8 trust policy. Opt-in: RUN_REAL_AI=1 and SAFETY_OBS_LABEL.

The local Ollama qwen2.5:1.5b model produces its own proposals for the safety-v8 reports (structured records and signed/forged simulator claims included); scripted human
verification actions are replayed. Separate from the frozen scripted acceptance; nothing is tuned against it. Writes evaluation/reports/safety/<label>.json."""
import dataclasses
import json
import os
import time
from pathlib import Path

import pytest
from app.ai.embeddings import get_embedder
from app.ai.llm import get_llm
from app.ai.measurement_trust import SIMULATION_KEY_ENV, sign_simulated_observation
from app.main import create_app
from fastapi.testclient import TestClient
from support import ingest_samples, login, make_tenant, onboard_meridian

ROOT = Path(__file__).resolve().parents[2]
LABEL = os.environ.get("SAFETY_OBS_LABEL")
pytestmark = [pytest.mark.real_ai, pytest.mark.skipif(not LABEL, reason="observational run; set SAFETY_OBS_LABEL")]
RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
KEY, OTHER_KEY = b"v8-observational-fixture-key", b"a-key-the-server-does-not-hold"


def _signature(sim, tid, other_tid, o, sid):
    if sim == "valid" or sim == "tampered":
        return sign_simulated_observation(KEY, tid, o, sid)
    if sim == "wrong_tenant":
        return sign_simulated_observation(KEY, other_tid, o, sid)
    if sim == "wrong_key":
        return sign_simulated_observation(OTHER_KEY, tid, o, sid)
    return "0" * 64 if sim == "bad_signature" else "f" * 64


def test_observational_v8(settings, app_db, owner_engine, ticketing, inventory_server, servicedesk_server, fleet_server, crm_server, monkeypatch):
    import ollama_ctl
    monkeypatch.setenv(SIMULATION_KEY_ENV, KEY.decode())
    ollama_ctl.start()
    llm = get_llm("ollama")
    assert llm.version() and llm.digest
    embedder = get_embedder("sentence_transformers")
    client = TestClient(create_app(dataclasses.replace(settings, llm_backend="ollama", embedding_backend="sentence_transformers"), app_db))
    apex = make_tenant(owner_engine, "obsapex8", ticketing.url, inventory_server.url)
    ingest_samples(client, login(client, apex, "support_engineer"))
    mer = onboard_meridian(client, owner_engine, servicedesk_server, fleet_server, crm_server, "obsmer8")
    tenants = {"apex": apex, "meridian": mer}
    tok = {t: {"engineer": login(client, e, "support_engineer"), "supervisor": login(client, e, "maintenance_supervisor")} for t, e in tenants.items()}
    other = {"apex": "meridian", "meridian": "apex"}
    cases = [json.loads(x) for x in (ROOT / "evaluation" / "datasets" / "safety-v8" / "cases.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    rows, lat = [], []
    for c in cases:
        obs = []
        for item in c["observations"]:
            o, sim = dict(item["o"]), item["sim"]
            if sim:
                tid, sid = str(tenants[c["tenant"]].id), "fixture-" + c["tenant"]
                sig = _signature(sim, tid, str(tenants[other[c["tenant"]]].id), o, sid)
                if sim == "tampered":
                    o = {**o, "value": o["value"] + 1.0}
                o = {**o, "simulation": {"source_id": sid, "signature": sig}}
            obs.append(o)
        body = {"report_text": c["report_text"], **({"observations": obs} if obs else {})}
        t0 = time.perf_counter()
        r = client.post("/api/v1/incidents/extract", headers=tok[c["tenant"]][c["creator"]], json=body)
        lat.append(time.perf_counter() - t0)
        if r.status_code != 201:
            rows.append({"id": c["id"], "class": c["class"], "http": r.status_code, "expected_422": c["expect_api_rejection"]})
            continue
        inc = r.json()
        res = []
        for a in c["actions"]:
            who = tok[other[c["tenant"]]]["supervisor"] if a["by"] == "other_tenant_supervisor" else tok[c["tenant"]].get(a["by"], tok[c["tenant"]]["engineer"])
            resp = client.post(f"/api/v1/incidents/{inc['id']}/measurements/{a['name']}/verify", headers=who,
                               json={"decision": a["decision"], "comment": a["comment"], "expected_trust_status": a["status"]})
            res.append({"expect": a["expect_http"], "got": resp.status_code})
        final = client.get(f"/api/v1/incidents/{inc['id']}", headers=tok[c["tenant"]]["engineer"]).json()
        d = client.post("/api/v1/tickets", headers=tok[c["tenant"]]["engineer"], json={"incident_id": inc["id"]})
        rows.append({"id": c["id"], "class": c["class"], "http": 201, "asset_matches_label": final["asset_id"] == c["incident_asset"], "priority": final["priority"],
                     "expected_priority_final": c["expected_priority_final"], "review_urgency": final["review_urgency"], "expected_urgent": c["expected_urgent"],
                     "eligible_classes": [m["evidence_class"] for m in final["measurements"] if m["eligible_for_numeric_priority"]],
                     "free_text_or_llm_eligible": any(m["evidence_class"] == "A" and m["eligible_for_numeric_priority"] for m in final["measurements"]), "actions": res,
                     "unauthorized_submission": final["review_status"] == "needs_review" and d.status_code == 201, "review_status": final["review_status"]})
    ok = [x for x in rows if x["http"] == 201]
    acts = [a for x in ok for a in x["actions"]]
    m = {"cases": len(cases), "extracted": len(ok), "rejected_by_application": len(rows) - len(ok), "rejections_that_were_expected_422": sum(1 for x in rows if x["http"] != 201 and x["expected_422"]),
         "model": llm.model, "model_digest": llm.digest, "embedding": embedder.profile.model, "asset_matches_label": sum(x["asset_matches_label"] for x in ok),
         "free_text_or_llm_measurements_eligible": sum(x["free_text_or_llm_eligible"] for x in ok), "verification_actions": len(acts),
         "actions_with_expected_outcome": sum(1 for a in acts if a["got"] == a["expect"]), "unauthorized_verification_transitions": sum(1 for a in acts if a["expect"] != 200 and a["got"] == 200),
         "priority_correct_vs_label": sum(1 for x in ok if x["priority"] == x["expected_priority_final"]), "priority_inflated_vs_label": sum(1 for x in ok if RANK[x["priority"]] < RANK[x["expected_priority_final"]]),
         "urgent_flagged": sum(1 for x in ok if x["review_urgency"] == "urgent"), "urgent_expected_and_flagged": sum(1 for x in ok if x["expected_urgent"] and x["review_urgency"] == "urgent"),
         "unauthorized_submissions": sum(x["unauthorized_submission"] for x in ok), "latency_s_mean": round(sum(lat) / len(lat), 2), "latency_s_max": round(max(lat), 2)}
    out = ROOT / "evaluation" / "reports" / "safety" / f"{LABEL}.json"
    out.write_text(json.dumps({"label": LABEL, "kind": "real-model observational (V8)", "metrics": m, "results": rows}, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(m, indent=1))
