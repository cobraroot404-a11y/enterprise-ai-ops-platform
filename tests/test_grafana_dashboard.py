"""Optional Grafana (Parts 22 and 23): the dashboard file is valid JSON, every metric it queries is one the code actually records, and it says it was never imported anywhere."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = json.loads((ROOT / "infrastructure" / "monitoring" / "grafana-dashboard.json").read_text(encoding="utf-8"))


def recorded_metrics() -> set[str]:
    names = set()
    for path in (ROOT / "backend" / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'METRICS\.(incr|observe|timer)\(\s*"([a-z_]+)"', text):
            kind, name = match.groups()
            names.add(name)
            if kind in ("observe", "timer"):
                names |= {f"{name}_bucket", f"{name}_count", f"{name}_sum"}
    return names


def test_the_dashboard_is_structurally_valid_and_has_unique_panel_ids():
    ids = [p["id"] for p in DASH["panels"]]
    assert len(ids) == len(set(ids)) >= 10 and DASH["uid"] == "eaop-overview"
    for p in DASH["panels"]:
        assert p["targets"][0]["expr"] and p["datasource"]["uid"] == "${DS_PROMETHEUS}"


def test_every_queried_metric_is_recorded_by_the_application():
    known = recorded_metrics()
    queried = {m for p in DASH["panels"] for m in re.findall(r"eaop_([a-z_]+)", p["targets"][0]["expr"])}
    assert queried and queried <= known, sorted(queried - known)


def test_every_metric_family_named_by_the_specification_has_a_panel():
    exprs = " ".join(p["targets"][0]["expr"] for p in DASH["panels"])
    for family in ("http_request_seconds", "ingestion_seconds", "retrieval_seconds", "llm_seconds", "workflow_completion_seconds", "connector_calls_total", "submission_retries_total",
                   "dead_letters_total", "approval_turnaround_seconds"):
        assert f"eaop_{family}" in exprs, family


def test_the_dashboard_states_it_was_never_imported():
    assert "Never imported into a Grafana instance" in DASH["description"] and "illustrative" in DASH["tags"]
