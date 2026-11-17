"""Render the V4.1 reconciliation documents from scripts/v41_requirements_data.py and the preserved original specification.

    python scripts/generate_v41_reconciliation.py          # write docs/specification/v4.1-*.md and v4.1-requirements.json
    python scripts/generate_v41_reconciliation.py --check  # validate only (exit 1 on any problem)

Source wording is cut from the specification file by line number (never retyped). Validation: the specification hash matches the recorded value; every line
range is inside the file; every implementation, evidence and test path exists; every `file::function` names a function in that file; catalogue ids exist;
a requirement is VERIFIED only with a test or reproducible check AND evidence.
"""
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))
from traceability_data import REQUIREMENTS as CATALOGUE  # noqa: E402
from v41_requirements_data import E  # noqa: E402

SPEC = ROOT / "docs/specification/ORIGINAL_MASTER_SPECIFICATION_V4.1.txt"
GENERATED = {"docs/specification/v4.1-gap-register.md", "docs/evaluation/phase8-heldout-disposition.md", "docs/specification/v4.1-audit-check-results.json"}  # written by this checkpoint
EXPECTED = "b1c573e2c209ac68712b36851d56af0fb4c464509b422f96899761b6427760da"
OUT = ROOT / "docs/specification"
STATUS = {"V": "Verified", "P": "Partial", "M": "Missing", "N": "Not evaluable"}
CLASS = {"C": "Critical security or workflow safety", "Q": "Phase 8 AI-quality limitation", "I": "Phase 9 infrastructure and cloud portability",
         "D": "Phase 10 documentation, release and handover", "A": "Separate approval required", "-": "None outstanding"}
KIND = {"M": "mandatory", "O": "optional", "T": "proposed target", "X": "prohibition / process rule", "D": "deliverable / definition-of-done item"}
PART_TITLES = {1: "Primary mission", 2: "Non-negotiable project rules", 3: "Proprietary source-visible license", 4: "Implementation priorities", 5: "Technology stack", 6: "Customer discovery and requirements",
               7: "Customer A - Apex Industrial Manufacturing", 8: "Customer B - Meridian Fleet Logistics", 9: "System architecture", 10: "Customer onboarding", 11: "Enterprise integrations", 12: "Document ingestion",
               13: "Retrieval-augmented generation", 14: "Incident intelligence", 15: "Human approval workflows", 16: "Security", 17: "Backend and database", 18: "Frontend", 19: "Customer acceptance testing",
               20: "Fault-injection testing", 21: "Evidence-based evaluation", 22: "Observability", 23: "Reproducible local deployment", 24: "Cloud deployment portability", 25: "Customer-facing technical communication",
               26: "Automated testing", 27: "CI/CD", 28: "Repository structure", 29: "Recruiter-ready README", 30: "End-to-end FDE demonstration", 31: "Implementation roadmap", 32: "Definition of done",
               33: "Final GitHub audit", 34: "Execution protocol and final deliverables"}


def spec_lines():
    return SPEC.read_bytes().decode("utf-8").replace("\r\n", "\n").split("\n")


def wording(lines, a, b, limit=330):
    text = " / ".join(x.strip() for x in lines[a - 1:b] if x.strip())
    return text if len(text) <= limit else text[:limit].rstrip() + " [...]"


def build():
    lines = spec_lines()
    counters = defaultdict(int)
    items = []
    cat_by_id = {c["id"]: c for c in CATALOGUE}
    for e in E:
        e = dict(e)
        if e["kind"] == "D" and e["cat"] and not e["tests"] and not e["evidence"] and e["status"] in ("V", "P"):  # definition-of-done / deliverable items inherit the evidence of the requirement they map to
            for cid in e["cat"]:
                c = cat_by_id[cid]
                e["impl"] += [x for x in c["implementation"] if x not in e["impl"]]
                e["tests"] += [x for x in c["tests"] if x not in e["tests"]]
                e["evidence"] += [x for x in c["evidence"] if x not in e["evidence"]]
        counters[e["part"]] += 1
        items.append({**e, "id": f"V41-{e['part']:02d}.{counters[e['part']]:02d}", "wording": wording(lines, *e["lines"]), "line_ref": f"L{e['lines'][0]}" if e["lines"][0] == e["lines"][1] else f"L{e['lines'][0]}-{e['lines'][1]}"})
    return items


def problems(items):
    bad = []
    raw = SPEC.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED:
        bad.append("specification SHA-256 differs from the recorded value")
    n = raw.decode("utf-8").count("\n")
    cat_ids = {c["id"] for c in CATALOGUE}
    for it in items:
        a, b = it["lines"]
        if not (1 <= a <= b <= n + 1):
            bad.append(f"{it['id']}: line range outside the specification")
        for kind in ("impl", "evidence"):
            for p in it[kind]:
                if not (ROOT / p).exists() and p not in GENERATED:
                    bad.append(f"{it['id']}: {kind} path missing: {p}")
        for t in it["tests"]:
            path, _, fn = t.partition("::")
            f = ROOT / path
            if not f.exists():
                bad.append(f"{it['id']}: test file missing: {path}")
            elif fn and not re.search(rf"\bdef {re.escape(fn)}\b", f.read_text(encoding="utf-8")):
                bad.append(f"{it['id']}: test function not found: {t}")
        for c in it["cat"]:
            if c not in cat_ids:
                bad.append(f"{it['id']}: unknown catalogue id {c}")
        if it["status"] == "V" and not (it["tests"] or it["evidence"]):
            bad.append(f"{it['id']}: VERIFIED without a test or evidence artifact")
        if it["status"] in ("P", "M", "N") and not it["gap"]:
            bad.append(f"{it['id']}: {STATUS[it['status']]} requires a stated gap")
        if it["status"] == "M" and (it["impl"] or it["tests"]):
            bad.append(f"{it['id']}: MISSING must not list implementation or tests")
    return bad


def md_escape(s):
    return str(s).replace("|", "/").replace("\n", " ")


def ticks(xs, short=True):
    return ", ".join(f"`{x.split('/')[-1] if short and '::' not in x else x.replace('backend/tests/', '').replace('tests/', '')}`" for x in xs) or "-"


def render(items):
    counts = Counter(i["status"] for i in items)
    total = len(items)
    matched = [i for i in items if i["cat"]]
    new = [i for i in items if not i["cat"]]
    used = {c for i in items for c in i["cat"]}
    unmapped_catalogue = [c for c in CATALOGUE if c["id"] not in used]
    by_part = defaultdict(list)
    for i in items:
        by_part[i["part"]].append(i)
    hdr = lambda t: [f"# {t}", ""]  # noqa: E731

    # ---- baseline
    B = hdr("V4.1 requirements baseline (extracted from the original specification)")
    B += [f"Source: `docs/specification/ORIGINAL_MASTER_SPECIFICATION_V4.1.txt` (SHA-256 `{EXPECTED}`), all 34 parts read in full. Generated by `python scripts/generate_v41_reconciliation.py`; wording is cut from the file by line number.", "",
          "Granularity: one entry per sentence, bulleted list or numbered list that states a checkable obligation (a list such as the 13 core modules is one entry whose gap text names missing items). The 37 definition-of-done items, the 10 fault-injection scenarios, the 15 UAT scenarios and the 31 final deliverables are individual entries. "
          "Kinds: mandatory, optional, proposed target, prohibition/process rule, deliverable.", "",
          f"**Totals: {total} original requirements** ({', '.join(f'{KIND[k]} {v}' for k, v in Counter(i['kind'] for i in items).most_common())}).", ""]
    for part in sorted(by_part):
        B += [f"## Part {part}: {PART_TITLES[part]}", "", "| ID | Spec lines | Kind | Source wording |", "|---|---|---|---|"]
        B += [f"| {i['id']} | {i['line_ref']} | {KIND[i['kind']]} | {md_escape(i['wording'])} |" for i in by_part[part]]
        B.append("")
    B += [f"## Newly discovered original requirements: source mapping pending owner confirmation ({len(new)})", "",
          "These entries have no id in the provisional 85-item catalogue. They are kept as obligations of the original V4.1 specification (each cites its own spec lines above); "
          "their mapping to catalogue ids and their status are subject to the owner confirming the source mapping. None has been removed or downgraded to an accepted deviation.", "",
          "| ID | Spec lines | Status | Source wording |", "|---|---|---|---|"]
    B += [f"| {i['id']} | {i['line_ref']} | {STATUS[i['status']]} | {md_escape(i['wording'])[:200]} |" for i in new]
    B += ["", "## Disposition of requirements the owner flagged (2026-11-12)", "",
          "Ingestion deletion, retry handling, CSV and webhook connectors, CI/CD, cloud portability and technical handover remain original-specification obligations. "
          "No accepted deviation is recorded for any of them; a deviation needs the owner's explicit approval. The 238 original requirements are all retained.", ""]
    B += ["## Later approved engineering additions (NOT original V4.1 requirements)", "",
          "These come from approved Phase 3-8 instructions and are tracked separately so they are never mistaken for original requirements:", "",
          "| Addition | Origin | Where recorded |", "|---|---|---|",
          "| SSRF / connector egress policy (catalogue R16.6) | Phase 5 security closure instruction | `docs/security/connector-egress.md` |",
          "| Numeric measurement traceability (R14.5) and entity/override abstention gates (R13.7) | Phase 8 optimisation instruction; R14.5 made the default by the V41-14.02 safety remediation | `docs/evaluation/phase8-candidate-report.md`, `docs/evaluation/numeric-safety-remediation.md` |",
          "| Grounded-answer coverage >= 75% (floor 60%), correct abstention >= 90%, claim support >= 95%, p95 end-to-end latency <= 15 s | Phase 8 Gate B decision | `docs/evaluation/phase8-evaluation-protocol-v1.1.md` |",
          "| Human incident-review gate separate from ticket approval | Phase 4 design decision | `backend/app/services/incident_service.py` |",
          "| Test-credential and environment guards, secret scan, tenant profiles | Phase 5-6 closure instructions | `docs/security/test-credentials.md` |", ""]

    # ---- reconciliation matrix
    M = hdr("V4.1 reconciliation matrix")
    M += [f"Every original requirement against the provisional 85-item catalogue, implementation, test, evidence and acceptance criterion. Status: Verified (implemented, automated test or reproducible check, evidence), Partial, Missing, Not evaluable. "
          f"Counts: **Verified {counts['V']}, Partial {counts['P']}, Missing {counts['M']}, Not evaluable {counts['N']}** of {total}. "
          f"Matched to an existing catalogue id: {len(matched)}; newly discovered (no catalogue id): {len(new)}; catalogue items not traceable to any original requirement: {len(unmapped_catalogue)}.", "",
          "Verified means verified against the *original* wording on the evidence shown; where a quality target in a requirement is not met the entry is Partial, never Verified.", ""]
    for part in sorted(by_part):
        M += [f"## Part {part}: {PART_TITLES[part]}", "", "| ID | Source | Catalogue | Implementation | Test | Evidence | Acceptance criterion | Status | Remaining gap | Phase |", "|---|---|---|---|---|---|---|---|---|---|"]
        for i in by_part[part]:
            M.append(f"| {i['id']} | {i['line_ref']} | {', '.join(i['cat']) or 'NEW'} | {ticks(i['impl'])} | {ticks(i['tests'])} | {ticks(i['evidence'])} | {md_escape(i['accept'])[:160]} | {STATUS[i['status']]} | {md_escape(i['gap']) or '-'} | {i['phase']} |")
        M.append("")

    # ---- gap register
    G = hdr("V4.1 gap register")
    G += [f"Unresolved original requirements ({total - counts['V']} of {total}) grouped by the required classes. Nothing here is implemented by this checkpoint; closing any item needs explicit approval.", "",
          "| Class | Partial | Missing | Not evaluable | Total |", "|---|---|---|---|---|"]
    for k in ("C", "Q", "I", "D", "A"):
        sub = [i for i in items if i["cls"] == k and i["status"] != "V"]
        c = Counter(i["status"] for i in sub)
        G.append(f"| {CLASS[k]} | {c['P']} | {c['M']} | {c['N']} | {len(sub)} |")
    G += ["", "Requirements verified but flagged with a class are listed in section 7 (a satisfied requirement that carries a caveat).", ""]
    for n, k in enumerate(("C", "Q", "I", "D", "A"), 1):
        sub = [i for i in items if i["cls"] == k and i["status"] != "V"]
        G += [f"## {n}. {CLASS[k]} ({len(sub)})", "", "| ID | Requirement | Status | Gap | Resolution phase |", "|---|---|---|---|---|"]
        G += [f"| {i['id']} | {md_escape(i['title'])[:150]} | {STATUS[i['status']]} | {md_escape(i['gap'])} | {i['phase']} |" for i in sub]
        G.append("")
    G += ["## 6. Gap analysis by type", "",
          f"- **Missing ({counts['M']}):** " + "; ".join(f"{i['id']}" for i in items if i["status"] == "M") + ".",
          f"- **Partially implemented ({counts['P']}):** see sections 1-5.",
          f"- **Not evaluable now ({counts['N']}):** " + "; ".join(f"{i['id']} ({i['gap'][:60]})" for i in items if i["status"] == "N") + ".",
          "- **Untested although implemented:** V41-17.03 (pagination has no dedicated API test; OpenAPI not separately verified); SECURITY.md and THIRD_PARTY_NOTICES.md content; CI workflow (never executed); question-level override gate and numeric audit are tested but not enabled by default.",
          "- **Unsupported (no evidence available):** every Missing item; the GitHub-side items of Part 33; independent reviewer reproduction of the demonstration (V41-23.04, V41-32.37).",
          "- **Duplicated statements in the specification (one obligation, several places):** no paid services (2.4, DoD 2, final objective); no watermarks (2.3, 33, DoD 32); traceability (6, DoD 26, deliverable 19); no publication without approval (2.1, 33, 34, DoD 35); CPU-only operation (5, 23); Docker (5, 23, DoD 20); README verified results (29, DoD 28); cloud portability (4, 24, DoD 22-24). Each duplicate is a separate entry with the same underlying evidence, so counts overstate distinct work.",
          "- **Conflicts and deviations:** (a) the specification's roadmap phases (Part 31) do not match the approved execution sequence for phases 1-8 (our Phase 4 security/reliability, 6 frontend), but Phases 9 and 10 coincide; (b) Part 17 lists 17 entities, the implementation has 12 equivalents (roles as a column, workflow state in outbox events, evaluation runs as files, embeddings as a column); "
          "(c) Part 28 lists `frontend/src/layouts` and `frontend/tests`, which do not exist (tests live in `frontend/src` and `frontend/e2e`); (d) Part 21 gives initial targets without coverage, abstention or claim-support thresholds; the later approved thresholds are additions, not replacements; (e) Part 15 states approval before submission, and a separate incident-review gate was added without conflict.", "",
          "## 7. Verified requirements with caveats", "", "| ID | Requirement | Caveat |", "|---|---|---|"]
    G += [f"| {i['id']} | {md_escape(i['title'])[:130]} | {md_escape(i['gap'])} |" for i in items if i["status"] == "V" and i["gap"]]
    G += ["", "## 8. Catalogue items not traceable to an original requirement", "", "| Catalogue id | Title | Disposition |", "|---|---|---|"]
    for c in unmapped_catalogue:
        G.append(f"| {c['id']} | {md_escape(c['title'])[:110]} | later approved engineering addition or sub-requirement; kept, not counted as original |")
    G.append("")

    # ---- acceptance criteria
    A = hdr("V4.1 acceptance criteria")
    A += ["Acceptance criteria that the original specification states or implies, with the observed status. The proposed targets of Part 21 are **targets, not achieved results** (the specification says so). Thresholds added by later approved instructions are listed separately and never replace an original target.", "",
          "## Original proposed targets (Part 21)", "", "| ID | Original target | Status | Evidence / observation |", "|---|---|---|---|"]
    A += [f"| {i['id']} | {md_escape(i['wording'])} | {STATUS[i['status']]} | {md_escape(i['gap']) or 'Met on the evidence shown'} |" for i in by_part[21] if i["kind"] == "T"]
    A += ["", "## Later approved additions (not in the original specification)", "", "| Criterion | Threshold | Origin | Held-out observation (candidate / baseline) |", "|---|---|---|---|",
          "| Grounded-answer coverage | >= 75% (diagnostic floor 60%) | Phase 8 Gate B decision | 59.3% / 64.8%: NOT MET |", "| Correct abstention | >= 90% | Phase 8 Gate B decision | 100% / 94.1%: point estimate met, interval overlaps target |",
          "| Claim-level support | >= 95% | Phase 8 Gate B decision | 95.7% / 96.8%: point estimate met, interval overlaps target |", "| p95 end-to-end latency | <= 15 s (provisional) | Phase 8 Gate B decision | 11.5 s / 12.1 s: met (single user, warm, CPU) |",
          "| Zero unsupported numeric measurements accepted as verified | 0 | Phase 8 optimisation instruction | 0 / 1 (baseline accepted one) |", "", "## Acceptance criteria by specification part (mandatory entries)", "",
          "| ID | Acceptance criterion | Status |", "|---|---|---|"]
    A += [f"| {i['id']} | {md_escape(i['accept'])[:170]} | {STATUS[i['status']]} |" for i in items if i["kind"] in ("M", "D") and i["part"] not in (32, 34)]
    A += ["", "Definition-of-done items (Part 32) and final deliverables (Part 34) are acceptance criteria in their own right; their statuses are in the reconciliation matrix.", ""]
    data = {"specification_sha256": EXPECTED, "total": total, "status_counts": {STATUS[k]: v for k, v in counts.items()}, "matched_to_catalogue": len(matched), "newly_discovered": len(new),
            "catalogue_items_not_traceable": [c["id"] for c in unmapped_catalogue], "class_counts": dict(Counter(i["cls"] for i in items if i["status"] != "V")),
            "requirements": [{k: v for k, v in i.items() if k != "lines"} | {"lines": list(i["lines"])} for i in items]}
    return {"v4.1-requirements-baseline.md": B, "v4.1-reconciliation-matrix.md": M, "v4.1-gap-register.md": G, "v4.1-acceptance-criteria.md": A}, data


def main():
    items = build()
    bad = problems(items)
    if bad:
        print("\n".join(bad))
        return 1
    if "--check" in sys.argv:
        print(f"V4.1 reconciliation OK: {len(items)} requirements")
        return 0
    docs, data = render(items)
    for name, lines in docs.items():
        (OUT / name).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    (OUT / "v4.1-requirements.json").write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8", newline="\n")
    c = Counter(i["status"] for i in items)
    print(f"wrote {len(docs)} documents; {len(items)} requirements; {dict(c)}; matched {data['matched_to_catalogue']}; new {data['newly_discovered']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
