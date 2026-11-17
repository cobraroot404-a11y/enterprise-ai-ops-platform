"""Score an experiment run directory and compare it with the baseline (paired, same dev queries).

    python evaluation/phase8/score_experiment.py <exp_dir> [--baseline <baseline_dir>]

Writes <exp_dir>/scores_exp.json and prints a compact comparison. All formulas come from score_baseline.py / metrics.py. Repetition 1 is the headline;
other repetitions (if present) only give run-to-run spread. The baseline is scored read-only from its raw files with the same (current) scorer so that
new additive metrics (numeric audit) are available for it too.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evaluation" / "phase8"))
import score_baseline as sc  # noqa: E402

BASE = ROOT / "evaluation" / "reports" / "phase8" / "baseline-20261112T035539Z"
DS = sc.DS


def score_dir(run: Path) -> dict:
    run = Path(run)
    split = "dev"
    if (run / "manifest.json").exists():
        split = json.loads((run / "manifest.json").read_text(encoding="utf-8")).get("dataset", {}).get("split", "dev")
    queries = [q for q in sc.load(DS / "queries.jsonl") if q["split"] == split]
    cases = [c for c in sc.load(DS / "incidents.jsonl") if c["split"] == split]
    passages = sc.load(DS / "passages.jsonl")
    out = {"run": run.name, "scopes": {}}
    reps = sorted(int(re.search(r"rep(\d+)", p.name).group(1)) for p in run.glob("qa_rep*.jsonl"))
    ex_reps = sorted(int(re.search(r"rep(\d+)", p.name).group(1)) for p in run.glob("extraction_rep*.jsonl"))
    ret = sc.load(run / "retrieval.jsonl") if (run / "retrieval.jsonl").exists() else None
    for scope in (None, "apex", "meridian"):
        name = scope or "combined"
        s = {}
        if ret:
            s["retrieval"] = sc.score_retrieval(ret, None, queries, scope)
        if reps:
            s["qa"] = {f"rep{r}": sc.score_qa_rep(sc.load(run / f"qa_rep{r}.jsonl"), queries, passages, scope) for r in reps}
        if ex_reps:
            s["extraction"] = {f"rep{r}": sc.score_extraction_rep(sc.load(run / f"extraction_rep{r}.jsonl"), cases, scope) for r in ex_reps}
        out["scopes"][name] = s
    return out


def paired(a: dict, b: dict, key: str) -> dict:
    """Per-query paired outcome changes of a boolean flag between baseline a and candidate b."""
    better = worse = same = 0
    for qid, fa in a.items():
        fb = b.get(qid)
        if fb is None or key not in fa:
            continue
        better += (not fa[key]) and fb[key]
        worse += fa[key] and not fb[key]
        same += fa[key] == fb[key]
    return {"improved": better, "regressed": worse, "unchanged": same}


def headline(sc_: dict) -> dict:
    c = sc_["scopes"]["combined"]
    h = {}
    if "retrieval" in c and c["retrieval"].get("hybrid"):
        r = c["retrieval"]["hybrid"]
        h.update({"recall@1": r["recall@1"], "recall@5": r["recall@5"], "mrr": r["mrr"], "ndcg@5": r["ndcg@5"], "leak": c["retrieval"]["cross_tenant_leakage"]["foreign"]})
    if "qa" in c:
        q = c["qa"]["rep1"]
        for k in ("grounded_answer_coverage", "citation_correctness_answerable", "claim_support", "correct_abstention", "false_refusals", "withheld_unverified",
                  "unsupported_answer_rate", "answered"):
            h[k] = q[k]["value"]
            h[k + "_n"] = f"{q[k]['numerator']}/{q[k]['denominator']}"
        h["latency_p50"], h["latency_p95"] = q["latency_s"]["all"]["p50"], q["latency_s"]["all"]["p95"]
    if "extraction" in c:
        e = c["extraction"]["rep1"]
        for k in ("raw_schema_validity", "priority_accuracy", "final_category_accuracy", "review_rate", "evidence_completeness", "unsafe_automatic_acceptance"):
            h[k] = e[k]["value"]
            h[k + "_n"] = f"{e[k]['numerator']}/{e[k]['denominator']}"
        h["unsupported_numeric_accepted"] = e["unsupported_numeric_accepted_as_verified"]["count"]
        h["numeric_proposed_unsupported"] = f"{e['numeric_values_proposed_unsupported']['numerator']}/{e['numeric_values_proposed_unsupported']['denominator']}"
        h["review_missed_unsafe"] = e["review_missed_unsafe"]
        h["extract_latency_p95"] = e["latency_s"]["p95"]
    return h


def main():
    exp = Path(sys.argv[1]).resolve()
    base_dir = Path(sys.argv[sys.argv.index("--baseline") + 1]) if "--baseline" in sys.argv else BASE
    cand = score_dir(exp)
    (exp / "scores_exp.json").write_text(json.dumps(cand, indent=1, default=str), encoding="utf-8")
    base = score_dir(base_dir)
    hb, hc = headline(base), headline(cand)
    print(f"{'metric':36s} {'baseline':>12s} {'candidate':>12s}")
    for k in hc:
        if k.endswith("_n"):
            continue
        vb, vc = hb.get(k), hc.get(k)
        def f(v):
            return f"{v:.4f}" if isinstance(v, float) else str(v)
        print(f"{k:36s} {f(vb):>12s} {f(vc):>12s}   {hc.get(k + '_n', '')}")
    cb, cc = base["scopes"]["combined"], cand["scopes"]["combined"]
    if "qa" in cc and "qa" in cb:
        pb, pc = cb["qa"]["rep1"]["per_query"], cc["qa"]["rep1"]["per_query"]
        print("paired grounded-correct:", paired(pb, pc, "gc"), "| paired correct-refusal:", paired(pb, pc, "cr"))
    (exp / "comparison.json").write_text(json.dumps({"baseline": hb, "candidate": hc}, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
