"""Check the independent portfolio history and tracked-file provenance."""
import re
import subprocess
from pathlib import Path

import provenance_check

ROOT = Path(__file__).resolve().parents[1]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout


def test_portfolio_history_has_no_provenance_violations():
    state = provenance_check.state()
    assert state["violations"] == [], state["violations"]
    assert len(git("rev-list", "--max-parents=0", "HEAD").split()) == 1
    assert git("tag", "-l", "v4.1.0-local-rc1").strip() == ""


def test_tracked_files_carry_no_assistant_branding_or_generated_by_footers():
    pattern = re.compile(r"generated with \[?claude|co-authored-by:|🤖|made with chatgpt|written by (an )?ai", re.IGNORECASE)
    allowed = {"scripts/provenance_check.py", "tests/test_repository_provenance.py", "docs/planning/provenance-exceptions.json"}  # they name the patterns they look for
    hits = []
    for path in git("ls-files").splitlines():
        if path in allowed or path.startswith(("frontend/package-lock.json", "docs/specification/ORIGINAL_")) or path.endswith((".png", ".pdf", ".ico", ".dump", ".jsonl")):
            continue
        try:
            text = (ROOT / path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        if pattern.search(text):
            hits.append(path)
    assert hits == [], hits


def test_real_branding_in_commit_messages_is_detected():
    for message in ("Co-Authored-By: Claude <x@y.z>", "Generated with Claude Code", "written by Codex", "ask Claude to fix it"):
        assert provenance_check.BRANDING.search(provenance_check.FILENAMES.sub("", message)), message
