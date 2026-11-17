"""Gate C preparation: the independent review package exists, its references resolve, and the repository does NOT claim a review happened.
A completed review record (any file other than the template in evaluation/independent-review) would need the owner's decision before any status changes; none exists."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = (ROOT / "docs" / "customer-delivery" / "independent-review-package.md").read_text(encoding="utf-8")
TEMPLATE = ROOT / "evaluation" / "independent-review" / "review-record-template.md"


def test_the_package_states_it_was_not_performed_and_changes_no_status():
    assert "prepared, NOT performed" in PACKAGE and "stay **Partial**" in PACKAGE
    assert "TEMPLATE: this file is not a review" in TEMPLATE.read_text(encoding="utf-8")


def test_every_relative_link_and_cited_path_resolves():
    for target in re.findall(r"\]\(([^)#]+)", PACKAGE):
        assert ((ROOT / "docs" / "customer-delivery") / target).resolve().exists() or (ROOT / target).exists(), target
    for path in re.findall(r"`((?:backend|evaluation|docs|scripts|tests)/[^`]+?)`", PACKAGE):
        if "<" in path:
            continue  # a placeholder for the reviewer's own file name
        path = path.split(" ")[0].rstrip("/")
        assert (ROOT / path).exists() or list(ROOT.glob(path + "*")), path


def test_every_command_in_the_review_matches_a_command_in_the_readme_or_runbook():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for command in ("python -m pytest backend/tests -q", "python -m pytest tests -q", "python scripts/secret_scan.py", "python scripts/demo.py smoke --ingestion --rest --compare --backup", "python scripts/container_smoke.py"):
        assert command in PACKAGE and command in readme + (ROOT / "docs" / "operations" / "deployment-runbook.md").read_text(encoding="utf-8"), command


def test_no_completed_review_record_exists_and_the_template_has_every_track():
    records = [p for p in (ROOT / "evaluation" / "independent-review").glob("*.md") if p.name != "review-record-template.md"]
    assert records == [], "a review record exists: the owner must decide what it changes before the register is touched"
    text = TEMPLATE.read_text(encoding="utf-8")
    for heading in ("Track 1", "Track 2: V41-14.02", "Track 3", "Conclusion"):
        assert heading in text


def test_consumed_datasets_are_declared_consumed():
    assert "consumed" in PACKAGE and "must not be used for tuning" in PACKAGE


def test_reviewer_guide_links_resolve_and_claims_no_review():
    guide = ROOT / "docs" / "customer-delivery" / "gate-c-reviewer-guide.md"
    text = guide.read_text(encoding="utf-8")
    assert "prepared, NOT performed" in text and "stay **Partial**" in text
    assert "gate-c-reviewer-guide.md" in PACKAGE
    for target in re.findall(r"\]\(([^)#]+)", text):
        assert (guide.parent / target).resolve().exists(), target
    for path in re.findall(r"`((?:backend|evaluation|docs|scripts|tests)/[^`<>]+?)`", text):
        assert (ROOT / path.split(" ")[0].rstrip("/")).exists() or list(ROOT.glob(path.split(" ")[0] + "*")), path
