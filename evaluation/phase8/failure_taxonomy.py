"""Failure taxonomy over the DEVELOPMENT split (the eleven categories of the AI-quality directive), from a recorded run. Offline: it reads raw outputs and frozen dev labels only.

    python evaluation/phase8/failure_taxonomy.py <run_dir> [--rep 1] [--out docs/evaluation/ai-failure-taxonomy.md]

Every dev query gets ONE primary class (first matching, in the order below) so the counts add up; secondary flags are counted separately. Refuses runs whose queries are not dev. A class
describes where the pipeline lost the item, not why a model behaved so; counts are on 118 dev queries (87 answerable, 31 not) so every figure has a wide interval.
Classes for ANSWERABLE queries (a query is 'ok' when grounded, cited only labelled evidence, and every required fact is in the answer):
  1 retrieval: no relevant document in the top 5          2 retrieval: relevant document present, labelled page/record not in the top 5
  3 ranking: relevant page in the top 5 but below a hard negative
  10 multi-hop: category multi_hop and not ok (reported as a secondary flag, since it overlaps the others)
  8 unsupported: answered (grounded) but a required fact is absent or a forbidden fact is present
  5 citation association: grounded but cites an unlabelled / sibling page            6 missing citations: answered with no citation
  7 unnecessary abstention: refused or withheld although evidence was retrieved (withheld for quote or number mismatch counted separately as 'withheld by verifier')
  9 structured-output: the model call itself was invalid
For UNANSWERABLE queries: ok = refused; 'wrongly answered' = answered although unanswerable.
Class 4 (unsupported claims) and 11 (tenant-scoping or provenance error) are checked as flags: 4 = answer states a number not present in cited text; 11 = a citation whose document belongs to another tenant (must be 0)."""
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


def main() -> int:
    args = sys.argv[1:]
    run = Path(args[0])
    rep = args[args.index("--rep") + 1] if "--rep" in args else "1"
    queries = {q["id"]: q for q in load(DS / "queries.jsonl")}
    qa = load(run / f"qa_rep{rep}.jsonl")
    retrieval_file = run / "retrieval_default.jsonl"
    if not retrieval_file.exists():  # QA-only runs reuse the retrieval of the run they were derived from (same retrieval configuration): pass --retrieval-from
        retrieval_file = Path(args[args.index("--retrieval-from") + 1]) / "retrieval_default.jsonl"
    retrieval = {r["id"]: r for r in load(retrieval_file)}
    if any(queries[r["id"]]["split"] != "dev" for r in qa):
        raise SystemExit("refused: this run contains non-dev queries (consumed splits must not be analysed for tuning)")
    classes, secondary, examples = collections.Counter(), collections.Counter(), collections.defaultdict(list)
    for r in qa:
        q = queries[r["id"]]
        cites = r.get("citations") or []
        cited = {(c["filename"], c["page_number"] if c.get("page_number") is not None else c.get("record_id")) for c in cites}
        if not q["answerable"]:
            key = "unanswerable: correctly refused" if (not r["grounded"] or r["insufficient_evidence"]) else "unanswerable: wrongly answered"
            classes[key] += 1
            continue
        relevant = {(x["file"], x["unit"]) for x in q["relevant"]}
        hard = {(h["file"], h["unit"]) for h in q["hard_negatives"]}
        ranked = [(x["file"], x["unit"]) for x in retrieval[r["id"]]["modes"]["hybrid"]["ranked"][:5]]
        calls_bad = any(c.get("valid") is False for c in r.get("llm_calls", []))
        text = norm(r.get("answer") or "")
        facts_ok = all(has_fact(text, f) for f in q["required_facts"]) and not any(has_fact(text, f) for f in q.get("forbidden_facts", []))
        if q["category"] == "multi_hop":
            secondary["10 multi-hop (any outcome class below)"] += 0
        if not (relevant & set(ranked)):
            files = {f for f, _ in relevant}
            cls = "1 retrieval: no relevant document in the top 5" if not (files & {f for f, _ in ranked}) else "2 retrieval: relevant document present, labelled page or record not in the top 5"
        elif hard and min([i for i, u in enumerate(ranked) if u in hard] or [9]) < min(i for i, u in enumerate(ranked) if u in relevant):
            cls = "3 ranking: a hard negative ranks above the relevant page"
        elif calls_bad:
            cls = "9 structured-output: the model call was invalid"
        elif not r["grounded"]:
            probs = "; ".join(r.get("problems") or [])
            if r["insufficient_evidence"]:
                cls = "7 unnecessary abstention: refused although relevant evidence was retrieved"
            elif "quote not found" in probs:
                cls = "7b withheld by the verifier: quotation not verbatim"
            elif "number(s) not found" in probs:
                cls = "7c withheld by the verifier: number not in the cited text"
            else:
                cls = "7d withheld by the verifier: other"
        elif not cites:
            cls = "6 missing citations"
        elif not cited <= relevant:
            cls = "5 citation association: cites an unlabelled or sibling page"
        elif not facts_ok:
            cls = "8 unsupported or incomplete: a required fact is absent from the answer"
        else:
            cls = "ok: grounded, labelled citations, facts present"
        classes[cls] += 1
        if cls != "ok: grounded, labelled citations, facts present":
            examples[cls].append(r["id"])
            if q["category"] == "multi_hop":
                secondary["10 multi-hop queries among the failures"] += 1
        numbers = set(re.findall(r"\d+(?:\.\d+)?", text))
        cited_text = " ".join(norm(c.get("quote") or "") for c in cites)
        if r["grounded"] and numbers - set(re.findall(r"\d+(?:\.\d+)?", cited_text)) - set(re.findall(r"\d+(?:\.\d+)?", norm(q["query"]))):
            secondary["4 unsupported claims: a number in the answer is absent from the cited quotes"] += 1
    tenants_cross = sum(1 for r in qa for c in (r.get("citations") or []) if r["tenant"] == "apex" and ("meridian" in (c.get("filename") or "") or "fleet" in (c.get("filename") or "")))
    secondary["11 tenant-scoping or provenance error: citations from another tenant's files (must be 0)"] = tenants_cross
    answerable = sum(v for k, v in classes.items() if not k.startswith("unanswerable"))
    out = {"run": run.name, "rep": int(rep), "dev_queries": len(qa), "answerable": answerable, "classes": dict(sorted(classes.items())), "secondary_flags": dict(secondary),
           "examples": {k: v[:6] for k, v in examples.items()}}
    print(json.dumps(out, indent=1))
    if "--out" in args:
        Path(args[args.index("--out") + 1]).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
