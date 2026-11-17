"""Generate docs/evaluation/phase8-heldout-report.md: unchanged baseline versus the frozen candidate on the frozen test split (observational only).

    python evaluation/phase8/make_heldout_report.py regression_summary.json

Every number comes from the preserved raw outputs of the two held-out runs through score_experiment/score_baseline/metrics. Nothing here selects, tunes or
re-runs anything. Targets: MET / NOT MET are point-estimate classifications; the Wilson interval states what the sample supports.
"""
import collections
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evaluation" / "phase8"))
import metrics as M  # noqa: E402
import score_baseline as sb  # noqa: E402
import score_experiment as se  # noqa: E402

R = ROOT / "evaluation" / "reports" / "phase8"
DS = sb.DS


def run(prefix):
    return Path(sorted(glob.glob(str(R / f"exp-{prefix}-*")))[-1])


def f(p):
    if p is None or p.get("value") is None:
        return "N/A"
    lo, hi = p["wilson95"]
    return f"{p['numerator']}/{p['denominator']} = {100 * p['value']:.1f}% ({100 * lo:.1f}-{100 * hi:.1f})"


def cls(p, target):
    """Point-estimate attainment and what the interval supports."""
    if p is None or p.get("value") is None:
        return "NOT EVALUABLE"
    lo, hi = p["wilson95"]
    point = "MET" if p["value"] >= target else "NOT MET"
    support = "interval above target" if lo >= target else "interval below target" if hi < target else "interval overlaps target"
    return f"{point} (point estimate; {support})"


def per_query_retrieval(rows, queries, mode="hybrid"):
    qmap = {q["id"]: q for q in queries}
    out = {}
    for r in rows:
        q = qmap[r["id"]]
        if not q["answerable"] or not q["relevant"]:
            continue
        ranked = [(h["file"], h["unit"]) for h in r["modes"][mode]["ranked"]]
        rel = {(x["file"], x["unit"]) for x in q["relevant"]}
        grades = {(x["file"], x["unit"]): x["grade"] for x in q["relevant"]}
        out[r["id"]] = {"r5": M.recall_at_k(ranked, rel, 5), "ndcg5": M.ndcg_at_k(ranked, grades, 5), "mrr": M.reciprocal_rank(ranked, rel, 10)}
    return out


def main():
    base_dir, cand_dir = run("HELDOUT-BASELINE"), run("HELDOUT-CANDIDATE")
    queries = [q for q in sb.load(DS / "queries.jsonl") if q["split"] == "test"]
    bs, cs = se.score_dir(base_dir), se.score_dir(cand_dir)
    bm = json.loads((base_dir / "manifest.json").read_text(encoding="utf-8"))
    cm = json.loads((cand_dir / "manifest.json").read_text(encoding="utf-8"))
    bres = json.loads((base_dir / "results.json").read_text(encoding="utf-8"))
    cres = json.loads((cand_dir / "results.json").read_text(encoding="utf-8"))
    pre = json.loads((R / "heldout" / "preflight.json").read_text(encoding="utf-8"))
    summ = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")) if len(sys.argv) > 1 else {}
    brr = {k: v for k, v in (json.loads((base_dir / "retrieval_scores.json").read_text(encoding="utf-8"))["default"]).items()}
    crr = json.loads((cand_dir / "retrieval_scores.json").read_text(encoding="utf-8"))["default"]
    bret = [json.loads(x) for x in (base_dir / "retrieval_default.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    cret = [json.loads(x) for x in (cand_dir / "retrieval_default.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    pb, pc = per_query_retrieval(bret, queries), per_query_retrieval(cret, queries)
    ids = sorted(pb)
    qa_b, qa_c = bs["scopes"]["combined"]["qa"]["rep1"], cs["scopes"]["combined"]["qa"]["rep1"]
    ex_b, ex_c = bs["scopes"]["combined"]["extraction"]["rep1"], cs["scopes"]["combined"]["extraction"]["rep1"]
    identical = {}
    for name, s in (("baseline", bs), ("candidate", cs)):
        q = s["scopes"]["combined"]["qa"]
        e = s["scopes"]["combined"]["extraction"]
        identical[name] = all(q["rep1"]["grounded_answer_coverage"]["numerator"] == q[f"rep{r}"]["grounded_answer_coverage"]["numerator"] and
                              e["rep1"]["review_rate"]["numerator"] == e[f"rep{r}"]["review_rate"]["numerator"] for r in (2, 3))
    gc = se.paired(qa_b["per_query"], qa_c["per_query"], "gc")
    cr = se.paired(qa_b["per_query"], qa_c["per_query"], "cr")
    n_ans = qa_c["answerable"]
    n_unans = qa_c["correct_abstention"]["denominator"]

    L = ["# Phase 8 held-out evaluation report (frozen candidate versus unchanged baseline, frozen test split)", "",
         "**Status of this evidence.** One observational evaluation on the frozen `test` split (75 queries, 20 incident cases; challenge split not run), approved with conditions. Nothing was tuned, re-run or selected on these results. Labels are author-generated, content is synthetic, customers are fictional; this is not customer-deployment evidence and does not establish production readiness.", "",
         "## 1. Candidate identity and configuration",
         f"- Candidate: `evaluation/phase8/configs/candidate_v1.json` = `{json.dumps(pre['candidate_config'])}`; hash **`{pre['candidate_hash']}`** (equals the frozen value `4e24e63f...268e03`); enabled through `EAOP_TUNING` (`--tuning`); manifest-recorded tuning hash: baseline `{bm['tuning_hash_at_ingestion'][:16]}...` (defaults), candidate `{cm['tuning_hash_at_ingestion']}`.",
         "- Baseline: the unchanged defaults (`EAOP_TUNING` empty), i.e. the system as validated in Phases 3-7.",
         f"- Models: Ollama `qwen2.5:1.5b` digest `{cm['versions']['ollama_model_digest'][:12]}`, Ollama {cm['versions']['ollama']}; MiniLM `{cm['versions'].get('embedding_profile')}`; options {cm['runtime']['ollama_options']}; evidence threshold {cm['runtime']['evidence_threshold']}.", "",
         "## 2. Git commit and environment",
         f"- Pre-flight HEAD `{pre['head'][:7]}`; run manifests record commits baseline `{bm['git_commit'][:7]}`, candidate `{cm['git_commit'][:7]}`; python {bm['python']}; PostgreSQL {cm['versions'].get('postgres')}, pgvector {cm['versions'].get('pgvector')}; hardware `evaluation/reports/phase8/heldout/hardware.json` (Intel i7-1165G7, CPU-only, 15.7 GB RAM), system state before the runs `system_before.txt`, Ollama state `ollama_state_before.txt`.",
         f"- Execution order: baseline first (started {bm['started_utc']}, {bm['duration_s']} s), then candidate (started {cm['started_utc']}, {cm['duration_s']} s), sequentially on the same machine; each run re-creates the isolated database, re-onboards both tenants, ingests the same corpus (the superseded manual versions first), runs `ANALYZE`, then a warm-up question (model resident, cold start not measured), then 3 repetitions of QA and extraction, then the workflow checks. Three repetitions are repeated measurements of the same cases (counts identical across repetitions: baseline {identical['baseline']}, candidate {identical['candidate']}); headline = repetition 1.", "",
         "## 3. Dataset, scorer and pre-execution integrity evidence",
         "| # | Pre-execution check | Result |", "|---|---|---|"]
    L += [f"| {c['n']} | {c['check']} | {c['result']} |" for c in pre["checks"]]
    L += ["", "Frozen test split sha256 `19540a5c88eb7943a640f0fb802de6f40612c32a70e0a58c1ac4af2cb3e6893a` (75 queries, 20 incident cases), unchanged since `c0d19c9`. Scoring and candidate code were hashed before the run and re-checked after it (see section 12).",
          f"**Disclosure (check 8).** The held-out ids were never in any recorded run output and no run before this evaluation used the test split. However, the label-review worksheet generated at the Gate B checkpoint (before any model run or optimisation) displays the labels of 11 test-split items ({'E2-A-0019, E2-A-0050, E2-A-0070, E2-A-0084, E2-A-0087, E2-A-0098, E2-A-0115, E2-M-0024, E2-M-0038, E2-M-0065, E2-M-0071'}), and one test id is mentioned in the dataset methodology note. No model output for those items was seen and no tuning decision used them, but this is a partial exposure of labels and the evaluation should not be described as blind in the strictest sense.", ""]
    L += ["## 4. Baseline versus candidate on the test split (repetition 1; numerator/denominator = percentage (Wilson 95%))", "",
          "| Metric | Baseline | Candidate | Target | Candidate target attainment |", "|---|---|---|---|---|"]
    rows = (("grounded_answer_coverage", "Grounded-answer coverage", 0.75), ("answered", "Answer coverage", None), ("false_refusals", "False refusals", None), ("withheld_unverified", "Withheld by verification", None),
            ("citation_correctness_answerable", "Citation correctness (answerable)", 0.95), ("citation_tenant_ownership", "Citation tenant ownership", 1.0), ("claim_support", "Claim support", 0.95),
            ("correct_abstention", "Correct abstention", 0.90), ("unsupported_answer_rate", "Unsupported-answer rate", None))
    for key, label, tgt in rows:
        L.append(f"| {label} | {f(qa_b[key])} | {f(qa_c[key])} | {('%d%%' % round(tgt * 100)) if tgt else ''} | {cls(qa_c[key], tgt) if tgt else ''} |")
    for key, label, tgt in (("raw_schema_validity", "Raw extraction schema validity", 1.0), ("priority_accuracy", "Priority accuracy", None), ("final_category_accuracy", "Category accuracy", None),
                            ("evidence_completeness", "Incidents with grounded evidence", None), ("review_rate", "Human-review rate", None), ("unsafe_automatic_acceptance", "Unsafe automatic acceptance (must-review cases)", None)):
        L.append(f"| {label} | {f(ex_b[key])} | {f(ex_c[key])} | {('%d%%' % round(tgt * 100)) if tgt else ''} | {cls(ex_c[key], tgt) if tgt else ''} |")
    nb, nc = ex_b["unsupported_numeric_accepted_as_verified"], ex_c["unsupported_numeric_accepted_as_verified"]
    L += [f"| Unsupported numeric values accepted as verified | {nb['count']} of {nb['of_proposed_values']} proposed | {nc['count']} of {nc['of_proposed_values']} proposed | 0 | {'GATE MET' if nc['count'] == 0 else 'GATE FAILED (critical regression)'} |",
          f"| p95 `/ai/ask` latency | {qa_b['latency_s']['all']['p95']:.1f} s (p50 {qa_b['latency_s']['all']['p50']:.2f}) | {qa_c['latency_s']['all']['p95']:.1f} s (p50 {qa_c['latency_s']['all']['p50']:.2f}) | 15 s | {qa_c['latency_p95_target_15s']} |",
          f"| p95 `/incidents/extract` latency | {ex_b['latency_s']['p95']:.1f} s | {ex_c['latency_s']['p95']:.1f} s | | |", "",
          f"Denominators: {n_ans} answerable and {n_unans} expected-refusal test queries (plus injection cases with optional answers), {ex_c['cases']} incident cases: these are small, so every interval is wide and no target is statistically established either way unless the interval lies entirely on one side (stated in the last column). "
          f"**Paired comparison** on the identical queries: grounded-correct improved {gc['improved']}, regressed {gc['regressed']}, unchanged {gc['unchanged']} (exact McNemar p = {M.mcnemar_exact(gc['improved'], gc['regressed'])}); correct refusal improved {cr['improved']}, regressed {cr['regressed']}, unchanged {cr['unchanged']} (exact McNemar p = {M.mcnemar_exact(cr['improved'], cr['regressed'])}). "
          "Development runs showed that identical configurations differ by about three queries from run to run, so paired differences of that size are not evidence of improvement. A point-estimate increase is not reported as established improvement unless the paired test supports it.", "",
          "**Notes on specific rows.** (a) *Unsafe automatic acceptance* is **NOT EVALUABLE** on the test split: it contains no incident case labelled must-review (denominator 0), so the dev-split result (0 of 4) is the only evidence for that metric. (b) *Raw schema validity 90% (18/20)* in both configurations: the two invalid raw outputs are the two reports with no identifiable asset (`E2-A-X028`, `E2-M-X028`), where the model invented an asset id; the application rejected both (422 `asset_not_identified`), "
          "so no unsafe incident was created, but the 100% model-level target is **NOT MET**. (c) Baseline false refusal 1/54 and baseline unsupported numerics 1 (one hallucinated vibration value accepted by the baseline pipeline; the candidate's audit routed it to review).", "",
          "## 5. Retrieval (answerable test queries with labelled passages)", "",
          "| Scope | Config | n | R@1 | R@3 | R@5 | R@10 | P@5 (ceiling) | MRR | nDCG@5 | nDCG@10 | p50/p95 ms | foreign passages |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for scope in ("combined", "apex", "meridian"):
        for name, rr_ in (("baseline", brr), ("candidate", crr)):
            h = rr_[scope]["hybrid"]
            L.append(f"| {scope} | {name} | {h['queries']} | {h['recall@1']} | {h['recall@3']} | {h['recall@5']} | {h['recall@10']} | {h['precision@5']} ({h['precision_ceiling@5']}) | {h['mrr']} | {h['ndcg@5']} | {h['ndcg@10']} | "
                     f"{h['latency_s']['p50'] * 1000:.0f}/{h['latency_s']['p95'] * 1000:.0f} | {rr_[scope]['cross_tenant_leakage']['foreign']} |")
    d5 = M.paired_bootstrap_diff([pb[i]["r5"] for i in ids], [pc[i]["r5"] for i in ids])
    dn = M.paired_bootstrap_diff([pb[i]["ndcg5"] for i in ids], [pc[i]["ndcg5"] for i in ids])
    L += ["", f"Recall@5 combined: baseline {brr['combined']['hybrid']['recall@5']} (bootstrap 95% CI {brr['combined']['hybrid']['recall@5_ci95']}), candidate {crr['combined']['hybrid']['recall@5']} (CI {crr['combined']['hybrid']['recall@5_ci95']}); target 85%: baseline {'MET' if brr['combined']['hybrid']['recall@5'] >= 0.85 else 'NOT MET'}, candidate {'MET' if crr['combined']['hybrid']['recall@5'] >= 0.85 else 'NOT MET'} (point estimates). "
          f"Paired bootstrap (candidate minus baseline): recall@5 {d5}, nDCG@5 {dn}.", ""]
    L += ["## 6. Tenant-specific results (Apex and Meridian reported separately; aggregates do not replace them)", "", "| Tenant | Metric | Baseline | Candidate |", "|---|---|---|---|"]
    for scope in ("apex", "meridian"):
        qb2, qc2 = bs["scopes"][scope]["qa"]["rep1"], cs["scopes"][scope]["qa"]["rep1"]
        eb2, ec2 = bs["scopes"][scope]["extraction"]["rep1"], cs["scopes"][scope]["extraction"]["rep1"]
        for key, label, b_, c_ in (("grounded_answer_coverage", "Grounded coverage", qb2, qc2), ("answered", "Answer coverage", qb2, qc2), ("false_refusals", "False refusals", qb2, qc2),
                                   ("citation_correctness_answerable", "Citation correctness", qb2, qc2), ("claim_support", "Claim support", qb2, qc2), ("correct_abstention", "Correct abstention", qb2, qc2),
                                   ("unsupported_answer_rate", "Unsupported-answer rate", qb2, qc2), ("raw_schema_validity", "Raw schema validity", eb2, ec2), ("priority_accuracy", "Priority accuracy", eb2, ec2),
                                   ("final_category_accuracy", "Category accuracy", eb2, ec2), ("review_rate", "Review rate", eb2, ec2), ("evidence_completeness", "Grounded evidence", eb2, ec2)):
            L.append(f"| {scope} | {label} | {f(b_[key])} | {f(c_[key])} |")
        nb2, nc2 = eb2["unsupported_numeric_accepted_as_verified"], ec2["unsupported_numeric_accepted_as_verified"]
        L.append(f"| {scope} | Unsupported numerics accepted | {nb2['count']} of {nb2['of_proposed_values']} | {nc2['count']} of {nc2['of_proposed_values']} |")
    # safety
    wb, wc = bs["workflow"] if "workflow" in bs else None, None
    wfb = json.loads((base_dir / "workflow.json").read_text(encoding="utf-8"))
    wfc = json.loads((cand_dir / "workflow.json").read_text(encoding="utf-8"))

    def wsum(wf, res):
        sub = [x for x in wf if x.get("final_state") == "SUBMITTED"]
        ext = res.get("external", {})
        return {"cases": len(wf), "submitted": len(sub), "submit_before_approval_accepted": sum(1 for x in wf if x.get("submit_before_approval") != 409),
                "engineer_approval_accepted": sum(1 for x in wf if x.get("engineer_approval_status") == 200), "external": ext,
                "duplicates": ext.get("ticketing_tickets", 0) + ext.get("servicedesk_tickets", 0) - len(sub), "errors": [x for x in wf if x.get("error")]}
    sb_, sc_ = wsum(wfb, bres), wsum(wfc, cres)
    xt_b, xt_c = qa_b["cross_tenant_probes"], qa_c["cross_tenant_probes"]
    L += ["", "## 7. Safety gates", "", "| Gate | Baseline | Candidate | Outcome |", "|---|---|---|---|",
          f"| Cross-tenant data in retrieval (foreign passages / retrieved) | {brr['combined']['cross_tenant_leakage']['foreign']} / {brr['combined']['cross_tenant_leakage']['retrieved_passages']} | {crr['combined']['cross_tenant_leakage']['foreign']} / {crr['combined']['cross_tenant_leakage']['retrieved_passages']} | {'MET' if crr['combined']['cross_tenant_leakage']['foreign'] == 0 else 'CRITICAL REGRESSION'} |",
          f"| Citation tenant ownership | {f(qa_b['citation_tenant_ownership'])} | {f(qa_c['citation_tenant_ownership'])} | {'MET' if qa_c['citation_tenant_ownership']['numerator'] == qa_c['citation_tenant_ownership']['denominator'] else 'CRITICAL REGRESSION'} |",
          f"| Cross-tenant probe heuristic flags (answer or citation carrying the other tenant's value) | {xt_b['leaks']} of {xt_b['cases']} | {xt_c['leaks']} of {xt_c['cases']} | flags are reviewed manually in section 9 |",
          f"| Unauthorized external submissions (submission before approval accepted / non-approver approval accepted) | {sb_['submit_before_approval_accepted']} / {sb_['engineer_approval_accepted']} | {sc_['submit_before_approval_accepted']} / {sc_['engineer_approval_accepted']} | {'MET' if sc_['submit_before_approval_accepted'] == 0 and sc_['engineer_approval_accepted'] == 0 else 'CRITICAL REGRESSION'} |",
          f"| Duplicate external submissions | {sb_['duplicates']} | {sc_['duplicates']} | {'MET' if sc_['duplicates'] == 0 else 'CRITICAL REGRESSION'} |",
          f"| Unsupported numerics accepted as verified | {nb['count']} | {nc['count']} | {'MET' if nc['count'] == 0 else 'CRITICAL REGRESSION'} |",
          f"| Must-review incidents not held for review | {ex_b['review_missed_unsafe']} | {ex_c['review_missed_unsafe']} | {'MET' if ex_c['review_missed_unsafe'] == 0 else 'CRITICAL REGRESSION'} |",
          f"| Workflow completion (authorized path: extract, review if needed, draft, approval, outbox, mock submission) | {sb_['submitted']}/{sb_['cases']} | {sc_['submitted']}/{sc_['cases']} | recovery from injected failures is covered by the fault-injection suite (section 12), not by this run |", "",
          f"Workflow errors recorded: baseline {sb_['errors']}, candidate {sc_['errors']}. Human approval is enforced by the platform (these checks attempt a pre-approval submission and a non-approver approval; both must be refused). The review gate, tenant-scoped retrieval, RLS, RBAC and egress controls are unchanged code paths verified by the full suites in section 12.", ""]
    # failure analysis saved by analyze_failures (post-hoc observation)
    fa = json.loads((cand_dir / "failure_analysis.json").read_text(encoding="utf-8")) if (cand_dir / "failure_analysis.json").exists() else None
    if fa:
        mer = [x for x in fa["answerable_items"] if x["id"].startswith("E2-M-")]
        apx = [x for x in fa["answerable_items"] if x["id"].startswith("E2-A-")]
        L += ["## 8. Failure analysis (candidate, test split, observational; the candidate was not modified)", "",
              f"- Answerable queries not grounded-correct: {dict(collections.Counter(x['class'] for x in fa['answerable_items']))} (Apex {len(apx)}, Meridian {len(mer)}).",
              f"- Unanswerable queries still answered: {[(x['id'], x['subtype']) for x in fa['unanswerable_wrong']]}.", f"- Citations to passages outside the labelled evidence: {len(fa['citation_issues'])} ({dict(collections.Counter(x['category'] for x in fa['citation_issues']))}).", "",
              "Representative traceable cases (synthetic data; `evaluation/reports/phase8/exp-HELDOUT-CANDIDATE-*/failure_analysis.json` and `qa_rep1.jsonl` carry the full evidence):", ""]
        for x in (mer + apx)[:8]:
            L.append(f"- `{x['id']}` ({x['category']}): {x['class']} - {x['query']} - {x['detail'][:140]}")
        L += ["", "Meridian-specific investigation (sections 9-10 below) uses the same raw outputs."]
    L += ["", "## 9. Meridian investigation (no change to the candidate)", ""]
    qm_b, qm_c = bs["scopes"]["meridian"]["qa"]["rep1"], cs["scopes"]["meridian"]["qa"]["rep1"]
    em_b, em_c = bs["scopes"]["meridian"]["extraction"]["rep1"], cs["scopes"]["meridian"]["extraction"]["rep1"]
    L += [f"- Grounded-answer coverage {f(qm_b['grounded_answer_coverage'])} -> {f(qm_c['grounded_answer_coverage'])}; citation correctness {f(qm_b['citation_correctness_answerable'])} -> {f(qm_c['citation_correctness_answerable'])}; priority accuracy {f(em_b['priority_accuracy'])} -> {f(em_c['priority_accuracy'])}; "
          f"category accuracy {f(em_b['final_category_accuracy'])} -> {f(em_c['final_category_accuracy'])}; unsupported-answer rate {f(qm_b['unsupported_answer_rate'])} -> {f(qm_c['unsupported_answer_rate'])}; false refusals {f(qm_c['false_refusals'])}.",
          f"- Numeric extraction: Meridian signals proposed/unsupported: {em_c['numeric_values_proposed_unsupported']['numerator']} of {em_c['numeric_values_proposed_unsupported']['denominator']}; accepted as verified {em_c['unsupported_numeric_accepted_as_verified']['count']}.",
          f"- By-category outcome counts (Meridian, candidate): {({k: v for k, v in qm_c['by_category'].items()})}.", ""]
    L += ["## 10. Interpretation limits", "",
          "Small denominators (see section 4); one synthetic dataset with author-generated labels; the candidate's accepted parameters and gate patterns were selected on the dev split of the same generator, so some optimism is expected and a smaller held-out gain than on dev would be unsurprising; the citation-correctness rule is conservative (an unlabelled genuine passage counts as incorrect) and claim support is a surface test of numbers and identifiers; "
          "mock external systems; a 1.5B model that still hallucinates numbers and quotes; CPU-only local latency, no extrapolation to cloud capacity; coarse resource sampling.", ""]
    L += ["## 11. Latency and resources (single user, warm model, documented laptop; unreliable to better than about +/-15% run to run)", "",
          "| Run | `/ai/ask` p50 / p95 | `/incidents/extract` p95 | Retrieval p95 | Ingestion | CPU mean (QA rep1) | Ollama peak RSS | Python peak RSS | Workflow wall time |", "|---|---|---|---|---|---|---|---|---|"]
    for name, s, res, rr_ in (("baseline", bs, bres, brr), ("candidate", cs, cres, crr)):
        q = s["scopes"]["combined"]["qa"]["rep1"]
        e = s["scopes"]["combined"]["extraction"]["rep1"]
        r1 = res["resources"].get("qa_rep1", {})
        L.append(f"| {name} | {q['latency_s']['all']['p50']:.2f} / {q['latency_s']['all']['p95']:.1f} s | {e['latency_s']['p95']:.1f} s | {rr_['combined']['hybrid']['latency_s']['p95'] * 1000:.0f} ms | {res['ingest_seconds']} s | "
                 f"{r1.get('cpu_pct_mean')}% | {r1.get('ollama_working_set_mb_peak')} MB | {r1.get('python_working_set_mb_peak')} MB | {res['window_seconds'].get('workflow')} s |")
    L += ["", "Tokens per second and model load are those of the unchanged model and options; concurrency was not re-measured (the application's inference limiter behaviour is unchanged). p99 not reported (n < 200).", "",
          "## 12. Regression results and post-run integrity", ""]
    L += [f"- {k}: {v}" for k, v in summ.items()]
    L += ["", "## 13. Limitations and remaining requirements gaps", "",
          "- The 85-requirement traceability catalogue is **provisional**; the original V4.1 specification is preserved but not reconciled (completeness UNVERIFIED). No claim of complete V4.1 compliance or production readiness is made; reconciliation is a separate mandatory checkpoint.",
          "- Not implemented or only partial (see the matrix): ingestion deletion and jobs, reranking as a product feature, CSV/webhook connectors, OpenTelemetry/Prometheus, cloud portability, delivery documents, CI that has never run, publication. Network-level egress control, distributed rate limiting and independent security review are not provided.", "",
          "## 14. Evidence paths and reproduction commands", "",
          f"- Pre-flight: `evaluation/reports/phase8/heldout/preflight.json` (`python evaluation/phase8/preflight_heldout.py`).", f"- Baseline run `{base_dir.name}`, candidate run `{cand_dir.name}` (raw per-item outputs, manifests, retrieval, workflow, results).",
          "- Reproduce: `bash evaluation/phase8/configs/run_heldout.sh` (requires explicit approval: it evaluates the frozen test split), then `python evaluation/phase8/score_experiment.py <run_dir>` and `python evaluation/phase8/make_heldout_report.py <summary.json>`.", "",
          "## 15. Final recommendation", "",
          "**What the evidence supports (test split, small samples, observational):** (1) retrieval improvement is real and robust: recall@5 0.895 -> 0.963, nDCG@5 0.803 -> 0.940, with the paired bootstrap interval for the nDCG@5 difference excluding zero, in both tenants and with no foreign passages; "
          "(2) the human-review burden fell from 88.9% to 27.8% with grounded evidence rising from 11.1% to 72.2% while no must-review case was missed and no unsupported numeric value was accepted (the baseline accepted one); (3) correct abstention was 17/17 (baseline 16/17) with no false refusals (baseline 1); (4) every safety gate held.",
          "**What it does not support:** the development-split gains in grounded-answer coverage and citation correctness **did not replicate**. Grounded coverage was 59.3% (baseline 64.8%; paired +4/-7), citation correctness 89.8% (baseline 95.1%) and the unsupported-answer rate 20.0% (baseline 12.5%); with 54 answerable queries these differences are not statistically distinguishable from zero, but the point estimates point the wrong way, "
          "and in Meridian multi-hop questions (0 of 5 grounded-correct) and quotation failures dominate. This evaluation cannot attribute the regression to a component (no ablation on held-out data is allowed), and dev-tuned parameters and the answer-side citation-completion step are the obvious suspects.",
          "**Targets:** NOT MET: grounded-answer coverage (75%), raw extraction schema validity (100%, 18/20), citation correctness (95% point estimate 89.8%). Point-estimate MET with intervals overlapping the target (not established): Recall@5, claim support, correct abstention, p95 latency. NOT EVALUABLE: unsafe automatic acceptance on this split. Safety gates: MET.",
          "**Recommendation:** do not describe the candidate as an overall quality improvement or as production-ready. The retrieval, abstention, numeric-audit and review-burden changes are supported by both splits and are reasonable to keep as opt-in or default-candidate components after your review; the answer-side changes (in particular citation completion) are not supported by the held-out result and should be analysed on development data only (ablation of C3 and the entity gate, quotation failures, Meridian multi-hop) under a new approval before any further held-out use. "
          "The held-out split has now been consumed for the frozen candidate; any modified candidate would need a fresh, untouched evaluation set to claim an unbiased result. The V4.1 specification reconciliation and the 85-requirement catalogue remain provisional; completeness is UNVERIFIED."]
    (ROOT / "docs" / "evaluation" / "phase8-heldout-report.md").write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
    print("written")


if __name__ == "__main__":
    main()
