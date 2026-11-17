"""Generate docs/evaluation/phase8-optimization-log.md from the preserved experiment run directories.

    python evaluation/phase8/make_optimization_log.py

Every number is read from the raw outputs through score_experiment/score_baseline; the verdicts and rationales below are the engineering decisions recorded
before the integrated candidate was built (they cite the numbers they rest on). Dev split only; nothing here touches the held-out splits.
"""
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evaluation" / "phase8"))
import score_experiment as se  # noqa: E402

R = ROOT / "evaluation" / "reports" / "phase8"
BASE = R / "baseline-20261112T035539Z"


def run(prefix):
    return sorted(glob.glob(str(R / f"exp-{prefix}-*")))[-1]


def qa(d):
    return se.score_dir(d)["scopes"]["combined"]["qa"]["rep1"]


def ext(d):
    return se.score_dir(d)["scopes"]["combined"]["extraction"]["rep1"]


def f(p):
    return f"{p['numerator']}/{p['denominator']} ({100 * p['value']:.1f}%)" if p["value"] is not None else "N/A"


def main():
    base_qa = qa(BASE)
    rstar_qa = qa(run("RSTAR"))
    retr = json.loads(Path(run("RETR-SWEEP") + "/retrieval_scores.json").read_text(encoding="utf-8"))
    e1 = json.loads(Path(run("E1") + "/retrieval_scores.json").read_text(encoding="utf-8"))

    def rr(name, src=retr):
        h = src[name]["combined"]["hybrid"]
        return f"R@1 {h['recall@1']:.3f}, R@5 {h['recall@5']:.3f}, MRR {h['mrr']:.3f}, nDCG@5 {h['ndcg@5']:.3f}, p95 {h['latency_s']['p95'] * 1000:.0f} ms"

    def row(title, d, ref_qa, label):
        q = qa(d)
        pq = se.paired(ref_qa["per_query"], q["per_query"], "gc")
        pc = se.paired(ref_qa["per_query"], q["per_query"], "cr")
        return (f"| {title} | {f(q['grounded_answer_coverage'])} | {f(q['citation_correctness_answerable'])} | {f(q['claim_support'])} | {f(q['correct_abstention'])} | "
                f"{f(q['false_refusals'])} | {q['withheld_unverified']['numerator']} | {f(q['unsupported_answer_rate'])} | {q['latency_s']['all']['p95']:.1f} | "
                f"gc +{pq['improved']}/-{pq['regressed']}; refusal +{pc['improved']}/-{pc['regressed']} vs {label} |")

    L = ["# Phase 8 optimisation log (development split only)", "",
         "Baseline `baseline-20261112T035539Z`; defaults regression `exp-B0` (identical to the baseline on every metric and every query); accepted retrieval reference `exp-RSTAR` (E3 only). All runs, successful or not, are preserved under `evaluation/reports/phase8/exp-*`. "
         "Held-out test and challenge splits were never run or inspected. No model was downloaded.", "",
         "## Run-to-run noise (measured, not assumed)",
         "Two identical runs of the reference configuration (`RSTAR`, `RSTAR2`) differ in about 14% of answer texts (16 of 118) and in 4 of 118 grounded flags; paired grounded-correct changes were +1 / -1. A second pair with a deterministic ranking tie-break (`DET1`, `DET2`) was no better "
         "(12 of 118 answer texts differ), so that switch (C2) has no effect and is rejected. Three repetitions inside one run are identical. **Paired changes of about three queries or fewer are therefore treated as noise.** p95 latency of identical configurations varies between about 10.3 and 13.6 s.", "",
         "## Retrieval experiments (87 answerable dev queries with labelled passages; no model calls)", "",
         "| Experiment | Configuration | Result | Decision |", "|---|---|---|---|",
         f"| baseline | hybrid, RRF k=60 | {rr('default')} | reference |",
         f"| E1 index text with document context | embed `<kind> <file name>: <text>` | alone: {rr('E1_prefix', e1)}; with E3: {rr('E1_prefix_E3', e1)} | **REJECT**: +1.5 points R@5 alone (one query), nothing on top of E3, and a re-embedding of the whole corpus; stored text and quotes were unchanged |",
         f"| E2 fusion weights / RRF constant | k in {{20,100}}, text weight 0.5-2.0, vector weight 1.5 | best single change `w_text=0.5`: {rr('E2_wt0.5')} | **REJECT**: modest; its benefit is subsumed by E3 |",
         f"| E3 identifier handling | boost passages naming query identifiers (assets resolved to models via the register); boost 0.005-0.05 | boost 0.02: {rr('E3_b0.02')} (0.05 identical) | **ACCEPT** (boost 0.02): R@1 +0.245, R@5 +0.054, nDCG@5 +0.145, no foreign passages, p95 +15 ms |",
         f"| E4 rule-based question splitting | split multi-part questions, carry identifiers, fuse | {rr('E4_split')}; with E3: {rr('E3b0.02_E4')} | **REJECT**: no gain; p95 105 ms |",
         f"| E9 feature reranker (existing MiniLM + lexical features, no new weights) | 7 weight sets fitted on dev; top 20 | best {rr('E9_w1')}; with E3: {rr('E3b0.02_E9w1')} | **REJECT**: equals E3 alone (+0.4 point R@5 is one query) with more machinery |", "",
         "Remaining retrieval weakness: multi-hop queries (three relevant passages) reach recall@5 of about 0.67; conflicting-record queries 0.8.", "",
         "## Generation and abstention experiments (QA over 118 dev queries, reference = E3 alone unless stated)", "",
         "| Experiment | Grounded coverage | Citation correctness | Claim support | Correct abstention | False refusals | Withheld | Unsupported-answer rate | p95 s | Paired change |", "|---|---|---|---|---|---|---|---|---|---|",
         "| baseline | " + " | ".join([f(base_qa['grounded_answer_coverage']), f(base_qa['citation_correctness_answerable']), f(base_qa['claim_support']), f(base_qa['correct_abstention']),
                                      f(base_qa['false_refusals']), str(base_qa['withheld_unverified']['numerator']), f(base_qa['unsupported_answer_rate']), f"{base_qa['latency_s']['all']['p95']:.1f}"]) + " | - |",
         row("R* = E3", run("RSTAR"), base_qa, "baseline"),
         row("C1 citation marker formats", run("C1"), rstar_qa, "R*"),
         row("E5a diverse context (k=4)", run("E5a"), rstar_qa, "R*"),
         row("E5b diverse context (k=6)", run("E5b"), rstar_qa, "R*"),
         row("E6 prompt v4 (numbers verbatim)", run("E6v4"), rstar_qa, "R*"),
         row("E6 prompt v5 (+ one sentence per citation)", run("E6v5"), rstar_qa, "R*"),
         row("E6 prompt v6 (v5 without the worked example)", run("E6v6"), rstar_qa, "R*"),
         row("E7 quote snap", run("E7"), rstar_qa, "R*"),
         row("E8 entity gate", run("E8"), rstar_qa, "R*"),
         row("E8 + E8b override gate", run("E8b"), rstar_qa, "R*"),
         row("E8 + E8b + C3 citation completion", run("C3"), qa(run("E8b")), "E8+E8b"),
         row("E8 + E8b + C3 + E7", run("C3E7"), qa(run("C3")), "E8+E8b+C3"), "",
         "Decisions and reasons:", "",
         "- **E5 (context assembly): REJECT.** Diverse context lowers or does not change grounded coverage (k=4: paired +2/-5; k=6: +3/-4, within noise); claim support rises but answered volume falls.",
         "- **E6 (prompt wording): REJECT all three.** v4 +2/-5, v5 +4/-9 with citation correctness 81.9%, v6 (no worked example) collapses to 31% coverage (54 of 87 answers withheld). The validated prompt stays.",
         "- **E7 (quote snap): REJECT.** Alone +3/-1 (noise) with claim support falling to 93.5%; on top of C3 it raises coverage to 70.1% but the unsupported-answer rate rises from 16.7% to 23.4% and claim support falls to 94.97%: that trades verification for coverage, which is not allowed.",
         "- **E8 entity gate: ACCEPT.** Refuses when an identifier named in the question is absent from every cited passage (the sibling-model failure that explained 7 of the 9 wrongly answered unanswerable questions and 10 wrong-passage citations). Correct abstention 69.6% -> 87.0%, paired +4/-0, no false refusals.",
         "- **E8b override gate: ACCEPT** (abstention work, an addition to E8 recorded as such). Refuses questions that try to override the evidence, tenant or approval rules; 0 false positives on the 87 answerable dev queries; correct abstention 95.7% (22 of 23), paired +6/-0. The patterns are generic phrases; the held-out split contains different wordings, so this result is a development observation.",
         "- **C1 (citation marker formats): REJECT.** The diagnosis was right (6 withheld procedure answers cited `[1-3]`) but recovering them exposed citations to unlabelled passages: citation correctness fell from 89.0% to 77.6% with no coverage gain.",
         "- **C3 (citation completion, evidence-driven, added after diagnosis; not one of E1-E10): ACCEPT.** The answer states a value found in another retrieved passage that the model did not cite; the passage is attached with a verbatim sentence only if it contains the value and names a question entity. Withheld 23 -> 16, answered 64 -> 71, unsupported-answer rate unchanged (16.7%), claim support 97.3%.",
         "- **C2 (stable ranking tie-break): REJECT** (no effect on repeatability, see noise section).", "",
         "## Incident extraction experiments (34 dev cases, reference = E3 alone)", "",
         "| Experiment | Priority accuracy | Review rate | Evidence completeness | Unsupported numerics accepted | Hallucination cases routed to review | Must-review cases missed | Unsafe automatic acceptance |", "|---|---|---|---|---|---|---|---|"]
    for title, d in (("baseline", BASE), ("R* = E3", run("RSTAR")), ("E10a numeric verification", run("E10a")), ("E10b category cross-check", run("E10b")),
                     ("E10c guidance query with model id", run("E10c")), ("E10d guidance query with asset name", run("E10d")),
                     ("E10e = E10a + E10d", run("E10e")), ("E10 all (a+b+c)", run("E10all"))):
        e = ext(d)
        cw = e["cases_with_unsupported_numeric"]
        L.append(f"| {title} | {f(e['priority_accuracy'])} | {f(e['review_rate'])} | {f(e['evidence_completeness'])} | {e['unsupported_numeric_accepted_as_verified']['count']} of {e['unsupported_numeric_accepted_as_verified']['of_proposed_values']} proposed | "
                 f"{cw['routed_to_review']} of {cw['cases']} | {e['review_missed_unsafe']} | {f(e['unsafe_automatic_acceptance'])} |")
    L += ["",
          "- **Numeric verification (priority 1, E10a): ACCEPT.** Values not stated in the report are dropped from the rule inputs, preserved with status `unsupported` on the record, and the incident is routed to review. Accepted-unsupported numerics 3 -> 0, priority accuracy 82.4% -> 88.2% (Apex 100%), genuine values and genuine P1 incidents unchanged.",
          "- **E10b category cross-check: REJECT** as a burden reducer: it only adds reviews (79.4% -> 85.3%) with no accuracy gain.",
          "- **E10c guidance query with the model id: REJECT.** Evidence completeness unchanged (8/34): guidance lives in family-level troubleshooting pages that do not name models.",
          "- **E10d guidance query with the asset's register name (equipment family) - refinement of E10c after the guidance diagnosis: ACCEPT only together with numeric verification.** Diagnosis (`diagnosis-guidance-*`): 24 of 34 guidance retrievals were below the evidence gate because the query ignored the equipment. E10d lifts evidence completeness to 73.5% and cuts the review rate to 32.4% with 0 must-review cases missed, "
          "but without numeric verification one hallucination-driven P1 incident was no longer held for review (2 of 3 routed instead of the previous 2 of 3 for the wrong reason): the two changes are interdependent. E10e (both) routes 3 of 3 to review.", "",
          "## Integrated candidate", "",
          "See `phase8-candidate-report.md`: configuration `evaluation/phase8/configs/candidate_v1.json` (E3 boost 0.02, E8 entity gate, E8b override gate, C3 citation completion, numeric verification, asset-context guidance query)."]
    (ROOT / "docs" / "evaluation" / "phase8-optimization-log.md").write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
    print("written")


if __name__ == "__main__":
    main()
