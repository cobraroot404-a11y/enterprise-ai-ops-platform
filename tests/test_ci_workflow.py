"""V41-27.01/27.04: the CI workflow is least-privilege, uses free hosted runners, never writes to the repository, and is documented job by job.
These tests check the workflow definition without running it."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
WORKFLOW = yaml.safe_load(TEXT)
DOC = (ROOT / "docs" / "operations" / "ci-and-local-tests.md").read_text(encoding="utf-8")
JOBS = {"backend", "acceptance", "frontend", "dependency-and-security", "docker-build", "release-validation"}


def commands() -> str:
    return " ".join(str(step.get("run", "")) for job in WORKFLOW["jobs"].values() for step in job["steps"])


def test_permissions_are_read_only_at_workflow_and_job_level():
    assert WORKFLOW["permissions"] == {"contents": "read"}
    for name, job in WORKFLOW["jobs"].items():
        assert "permissions" not in job or all(v == "read" for v in job["permissions"].values()), name


def test_only_free_hosted_runners_and_no_repository_writes():
    for job in WORKFLOW["jobs"].values():
        assert job["runs-on"] == "ubuntu-latest"
    for forbidden in ("git push", "git commit", "gh release", "secrets.", "self-hosted", "contents: write"):
        assert forbidden not in TEXT, forbidden


def test_every_specified_check_family_has_a_job_and_the_doc_names_every_job():
    assert set(WORKFLOW["jobs"]) == JOBS
    for job in JOBS:
        assert f"`{job}`" in DOC, job
    for needle in ("ruff check", "pytest -q backend/tests", "pytest -q tests", "npm run typecheck", "npm run lint", "npm test", "npm run build", "secret_scan", "docker build", "pip check"):
        assert needle in commands(), needle


def test_portfolio_ci_is_documented_separately_from_the_engineering_run():
    assert "Portfolio CI" in TEXT and "private engineering source commit passed all six CI jobs" in DOC


def test_acceptance_checkout_provides_full_provenance_history():
    steps = WORKFLOW["jobs"]["acceptance"]["steps"]
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == 0


def test_ci_does_not_run_the_expensive_local_only_suites():
    for local_only in ("RUN_REAL_AI", "ollama", "container_smoke", "playwright test", "demo.py smoke"):
        assert local_only not in commands(), local_only
