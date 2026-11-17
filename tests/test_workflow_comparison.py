"""V41-21.14: the comparison protocol keeps measured automated, observed manual and simulated manual numbers apart and refuses to invent manual data."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import workflow_comparison as wc  # noqa: E402

ROWS = [{"task_id": f"T{i}", **{s: 0.1 * (i + 1) for s in wc.STEPS}} for i in range(20)]
BACKEND = {"ai": "deterministic"}


def test_the_synthetic_task_set_is_the_documented_twenty_equivalent_fictional_tasks():
    tasks = wc.load_tasks()
    assert len(tasks) == 20 and len({t["id"] for t in tasks}) == 20 and len({t["report"] for t in tasks}) == 20
    assert "fictional" in json.loads((wc.COMPARISON_DIR / "synthetic-tasks.json").read_text(encoding="utf-8"))["description"].lower()
    lengths = [len(t["report"]) for t in tasks]
    assert max(lengths) - min(lengths) < 60  # similar size: the tasks are equivalent in form


def test_percentiles_use_nearest_rank_and_the_summary_is_complete():
    assert wc.percentile(list(range(1, 101)), 95) == 95 and wc.percentile([5], 95) == 5 and wc.percentile([1, 2, 3, 4], 50) == 2
    s = wc.summarise([1.0, 2.0, 3.0, 4.0, 100.0])
    assert s["n"] == 5 and s["median_s"] == 3.0 and s["p95_s"] == 100.0 and s["min_s"] == 1.0 and s["max_s"] == 100.0


def test_without_observed_or_assumed_data_the_report_is_measured_automated_only_and_says_so():
    report = wc.build_report(ROWS, 20, BACKEND, None, None)
    assert report["B_observed_manual"]["available"] is False and report["B_observed_manual"]["summary"] is None and "no comparison" in report["B_observed_manual"]["note"]
    assert report["C_simulated_manual"]["available"] is False and report["C_simulated_manual"]["result"] is None and "nothing is simulated" in report["C_simulated_manual"]["note"]
    assert report["A_measured_automated"]["kind"] == "measured automated system time" and len(report["A_measured_automated"]["human_touchpoints_that_remain"]) == 5
    text = wc.markdown(report)
    for banned in ("faster than", "% faster", "saves", "speed-up", "speedup", "time saved"):
        assert banned not in text.lower()
    assert text.lower().count("productivity gain") == 1  # only the disclaimer that none is claimed
    assert "No real productivity gain is claimed" in text and "human think and reading time" in text


def test_observed_data_is_read_as_observed_and_kept_in_its_own_section(tmp_path):
    csv = tmp_path / "observed.csv"
    csv.write_text("task_id,participant_role,seconds,notes\nT01,engineer,600,searched PDFs by hand\nT02,engineer,420,\n", encoding="utf-8")
    observed = wc.read_observed(csv)
    assert observed == [600.0, 420.0] and wc.read_observed(tmp_path / "missing.csv") is None
    report = wc.build_report(ROWS, 20, BACKEND, observed, None)
    assert report["B_observed_manual"]["available"] and report["B_observed_manual"]["summary"]["n"] == 2 and report["C_simulated_manual"]["result"] is None
    for bad in ("task_id,participant_role,seconds,notes\nT01,e,abc,\n", "task_id,participant_role,seconds,notes\nT01,e,-5,\n", "task_id,participant_role,seconds,notes\n"):
        csv.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError):
            wc.read_observed(csv)


def test_assumptions_must_be_supplied_complete_and_sourced_and_the_result_is_labelled_hypothetical(tmp_path):
    path = tmp_path / "assumptions.json"
    assert wc.read_assumptions(path) is None
    path.write_text(json.dumps({"source": "reader's own estimate", "steps": {"search": [60, 120], "enter_ticket": [30, 60]}}), encoding="utf-8")
    assumptions = wc.read_assumptions(path)
    report = wc.build_report(ROWS, 20, BACKEND, None, assumptions)
    assert report["C_simulated_manual"]["result"]["hypothetical_manual_total_s"] == [90, 180] and "HYPOTHETICAL" in report["C_simulated_manual"]["result"]["label"]
    assert "HYPOTHETICAL" in wc.markdown(report) and "reader's own estimate" in wc.markdown(report)
    for bad in ({"steps": {"a": [1, 2]}}, {"source": "x", "steps": {}}, {"source": "x", "steps": {"a": [None, None]}}, {"source": "x", "steps": {"a": [5, 1]}}, {"source": "x", "steps": {"a": [1]}}, {"source": "x", "steps": {"a": [True, 2]}}):
        path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError):
            wc.read_assumptions(path)


def test_the_repository_ships_no_assumed_or_observed_manual_numbers():
    assert not (wc.COMPARISON_DIR / "observed-manual.csv").exists() and not (wc.COMPARISON_DIR / "assumptions.json").exists()  # only templates
    template = json.loads((wc.COMPARISON_DIR / "assumptions.template.json").read_text(encoding="utf-8"))
    assert all(v == [None, None] for v in template["steps"].values())  # the template contains no numbers at all
    assert (wc.COMPARISON_DIR / "observed-manual.template.csv").read_text(encoding="utf-8").strip() == "task_id,participant_role,seconds,notes"
    protocol = (wc.COMPARISON_DIR / "protocol.md").read_text(encoding="utf-8")
    assert "None." in protocol and "Do not claim" not in protocol and "No sentence in any report" in protocol
