"""Real-model OBSERVATIONAL assessment of the numeric-measurement control (hardening V5). Opt-in: RUN_REAL_AI=1 and SAFETY_OBS_LABEL.

The local Ollama qwen2.5:1.5b model produces its own extraction proposals for the safety-v5 report texts (no scripted proposals). The scripted
safety-v5 acceptance result is reported separately; nothing here is tuned against. Labels are the frozen v5 labels; category chosen by the real model can
change the label's priority, so priority correctness here is indicative only. Writes evaluation/reports/safety/<label>.json.
"""
import dataclasses
import json
import os
import time
from pathlib import Path

import pytest
from app.ai.embeddings import get_embedder
from app.ai.llm import get_llm
from app.main import create_app
from fastapi.testclient import TestClient
from support import ingest_samples, login, make_tenant, onboard_meridian

ROOT = Path(__file__).resolve().parents[2]
LABEL = os.environ.get("SAFETY_OBS_LABEL")
pytestmark = [pytest.mark.real_ai, pytest.mark.skipif(not LABEL, reason="observational run; set SAFETY_OBS_LABEL")]
RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}


def same(a, b):
    return abs(a - b) <= max(1e-6, 0.005 * max(abs(a), abs(b)))


def test_observational(settings, app_db, owner_engine, ticketing, inventory_server, servicedesk_server, fleet_server, crm_server):
    import ollama_ctl
    ollama_ctl.start()
    llm = get_llm("ollama")
    assert llm.version() and llm.digest
    embedder = get_embedder("sentence_transformers")
    client = TestClient(create_app(dataclasses.replace(settings, llm_backend="ollama", embedding_backend="sentence_transformers"), app_db))
    apex = make_tenant(owner_engine, "obsapex", ticketing.url, inventory_server.url)
    ingest_samples(client, login(client, apex, "support_engineer"))
    mer = onboard_meridian(client, owner_engine, servicedesk_server, fleet_server, crm_server, "obsmer")
    eng = {"apex": login(client, apex, "support_engineer"), "meridian": login(client, mer, "support_engineer")}
    cases = [json.loads(x) for x in (ROOT / "evaluation" / "datasets" / os.environ.get("SAFETY_DATASET", "safety-v5") / "cases.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    rows, lat = [], []
    for c in cases:
        t0 = time.perf_counter()
        r = client.post("/api/v1/incidents/extract", headers=eng[c["tenant"]], json={"report_text": c["report_text"], **({"observations": c["observations"]} if c.get("observations") else {}), **({"numeric_locale": c["numeric_locale"]} if c.get("numeric_locale") else {})})
        lat.append(time.perf_counter() - t0)
        if r.status_code != 201:
            rows.append({"id": c["id"], "class": c["class"], "valid": c["valid"], "http": r.status_code, "error": r.json().get("error", {}).get("code")})
            continue
        inc = r.json()
        recs = inc["measurements"]
        verified = {m["name"]: m["value"] for m in recs if m["status"] == "verified"}
        exp = c["expected_verified"]
        wrong = {k: v for k, v in verified.items() if k not in exp or not same(v, exp[k])}
        d = client.post("/api/v1/tickets", headers=eng[c["tenant"]], json={"incident_id": inc["id"]})
        rows.append({"id": c["id"], "class": c["class"], "valid": c["valid"], "http": 201, "asset_matches_label": inc["asset_id"] == c["incident_asset"], "priority": inc["priority"],
                     "expected_priority": c["expected_priority"], "review_status": inc["review_status"], "review_urgency": inc["review_urgency"], "verified": verified,
                     "wrong_verified": wrong, "missing_verified": [k for k in exp if k not in verified],
                     "held": [(m["name"], m["status"], m["context_type"]) for m in recs if m["status"] != "verified"], "model_proposed": [m["model_proposed_value"] for m in recs],
                     "trace_ok": all((m["evidence_location"].get("field") == m["evidence_span"]) if m["source"] == "structured_record" else (c["report_text"][m["evidence_location"]["start"]:m["evidence_location"]["end"]] == m["evidence_span"]) for m in recs if m["status"] == "verified"),
                     "draft_before_review": d.status_code, "backend": inc["extraction_backend"]})
    ok = [x for x in rows if x["http"] == 201]
    inv, val = [x for x in ok if not x["valid"]], [x for x in ok if x["valid"]]
    m = {"cases": len(cases), "extracted": len(ok), "rejected_by_application": len(rows) - len(ok), "model": llm.model, "model_digest": llm.digest, "embedding": embedder.profile.model,
         "asset_matches_label": sum(x["asset_matches_label"] for x in ok), "invalid_cases": len(inv), "unsupported_values_verified": sum(len(x["wrong_verified"]) for x in ok),
         "invalid_cases_with_any_verified_value_wrong": sum(1 for x in inv if x["wrong_verified"]), "valid_cases": len(val),
         "valid_expected_measurement_verified": sum(1 for x in val if not x["missing_verified"] and not x["wrong_verified"]),
         "valid_false_rejections": sum(1 for x in val if x["missing_verified"] or x["wrong_verified"]),
         "priority_correct": sum(1 for x in ok if x["priority"] == x["expected_priority"]), "urgent_flagged": sum(1 for x in ok if x["review_urgency"] == "urgent"),
         "verified_with_exact_trace": sum(1 for x in ok if x["verified"] and x["trace_ok"]), "verified_total": sum(1 for x in ok if x["verified"]),
         "ticket_drafts_blocked_invalid": sum(1 for x in inv if x["draft_before_review"] >= 400), "latency_s_mean": round(sum(lat) / len(lat), 2), "latency_s_max": round(max(lat), 2)}
    out = ROOT / "evaluation" / "reports" / "safety"
    (out / f"{LABEL}.json").write_text(json.dumps({"label": LABEL, "kind": "real-model observational", "metrics": m, "results": rows}, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(m, indent=1))
