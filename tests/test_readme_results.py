"""V41-01.04, V41-29.02, V41-32.28: the README has the 21 required sections in order and a Verified Engineering Results table whose values are checked against the cited artifacts.
A README figure that no artifact supports fails here instead of drifting."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
SECTIONS = ["Project overview", "Business problem", "Key capabilities", "Architecture diagram", "Technology stack", "Customer scenarios", "Screenshots", "Local setup", "End-to-end demo",
            "API documentation", "Security model", "Customer acceptance results", "Fault-injection results", "Verified engineering benchmarks", "Hardware specifications", "Test commands",
            "CI status", "Cloud portability", "Architecture tradeoffs", "Known limitations", "License information"]


def table_lines() -> list[str]:
    block = README.split("### Verified Engineering Results", 1)[1].split("\n## ", 1)[0]
    return [line for line in block.splitlines() if line.startswith("|")]


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def table_rows() -> list[list[str]]:
    return [cells(line) for line in table_lines()[2:]]


def row_named(prefix: str) -> list[str]:
    return next(r for r in table_rows() if r[0].startswith(prefix))


def test_the_21_required_sections_exist_in_order():
    headings = re.findall(r"^## (\d+)\. (.+)$", README, re.MULTILINE)
    assert [(int(n), t) for n, t in headings] == list(enumerate(SECTIONS, start=1))


def test_the_results_table_has_the_five_required_columns_and_complete_rows():
    assert cells(table_lines()[0]) == ["Metric", "Actual result", "Target", "Test command", "Evidence location"]
    rows = table_rows()
    assert len(rows) >= 10 and all(len(r) == 5 and all(r) for r in rows)


def test_every_evidence_path_in_the_table_exists():
    for row in table_rows():
        for path in re.findall(r"`([^`]+)`", row[4]):
            if "/" in path:
                assert (ROOT / path).exists(), f"{row[0]}: {path}"


def test_reconciliation_counts_match_the_requirement_register():
    sys.path.insert(0, str(ROOT / "scripts"))
    from v41_requirements_data import E

    c = {k: sum(1 for e in E if e["status"] == k) for k in "VPMN"}
    assert f"{c['V']} verified, {c['P']} partial, {c['M']} missing, {c['N']} not evaluable" in row_named("Requirements assessed verified")[1]
    assert f"{c['V']} are assessed verified, {c['P']} partial, {c['M']} missing and {c['N']} not evaluable" in README


def test_fault_injection_and_acceptance_figures_match_their_reports():
    fi = json.loads((ROOT / "evaluation/failure-reports/phase7/fi-report.json").read_text(encoding="utf-8"))["summary"]
    assert f"{fi['passed']} of {fi['scenarios']} passed" in row_named("Fault-injection")[1] and fi["failed"] == 0
    assert "15 of 15" in row_named("Customer acceptance")[1]
    assert (ROOT / "evaluation/customer-acceptance/deterministic/uat-report.json").exists()


def test_ai_quality_figures_appear_in_the_cited_held_out_report_and_are_not_overstated():
    report = (ROOT / "docs/evaluation/phase8-heldout-report.md").read_text(encoding="utf-8")
    for needle in ("95.1%", "89.8%", "59.3%", "18/20 = 90.0%"):
        assert needle in report, needle
    for row in table_rows():
        if row[0].startswith(("Citation correctness", "Grounded-answer", "Raw structured")):
            assert row[4].startswith("`docs/evaluation/phase8-heldout-report.md`")
    candidate = next(r for r in table_rows() if r[0].startswith("Citation correctness") and "candidate" in r[0])
    assert "89.8%" in candidate[1] and "at least 95%" in candidate[2]


def test_recovery_rate_matches_its_report_and_target():
    report = json.loads((ROOT / "evaluation/recovery/recovery-rate-report.json").read_text(encoding="utf-8"))
    row = row_named("Transient-failure")
    assert f"{report['recovered']} of {report['denominator']} recovered" in row[1]
    assert report["target_met"] == (report["recovered"] / report["denominator"] >= report["target"])
    assert "at least 95%" in row[2] and "same-author" in row[1]


def test_integration_success_rate_matches_its_report():
    report = json.loads((ROOT / "evaluation/integration/integration-success-rate-report.json").read_text(encoding="utf-8"))
    row = row_named("Integration success rate")
    assert f"{report['succeeded']} of {report['denominator']} succeeded" in row[1] and "same-author" in row[1]
    assert report["target_met"] == (report["succeeded"] / report["denominator"] >= report["target"])


def test_ci_evidence_distinguishes_the_source_commit_from_the_portfolio_snapshot():
    assert "All six GitHub Actions jobs passed on the private engineering source commit" in README
    assert "Portfolio CI results are tracked separately" in README
