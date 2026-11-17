"""V41-30.01: the 27-step demonstration is a single reproducible entry point. `demo.py steps` prints all 27 steps from the documented table, starts nothing, and every
document and test path the table cites exists. Executing the automated steps is `demo.py smoke` (covered by the recorded live runs under evaluation/demo-runs)."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "docs" / "customer-delivery" / "demonstration-27-steps.md"


def rows() -> list[list[str]]:
    return [[c.strip() for c in line.strip().strip("|").split("|")] for line in TABLE.read_text(encoding="utf-8").splitlines()
            if line.startswith("|") and line.split("|")[1].strip().isdigit()]


def test_the_table_has_exactly_the_27_specified_steps_in_order():
    spec = (ROOT / "docs" / "specification" / "ORIGINAL_MASTER_SPECIFICATION_V4.1.txt").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(spec) if line.startswith("PART 30"))
    specified = [re.sub(r"^\d+\.\s*", "", line).rstrip(".").lower() for line in spec[start:start + 45] if re.match(r"^\d+\. ", line)]
    assert len(specified) == 27
    table = rows()
    assert [int(r[0]) for r in table] == list(range(1, 28))
    for row, wording in zip(table, specified, strict=True):  # a row may add a clarification after the specified wording
        assert row[1].rstrip(".").lower().startswith(wording), (row[1], wording)


def test_every_cited_path_exists_and_explanations_are_not_reported_as_checks():
    for number, _step, how, evidence in rows():
        for path in re.findall(r"`([^`]+/[^`]*)`", evidence) + re.findall(r"\]\(([^)]+)\)", evidence):
            if "*" in path:
                assert list((ROOT / Path(path).parent).glob(Path(path).name)), path
            elif path.endswith((".md", ".py", ".json", ".yml")) or "/" in path:
                target = (TABLE.parent / path) if path.startswith("..") or not (ROOT / path).exists() else ROOT / path
                assert target.resolve().exists() or (ROOT / path).exists(), f"step {number}: {path}"
        if number in ("26", "27"):
            assert "explain" in how


def test_steps_command_prints_all_27_and_starts_nothing():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "demo.py"), "steps"], capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert result.returncode == 0, result.stderr
    numbered = [line for line in (result.stdout + result.stderr).splitlines() if re.search(r"\] +\d+\. ", line)]
    assert len(numbered) == 27
    assert "nothing was started" in result.stdout + result.stderr
