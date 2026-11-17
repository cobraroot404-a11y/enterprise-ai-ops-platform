"""V41-06.02: the traceability matrix covers ALL 238 original requirements with the six items of specification Part 6, is generated (never hand-edited), references only files that
exist, and does not pad: a verified requirement must have all six items, and anything without them is listed as such."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROWS = json.loads((ROOT / "docs" / "traceability" / "v4.1-full-traceability-matrix.json").read_text(encoding="utf-8"))["requirements"]
MATRIX = (ROOT / "docs" / "traceability" / "v4.1-full-traceability-matrix.md").read_text(encoding="utf-8")


def test_all_238_original_requirements_are_present_once_with_a_customer_need_and_an_acceptance_criterion():
    register = json.loads((ROOT / "docs" / "specification" / "v4.1-requirements.json").read_text(encoding="utf-8"))
    register = register["requirements"] if isinstance(register, dict) else register
    assert [r["id"] for r in ROWS] == [r["id"] for r in register] and len({r["id"] for r in ROWS}) == 238
    assert all(r["customer_need"] and r["acceptance_criterion"] for r in ROWS)
    assert all(f"| {r['id']} (" in MATRIX for r in ROWS)


def test_every_verified_requirement_has_all_six_items():
    incomplete = [r["id"] for r in ROWS if r["status"] == "verified" and not r["complete"]]
    assert incomplete == [], incomplete


def test_requirements_without_all_six_items_are_only_unverified_ones_and_are_counted_in_the_document():
    incomplete = [r for r in ROWS if not r["complete"]]
    assert all(r["status"] != "verified" for r in incomplete)
    assert f"All six items present: **{len(ROWS) - len(incomplete)} of 238**" in MATRIX
    assert "none recorded" in MATRIX or not incomplete


def test_every_referenced_file_exists():
    missing = []
    for r in ROWS:
        for item in r["implementation"] + r["tests"] + r["evidence"]:
            path = item.split("::")[0]
            if not (ROOT / path).exists():
                missing.append((r["id"], path))
    assert missing == [], missing[:10]


def test_statuses_match_the_register_and_the_matrix_says_what_it_is_not():
    register = json.loads((ROOT / "docs" / "specification" / "v4.1-requirements.json").read_text(encoding="utf-8"))
    register = register["requirements"] if isinstance(register, dict) else register
    names = {"V": "verified", "P": "partial", "M": "missing", "N": "not evaluable"}
    assert {r["id"]: r["status"] for r in ROWS} == {r["id"]: names[r["status"]] for r in register}
    assert "fictional assumptions" in MATRIX and "not independent validation" in MATRIX


def test_the_committed_matrix_is_current():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_full_traceability.py"), "--check"], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
