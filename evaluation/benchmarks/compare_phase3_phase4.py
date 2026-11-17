"""Phase 3 vs Phase 4 comparison computed from the raw per-query files of every real-AI run (never from prose).

Phase 3 runs are read from evaluation/reports/phase3 (unchanged); Phase 4 runs from
evaluation/reports/phase4-remeasure. Both use the same frozen apex-eval-v1 held-out split, models and harness.
Writes evaluation/reports/phase4-remeasure/COMPARISON.{json,md}.
"""
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
P3 = ROOT / "evaluation" / "reports" / "phase3"
P4 = ROOT / "evaluation" / "reports" / "phase4-remeasure"
SUFFIX = "_ollama_sentence_transformers"


def load_jsonl(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def runs(root):
    return sorted(p for p in root.glob(f"*{SUFFIX}") if (p / "results.json").exists())


def qa_metrics(rows):
    ans = [r for r in rows if r["answerable"]]
    unans = [r for r in rows if not r["answerable"]]
    grounded = [r for r in rows if r["grounded"]]
    g_ans = [r for r in ans if r["grounded"]]
    cites = [c for r in ans for c in r["citations"]]
    wrong_cite = lambda r: any(not c["correct"] for c in r["citations"])  # noqa: E731
    correct_grounded = [r for r in g_ans if r["facts_in_answer_or_quotes"] and not wrong_cite(r)]
    unsupported = [r for r in grounded if (not r["answerable"]) or wrong_cite(r)
                   or (r["answerable"] and not r["facts_in_answer_or_quotes"])]
    return {
        "answerable": len(ans), "unanswerable": len(unans),
        "citation_correctness": len([c for c in cites if c["correct"]]) / len(cites) if cites else None,
        "citations": len(cites), "citations_correct": len([c for c in cites if c["correct"]]),
        "answer_coverage": len(g_ans) / len(ans),
        "grounded_answers": len(g_ans),
        "false_refusals": sum(1 for r in ans if r["insufficient_evidence"]),
        "withheld_by_verification_or_safeguard": sum(1 for r in ans if not r["grounded"] and not r["insufficient_evidence"]),
        "grounded_answer_correctness": len(correct_grounded) / len(g_ans) if g_ans else None,
        "unsupported_answer_rate": len(unsupported) / len(grounded) if grounded else None,
        "unsupported_answers": len(unsupported), "grounded_total": len(grounded),
        "correct_refusal_rate": sum(1 for r in unans if r["insufficient_evidence"]) / len(unans),
        "unanswerable_wrongly_answered": sum(1 for r in unans if r["grounded"]),
        "safeguard_withholds_with_problem_text": sum(1 for r in rows if r["problems"]),
    }


def run_metrics(path):
    res = json.loads((path / "results.json").read_text(encoding="utf-8"))
    man = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    qa = qa_metrics(load_jsonl(path / "qa_test.jsonl"))
    st, e2e, ret = res["structured"], res["e2e"], res["retrieval"]["test"]
    out = {
        "run": path.name, "dataset_sha256": man["dataset"]["text_files_sha256"],
        "recall_at_5": ret["recall_at_5"], "mrr": ret["mrr"], "precision_at_5": ret["precision_at_5"],
        **qa,
        "structured_model_valid": f'{st["model_output_schema_valid"]}/{st["reports"]}',
        "structured_validity_rate": st["model_output_validity_rate"],
        "structured_pipeline_ok": st["pipeline_ok_or_expected_rejection"],
        "e2e_runs": len(e2e["runs"]), "e2e_submitted": sum(1 for r in e2e["runs"] if r["state"] == "SUBMITTED"),
        "e2e_duplicates": e2e["duplicates"], "e2e_total_median_s": e2e["total_s"]["median"],
        "e2e_total_p95_s": e2e["total_s"]["p95"],
        "inference_median_s": res["qa"]["llm_inference_s"]["median"], "inference_p95_s": res["qa"]["llm_inference_s"]["p95"],
        "qa_wall_median_s": res["qa"]["latency_wall_s"]["median"], "qa_wall_p95_s": res["qa"]["latency_wall_s"]["p95"],
        "tokens_per_s_median": res["qa"]["tokens_per_s"]["median"],
        "versions": {k: res["versions"].get(k) for k in ("ollama", "ollama_model", "ollama_model_digest",
                                                          "prompt_version", "embedding_profile",
                                                          "embedding_evidence_threshold_used")},
        "command": man["command"], "started_utc": man["started_utc"],
    }
    if "review" in st:
        out["review"] = st["review"]
        out["e2e_human_review_required"] = sum(1 for r in e2e["runs"] if r.get("human_review_required"))
    return out


def agg(values):
    values = [v for v in values if v is not None]
    return {"min": min(values), "max": max(values), "mean": round(statistics.mean(values), 4)} if values else None


KEYS = ["recall_at_5", "mrr", "citation_correctness", "unsupported_answer_rate", "correct_refusal_rate",
        "answer_coverage", "grounded_answer_correctness", "structured_validity_rate", "e2e_total_median_s",
        "inference_median_s", "inference_p95_s", "qa_wall_median_s", "qa_wall_p95_s"]


def main():
    p3, p4 = [run_metrics(p) for p in runs(P3)], [run_metrics(p) for p in runs(P4)]
    if not p4:
        sys.exit("no Phase 4 runs found")
    same_dataset = {m["dataset_sha256"] for m in p3 + p4}
    summary = {"dataset_identical_across_all_runs": len(same_dataset) == 1, "dataset_sha256": sorted(same_dataset),
               "phase3_runs": [m["run"] for m in p3], "phase4_runs": [m["run"] for m in p4],
               "phase3": {k: agg([m[k] for m in p3]) for k in KEYS},
               "phase4": {k: agg([m[k] for m in p4]) for k in KEYS},
               "phase4_review": [m.get("review") for m in p4],
               "phase4_e2e_human_review_required": [m.get("e2e_human_review_required") for m in p4],
               "per_run": {"phase3": p3, "phase4": p4}}
    (P4 / "COMPARISON.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    fmt = lambda a, pct=False: ("n/a" if a is None else (  # noqa: E731
        f"{a['min']*100:.1f}-{a['max']*100:.1f}%" if pct else f"{a['min']:.3g}-{a['max']:.3g}"))
    rows = [("Recall@5", "recall_at_5", True), ("MRR", "mrr", False), ("Citation correctness", "citation_correctness", True),
            ("Unsupported-answer rate", "unsupported_answer_rate", True),
            ("Correct refusal rate (unanswerable)", "correct_refusal_rate", True),
            ("Answer coverage (answerable)", "answer_coverage", True),
            ("Grounded-answer correctness", "grounded_answer_correctness", True),
            ("Structured model-output validity", "structured_validity_rate", True),
            ("LLM inference median (s)", "inference_median_s", False), ("LLM inference p95 (s)", "inference_p95_s", False),
            ("Question wall-clock median (s)", "qa_wall_median_s", False),
            ("Question wall-clock p95 (s)", "qa_wall_p95_s", False),
            ("E2E workflow median (s)", "e2e_total_median_s", False)]
    md = ["# Phase 3 vs Phase 4 (real Ollama + MiniLM, frozen apex-eval-v1 held-out test split)", "",
          f"Dataset identical across all runs: **{summary['dataset_identical_across_all_runs']}** "
          f"(sha256 {', '.join(s[:16] for s in sorted(same_dataset))}...).",
          f"Phase 3 runs: {len(p3)}; Phase 4 runs: {len(p4)}. Ranges are min-max across runs. Generated from raw per-query files by "
          "`python evaluation/benchmarks/compare_phase3_phase4.py`.", "",
          "| Metric | Phase 3 | Phase 4 |", "|---|---|---|"]
    md += [f"| {label} | {fmt(summary['phase3'][k], pct)} | {fmt(summary['phase4'][k], pct)} |" for label, k, pct in rows]
    md += ["", "E2E completion: " + "; ".join(f"{m['run'][:15]}: {m['e2e_submitted']}/{m['e2e_runs']} submitted, "
                                               f"{m['e2e_duplicates']} duplicates" for m in p3 + p4), "",
           "Phase 4 incident review (structured set, 24 reports): " + "; ".join(
               f"run {i + 1}: {r['pending_review']} pending_review, {r['needs_review']} needs_review, "
               f"{r['rejected_at_extraction']} rejected at extraction" for i, r in enumerate(summary["phase4_review"])),
           "", "E2E runs needing human review: " + ", ".join(str(x) for x in summary["phase4_e2e_human_review_required"])]
    (P4 / "COMPARISON.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
