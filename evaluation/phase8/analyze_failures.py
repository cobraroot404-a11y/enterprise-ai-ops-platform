"""Root-cause listing of baseline (or candidate) failures on the DEV split.

    python evaluation/phase8/analyze_failures.py <run_dir> [--md out.md]

Reads raw outputs plus frozen labels; classifies each non-correct item. Dev split only (refuses runs whose manifest split is not dev).
"""
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evaluation.phase8.score_baseline import has_fact, norm  # noqa: E402

DS = ROOT / "evaluation" / "datasets" / "eval-v2"


def load(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def classify_answerable(q, r, ptext):
    """Return (class, detail) for an answerable query whose answer was not grounded-correct."""
    rel = {(x["file"], x["unit"]) for x in q["relevant"]}
    cites = r["citations"] or []
    units = [(c["filename"], c["page_number"] if c.get("page_number") is not None else c.get("record_id")) for c in cites]
    if not r["grounded"]:
        probs = "; ".join(r["problems"])
        if "number(s) not found" in probs:
            return "withheld: numeric mismatch", probs
        if "quote not found" in probs:
            return "withheld: incorrect quotation", probs
        if r["insufficient_evidence"]:
            return "refused", ""
        return "withheld: other", probs
    wrong = [u for u in units if u not in rel]
    if wrong:
        sib = any(u in {(h["file"], h["unit"]) for h in q["hard_negatives"]} for u in wrong)
        return ("wrong passage: sibling/hard-negative page" if sib else "wrong passage: unlabelled or unrelated"), str(wrong)
    if not all(has_fact(r["answer"], f) for f in q["required_facts"]):
        missing = [f for f in q["required_facts"] if not has_fact(r["answer"], f)]
        return "incomplete evidence: required fact missing from answer", f"missing {missing}; relevant needs {len(rel)} passages, cited {len(set(units))}"
    if any(has_fact(r["answer"], f) for f in q["forbidden_facts"]):
        return "forbidden (conflicting/outdated) value used", ""
    return "other", ""


def main():
    run = Path(sys.argv[1]).resolve()
    man = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    if man["dataset"]["split"] != "dev" and "--post-hoc-observation" not in sys.argv:
        sys.exit("dev split only (pass --post-hoc-observation for the approved observational analysis of a completed held-out run)")
    qs = {q["id"]: q for q in load(DS / "queries.jsonl")}
    cs = {c["id"]: c for c in load(DS / "incidents.jsonl")}
    ptext = {(p["tenant"], p["file"], p["unit"]): norm(p["text"]) for p in load(DS / "passages.jsonl") if p["current"]}
    qa = load(run / "qa_rep1.jsonl")
    out = {"answerable": collections.Counter(), "answerable_items": [], "unanswerable_wrong": [], "citation_issues": [], "extraction": []}
    for r in qa:
        q = qs[r["id"]]
        if q.get("answer_optional"):
            continue
        if q["answerable"]:
            if r["grounded"] and all(c for c in [1]) and not classify_answerable(q, r, ptext)[0] == "other" or not r["grounded"]:
                cls, det = classify_answerable(q, r, ptext)
                out["answerable"][cls] += 1
                out["answerable_items"].append({"id": r["id"], "category": q["category"], "class": cls, "detail": det[:200], "query": q["query"][:110]})
        elif q["expected_refusal"] and r["grounded"]:
            subtype = [t for t in q["tags"] if t in ("gap_in_manual", "nonexistent_id", "other_tenant_only", "undocumented", "outside_domain", "approval_bypass", "direct_injection")]
            out["unanswerable_wrong"].append({"id": r["id"], "subtype": subtype, "query": q["query"][:100], "answer": (r["answer"] or "")[:160],
                                              "cited": [c["filename"] for c in r["citations"]]})
    for r in qa:
        q = qs[r["id"]]
        if not q["answerable"] or q.get("answer_optional"):
            continue
        rel = {(x["file"], x["unit"]) for x in q["relevant"]}
        for c in r["citations"] or []:
            u = (c["filename"], c["page_number"] if c.get("page_number") is not None else c.get("record_id"))
            if u not in rel:
                out["citation_issues"].append({"id": r["id"], "category": q["category"], "cited": list(u), "relevant": sorted(map(list, rel))})
    ex = load(run / "extraction_rep1.jsonl")
    for r in ex:
        c = cs[r["id"]]
        raw = r["raw"][0]["fields"] if r["raw"] and r["raw"][0].get("valid") else {}
        out["extraction"].append({"id": r["id"], "tenant": c["tenant"], "tags": c["tags"], "label": [c["category"], c["expected_priority"], c.get("vibration_mm_s"), c.get("brake_psi"), c.get("coolant_c")],
                                  "got": [r.get("category"), r.get("priority"), r.get("review_status"), r.get("n_citations")], "raw_vib": raw.get("vibration_mm_s"),
                                  "notes": (r.get("notes") or [])[:2]})
    print(json.dumps({"answerable_failure_classes": dict(out["answerable"]), "unanswerable_wrongly_answered": len(out["unanswerable_wrong"]),
                      "non_labelled_citations": len(out["citation_issues"])}, indent=1))
    (run / "failure_analysis.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(re.sub(r"\s+", " ", "analysis written"))


if __name__ == "__main__":
    main()
