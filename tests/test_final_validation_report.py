"""P34L1365 / P1L37: the final validation report matches the requirement register and cites only existing artifacts."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = (ROOT / "docs/planning/final-validation-report.md").read_text(encoding="utf-8")


def test_report_counts_match_the_register():
    sys.path.insert(0, str(ROOT / "scripts"))
    from v41_requirements_data import E

    c = {k: sum(1 for e in E if e["status"] == k) for k in "VPMN"}
    assert f"**{c['V']} verified, {c['P']} partial, {c['M']} missing, {c['N']} not evaluable**" in REPORT


def test_report_cited_paths_exist():
    for path in re.findall(r"`([^`\s]+/[^`\s]+)`", REPORT):
        if path.startswith(("python", "tests/fault", "tests/acceptance")) or "*" in path or "=" in path:
            continue
        assert (ROOT / path).exists(), path


def test_report_states_acceptance_not_achieved_and_no_ci():
    assert "NOT achieved" in REPORT and "no CI ever ran" in REPORT
