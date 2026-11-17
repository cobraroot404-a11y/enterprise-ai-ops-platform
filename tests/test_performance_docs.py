"""V41-21.01: docs/performance is populated only from committed artifacts; each figure is checked against its source so it cannot drift or be invented."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs" / "performance" / "measured-performance.md").read_text(encoding="utf-8")


def test_every_linked_artifact_exists():
    for target in re.findall(r"\]\((\.\./[^)#]+)", DOC):
        assert (ROOT / "docs" / "performance" / target).resolve().exists(), target


def test_platform_step_timings_match_the_recorded_comparison_run():
    data = json.loads((ROOT / "evaluation/demo-runs/20261113-152713-c19b/comparison/comparison.json").read_text(encoding="utf-8"))["report"]["A_measured_automated"]
    steps = {"extract incident": "extract_incident", "draft ticket": "draft_ticket", "request approval": "request_approval", "approve": "approve", "worker submission": "worker_submission"}
    rows = {m.group(1).strip(): (m.group(2), m.group(3)) for m in re.finditer(r"^\| ([^|]+?) \| ([\d.]+) \| ([\d.]+) \|$", DOC, re.MULTILINE)}
    for label, key in steps.items():
        row = next(v for k, v in rows.items() if k.startswith(label))
        assert (float(row[0]), float(row[1])) == (data["per_step"][key]["median_s"], data["per_step"][key]["p95_s"]), label
    e2e = next(v for k, v in rows.items() if k.startswith("end to end"))
    assert (float(e2e[0]), float(e2e[1])) == (data["end_to_end_system_time"]["median_s"], data["end_to_end_system_time"]["p95_s"])
    assert "not a productivity claim" in DOC


def test_language_model_figures_appear_in_the_phase8_baseline_report():
    report = (ROOT / "docs/evaluation/phase8-baseline-report.md").read_text(encoding="utf-8")
    for needle in ("p50 4.41 s, p95 12.43 s (n=118)", "p50 3.40 s, p95 7.84 s (n=34)", "'tokens_per_s_median': 25.375"):
        assert needle in report, needle
    for figure in ("p50 4.41 s, p95 12.43 s (n=118)", "p50 3.40 s, p95 7.84 s (n=34)", "25.4 tokens per second"):
        assert figure in DOC, figure


def test_rate_figures_match_their_reports():
    recovery = json.loads((ROOT / "evaluation/recovery/recovery-rate-report.json").read_text(encoding="utf-8"))
    integration = json.loads((ROOT / "evaluation/integration/integration-success-rate-report.json").read_text(encoding="utf-8"))
    assert f"{recovery['recovered']} of {recovery['denominator']} recovered" in DOC
    assert f"{integration['succeeded']} of {integration['denominator']}" in DOC
    fi = json.loads((ROOT / "evaluation/failure-reports/phase7/fi-report.json").read_text(encoding="utf-8"))["summary"]
    assert f"{fi['passed']} of {fi['scenarios']} passed" in DOC


def test_unmeasured_items_are_listed_and_rel01_is_not_claimed_closed():
    assert "## Not measured" in DOC and "Cold start | not measured" in DOC and "remains **open**" in DOC
