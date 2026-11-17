"""The traceability matrix must be consistent with the repository (see scripts/generate_traceability.py)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_traceability as gt  # noqa: E402


def test_matrix_references_resolve_and_verified_requires_evidence():
    assert gt.problems() == []


def test_committed_matrix_is_current():
    md, data = gt.render()
    committed = ROOT / "docs" / "traceability" / "requirements-traceability-matrix.json"
    assert committed.exists(), "run python scripts/generate_traceability.py"
    assert json.loads(committed.read_text(encoding="utf-8")) == json.loads(json.dumps(data))
    assert (ROOT / "docs" / "traceability" / "requirements-traceability-matrix.md").read_text(encoding="utf-8") == md


def test_uat_and_fi_requirement_ids_exist_in_catalogue():
    ids = {r["id"] for r in gt.REQUIREMENTS}
    import re
    used = set()
    for f in list((ROOT / "tests" / "acceptance").glob("test_uat_*.py")):
        used |= set(re.findall(r'"(R\d+\.\d+)"', f.read_text(encoding="utf-8")))
    assert used <= ids, sorted(used - ids)
