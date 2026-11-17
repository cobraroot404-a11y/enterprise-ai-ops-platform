"""P31L1229: retrospective phase-gate records cover Phases 1-4, cite existing paths, and are labelled honestly."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "planning" / "retrospective-phase-gates-1-4.md"
LABEL = "RETROSPECTIVE RECONSTRUCTION — NOT A CONTEMPORANEOUS PHASE-GATE APPROVAL"


def _text():
    return DOC.read_text(encoding="utf-8")


def test_label_and_four_phases_each_with_eight_items():
    t = _text()
    assert LABEL in t.splitlines()[2].replace("**", "")
    sections = re.split(r"^## ", t, flags=re.M)
    phases = [s for s in sections if re.match(r"Phase [1-4] ", s)]
    assert len(phases) == 4
    for s in phases:
        for n in range(1, 9):
            assert re.search(rf"^{n}\. \*\*", s, flags=re.M), (s[:20], n)
        assert "Formal approval recorded:** none found" in s


def test_cited_paths_and_commits_exist_and_status_not_overstated():
    t = _text()
    paths = {p for p in re.findall(r"`([A-Za-z0-9_./-]+\.[a-z]+)`", t) if "/" in p}
    paths |= {p for p in re.findall(r"`([A-Za-z0-9_./-]+/[A-Za-z0-9_-]+)`", t) if p.startswith("evaluation/")}
    assert len(paths) >= 15
    assert [p for p in sorted(paths) if not (ROOT / p).exists()] == []
    import subprocess
    for sha in sorted(set(re.findall(r"`([0-9a-f]{7})`", t))):
        assert subprocess.run(["git", "cat-file", "-e", sha + "^{commit}"], cwd=ROOT).returncode == 0, sha
    assert "stays PARTIAL" in t and "cannot create one" in t
