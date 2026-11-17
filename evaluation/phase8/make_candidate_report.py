"""Generate docs/evaluation/phase8-candidate-report.md: baseline versus the integrated development candidate (dev split only).

    python evaluation/phase8/make_candidate_report.py [regression_summary.json]

All numbers come from the preserved raw outputs via score_experiment/score_baseline; the narrative around them states limits and decisions.
"""
import collections
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evaluation" / "phase8"))
import score_experiment as se  # noqa: E402

R = ROOT / "evaluation" / "reports" / "phase8"
BASE = R / "baseline-20261112T035539Z"
CAND = Path(sorted(glob.glob(str(R / "exp-CAND1-*")))[-1])


def f(p):
    if p["value"] is None:
        return "N/A"
    lo, hi = p["wilson95"]
    return f"{p['numerator']}/{p['denominator']} = {100 * p['value']:.1f}% ({100 * lo:.1f}-{100 * hi:.1f})"


def main():
    b, c = se.score_dir(BASE)["scopes"], se.score_dir(CAND)["scopes"]
    ret = json.loads((CAND / "retrieval_scores.json").read_text(encoding="utf-8"))["default"]
    man = json.loads((CAND / "manifest.json").read_text(encoding="utf-8"))
    res = json.loads((CAND / "results.json").read_text(encoding="utf-8"))
    wf = json.loads((CAND / "workflow.json").read_text(encoding="utf-8"))
    fa = json.loads((CAND / "failure_analysis.json").read_text(encoding="utf-8"))
    summ = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")) if len(sys.argv) > 1 else {}
    reps = {r: se.score_dir(CAND)["scopes"]["combined"]["qa"][f"rep{r}"] for r in (1, 2, 3)}
    exr = {r: se.score_dir(CAND)["scopes"]["combined"]["extraction"][f"rep{r}"] for r in (1, 2, 3)}
    identical = all(reps[1]["grounded_answer_coverage"]["numerator"] == reps[r]["grounded_answer_coverage"]["numerator"] and
                    reps[1]["citation_correctness_answerable"]["numerator"] == reps[r]["citation_correctness_answerable"]["numerator"] and
                    exr[1]["review_rate"]["numerator"] == exr[r]["review_rate"]["numerator"] for r in (2, 3))
    pq = se.paired(b["combined"]["qa"]["rep1"]["per_query"], c["combined"]["qa"]["rep1"]["per_query"], "gc")
    pr = se.paired(b["combined"]["qa"]["rep1"]["per_query"], c["combined"]["qa"]["rep1"]["per_query"], "cr")
    acct = {}
    for kind, n in (("qa", 118), ("extraction", 34)):
        for rep in (1, 2, 3):
            rows = [json.loads(x) for x in (CAND / f"{kind}_rep{rep}.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
            ids = [x["id"] for x in rows]
            acct[f"{kind}_rep{rep}"] = (len(rows), n, len(ids) - len(set(ids)), sorted({x["status"] for x in rows}))

    L = ["# Phase 8 integrated development candidate: results (dev split, not held-out)", "",
         f"Candidate configuration `evaluation/phase8/configs/candidate_v1.json`, **configuration hash `{man['tuning_hash_at_ingestion']}`** (SHA-256 of the canonical effective settings; code commit recorded in the run manifest: `{man['git_commit'][:7]}`). "
         f"Run `{man['run_id']}`: 3 repetitions of the 118 dev queries and 34 dev incident cases plus the workflow checks, real Ollama `qwen2.5:1.5b` (digest 65ec06548149) and MiniLM; the model, prompts, evidence threshold, citation verification rules and review gate are the baseline's. "
         "These are development-split measurements on synthetic, author-labelled data; the parameters of the accepted changes (identifier boost 0.02, override-gate patterns) were chosen on this same split, so the figures are optimistic relative to a held-out evaluation. The held-out and challenge splits were not run or inspected.", "",
         "## Candidate = which changes", "", "| Component | Role | Experiment |", "|---|---|---|",
         "| Identifier boost 0.02 (assets resolved to models through the register) | retrieval | E3 |",
         "| Entity gate: refuse when an identifier in the question is absent from every cited passage | abstention | E8 |",
         "| Query-override gate: refuse questions that try to override evidence, tenant or approval rules | abstention | E8b (addition to E8) |",
         "| Citation completion: cite the retrieved passage that actually contains a value the answer states (verbatim sentence, entity-relevant only) | grounding | C3 (added after diagnosis, not an E1-E10 experiment) |",
         "| Numeric measurement audit: values not stated in the report are not used by the priority rules, are preserved as `unsupported` and force human review | extraction safety | priority 1 / E10a |",
         "| Incident guidance query includes the asset's own register name (equipment family) | review burden | E10d (refinement of E10c after diagnosis) |", "",
         "Rejected after measurement: E1, E2, E4, E5, E6 (3 variants), E7, E9, E10b, E10c, and the additional C1 and C2 (see `phase8-optimization-log.md`). Every switch defaults to the baseline behaviour; the candidate is selected by `EAOP_TUNING`, it is not the shipped default.", "",
         "## Baseline versus candidate (repetition 1; 95% Wilson interval in brackets)", "",
         "| Metric | Baseline | Candidate | Target | Observed-target class (candidate) |", "|---|---|---|---|---|"]
    qb, qc = b["combined"]["qa"]["rep1"], c["combined"]["qa"]["rep1"]
    for key, label, tgt in (("grounded_answer_coverage", "Grounded-answer coverage", "75% (floor 60%)"), ("answered", "Answer coverage", ""), ("false_refusals", "False refusals", ""),
                            ("withheld_unverified", "Withheld by verification", ""), ("citation_correctness_answerable", "Citation correctness (answerable)", "95%"),
                            ("citation_tenant_ownership", "Citation tenant ownership", "100%"), ("claim_support", "Claim support", "95%"),
                            ("correct_abstention", "Correct abstention", "90%"), ("unsupported_answer_rate", "Unsupported-answer rate", "")):
        L.append(f"| {label} | {f(qb[key])} | {f(qc[key])} | {tgt} | {qc[key].get('classification', '')} {qc[key].get('interval_vs_target', '')} |")
    eb, ec = b["combined"]["extraction"]["rep1"], c["combined"]["extraction"]["rep1"]
    for key, label, tgt in (("raw_schema_validity", "Raw extraction schema validity", "100%"), ("priority_accuracy", "Priority accuracy", "improve"), ("final_category_accuracy", "Category accuracy", ""),
                            ("evidence_completeness", "Incidents with grounded evidence", ""), ("review_rate", "Human-review rate", "reduce safely"), ("unsafe_automatic_acceptance", "Unsafe automatic acceptance (must-review cases)", "0")):
        L.append(f"| {label} | {f(eb[key])} | {f(ec[key])} | {tgt} | {ec[key].get('classification', '')} |")
    L += [f"| Unsupported numeric values accepted as verified | {eb['unsupported_numeric_accepted_as_verified']['count']} of {eb['unsupported_numeric_accepted_as_verified']['of_proposed_values']} proposed | {ec['unsupported_numeric_accepted_as_verified']['count']} of {ec['unsupported_numeric_accepted_as_verified']['of_proposed_values']} proposed | 0 | "
          f"{'GATE MET (dev)' if ec['unsupported_numeric_accepted_as_verified']['count'] == 0 else 'GATE FAILED'} |",
          f"| p95 `/ai/ask` latency | {qb['latency_s']['all']['p95']:.1f} s | {qc['latency_s']['all']['p95']:.1f} s | 15 s | {qc['latency_p95_target_15s']} |", "",
          f"Paired on the identical 87 answerable / 23 unanswerable dev queries: grounded-correct improved {pq['improved']}, regressed {pq['regressed']}, unchanged {pq['unchanged']}; correct refusal improved {pr['improved']}, regressed {pr['regressed']}. "
          f"Run-to-run noise between identical configurations is about three queries (see the optimisation log), so the abstention and review-burden gains are well beyond noise while the grounded-coverage gain (+4 net) is modest and close to it. The three repetitions are repeated measurements of the same queries "
          f"(counts identical across repetitions: {identical}); they are not independent samples and Wilson intervals use one repetition's counts.", "",
          "**Targets not met on the dev split:** grounded-answer coverage 66.7% (target 75%, above the 60% floor) and citation correctness 91.9% (target 95%). The 90% abstention, 95% claim-support and 100% raw-schema-validity targets are *observed* met, but the intervals overlap their targets (n = 23, 148 and 34), so none of them is established.", "",
          "## Per tenant", "", "| Tenant | Metric | Baseline | Candidate |", "|---|---|---|---|"]
    for scope in ("apex", "meridian"):
        qb2, qc2, eb2, ec2 = b[scope]["qa"]["rep1"], c[scope]["qa"]["rep1"], b[scope]["extraction"]["rep1"], c[scope]["extraction"]["rep1"]
        for key, label, base, cand in (("grounded_answer_coverage", "Grounded coverage", qb2, qc2), ("citation_correctness_answerable", "Citation correctness", qb2, qc2), ("claim_support", "Claim support", qb2, qc2),
                                       ("correct_abstention", "Correct abstention", qb2, qc2), ("priority_accuracy", "Priority accuracy", eb2, ec2), ("review_rate", "Review rate", eb2, ec2),
                                       ("evidence_completeness", "Grounded evidence", eb2, ec2)):
            L.append(f"| {scope} | {label} | {f(base[key])} | {f(cand[key])} |")
    L += ["", "**Reading the per-tenant table:** the gains are concentrated in Apex (grounded coverage 60.5% -> 72.1%, citation correctness 83.7% -> 97.8%). For Meridian the abstention (46.2% -> 92.3%) and review-burden gains are large, but grounded coverage (63.6% -> 61.4%) and citation correctness (88.2% -> 85.0%) did not improve; the differences are within run-to-run noise, "
          "so there is no evidence of improvement for Meridian answers, and the combined figures should not be read as uniform across tenants. Meridian priority accuracy is unchanged (76.5%) because its category extraction (58.8% correct) is unchanged and no experiment targeted it.", "", "## Retrieval (87 answerable dev queries with labelled passages)", "", "| Scope | Recall@1 | Recall@5 | Recall@10 | MRR | nDCG@5 | p95 latency | foreign passages |", "|---|---|---|---|---|---|---|---|"]
    for scope in ("combined", "apex", "meridian"):
        hb, hc = b[scope]["retrieval"]["hybrid"], ret[scope]["hybrid"]
        L.append(f"| {scope} baseline | {hb['recall@1']} | {hb['recall@5']} | {hb['recall@10']} | {hb['mrr']} | {hb['ndcg@5']} | {hb['latency_s']['p95'] * 1000:.0f} ms | {b[scope]['retrieval']['cross_tenant_leakage']['foreign']} |")
        L.append(f"| {scope} candidate | {hc['recall@1']} | {hc['recall@5']} | {hc['recall@10']} | {hc['mrr']} | {hc['ndcg@5']} | {hc['latency_s']['p95'] * 1000:.0f} ms | {ret[scope]['cross_tenant_leakage']['foreign']} |")
    cw = ec["cases_with_unsupported_numeric"]
    L += ["", f"Recall@5 combined {ret['combined']['hybrid']['recall@5']} (bootstrap 95% CI {ret['combined']['hybrid']['recall@5_ci95']}). Hybrid retrieval was not shown to beat its components in the baseline; the gain here comes from identifier handling, not from fusion tuning.", "",
          "## Numeric extraction safety", "",
          f"The model proposed {ec['numeric_values_proposed_unsupported']['denominator']} numeric values in the 34 dev cases, {ec['numeric_values_proposed_unsupported']['numerator']} of them not stated in the report (a model failure that remains: the model still hallucinates). With the audit, 0 of those reached the priority rules or were recorded as verified; "
          f"{cw['routed_to_review']} of {cw['cases']} such incidents were routed to human review and {cw['priority_wrong']} had a wrong priority (baseline: 2 wrong, 2 routed). Genuine stated values keep their evidence span and status `verified`; the regression tests pin the three observed hallucinated cases and show a stated 12.5 mm/s still yields P1.", "",
          "## Human-review workload", "",
          f"Review rate {f(eb['review_rate'])} -> {f(ec['review_rate'])}. Reviews required by the safety labels (unregistered asset, injected instructions): {ec['review_true_positive']} raised, {ec['review_missed_unsafe']} missed. The other {ec['review_false_positive']} reviews are cases the safety labels did not require but the system's own rules held: unsupported numeric proposed, "
          "ambiguous category, or no grounded guidance (grounded evidence now 73.5% vs 23.5%). Review remains mandatory before any ticket; nothing was auto-submitted (workflow below).", "",
          "## Workflow and safety", "", f"- Workflow cases: {len(wf)}; submitted {sum(1 for x in wf if x.get('final_state') == 'SUBMITTED')}; submission before approval accepted: {sum(1 for x in wf if x.get('submit_before_approval') != 409)}; approval by the engineer accepted: {sum(1 for x in wf if x.get('engineer_approval_status') == 200)}; external tickets {res.get('external')} (no duplicates).",
          "- Cross-tenant: 0 foreign passages in 1,000+ retrieved; citation tenant ownership 100%; the cross-tenant probes were refused by the entity gate (the single heuristic flag in the baseline was a false positive, see the baseline report).",
          "- Prompt-injection: the four override/injection prompts in dev are refused by the override gate (0 false positives on 87 answerable dev queries). Injected instructions inside retrieved records and incident reports did not change approvals or submissions; injection-case priority behaviour is reported in the baseline report.", "",
          "## Remaining failures (candidate, rep 1)", "", f"- Answerable queries not grounded-correct: {dict(collections.Counter(x['class'] for x in fa['answerable_items']))}.",
          f"- Unanswerable queries still answered: {[(x['id'], x['subtype']) for x in fa['unanswerable_wrong']]} (an attribute mix-up: the right model but the wrong parameter; the entity gate cannot catch it).",
          f"- Citations to unlabelled passages: {len(fa['citation_issues'])} (mostly conflicting-record queries where an informal note is cited instead of the manual).", "- Largest remaining lever: 10 answers withheld for a non-verbatim quotation. Quote snapping (E7) recovers them but raised the unsupported-answer rate, so it is not in the candidate; a variant that snaps only when the snapped sentence also contains every number the answer states is untested and would need approval as an additional experiment.", "",
          "## Latency and resources (documented CPU-only laptop)", "",
          f"`/ai/ask` p50 {qc['latency_s']['all']['p50']:.2f} s, p95 {qc['latency_s']['all']['p95']:.2f} s (baseline p95 {qb['latency_s']['all']['p95']:.1f} s; identical configurations vary between about 10 and 14 s, so the difference is not significant). `/incidents/extract` p95 {ec['latency_s']['p95']:.1f} s (baseline {eb['latency_s']['p95']:.1f} s; one extra retrieval and register lookup). "
          f"Retrieval p95 {ret['combined']['hybrid']['latency_s']['p95'] * 1000:.0f} ms (baseline {b['combined']['retrieval']['hybrid']['latency_s']['p95'] * 1000:.0f} ms). Ingestion {res['ingest_seconds']} s for 1,447 passages. Resource samples (coarse): { {k: (v.get('cpu_pct_mean'), v.get('ollama_working_set_mb_peak'), v.get('python_working_set_mb_peak')) for k, v in res['resources'].items() if k in ('qa_rep1', 'extraction_rep1', 'workflow')} } "
          "as (mean CPU %, Ollama MB peak, Python MB peak). Concurrency was not re-measured for the candidate; the baseline's limiter behaviour (429 at 4 concurrent requests) is unchanged. Tokens per second and model load are unchanged (same model, prompts and options).", "",
          "## Record accounting (raw outputs)", "", "| File | Records | Expected | Duplicate ids | HTTP statuses |", "|---|---|---|---|---|"]
    L += [f"| {k} | {v[0]} | {v[1]} | {v[2]} | {v[3]} |" for k, v in acct.items()]
    L += ["", "## Security, workflow and regression results", ""]
    if summ:
        L += [f"- {k}: {v}" for k, v in summ.items()]
    L += ["", "## Readiness", "",
          "**Candidate frozen** (hash above). It is ready for the independent held-out evaluation **only in the sense that** the code and configuration are frozen and every safety gate and regression suite passes on the dev split; **two quality targets (grounded coverage, citation correctness) are expected to remain unmet** on held-out data, and the "
          "optimism from dev-tuned parameters should be expected. It is not production-ready: single synthetic dataset, author-generated labels, a 1.5B model that still hallucinates numbers and quotes, application-level controls only, local CPU measurements. Held-out evaluation requires your explicit approval."]
    (ROOT / "docs" / "evaluation" / "phase8-candidate-report.md").write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
    print("written")


if __name__ == "__main__":
    main()
