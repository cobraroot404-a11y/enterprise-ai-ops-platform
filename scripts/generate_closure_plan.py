"""Generate docs/planning/requirement-closure-plan.json: one entry for every PARTIAL, MISSING and NOT EVALUABLE original requirement.

Type: A missing implementation, B incomplete implementation, C verification deficit, D environmental limitation, E independent-validation requirement.
The per-requirement judgement lives in PLAN below (keyed by specification line); everything else is read from the reconciliation data."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from v41_requirements_data import E  # noqa: E402

# line -> (type, package, minimum change, acceptance measurement, locally authorised, external prerequisite)
PLAN = {
    14: ("C", "PKG-DOCS", "Complete the Phase 9/10 deliverables that remain (release stays an owner decision)", "Every deliverable listed in Part 34 exists or is explicitly owner-gated", True, "Publication and release need owner approval"),
    16: ("C", "PKG-DOCS", "Cross-reference the 15 FDE capabilities to artifacts", "Capability-to-artifact table with every path resolving (test)", True, ""),
    37: ("C", "PKG-DOCS", "README-versus-artifact consistency test so no figure lacks an artifact", "Test fails when a README metric differs from its evidence file", True, ""),
    39: ("D", "PKG-OWNER", "Apply the completed publication handoff after owner approval", "Approved personal account and repository controls verified", False, "Owner authorization and GitHub access"),
    91: ("C", "PKG-DOCS", "Automated dependency and cost check; electricity and bandwidth documentation", "Test: no paid-service dependency in requirements, compose or workflow", True, ""),
    210: ("B", "PKG-DOCS", "Audit installed Python and Node dependencies, models, images and datasets into THIRD_PARTY_NOTICES.md", "No 'to verify' entry remains; test checks every direct dependency is listed", True, ""),
    230: ("B", "PKG-OBS", "Add trace ids (W3C traceparent) propagated API to worker to connectors and logged", "Test: one trace id appears in API, job and connector log records", True, ""),
    241: ("C", "PKG-AI", "Define the integration-success and recovery-rate suites and compute the rates", "Rates computed from defined suites with denominators", True, ""),
    251: ("B", "PKG-DOCS", "Reassess against the delivery documents that now exist; add handover verification", "Document tests pass and reviewer package exists", True, ""),
    262: ("D", "PKG-INFRA", "Terraform schema validation needs the AWS provider download", "terraform validate passes", False, "Owner approval to download the provider"),
    270: ("C", "PKG-DOCS", "Principle; evidence is the delivery order", "Documented rationale; not testable", True, ""),
    303: ("D", "PKG-INFRA", "Ollama inside a container untested", "Container real-AI profile passes smoke or the limitation is measured", True, "Model already on the host (no new download)"),
    313: ("A", "PKG-OBS", "OpenTelemetry where practical: trace ids first, SDK only if no heavy dependency", "Trace ids across processes; text metrics endpoint", True, "SDK dependency may need approval"),
    319: ("D", "PKG-CI", "Workflow exists; expand jobs; cannot execute without a remote", "Workflow parses and each step runs locally", True, "A remote to execute CI"),
    323: ("D", "PKG-INFRA", "As V41-24.02", "terraform validate passes", False, "Provider download approval"),
    350: ("B", "PKG-DOCS", "Customer-need column; align catalogue with the reconciliation baseline", "Matrix covers every Verified and Partial requirement (test)", True, ""),
    417: ("B", "PKG-OBS", "Expose the evaluation registry as a read-only module endpoint; complete observability module", "Endpoint test; module listed in architecture", True, ""),
    462: ("C", "PKG-DOCS", "Reassess the capability list against implemented connectors", "Table of capability by connector with a test per cell", True, ""),
    511: ("D", "PKG-AI", "Neural reranker needs model weights", "Reranker decision recorded", False, "Approval to download weights"),
    512: ("E", "PKG-AI", "Confirm grounded coverage on fresh independently labelled data with the frozen verifier", "Grounded coverage measured against its acceptance criterion", False, "Independent labels and owner authorization for inference"),
    515: ("E", "PKG-AI", "Confirm citation correctness on fresh independently labelled data with the frozen verifier", "95% citation correctness on a fresh independently labelled set", False, "Independent labels and owner authorization for inference"),
    517: ("E", "PKG-AI", "Confirm abstention on fresh independently labelled data with the frozen verifier", "Abstention rate on a fresh set", False, "Independent labels and owner authorization for inference"),
    574: ("A", "PKG-SEC", "Distributed rate limiting through the shared database (no new infrastructure)", "Two API processes share one limit (test)", True, ""),
    659: ("D", "PKG-FE", "Record manual keyboard and Windows Narrator observations", "Owner or reviewer records manual keyboard and screen-reader results for the documented workflows", True, ""),
    744: ("C", "PKG-DOCS", "Populate docs/performance from measured evidence", "Files reference artifacts (test)", True, ""),
    749: ("B", "PKG-AI", "Compute integration success and recovery rates from defined suites", "Rates with denominators in evidence", True, ""),
    769: ("E", "PKG-AI", "Confirm citation correctness on a fresh independently labelled set", "95% on a fresh independent set", False, "Independent labels and owner authorization for inference"),
    770: ("E", "PKG-AI", "Measure raw structured validity on fresh independently labelled data", "Fresh-set raw validity against the original target", False, "Independent labels and owner authorization for inference"),
    775: ("A", "PKG-AI", "Define the transient-failure suite (denominator) and compute the recovery rate", "Recovery rate >= 95% over the defined suite", True, ""),
    796: ("E", "PKG-OWNER", "Needs observed human timings", "observed-manual.csv from a real observer", False, "Human observer"),
    800: ("B", "PKG-OBS", "Trace ids; durable metrics across restarts", "Trace id present; metrics survive restart (test)", True, ""),
    815: ("A", "PKG-OBS", "OpenTelemetry where practical", "As the observability package", True, "SDK dependency may need approval"),
    816: ("A", "PKG-OBS", "Prometheus text endpoint over durable counters (no Grafana)", "/metrics test", True, ""),
    822: ("C", "PKG-INFRA", "Core compose services run; Ollama in container untested", "Smoke passes", True, ""),
    835: ("D", "PKG-INFRA", "Optional; decision recorded", "n/a", False, "Owner decision to adopt a broker"),
    841: ("B", "PKG-INFRA", "Validate backup and restore for the disposable full container deployment", "Container backup and restore-check pass", True, ""),
    856: ("D", "PKG-REPRO", "Reviewer reproduction on compatible hardware", "Owner or reviewer reproduces the main CPU-only demo from the package on compatible hardware and records results and deviations", True, ""),
    859: ("C", "PKG-DOCS", "Cloud adaptability documented (cloud-portability.md exists)", "Doc test", True, ""),
    868: ("D", "PKG-INFRA", "Terraform schema validation", "terraform validate passes", False, "Provider download approval"),
    899: ("A", "PKG-INFRA", "Optional Kubernetes manifests, parse-only", "YAML parse test; no deployment claim", True, ""),
    929: ("C", "PKG-DOCS", "Discovery docs exist (fictional, labelled): reassess", "Doc test", True, ""),
    945: ("B", "PKG-QA", "Deployment smoke (container) and contract tests beyond the route table", "Both pass", True, ""),
    968: ("D", "PKG-CI", "Add dependency, security, Docker, smoke, acceptance and release jobs", "Workflow parses; each job command runs locally", True, "A remote to execute CI"),
    983: ("C", "PKG-CI", "Write docs/operations/ci-and-local-tests.md", "Doc test lists every suite", True, ""),
    989: ("B", "PKG-DOCS", "Reassess structure; add missing folders", "Structure test against the listed tree", True, ""),
    1070: ("B", "PKG-DOCS", "README with the 21 sections and an architecture diagram", "Test: sections present", True, ""),
    1094: ("B", "PKG-DOCS", "Verified Engineering Results table with consistency test", "Test", True, ""),
    1106: ("B", "PKG-DOCS", "Single reproducible 27-step demonstration script including steps 26 and 27", "Script exits 0 and prints the 27 steps", True, ""),
    1138: ("C", "PKG-DOCS", "Complete the remaining roadmap outputs in the Phase 9-10 exit evidence matrix after the documented local security review",
           "Artifact for every mandatory roadmap output, including performed GitHub audit and tested release", False,
           "Manual comparison inputs and authorized GitHub identity, CI, audit, publication and release"),
    1229: ("C", "PKG-DOCS", "Preserve historical gaps and record remaining Phase 9-10 exit actions when they occur",
           "Direct evidence for the required actions at each phase end, or explicit owner disposition preserving historical gaps", False,
           "Original historical records if any surface; authorized remaining phase-end actions and owner disposition of irreducible gaps"),
    1242: ("C", "PKG-DOCS", "Automated no-paid-service check", "Test", True, ""),
    1260: ("C", "PKG-INFRA", "Container reproducibility from a clean state; Ollama inside container", "Clean build and smoke", True, ""),
    1261: ("D", "PKG-CI", "CI cannot run without a remote", "CI run green", False, "A remote"),
    1263: ("D", "PKG-INFRA", "Terraform validation", "terraform validate passes", False, "Provider download approval"),
    1266: ("C", "PKG-DOCS", "Traceability aligned with reconciliation", "Test", True, ""),
    1268: ("B", "PKG-DOCS", "Add Phase 8 results to README", "Consistency test", True, ""),
    1270: ("B", "PKG-DOCS", "Complete notices audit", "Test", True, ""),
    1274: ("D", "PKG-OWNER", "No repository exists", "n/a", False, "A repository"),
    1275: ("D", "PKG-OWNER", "Owner must authorise publication", "n/a", False, "Owner decision"),
    1276: ("D", "PKG-OWNER", "Release needs publication", "n/a", False, "Owner decision"),
    1277: ("C", "PKG-REPRO", "Document complete demonstration reproduction and deviations", "One observed session accounts for all 27 demonstration steps and records deviations and limitations", True, ""),
    1282: ("D", "PKG-OWNER", "Execute the handoff permission and publication audit after authorization", "All pre-publication checks evidenced", False, "An authorized GitHub repository"),
    1308: ("C", "PKG-DOCS", "Record environment verification (Docker, git, hardware) in a repository artifact", "Artifact exists", True, ""),
    1322: ("C", "PKG-DOCS", "Process rules; evidence is history", "Documented", True, ""),
    1347: ("B", "PKG-AI", "Benchmark reports complete after rate suites", "Reports exist", True, ""),
    1348: ("C", "PKG-INFRA", "Docker deployment reassessment", "Smoke passes", True, ""),
    1349: ("D", "PKG-CI", "CI workflow deliverable", "Workflow complete", True, "A remote to execute"),
    1350: ("B", "PKG-DOCS", "README", "As the README requirement", True, ""),
    1353: ("B", "PKG-DOCS", "Traceability", "As the matrix requirement", True, ""),
    1355: ("B", "PKG-DOCS", "Security documentation index", "Doc test", True, ""),
    1358: ("D", "PKG-INFRA", "Terraform", "terraform validate passes", False, "Provider download approval"),
    1361: ("B", "PKG-DOCS", "Notices", "As the notices requirement", True, ""),
    1362: ("D", "PKG-OWNER", "Repository", "n/a", False, "Owner decision"),
    1363: ("D", "PKG-OWNER", "Release", "n/a", False, "Owner decision"),
    1364: ("B", "PKG-DOCS", "Demo script", "As the 27-step demo", True, ""),
    1365: ("B", "PKG-DOCS", "Final validation report refreshed", "Report matches registers", True, ""),
    1368: ("C", "PKG-DOCS", "Abilities table with artifacts", "Test", True, ""),
    54: ("D", "PKG-OWNER", "PROV-01: history contains AI co-author trailers and tool-authored commits; only a history rewrite removes them", "provenance check reports zero violations", False, "Owner decision on rewriting history (moves the protected tag)"),
    71: ("D", "PKG-OWNER", "PROV-01: history contains AI co-author trailers and tool-authored commits; only a history rewrite removes them", "provenance check reports zero violations", False, "Owner decision on rewriting history (moves the protected tag)"),
    1272: ("D", "PKG-OWNER", "PROV-01: history contains AI co-author trailers and tool-authored commits; only a history rewrite removes them", "provenance check reports zero violations", False, "Owner decision on rewriting history (moves the protected tag)"),
    1273: ("D", "PKG-OWNER", "PROV-01: history contains AI co-author trailers and tool-authored commits; only a history rewrite removes them", "provenance check reports zero violations", False, "Owner decision on rewriting history (moves the protected tag)"),
    1303: ("D", "PKG-OWNER", "PROV-01: history contains AI co-author trailers and tool-authored commits; only a history rewrite removes them", "provenance check reports zero violations", False, "Owner decision on rewriting history (moves the protected tag)"),
    1389: ("D", "PKG-OWNER", "PROV-01: history contains AI co-author trailers and tool-authored commits; only a history rewrite removes them", "provenance check reports zero violations", False, "Owner decision on rewriting history (moves the protected tag)"),
    1395: ("C", "PKG-DOCS", "Sequence followed", "n/a", True, ""),
}


def main() -> int:
    items = []
    for e in E:
        if e["status"] == "V":
            continue
        line = e["lines"][0]
        if line not in PLAN:
            raise SystemExit(f"no plan for line {line}: {e['title'][:60]}")
        typ, pkg, change, test, local, ext = PLAN[line]
        items.append({"id": f"P{e['part']}L{line}", "part": e["part"], "spec_lines": list(e["lines"]), "status": {"P": "PARTIAL", "M": "MISSING", "N": "NOT_EVALUABLE"}[e["status"]],
                      "acceptance_wording": e["accept"], "title": e["title"], "current_implementation": e["impl"], "current_evidence": e["evidence"], "current_gap": e["gap"],
                      "gap_type": typ, "package": pkg, "minimum_change": change, "acceptance_test": test, "fully_local_authorised": local, "external_prerequisite": ext})
    out = ROOT / "docs" / "planning" / "requirement-closure-plan.json"
    out.write_text(json.dumps({"baseline_commit": "f098cee3c147dc8c7486d56b0d70c735fde94e6a", "count": len(items), "items": items}, indent=1) + "\n", encoding="utf-8", newline="\n")
    by = {}
    for i in items:
        by.setdefault(i["package"], []).append(i["id"])
    print(len(items), {k: len(v) for k, v in sorted(by.items())})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
