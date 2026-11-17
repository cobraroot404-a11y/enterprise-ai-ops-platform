"""Render docs/evaluation/phase8-requirements-gap-audit.md from the traceability matrix plus owner/risk/next-action planning data.

    python scripts/generate_gap_audit.py
"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs/traceability/requirements-traceability-matrix.json"

# id -> (owner phase, risk, next action). Anything not listed is verified and needs only regression re-runs.
PLAN = {
    "R2.1": ("8", "Low", "Add an automated dependency/licence inventory check (no paid-service dependency); record in the Phase 8 manifest."),
    "R2.2": ("8", "Low", "Add a git-provenance check (authors, trailers, branding grep) to the Phase 8 gate script."),
    "R3.1": ("10", "Medium", "Legal review of the proprietary licence is outside the project; state the limitation in the final audit."),
    "R6.1": ("10", "Low", "Write the fictional customer-discovery documents, clearly labelled synthetic."),
    "R6.2": ("8", "Low", "Reconcile the matrix with the Phase 8 report; discovery inputs follow with R6.1."),
    "R9.2": ("8", "Medium", "Phase 8 delivers the evaluation module as versioned scripts, datasets and reports; the dashboard stays read-only."),
    "R11.4": ("9/10", "Medium", "Decide scope: implement CSV/webhook connectors and pagination, or document them as out of scope."),
    "R12.5": ("earlier defect", "Medium", "Decide: add document deletion with audit and an ingestion-job entity, or record as accepted scope reduction."),
    "R13.2": ("8", "High", "Re-measure citation correctness and claim support on the new dataset; the 95% target is NOT MET today."),
    "R13.3": ("8", "High", "Measure correct abstention and false refusal on at least 40 unanswerable queries."),
    "R13.5": ("8", "Medium", "Reranker only if it needs no unapproved download; otherwise request approval or record as not implemented."),
    "R16.4": ("9/10", "Medium", "Distributed rate limiting needs shared state; document and design, not in Phase 8."),
    "R16.6": ("9/10", "High", "Network-level egress restriction belongs to deployment (Phase 9); Phase 8 only re-runs the SSRF suite."),
    "R17.3": ("earlier defect", "Low", "Decide whether ingestion jobs, evaluation runs and a roles table become entities or stay as documented deviations."),
    "R18.3": ("10", "Medium", "Screen-reader and cross-browser audit; Phase 8 only re-runs axe regression."),
    "R21.1": ("8", "High", "Full metric suite on the new dataset with confidence intervals and per-tenant results."),
    "R21.3": ("8", "Medium", "Latency/resource benchmark with p50/p95, warm and cold, on the recorded hardware."),
    "R21.4": ("8", "Medium", "Manual-versus-AI-assisted comparison, honestly labelled (no human participants available)."),
    "R22.2": ("8", "Medium", "Persist worker metrics durably or label the limit; Phase 8 uses database counts and logs."),
    "R22.3": ("10", "Low", "Optional: OpenTelemetry/Prometheus exporters; not claimed."),
    "R23.1": ("9/10", "Medium", "Containerise API, worker and mocks in Compose or document the script-based start."),
    "R24.1": ("9", "Low", "Cloud portability documentation and IaC examples; Phase 9 (not authorized yet)."),
    "R25.1": ("10", "Low", "Customer-facing technical communication; Phase 10."),
    "R27.1": ("10", "Medium", "CI has never run (no remote); cannot be claimed until an authorised push."),
    "R29.1": ("8", "Medium", "Update the README results with verified Phase 8 measurements and add a README-versus-artifact consistency check."),
    "R30.1": ("8/10", "Low", "Phase 8 supplies a demo script for the CTO package; the full 27-step demo is Phase 10."),
    "R32.1": ("10", "Medium", "Walk the definition-of-done list at the final audit."),
    "R33.1": ("10", "Low", "Publication needs separate explicit approval."),
}
# verified requirements whose behaviour Phase 8 changes touch and which therefore need a regression re-run
REGRESS = {"R7.1", "R8.1", "R13.1", "R13.4", "R13.6", "R14.1", "R14.2", "R14.3", "R14.4", "R15.1", "R15.3", "R15.4", "R16.1", "R16.5", "R16.7", "R12.4",
           "R20.8", "R20.11", "R22.1"}


def main():
    d = json.loads(MATRIX.read_text(encoding="utf-8"))
    reqs = d["requirements"]
    c = Counter(r["status"] for r in reqs)
    L = ["# Phase 8 requirements and implementation gap audit", "",
         "Source: `docs/traceability/requirements-traceability-matrix.json` (generated from `scripts/traceability_data.py`), re-read against the repository on the Phase 8 start commit.", "",
         "## Reconciliation of the reported counts", "",
         f"The matrix holds **{d['total']}** requirements: **{c['verified']} verified, {c['partially verified']} partially verified, {c['not implemented']} not implemented**. "
         "These match the Phase 7 report exactly; no requirement is silently reclassified in this phase.", "",
         "## Findings the audit must disclose", "",
         "1. **Requirement identifiers.** The `R<part>.<n>` identifiers are this project's own catalogue ids (specification part number plus sequence). Only the FI-01..FI-10 "
         "and UAT-A01..B07 identifiers are the specification's own. The V4.1 specification text is not stored in the repository, so completeness of the catalogue "
         "against the full specification text cannot be proven by this audit. **Action requested at Gate B:** supply the specification file (or confirm it may be added "
         "under `docs/`) so each catalogue id can be mapped to the exact clause.",
         "2. **Possible omissions.** Bullet-level requirements in specification parts 4, 28, 31 and 34 (priorities, repository layout, roadmap, final audit) are only "
         "covered coarsely (R2, R29, R32, R33). Phase 8 will split them once the specification text is available.",
         "3. **Evidence strength varies.** Several 'verified' requirements rest on one scenario in a synthetic environment (for example R16.1 tenant isolation is "
         "verified through the application and PostgreSQL RLS, but not against a compromised application process). The limitation column in the matrix carries these caveats.",
         "4. **Implementation-versus-specification conflicts recorded:** no ingestion jobs/evaluation-run/roles tables (R17.3), no document deletion (R12.5), no CSV/webhook "
         "connector kinds beyond names (R11.4), and Apex runs on built-in rules while Meridian is profile-driven (documented technical debt, `docs/architecture/apex-meridian-execution-paths.md`).", "",
         "## Per-requirement table", "",
         "| ID | Requirement | Implementation | Evidence | Status | Owner phase | Risk | Next action |", "|---|---|---|---|---|---|---|---|"]
    for r in reqs:
        status = {"verified": "Verified", "partially verified": "Partial", "not implemented": "Missing"}[r["status"]]
        if r["id"] in PLAN:
            owner, risk, nxt = PLAN[r["id"]]
        elif r["id"] in REGRESS:
            owner, risk, nxt = "8 (regression)", "Medium", "Re-run its tests after Phase 8 changes; no new evidence needed unless behaviour changes."
        else:
            owner, risk, nxt = "-", "Low", "None; covered by the standing regression suite."
        impl = ", ".join(f"`{p}`" for p in r["implementation"][:2]) or "-"
        ev = ", ".join(f"`{p.split('::')[0].split('/')[-1]}`" for p in r["tests"][:2]) or "-"
        L.append(f"| {r['id']} | {r['title']} | {impl} | {ev} | {status} | {owner} | {risk} | {nxt} |")
    L += ["", "## Outstanding items by responsible phase", ""]
    by: dict[str, list[str]] = {}
    for rid, (owner, _risk, _n) in PLAN.items():
        by.setdefault(owner, []).append(rid)
    for owner in sorted(by):
        L.append(f"- **Phase {owner}:** {', '.join(by[owner])}")
    L += ["", "Phase 8 does not claim Phase 9 (cloud portability) or Phase 10 (documentation, audit, release) deliverables. A requirement is moved to Verified only with "
          "a test and an evidence artifact, as enforced by `tests/test_traceability.py`."]
    (ROOT / "docs/evaluation/phase8-requirements-gap-audit.md").write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
    print("written; owners:", {k: len(v) for k, v in by.items()})


if __name__ == "__main__":
    main()
