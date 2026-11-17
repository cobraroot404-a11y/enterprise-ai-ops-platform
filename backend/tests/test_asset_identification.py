"""The asset id is identified by the application, not trusted from the model (development evidence: evaluation/reports/dev-noasset-v1). No model or Ollama is needed here."""
import json
from pathlib import Path

import pytest
from app.ai.ollama_llm import OllamaLLM, asset_candidates, choose_asset

ROOT = Path(__file__).resolve().parents[2]
CASES = [json.loads(line) for line in (ROOT / "evaluation" / "datasets" / "dev-noasset-v1" / "cases.jsonl").read_text(encoding="utf-8").splitlines()]


def test_candidates_are_the_ids_literally_written_in_order_without_duplicates():
    assert asset_candidates("Pump P-101 and pump p-102 and P-101 again, plus MX-6.") == ["P-101", "P-102", "MX-6"]
    assert asset_candidates("The big pump near the dock is shaking; part number 12345, rev 3-4.") == []


@pytest.mark.parametrize("report,model,expected,status", [
    ("The big pump is shaking.", "XJ-204", None, "invented"),            # no id written: an invented id is dropped
    ("The big pump is shaking.", None, None, "null"),
    ("Pump P-101 vibrates.", "P-101", "P-101", "agrees"),
    ("Pump P-101 vibrates.", "Q-999", "P-101", "invented"),               # the written id wins over an invented one
    ("Pump P-101 vibrates.", "P-102", "P-101", "invented"),
    ("Charger CH-5 hot, near pump P-77.", "CH-5", "CH-5", "chose_among_candidates"),
    ("Charger CH-5 hot, near pump P-77.", "P-77", "P-77", "chose_among_candidates"),
    ("Charger CH-5 hot, near pump P-77.", "ZZ-1", "CH-5", "invented"),    # several written ids and an invented pick: the first written
    ("Tank T-02 leaks; T-03 is fine.", None, "T-02", "null"),
    ("pump p-101 vibrates", "P-101", "P-101", "agrees"),                  # case-insensitive, upper-cased
])
def test_choose_asset_rules(report, model, expected, status):
    assert choose_asset(report, model) == (expected, status)


def test_every_development_case_gets_the_right_asset_whatever_the_model_says():
    for case in CASES:
        for model_value in (None, "INVENTED-1", "P-101", case["expected_asset"]):
            asset, _ = choose_asset(case["text"], model_value)
            if case["expected_asset"] is None:
                assert asset is None, (case["id"], model_value)  # nothing written, nothing returned
            elif len(asset_candidates(case["text"])) == 1:
                assert asset == case["expected_asset"], (case["id"], model_value)
            else:  # several written ids: only a model pick that is among them can change the first-written default
                assert asset in asset_candidates(case["text"])


def test_extract_fields_records_the_models_value_and_never_fails_on_an_invented_asset(monkeypatch):
    llm = OllamaLLM("http://127.0.0.1:9", "m")

    def fake_chat(self, kind, system, user, schema):
        self.calls.append({"kind": kind, "valid": None})
        return json.dumps({"asset_id": "XJ-204", "category": "noise", "symptoms": ["grinding"], "vibration_mm_s": None, "smoke_or_fire": False})

    monkeypatch.setattr(OllamaLLM, "_chat", fake_chat)
    fields = llm.extract_fields("The big pump near the dock is making a grinding noise.")
    assert fields["asset_id"] is None and fields["category"] == "noise"  # category from the model is kept; no fallback, no exception
    assert llm.calls[-1]["asset_model_output"] == "invented" and llm.calls[-1]["valid"] is True
    fields = llm.extract_fields("Pump P-101 is making a grinding noise.")
    assert fields["asset_id"] == "P-101" and llm.calls[-1]["asset_model_output"] == "invented"
