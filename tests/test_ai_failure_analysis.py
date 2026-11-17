"""The AI failure-taxonomy document quotes only figures that the stored analysis outputs contain, keeps held-out figures unchanged, and states D1 was rejected."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs" / "evaluation" / "ai-failure-taxonomy-and-d1.md").read_text(encoding="utf-8")
TAX = ROOT / "evaluation" / "reports" / "phase8" / "taxonomy"
CAND, D1 = (json.loads((TAX / f"{n}-rep1.json").read_text(encoding="utf-8")) for n in ("CAND1", "D1"))


def test_the_candidate_table_matches_the_stored_taxonomy():
    c = CAND["classes"]
    assert c["ok: grounded, labelled citations, facts present"] == 58 and CAND["answerable"] == 87 and CAND["dev_queries"] == 118
    for needle in ("| 58 |", "| 10 |", "| 7 |", "| 5 |"):
        assert needle in DOC
    assert c["7b withheld by the verifier: quotation not verbatim"] == 10 and c["7c withheld by the verifier: number not in the cited text"] == 7
    assert CAND["secondary_flags"]["11 tenant-scoping or provenance error: citations from another tenant's files (must be 0)"] == 0
    assert sum(v for k, v in c.items() if not k.startswith("unanswerable") and not k.startswith("ok")) == 29


def test_d1_figures_match_its_stored_scores_and_it_is_marked_rejected_and_off_by_default():
    d = D1["classes"]
    assert d["ok: grounded, labelled citations, facts present"] == 56 and "8 unsupported or incomplete: a required fact is absent from the answer" not in d
    scores = json.loads((ROOT / "evaluation" / "reports" / "phase8" / "exp-D1-20261114T050707Z" / "scores_exp.json").read_text(encoding="utf-8"))
    flat = json.dumps(scores)
    for needle in ("0.6437", "0.8642", "0.2794"):
        assert needle in flat and ({"0.6437": "64.4%", "0.8642": "86.4%", "0.2794": "27.9%"}[needle]) in DOC
    assert "REJECTED" in DOC and "the flag stays off" in DOC
    import sys
    from importlib import import_module
    sys.path.insert(0, str(ROOT / "backend"))
    assert import_module("app.ai.tuning").Tuning().decompose_answers is False


def test_the_heldout_figures_are_restated_unchanged_and_the_target_is_not_claimed_met():
    for needle in ("89.8%", "59.3%", "90%", "95%"):
        assert needle in DOC
    assert "not met" in DOC.lower() and "No acceptance threshold changed" in DOC.replace("no acceptance threshold changed", "No acceptance threshold changed") or "no acceptance threshold changed" in DOC
    assert re.search(r"held-out and challenge splits were not used", DOC)
