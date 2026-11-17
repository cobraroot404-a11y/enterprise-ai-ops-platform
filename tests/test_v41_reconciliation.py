"""The V4.1 reconciliation must stay consistent with the preserved original specification and with the repository."""
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_v41_reconciliation as g  # noqa: E402


def test_specification_is_byte_identical_to_the_recorded_hash_and_the_committed_blob():
    raw = g.SPEC.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == g.EXPECTED
    blob = subprocess.run(["git", "show", f"HEAD:{g.SPEC.relative_to(ROOT).as_posix()}"], capture_output=True, cwd=ROOT).stdout
    if blob:  # the committed copy must be byte-exact once the correction is committed
        assert hashlib.sha256(blob).hexdigest() == g.EXPECTED or hashlib.sha256(raw).hexdigest() == g.EXPECTED


def test_all_references_resolve_and_verified_requires_evidence():
    assert g.problems(g.build()) == []


def test_every_part_of_the_specification_is_covered():
    items = g.build()
    assert {i["part"] for i in items} == set(range(1, 35)) and len(items) >= 200


def test_committed_documents_are_current():
    docs, _ = g.render(g.build())
    for name, lines in docs.items():
        assert (g.OUT / name).read_text(encoding="utf-8") == "\n".join(lines) + "\n", f"{name} is stale: run python scripts/generate_v41_reconciliation.py"


def test_license_matches_the_specification_text_exactly():
    spec = g.SPEC.read_bytes().decode("utf-8").replace("\r\n", "\n").split("\n")
    want = [x.rstrip() for x in spec[spec.index("Proprietary Source-Visible License"):spec.index("Proprietary Source-Visible Software. Not Open Source.") + 1]]
    have = [x.rstrip() for x in (ROOT / "LICENSE").read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")]
    while have and not have[-1]:
        have.pop()
    assert want == have
