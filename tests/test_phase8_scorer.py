"""Hand-built raw outputs scored by the Phase 8 scorer; every expected value below is computed by hand."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evaluation.phase8 import score_baseline as S  # noqa: E402

PASSAGES = [
    {"tenant": "apex", "file": "apex_a.pdf", "unit": 1, "current": True, "text": "Replace the seal at 5 drops per minute."},
    {"tenant": "apex", "file": "apex_a.pdf", "unit": 2, "current": True, "text": "Check the strainer every 3 months."},
]


def q(id_, answerable=True, refusal=False, facts=(), forbidden=(), rel=((("apex_a.pdf", 1)),), **kw):
    return {"id": id_, "tenant": "apex", "answerable": answerable, "expected_refusal": refusal, "required_facts": list(facts), "forbidden_facts": list(forbidden),
            "relevant": [{"file": f, "unit": u, "grade": 2} for f, u in rel] if answerable else [], "category": "keyword", "safety_tags": [], "query": "question", **kw}


def row(id_, answer=None, grounded=False, insufficient=False, cites=(), wall=1.0):
    return {"id": id_, "wall_s": wall, "answer": answer, "grounded": grounded, "insufficient_evidence": insufficient, "citations": list(cites), "llm_calls": []}


def cite(file, unit, quote):
    return {"filename": file, "page_number": unit, "record_id": None, "quote": quote}


def test_qa_scoring_by_hand():
    queries = [q("a", facts=["5"]), q("b", facts=["3"], rel=(("apex_a.pdf", 2),)), q("c", answerable=False, refusal=True), q("d", facts=["5"]), q("e", answerable=False, refusal=True)]
    rows = [
        row("a", "Replace at 5 drops per minute [1].", True, cites=[cite("apex_a.pdf", 1, "Replace the seal at 5 drops per minute.")]),       # fully correct
        row("b", "Check every 3 months [1].", True, cites=[cite("apex_a.pdf", 1, "Replace the seal at 5 drops per minute.")]),              # cites the wrong passage
        row("c", None, False, insufficient=True),                                                                                         # correct refusal
        row("d", None, False, insufficient=True),                                                                                         # false refusal
        row("e", "It is 7 days [1].", True, cites=[cite("apex_a.pdf", 2, "Check the strainer every 3 months.")]),                         # answered an unanswerable query
    ]
    s = S.score_qa_rep(rows, queries, PASSAGES, None)
    assert (s["answerable"], s["grounded_answer_coverage"]["numerator"]) == (3, 1)               # only "a" is grounded and correct
    assert s["answered"]["numerator"] == 2 and s["false_refusals"]["numerator"] == 1
    assert (s["citation_correctness_answerable"]["numerator"], s["citation_correctness_answerable"]["denominator"]) == (1, 2)
    assert (s["correct_abstention"]["numerator"], s["correct_abstention"]["denominator"]) == (1, 2)
    assert s["claim_support"]["denominator"] == 2 and s["claim_support"]["numerator"] == 1    # "5" is in its cited quote; "3" (query b) is not in the wrong passage it cited
    assert s["grounded_answer_coverage"]["classification"] == "OBSERVED TARGET NOT MET"
    assert s["unsupported_answer_rate"]["numerator"] == 2 and s["unsupported_answer_rate"]["denominator"] == 3   # b (wrong citation) and e (unanswerable answered) of a, b, e


def test_zero_denominator_is_not_a_pass():
    s = S.score_qa_rep([row("a", "x", True)], [q("a", answerable=False, refusal=False, **{"answer_optional": True})], PASSAGES, None)
    assert s["correct_abstention"]["classification"] == "NOT EVALUABLE" and s["correct_abstention"]["value"] is None


def test_fact_matching_is_boundary_aware():
    assert S.has_fact("interval is 2250 hours", "2250") and not S.has_fact("interval is 12250 hours", "2250")
    assert S.has_fact("limit 1,500 hours", "1500") and not S.has_fact("5.5 mm/s", "5")


def test_extraction_scoring_by_hand():
    cases = [
        {"id": "x1", "tenant": "apex", "text": "P-101 leaks oil", "asset_id": "P-101", "category": "leak", "vibration_mm_s": None, "brake_psi": None, "coolant_c": None,
         "expected_outcome": "incident", "review_expectation": "may_proceed", "expected_priority": "P2", "soft_review": False, "tags": []},
        {"id": "x2", "tenant": "apex", "text": "P-999 vibrates", "asset_id": "P-999", "category": "mechanical_vibration", "vibration_mm_s": None, "brake_psi": None, "coolant_c": None,
         "expected_outcome": "incident", "review_expectation": "must_review", "expected_priority": "P3", "soft_review": False, "tags": ["unregistered_asset"]},
        {"id": "x3", "tenant": "apex", "text": "noise somewhere", "asset_id": None, "category": "other", "vibration_mm_s": None, "brake_psi": None, "coolant_c": None,
         "expected_outcome": "reject_asset_not_identified", "review_expectation": "n/a", "expected_priority": "P4", "soft_review": False, "tags": ["no_asset"]},
    ]
    rows = [
        {"id": "x1", "status": 201, "wall_s": 1, "raw": [{"valid": True, "fields": {"asset_id": "P-101", "category": "leak", "vibration_mm_s": 99.0}}], "asset_id": "P-101", "category": "leak",
         "priority": "P2", "review_status": "pending_review", "n_citations": 1},
        {"id": "x2", "status": 201, "wall_s": 1, "raw": [{"valid": False, "error": "bad"}], "asset_id": "P-999", "category": "mechanical_vibration", "priority": "P3",
         "review_status": "pending_review", "n_citations": 0},                         # unregistered asset NOT blocked: unsafe automatic acceptance
        {"id": "x3", "status": 422, "wall_s": 1, "raw": [], "error_code": "asset_not_identified"},
    ]
    e = S.score_extraction_rep(rows, cases, None)
    assert (e["raw_schema_validity"]["numerator"], e["raw_schema_validity"]["denominator"]) == (1, 2)
    assert e["raw_schema_validity"]["classification"] == "OBSERVED TARGET NOT MET"
    assert (e["hallucinated_numeric_signal_rate"]["numerator"], e["hallucinated_numeric_signal_rate"]["denominator"]) == (1, 1)
    assert (e["unsafe_automatic_acceptance"]["numerator"], e["unsafe_automatic_acceptance"]["denominator"]) == (1, 1)
    assert e["review_missed_unsafe"] == 1 and e["invalid_asset_rejection"]["numerator"] == 1
    assert e["priority_accuracy"]["numerator"] == 2 and e["evidence_completeness"]["numerator"] == 1
