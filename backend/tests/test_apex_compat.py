"""Apex compatibility: the built-in (no-profile) path must behave exactly as it did before profiles existed.

Evidence: (1) golden outputs recorded from the Phase 4 commit 44b1083, (2) the built-in rule/safeguard modules are
byte-identical to that commit, (3) the Ollama prompts and schemas used for Apex hash to the value recorded in the
Phase 3 evidence manifests, and (4) an Apex tenant without a profile is still served by the built-in path."""
import hashlib
import json
from pathlib import Path

from app.ai import ollama_llm, rules
from support import REPORT, login

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = json.loads((Path(__file__).parent / "data" / "apex_builtin_golden.json").read_text(encoding="utf-8"))


def test_builtin_rules_reproduce_the_phase4_golden_outputs():
    assert GOLDEN["source_commit"] == "44b1083" and len(GOLDEN["cases"]) >= 30
    for case in GOLDEN["cases"]:
        parsed = rules.parse_report(case["text"])
        assert parsed == case["parsed"], case["text"]
        assert rules.decide_priority(parsed) == case["priority"], case["text"]


def test_builtin_rules_module_is_byte_identical_to_the_phase4_commit():
    current = (ROOT / "backend" / "app" / "ai" / "rules.py").read_bytes()
    normalized = current.replace(b"\r\n", b"\n")  # the repository normalizes line endings to LF
    assert hashlib.sha256(normalized).hexdigest() == GOLDEN["rules_py_sha256_at_source"]


def test_apex_ollama_prompts_and_schemas_match_the_phase3_evidence():
    digest = hashlib.sha256((ollama_llm.ANSWER_SYSTEM + ollama_llm.EXTRACT_SYSTEM + json.dumps(ollama_llm.ANSWER_SCHEMA)
                             + json.dumps(ollama_llm.FIELDS_SCHEMA)).encode()).hexdigest()
    recorded = {json.loads(p.read_text(encoding="utf-8"))["versions"]["prompts_sha256"]
                for p in (ROOT / "evaluation" / "reports" / "phase3").glob("*_ollama_sentence_transformers/results.json")}
    assert recorded == {digest} and ollama_llm.PROMPT_VERSION == "3"


def test_apex_without_a_profile_uses_the_builtin_path(client, apex_loaded):
    headers = login(client, apex_loaded, "support_engineer")
    assert client.get("/api/v1/tenant-profile", headers=headers).json()["using_defaults"] is True
    inc = client.post("/api/v1/incidents/extract", headers=headers, json={"report_text": REPORT}).json()
    expected = rules.parse_report(REPORT)
    assert (inc["asset_id"], inc["category"], inc["priority"]) == (
        expected["asset_id"], expected["category"], rules.decide_priority({**expected, "vibration_mm_s": None}))  # V8: free-text numbers never drive numeric priority
    assert inc["review_status"] == "pending_review" and inc["asset_verified"] is True
