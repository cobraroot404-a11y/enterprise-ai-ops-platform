"""Draw a stratified, seeded sample of about 30 labels for independent human review and write it as a reviewer worksheet.

    python evaluation/phase8/make_review_sample.py

Strata: tenant x answerable/unanswerable x difficulty, with extra weight on hard retrieval cases. The worksheet shows the query, the labelled
evidence passages and the required facts so a reviewer can mark each label correct / incorrect / ambiguous. No reviewer has been assigned.
"""
import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DS = ROOT / "evaluation" / "datasets" / "eval-v2"
OUT = ROOT / "docs" / "evaluation" / "phase8-label-review-sample.md"


def load(name):
    return [json.loads(x) for x in (DS / name).read_text(encoding="utf-8").splitlines() if x.strip()]


def main():
    queries, passages = load("queries.jsonl"), load("passages.jsonl")
    text = {(p["tenant"], p["file"], p["unit"]): p["text"] for p in passages if p["current"]}
    strata = defaultdict(list)
    for q in queries:
        strata[(q["tenant"], q["answerable"], q["difficulty"] == "hard")].append(q)
    rng = random.Random(20261111)
    picked = []
    for key in sorted(strata, key=str):
        pool = strata[key][:]
        rng.shuffle(pool)
        picked += pool[:4 if key[2] else 3]
    rng.shuffle(picked)
    picked = sorted(picked[:30], key=lambda q: q["id"])
    lines = ["# Label review worksheet (eval-v2, stratified sample)", "",
             "For independent human review. For each item mark: **Label correct / incorrect / ambiguous**, and note any disagreement. Labels were written by the dataset author before any model run; "
             "no independent reviewer has reviewed them yet. Disagreements will be adjudicated and recorded, not silently fixed.", ""]
    for q in picked:
        lines += [f"## {q['id']} ({q['tenant']}, {q['category']}, {'answerable' if q['answerable'] else 'unanswerable'})", "", f"- **Query:** {q['query']}",
                  f"- **Required facts:** {', '.join(q['required_facts']) or '-'}", f"- **Forbidden facts:** {', '.join(q['forbidden_facts']) or '-'}",
                  f"- **Expected refusal:** {q['expected_refusal']}"]
        for r in q["relevant"]:
            lines.append(f"- **Labelled evidence (grade {r['grade']}) `{r['file']}#{r['unit']}`:** {text.get((q['tenant'], r['file'], r['unit']), '(missing)')[:400]}")
        lines += ["- **Reviewer verdict:** [ ] correct  [ ] incorrect  [ ] ambiguous   Notes:", ""]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(picked)} items -> {OUT}")


if __name__ == "__main__":
    main()
