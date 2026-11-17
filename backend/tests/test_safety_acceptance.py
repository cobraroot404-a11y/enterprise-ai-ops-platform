"""Frozen numeric-measurement safety acceptance run (dataset chosen by SAFETY_DATASET, default safety-v1; see evaluation/datasets/<name>/FROZEN.md).

Not part of the default suite: it runs only when SAFETY_ACCEPT_LABEL is set (e.g. `pre-fix`, `post-fix`), writes the per-case results and the
metrics to evaluation/reports/safety/<label>.json, and (a label starting with `post`) asserts zero unsafe acceptances. The frozen cases are read-only.
The scripted model mirrors the production clients: it proposes the case's values and, like the Ollama client and validate_fields, lets the first
regex match in the report override its value (so unattributed regex readings are exercised too).
"""
import hashlib
import json
import os
from pathlib import Path

import pytest
from app.ai import rules
from app.ai.llm import LLMAnswer
from app.profile import engine
from support import login, onboard_meridian

ROOT = Path(__file__).resolve().parents[2]
DATASET = os.environ.get("SAFETY_DATASET", "safety-v1")
DATA = ROOT / "evaluation" / "datasets" / DATASET
LABEL = os.environ.get("SAFETY_ACCEPT_LABEL")
pytestmark = pytest.mark.skipif(not LABEL, reason="frozen safety acceptance run; set SAFETY_ACCEPT_LABEL")
RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
REVIEW_REASONS = ("measurement could not be verified", "model output failed validation")


def _cases():
    return [json.loads(x) for x in (DATA / "cases.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]


class ScriptedLLM:
    name, model = "scripted-safety", "frozen-cases"

    def __init__(self, cases):
        self.by_text = {c["report_text"]: c for c in cases}

    def extract_fields(self, report_text, profile=None):
        c = self.by_text[report_text]
        prop = c["model_proposal"]
        if c["tenant"] == "apex":
            fields = {"asset_id": prop["asset_id"], "category": prop["category"], "symptoms": ["reported by operator"],
                      "vibration_mm_s": (prop["measurements"] or {}).get("vibration_mm_s"), "smoke_or_fire": c["smoke_or_fire"]}
            hit = rules.VIBRATION.search(report_text)
            if hit:
                fields["vibration_mm_s"] = float(hit.group(1))  # the production client's regex override
            return fields
        signals = dict(prop["measurements"])
        for name, value in engine.parse_report(profile, report_text)["signals"].items():
            if value is not None:
                signals[name] = value  # validate_fields' regex override
        return {"asset_id": prop["asset_id"], "category": prop["category"], "symptoms": ["reported by driver"], "signals": signals,
                "safety_flag": c["smoke_or_fire"]}

    def answer(self, question, passages):
        return LLMAnswer(text="", cited=[])


def test_frozen_safety_acceptance(client, apex_loaded, owner_engine, servicedesk_server, fleet_server, crm_server, monkeypatch):
    from app.api.v1 import domain_routes
    cases = _cases()
    assert hashlib.sha256((DATA / "cases.jsonl").read_bytes()).hexdigest() in (DATA / "MANIFEST.sha256").read_text()  # frozen set unmodified
    mer = onboard_meridian(client, owner_engine, servicedesk_server, fleet_server, crm_server)
    llm = ScriptedLLM(cases)
    monkeypatch.setattr(domain_routes, "get_llm", lambda _name: llm)
    heads = {"apex": login(client, apex_loaded, "support_engineer"), "meridian": login(client, mer, "support_engineer")}
    results = []
    for c in cases:
        r = client.post("/api/v1/incidents/extract", headers=heads[c["tenant"]], json={"report_text": c["report_text"]})
        assert r.status_code == 201, (c["id"], r.text)
        inc = r.json()
        recs = inc.get("measurements") or []
        holds = [m for m in recs if m["status"] in ("unsupported", "conflict", "quarantined")]
        verified = {m["name"]: m["value"] for m in recs if m["status"] == "verified"}
        notes = " ".join(inc["notes"])
        review_reason = any(x in notes for x in REVIEW_REASONS)
        wrong_verified = {k: v for k, v in verified.items() if c["expected_verified"].get(k) != v}
        draft = client.post("/api/v1/tickets", headers=heads[c["tenant"]], json={"incident_id": inc["id"]})
        results.append({"id": c["id"], "tenant": c["tenant"], "class": c["class"], "valid": c["valid"], "expected_priority": c["expected_priority"],
                        "priority": inc["priority"], "review_status": inc["review_status"], "measurement_hold_records": len(holds),
                        "review_reason_recorded": review_reason, "verified_measurements": verified, "wrong_verified": wrong_verified,
                        "priority_inflated": RANK[inc["priority"]] < RANK[c["expected_priority"]],
                        "priority_deflated": RANK[inc["priority"]] > RANK[c["expected_priority"]],
                        "draft_ticket_status_before_review": draft.status_code,
                        "unsupported_proposals": c["unsupported_proposals"], "must_review": c["must_review_for_measurement"]})
    invalid = [x for x in results if not x["valid"]]
    valid = [x for x in results if x["valid"]]
    metrics = {
        "cases": len(results), "valid": len(valid), "invalid": len(invalid),
        "false_acceptance_cases": sum(1 for x in invalid if x["wrong_verified"] or x["priority_inflated"] or not x["review_reason_recorded"]),
        "unsupported_values_accepted_as_verified": sum(len(x["wrong_verified"]) for x in results),
        "unsupported_proposals_total": sum(len(x["unsupported_proposals"]) for x in results),
        "unsupported_priority_inflation_cases": sum(1 for x in invalid if x["priority_inflated"]),
        "must_review_cases": sum(x["must_review"] for x in results),
        "must_review_held_with_recorded_reason": sum(1 for x in results if x["must_review"] and x["review_reason_recorded"]),
        "false_rejection_cases": sum(1 for x in valid if x["measurement_hold_records"] or x["review_reason_recorded"] or x["priority"] != x["expected_priority"]),
        "valid_cases_expecting_a_measurement": sum(1 for c in cases if c["valid"] and c["expected_verified"]),
        "valid_cases_with_verified_measurement": sum(1 for x in valid if x["verified_measurements"]),
        "priority_correct": sum(1 for x in results if x["priority"] == x["expected_priority"]),
        "priority_correct_valid": sum(1 for x in valid if x["priority"] == x["expected_priority"]),
        "priority_correct_invalid": sum(1 for x in invalid if x["priority"] == x["expected_priority"]),
        "priority_inflated_cases": sum(x["priority_inflated"] for x in results), "priority_deflated_cases": sum(x["priority_deflated"] for x in results),
        "genuine_p1_kept": sum(1 for x in valid if x["expected_priority"] == "P1" and x["priority"] == "P1"),
        "genuine_p1_total": sum(1 for x in valid if x["expected_priority"] == "P1"),
        "ticket_draft_blocked_before_review": sum(1 for x in invalid if x["draft_ticket_status_before_review"] >= 400),
        "by_class": {},
    }
    for x in results:
        b = metrics["by_class"].setdefault(x["class"], {"n": 0, "review_reason": 0, "priority_correct": 0})
        b["n"] += 1
        b["review_reason"] += x["review_reason_recorded"]
        b["priority_correct"] += x["priority"] == x["expected_priority"]
    out = ROOT / "evaluation" / "reports" / "safety"
    out.mkdir(parents=True, exist_ok=True)
    payload = {"label": LABEL, "dataset": DATASET, "cases_sha256": hashlib.sha256((DATA / "cases.jsonl").read_bytes()).hexdigest(),
               "metrics": metrics, "results": results}
    (out / f"{LABEL}.json").write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(metrics, indent=1))
    if LABEL.startswith("post"):
        assert metrics["false_acceptance_cases"] == 0 and metrics["unsupported_values_accepted_as_verified"] == 0
        assert metrics["false_rejection_cases"] == 0 and metrics["genuine_p1_kept"] == metrics["genuine_p1_total"]
